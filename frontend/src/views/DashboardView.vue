<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import { Activity, AlertTriangle, Coin, Plus, Robot, TestPipe } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import MetricCard from '@/components/common/MetricCard.vue'
import { useAgentStore } from '@/stores/agents'
import { useResourceStore } from '@/stores/resources'
import { useSystemStore } from '@/stores/system'
import { platformApi } from '@/api/platform'
import type { AgentTask, AuditLog, ExecutionLog, MetricsSummary } from '@/types/api'
import { formatDate, truncate } from '@/utils/format'

const router = useRouter()
const agentStore = useAgentStore()
const resourceStore = useResourceStore()
const systemStore = useSystemStore()
const recentRuns = ref<ExecutionLog[]>([])
const loadingRuns = ref(false)
const pageError = ref<string | null>(null)
const tasks = ref<AgentTask[]>([])
const metrics = ref<MetricsSummary | null>(null)
const recentAudit = ref<AuditLog[]>([])
const metricsLoading = ref(false)

const failedRuns = computed(() => recentRuns.value.filter((run) => run.status === 'failed').length)
const runningCount = computed(() => tasks.value.filter((item) => ['pending', 'retrying', 'running'].includes(item.status)).length)
const todayExecutionCount = computed(() => {
  const today = new Date()
  return recentRuns.value.filter((run) => {
    const value = new Date(run.started_at)
    return value.getFullYear() === today.getFullYear()
      && value.getMonth() === today.getMonth()
      && value.getDate() === today.getDate()
  }).length
})

async function loadDashboard() {
  pageError.value = null
  try {
    await Promise.all([
      agentStore.fetchAgents(),
      resourceStore.fetchAll(),
      systemStore.fetchHealth().catch(() => undefined),
    ])
    loadingRuns.value = true
    metricsLoading.value = true
    const [metricsResult, auditResult, ...settled] = await Promise.allSettled([
      platformApi.getMetricsSummary(),
      platformApi.listAuditLogs({ limit: 6 }),
      ...agentStore.agents.map((agent) => platformApi.listAgentRuns(agent.id)),
    ])
    metrics.value = metricsResult.status === 'fulfilled' ? metricsResult.value : null
    recentAudit.value = auditResult.status === 'fulfilled' ? auditResult.value : []
    recentRuns.value = settled
      .flatMap((result) => (result.status === 'fulfilled' ? result.value : []))
      .sort((left, right) => new Date(right.started_at).valueOf() - new Date(left.started_at).valueOf())
      .slice(0, 8)
    tasks.value = await platformApi.listTasks()
  } catch {
    pageError.value = agentStore.error || resourceStore.error || '总览数据加载失败'
  } finally {
    loadingRuns.value = false
    metricsLoading.value = false
  }
}

function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--'
  const normalized = value <= 1 ? value * 100 : value
  return `${normalized.toFixed(1)}%`
}

onMounted(loadDashboard)
</script>

