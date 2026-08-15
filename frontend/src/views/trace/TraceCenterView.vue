<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { NDatePicker, NIcon, NPagination } from 'naive-ui'
import { ArrowRight, Refresh, Search } from '@vicons/tabler'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import ExecutionMetricCard from '@/components/execution/ExecutionMetricCard.vue'
import { useAgentStore } from '@/stores/agents'
import { useExecutionStore } from '@/stores/executions'
import { formatDate } from '@/utils/format'
import { formatDurationMs } from '@/utils/executionStudio'

const router = useRouter()
const agentStore = useAgentStore()
const executionStore = useExecutionStore()
const agentId = ref<string | null>(null)
const status = ref<string | null>(null)
const search = ref('')
const dateRange = ref<[number, number] | null>(null)
const page = ref(1)
const pageSize = 50
let timer: number | null = null
let alive = true

const pageCount = computed(() => Math.max(1, Math.ceil(executionStore.total / pageSize)))
const agentOptions = computed(() => agentStore.agents.map((item) => ({ label: item.name, value: item.id })))
const pageNodeCount = computed(() => executionStore.histories.reduce((sum, item) => sum + item.trace_step_count, 0))
const pageFailedNodes = computed(() => executionStore.histories.reduce((sum, item) => sum + item.failed_step_count, 0))
const pageMcpCalls = computed(() => executionStore.histories.reduce((sum, item) => sum + item.mcp_call_count, 0))
const pageModelCalls = computed(() => executionStore.histories.reduce((sum, item) => sum + item.model_call_count, 0))

function stopTimer() {
  if (timer !== null) window.clearTimeout(timer)
  timer = null
}

function scheduleRefresh() {
  stopTimer()
  if (!alive || executionStore.metrics.running === 0) return
  timer = window.setTimeout(() => load(false), 5000)
}

async function load(showError = true) {
  stopTimer()
  try {
    await executionStore.fetchHistories({
      ...(agentId.value ? { agent_id: agentId.value } : {}),
      ...(status.value ? { status: status.value } : {}),
      ...(search.value.trim() ? { search: search.value.trim() } : {}),
      ...(dateRange.value ? {
        started_from: new Date(dateRange.value[0]).toISOString(),
        started_to: new Date(dateRange.value[1]).toISOString(),
      } : {}),
      limit: pageSize,
      offset: (page.value - 1) * pageSize,
    })
  } catch {
    if (!showError) return
  } finally {
    scheduleRefresh()
  }
}

function applyFilters() {
  page.value = 1
  load()
}

function resetFilters() {
  agentId.value = null
  status.value = null
  search.value = ''
  dateRange.value = null
  page.value = 1
  load()
}

function changePage(value: number) {
  page.value = value
  load()
}

onMounted(async () => {
  await Promise.allSettled([agentStore.fetchAgents(), load()])
})
onBeforeUnmount(() => {
  alive = false
  stopTimer()
})
</script>

<template>
  <div>
    <PageHeader title="Trace Center" description="分析 Agent 执行链中的 Skill、MCP、Knowledge、Model 与 Artifact 节点。">
      <template #actions>
        <NButton :loading="executionStore.loading" @click="load()"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
      </template>
    </PageHeader>

    <section class="execution-metric-grid trace-metric-grid" aria-label="Trace 统计">
      <ExecutionMetricCard label="Total Traces" :value="executionStore.metrics.total_executions" note="当前筛选范围" />
      <ExecutionMetricCard label="Trace Nodes" :value="pageNodeCount" note="当前页真实节点" />
      <ExecutionMetricCard label="Failed Nodes" :value="pageFailedNodes" tone="danger" note="当前页失败节点" />
      <ExecutionMetricCard label="MCP / Model" :value="`${pageMcpCalls} / ${pageModelCalls}`" tone="active" note="当前页调用数" />
    </section>

    <section class="surface trace-center-shell">
      <div class="execution-history-toolbar">
        <NInput v-model:value="search" clearable placeholder="搜索 Execution ID、Agent 或任务" @keyup.enter="applyFilters"><template #prefix><NIcon :component="Search" /></template></NInput>
        <NSelect v-model:value="agentId" :options="agentOptions" clearable filterable placeholder="全部 Agent" />
        <NSelect v-model:value="status" clearable placeholder="全部状态" :options="[
          { label: '排队中', value: 'queued' }, { label: '执行中', value: 'running' },
          { label: '成功', value: 'succeeded' }, { label: '失败', value: 'failed' },
          { label: '已取消', value: 'cancelled' },
        ]" />
        <NDatePicker v-model:value="dateRange" type="datetimerange" clearable :actions="['confirm']" />
        <NButton type="primary" @click="applyFilters">查询</NButton>
        <NButton @click="resetFilters">重置</NButton>
      </div>

      <div v-if="executionStore.error" class="error-panel execution-history-error">{{ executionStore.error }}</div>
      <div class="trace-table-head" aria-hidden="true">
        <span>Trace / Agent</span><span>Status</span><span>Nodes</span><span>Failed</span><span>Skill</span><span>MCP</span><span>Model</span><span>Duration</span><span>Created</span><span></span>
      </div>
      <div v-if="executionStore.loading" class="execution-table-loading"><div v-for="index in 6" :key="index" class="skeleton-line" /></div>
      <div v-else-if="executionStore.histories.length" class="execution-table-body">
        <button
          v-for="item in executionStore.histories"
          :key="item.id"
          type="button"
          class="trace-table-row"
          :aria-label="`查看 Trace ${item.id}`"
          @click="router.push({ name: 'trace-detail', params: { id: item.id } })"
        >
          <span class="execution-id-cell"><strong class="mono">{{ item.id }}</strong><small>{{ item.agent_name }} / {{ item.agent_id }}</small></span>
          <span><StatusTag :status="item.status" /></span>
          <span class="mono">{{ item.trace_step_count }}</span>
          <span class="mono" :class="{ 'trace-failed-value': item.failed_step_count > 0 }">{{ item.failed_step_count }}</span>
          <span class="mono">{{ item.skill_count }}</span>
          <span class="mono">{{ item.mcp_call_count }}</span>
          <span class="mono">{{ item.model_call_count }}</span>
          <span class="mono">{{ formatDurationMs(item.duration_ms) }}</span>
          <span>{{ formatDate(item.started_at) }}</span>
          <NIcon :component="ArrowRight" />
        </button>
      </div>
      <div v-else class="empty-state"><div><h3>没有匹配的 Trace</h3><p>Trace 来自真实 Execution；调整筛选条件或先执行 Agent。</p><NButton @click="resetFilters">清除筛选</NButton></div></div>

      <div v-if="executionStore.total > pageSize" class="execution-pagination">
        <span>共 {{ executionStore.total }} 条</span>
        <NPagination :page="page" :page-count="pageCount" @update:page="changePage" />
      </div>
    </section>
  </div>
</template>
