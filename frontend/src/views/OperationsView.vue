<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Activity, ChartBar, Coin, Heartbeat, PlugConnected, Robot, Server } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import AdminGuideLink from '@/components/AdminGuideLink.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import type { AgentHealth, AgentMetric, HealthStatus, MetricsSummary } from '@/types/api'

const metrics = ref<MetricsSummary | null>(null)
const agentMetrics = ref<AgentMetric[]>([])
const health = ref<HealthStatus | null>(null)
const agentHealth = ref<AgentHealth[]>([])
const loading = ref(false)
const error = ref<string | null>(null)

const components = computed(() => [
  { key: 'database', label: 'PostgreSQL', icon: Server },
  { key: 'memory', label: 'Memory', icon: Activity },
  { key: 'knowledge', label: 'Knowledge', icon: Robot },
  { key: 'queue', label: 'Worker Queue', icon: ChartBar },
  { key: 'artifact_storage', label: 'Artifact Storage', icon: PlugConnected },
].map((item) => ({ ...item, status: String(health.value?.[item.key as keyof HealthStatus] || 'unknown') })))
const runtimeComponents = computed(() => {
  const aggregate = (key: 'model' | 'skills' | 'mcp') => {
    const states = agentHealth.value.map((item) => item.checks[key]?.status).filter(Boolean)
    if (!states.length) return 'unknown'
    if (states.some((state) => state === 'unhealthy')) return 'unhealthy'
    if (states.some((state) => state === 'degraded')) return 'degraded'
    return 'healthy'
  }
  return [
    { key: 'model', label: 'Model', icon: Robot, status: aggregate('model'), detail: `${agentHealth.value.length} 个 Agent 健康检查` },
    { key: 'worker', label: 'Worker', icon: ChartBar, status: health.value?.queue || 'unknown', detail: '来自 /health queue' },
    { key: 'mcp', label: 'MCP', icon: PlugConnected, status: aggregate('mcp'), detail: '聚合 Agent MCP 检查' },
    { key: 'skill', label: 'Skill', icon: Activity, status: aggregate('skills'), detail: '聚合 Agent Skill 检查' },
  ]
})

function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return '--'
  return `${(value <= 1 ? value * 100 : value).toFixed(1)}%`
}

function latency(value: number | null | undefined): string {
  return value === null || value === undefined ? '--' : `${Math.round(value)} ms`
}

async function load() {
  loading.value = true
  error.value = null
  try {
    const [summary, agents, healthResult, registeredAgents] = await Promise.all([
      platformApi.getMetricsSummary(),
      platformApi.listAgentMetrics(),
      platformApi.health(),
      platformApi.listAgents(),
    ])
    metrics.value = summary
    agentMetrics.value = agents
    health.value = healthResult
    const checks = await Promise.allSettled(registeredAgents.map((agent) => platformApi.getAgentHealth(agent.id)))
    agentHealth.value = checks.flatMap((result) => result.status === 'fulfilled' ? [result.value] : [])
  } catch (cause) {
    error.value = getApiErrorMessage(cause)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="Operations" description="查看生产调用指标、Agent 运行表现和控制面组件健康状态。">
      <template #actions><AdminGuideLink section="operations" /><NButton secondary :loading="loading" @click="load">重新检查</NButton></template>
    </PageHeader>
    <div v-if="error" class="error-panel" style="margin-bottom: 16px">{{ error }}</div>

    <section class="metric-grid operations-metrics" aria-label="运行指标">
      <article class="metric metric-primary surface"><div class="metric-icon"><NIcon :component="Activity" /></div><div class="metric-value">{{ loading ? '--' : (metrics?.call_count ?? '--') }}</div><div class="metric-label">累计调用</div><div class="metric-note">{{ metrics?.published_agent_count ?? 0 }} 个已发布</div></article>
      <article class="metric surface"><div class="metric-icon"><NIcon :component="ChartBar" /></div><div class="metric-value">{{ loading ? '--' : latency(metrics?.average_latency_ms) }}</div><div class="metric-label">平均延迟</div></article>
      <article class="metric surface"><div class="metric-icon"><NIcon :component="Coin" /></div><div class="metric-value">{{ loading ? '--' : (metrics?.token_usage ?? '--') }}</div><div class="metric-label">Token 使用量</div></article>
      <article class="metric surface"><div class="metric-icon"><NIcon :component="Heartbeat" /></div><div class="metric-value">{{ loading ? '--' : (metrics?.failure_count ?? '--') }}</div><div class="metric-label">错误数</div><div class="metric-note">{{ percent(metrics?.error_rate) }}</div></article>
    </section>

    <div class="operations-grid">
      <section class="surface panel-flush">
        <div class="section-heading"><div><h2>Agent 指标</h2><p>仅展示生产调用聚合，不推测缺失数据</p></div></div>
        <div class="operations-table-head"><span>Agent</span><span>调用</span><span>成功率</span><span>延迟</span><span>Token</span><span>MCP</span></div>
        <div v-if="loading" class="loading-stack" style="padding: 16px"><div v-for="index in 4" :key="index" class="skeleton-line" /></div>
        <div v-else-if="agentMetrics.length === 0" class="version-empty">暂无 Agent 生产调用指标。</div>
        <div v-for="item in agentMetrics" v-else :key="item.agent_id" class="operations-table-row">
          <div><strong>{{ item.agent_name || item.agent_id }}</strong><span class="mono">{{ item.agent_id }}</span></div>
          <span>{{ item.call_count }}</span><span>{{ percent(item.success_rate) }}</span><span>{{ latency(item.average_latency_ms) }}</span><span>{{ item.token_usage ?? '--' }}</span><span>{{ item.mcp_call_count }}</span>
        </div>
      </section>

      <aside class="surface panel">
        <div class="section-heading"><div><h2>Runtime Health</h2><p>来自 FastAPI /health</p></div><StatusTag :status="health?.status || 'unknown'" /></div>
        <div class="health-component-list">
          <div v-for="item in runtimeComponents" :key="item.key" class="health-component-row">
            <span class="binding-icon"><NIcon :component="item.icon" /></span>
            <div><strong>{{ item.label }}</strong><span>{{ item.detail }}</span></div>
            <StatusTag :status="item.status" />
          </div>
        </div>
      </aside>
    </div>

    <section class="surface panel" style="margin-top: 16px">
      <div class="section-heading"><div><h2>基础设施健康</h2><p>数据库、记忆、知识、队列与产物存储</p></div></div>
      <div class="health-infrastructure-grid"><div v-for="item in components" :key="item.key" class="health-component-row"><span class="binding-icon"><NIcon :component="item.icon" /></span><strong>{{ item.label }}</strong><StatusTag :status="item.status" /></div></div>
    </section>
  </div>
</template>