<template>
  <div>
    <PageHeader
      eyebrow="Control plane"
      title="企业 Agent 运行总览"
      description="管理受控 Agent、能力资源和 Hermes 执行结果。页面数据全部来自当前 FastAPI 控制面。"
    >
      <template #actions>
        <NButton secondary @click="router.push({ name: 'agents' })">
          <template #icon><NIcon :component="Robot" /></template>
          查看 Agent
        </NButton>
        <NButton type="primary" @click="router.push({ name: 'agent-create' })">
          <template #icon><NIcon :component="Plus" /></template>
          创建 Agent
        </NButton>
      </template>
    </PageHeader>

    <div v-if="pageError" class="error-panel" style="margin-bottom: 16px">{{ pageError }}</div>

    <section class="metric-grid" aria-label="平台指标">
      <MetricCard
        label="Agent 数量"
        :value="agentStore.loading ? '--' : (metrics?.agent_count ?? agentStore.agents.length)"
        :note="metrics ? `${metrics.published_agent_count} 个已发布` : `${agentStore.activeAgentCount} 个可运行`"
        primary
      ><template #icon><NIcon :component="Robot" size="18" /></template></MetricCard>
      <MetricCard label="运行数量" :value="loadingRuns ? '--' : runningCount" note="排队、重试或执行中">
        <template #icon><NIcon :component="Activity" size="18" /></template>
      </MetricCard>
      <MetricCard label="今日执行" :value="loadingRuns ? '--' : todayExecutionCount" note="当前已加载记录">
        <template #icon><NIcon :component="Coin" size="18" /></template>
      </MetricCard>
      <MetricCard label="成功率" :value="metricsLoading ? '--' : formatPercent(metrics?.success_rate)" :note="metrics ? `${metrics.call_count} 次生产调用` : '指标接口暂不可用'">
        <template #icon><NIcon :component="AlertTriangle" size="18" /></template>
      </MetricCard>
    </section>

    <div class="content-grid">
      <section class="surface panel-flush">
        <div class="section-heading">
          <div>
            <h2>最近执行</h2>
            <p>从每个 Agent 的真实运行记录中汇总</p>
          </div>
          <NButton text type="primary" @click="loadDashboard">刷新</NButton>
        </div>
        <div v-if="loadingRuns" class="loading-stack" style="padding: 12px 20px 20px">
          <div v-for="index in 4" :key="index" class="skeleton-line" />
        </div>
        <div v-else-if="recentRuns.length === 0" class="empty-state">
          <div>
            <div class="empty-state-icon"><NIcon :component="TestPipe" size="24" /></div>
            <h3>还没有执行记录</h3>
            <p>创建并启用 Agent 后，在执行台提交任务，运行结果会显示在这里。</p>
          </div>
        </div>
        <div v-else>
          <button
            v-for="run in recentRuns"
            :key="run.id"
            class="history-row"
            type="button"
            @click="router.push({ name: 'execution-detail', params: { id: run.id } })"
          >
            <div class="history-execution"><strong class="mono">{{ run.id }}</strong><span>{{ run.agent_id }}</span></div>
            <div class="history-input truncate">{{ truncate(run.input, 100) }}</div>
            <div class="mono muted">{{ run.agent_version_id || '未记录版本' }}</div>
            <StatusTag :status="run.status" />
            <div class="mono muted">{{ run.duration_ms === null ? '--' : `${run.duration_ms} ms` }}</div>
            <div class="muted">{{ formatDate(run.started_at) }}</div>
          </button>
        </div>
      </section>

      <aside class="detail-stack">
        <section class="surface panel">
          <div class="section-heading">
            <div><h2>平台状态</h2><p>FastAPI `/health` 实时结果</p></div>
            <StatusTag :status="systemStore.health?.status || 'failed'" />
          </div>
          <div class="binding-list" style="margin-top: 18px">
            <div v-for="item in ['database', 'memory', 'knowledge']" :key="item" class="binding-row">
              <div>
                <strong>{{ { database: 'PostgreSQL', memory: 'Redis Memory', knowledge: 'Knowledge Service' }[item] }}</strong>
                <span>{{ systemStore.health?.[item as keyof typeof systemStore.health] === 'ok' ? '后端检查通过' : '未确认在线' }}</span>
              </div>
              <StatusTag :status="String(systemStore.health?.[item as keyof typeof systemStore.health] || 'failed')" style="margin-left: auto" />
            </div>
          </div>
        </section>
        <section class="surface panel">
          <div class="section-heading"><div><h2>执行提示</h2><p>当前后端能力边界</p></div></div>
          <p class="muted" style="margin: 14px 0 0; font-size: 12px; line-height: 1.7">
            同步 JSON、真实 SSE 与 Redis 异步队列并存；异步任务由 Worker Pool 执行，最终状态以后端 Task、Session 和 ExecutionLog 为准。
          </p>
          <p class="muted" style="margin: 10px 0 0; font-size: 12px; line-height: 1.7">
            最近记录中有 {{ failedRuns }} 次失败。失败原因以后端 `error` 字段为准。
          </p>
          <p class="muted" style="margin: 10px 0 0; font-size: 12px; line-height: 1.7">
            当前有 {{ tasks.filter((item) => ['pending','retrying','running'].includes(item.status)).length }} 个排队或执行中的异步任务。
          </p>
        </section>
      </aside>
    </div>

    <section class="surface panel-flush" style="margin-top: 18px">
      <div class="section-heading">
        <div><h2>最近调用审计</h2><p>不展示敏感输入，仅显示请求、Client、Agent 和生产调用指标</p></div>
        <span class="muted" style="font-size: 11px">{{ metrics ? `${metrics.call_count} 次累计调用` : '指标接口暂不可用' }}</span>
      </div>
      <div v-if="metricsLoading" class="loading-stack" style="padding: 12px 20px 20px"><div v-for="index in 3" :key="index" class="skeleton-line" /></div>
      <div v-else-if="recentAudit.length" class="audit-list">
        <div v-for="item in recentAudit" :key="item.id" class="audit-row">
          <StatusTag :status="item.status" />
          <div><strong class="mono">{{ item.request_id }}</strong><span>{{ item.agent_id }} · Client {{ item.client_id || '内部调用' }}</span></div>
          <span>{{ item.latency_ms }} ms</span>
          <span>{{ item.token_usage === null ? '--' : item.token_usage }} tokens</span>
          <span>{{ formatDate(item.created_at) }}</span>
        </div>
      </div>
      <div v-else class="version-empty">暂无可展示的生产调用审计记录。</div>
    </section>
  </div>
</template>
