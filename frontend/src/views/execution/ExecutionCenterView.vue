<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { NDatePicker, NIcon, NPagination } from 'naive-ui'
import { Refresh, Search } from '@vicons/tabler'
import { useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import ExecutionMetricCard from '@/components/execution/ExecutionMetricCard.vue'
import ExecutionTable from '@/components/execution/ExecutionTable.vue'
import { useAgentStore } from '@/stores/agents'
import { useExecutionStore } from '@/stores/executions'

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
const successRate = computed(() => executionStore.metrics.success_rate === null ? '--' : `${executionStore.metrics.success_rate.toFixed(1)}%`)

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
    <PageHeader title="执行历史中心" description="查询任务执行状态、结果、Token 与 Artifact，并进入单次执行详情。">
      <template #actions>
        <NButton :loading="executionStore.loading" @click="load()"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
      </template>
    </PageHeader>

    <section class="execution-metric-grid" aria-label="执行统计">
      <ExecutionMetricCard label="Total Executions" :value="executionStore.metrics.total_executions" note="当前筛选范围" />
      <ExecutionMetricCard label="Running" :value="executionStore.metrics.running" tone="active" note="持续自动刷新" />
      <ExecutionMetricCard label="Success Rate" :value="successRate" tone="success" note="成功 / 已完成" />
      <ExecutionMetricCard label="Failed" :value="executionStore.metrics.failed" tone="danger" note="当前筛选范围" />
    </section>

    <section class="surface execution-history-shell">
      <div class="execution-history-toolbar">
        <NInput v-model:value="search" clearable placeholder="搜索 Execution ID、Agent 或任务" @keyup.enter="applyFilters">
          <template #prefix><NIcon :component="Search" /></template>
        </NInput>
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
      <ExecutionTable
        :items="executionStore.histories"
        :loading="executionStore.loading"
        @select="router.push({ name: 'execution-detail', params: { id: $event } })"
      >
        <template #empty>
          <div><h3>没有匹配的执行记录</h3><p>调整筛选条件，或先从执行工作台提交任务。</p><NButton @click="resetFilters">清除筛选</NButton></div>
        </template>
      </ExecutionTable>

      <div v-if="executionStore.total > pageSize" class="execution-pagination">
        <span>共 {{ executionStore.total }} 条</span>
        <NPagination :page="page" :page-count="pageCount" @update:page="changePage" />
      </div>
    </section>
  </div>
</template>
