<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import { Activity, Hierarchy, PlugConnected, Plus, Robot, TestPipe } from '@vicons/tabler'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { useAgentStore } from '@/stores/agents'
import { useResourceStore } from '@/stores/resources'
import { useSystemStore } from '@/stores/system'
import { platformApi } from '@/api/platform'
import type { ExecutionLog } from '@/types/api'
import { formatDate, truncate } from '@/utils/format'

const router = useRouter()
const agentStore = useAgentStore()
const resourceStore = useResourceStore()
const systemStore = useSystemStore()
const recentRuns = ref<ExecutionLog[]>([])
const loadingRuns = ref(false)
const pageError = ref<string | null>(null)

const failedRuns = computed(() => recentRuns.value.filter((run) => run.status === 'failed').length)

async function loadDashboard() {
  pageError.value = null
  try {
    await Promise.all([
      agentStore.fetchAgents(),
      resourceStore.fetchAll(),
      systemStore.fetchHealth().catch(() => undefined),
    ])
    loadingRuns.value = true
    const settled = await Promise.allSettled(agentStore.agents.map((agent) => platformApi.listAgentRuns(agent.id)))
    recentRuns.value = settled
      .flatMap((result) => (result.status === 'fulfilled' ? result.value : []))
      .sort((left, right) => new Date(right.started_at).valueOf() - new Date(left.started_at).valueOf())
      .slice(0, 8)
  } catch {
    pageError.value = agentStore.error || resourceStore.error || '总览数据加载失败'
  } finally {
    loadingRuns.value = false
  }
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
      <article class="metric metric-primary surface">
        <div class="metric-icon"><NIcon :component="Robot" size="18" /></div>
        <div class="metric-value">{{ agentStore.loading ? '-' : agentStore.agents.length }}</div>
        <div class="metric-label">已注册 Agent</div>
        <div class="metric-note">{{ agentStore.activeAgentCount }} 个已启用</div>
      </article>
      <article class="metric surface">
        <div class="metric-icon"><NIcon :component="Hierarchy" size="18" /></div>
        <div class="metric-value">{{ resourceStore.loading ? '-' : resourceStore.skills.length }}</div>
        <div class="metric-label">可绑定 Skill</div>
      </article>
      <article class="metric surface">
        <div class="metric-icon"><NIcon :component="PlugConnected" size="18" /></div>
        <div class="metric-value">{{ resourceStore.loading ? '-' : resourceStore.mcpServers.length }}</div>
        <div class="metric-label">只读 MCP</div>
      </article>
      <article class="metric surface">
        <div class="metric-icon"><NIcon :component="Activity" size="18" /></div>
        <div class="metric-value">{{ loadingRuns ? '-' : recentRuns.length }}</div>
        <div class="metric-label">最近加载的执行</div>
      </article>
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
          <div
            v-for="run in recentRuns"
            :key="run.id"
            class="history-row"
            @click="router.push({ name: 'agent-playground', params: { id: run.agent_id } })"
          >
            <StatusTag :status="run.status" />
            <div class="history-input truncate">{{ truncate(run.input, 100) }}</div>
            <div class="mono muted" style="font-size: 10px">{{ run.agent_id }}</div>
            <div class="muted" style="font-size: 10px">{{ formatDate(run.started_at) }}</div>
          </div>
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
            Agent 运行是同步接口。执行过程来自完成后的 ExecutionLog，不显示伪造的实时流式状态。
          </p>
          <p class="muted" style="margin: 10px 0 0; font-size: 12px; line-height: 1.7">
            最近记录中有 {{ failedRuns }} 次失败。失败原因以后端 `error` 字段为准。
          </p>
        </section>
      </aside>
    </div>
  </div>
</template>
