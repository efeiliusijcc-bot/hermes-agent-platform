<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { ArrowLeft, ListCheck, Refresh } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import ExecutionMetricCard from '@/components/execution/ExecutionMetricCard.vue'
import TraceDetailDrawer from '@/components/trace/TraceDetailDrawer.vue'
import TraceTimeline from '@/components/trace/TraceTimeline.vue'
import { useExecutionStore } from '@/stores/executions'
import { formatDate } from '@/utils/format'
import { formatCount, formatDurationMs } from '@/utils/executionStudio'
import type { ExecutionStep } from '@/types/api'

const route = useRoute()
const router = useRouter()
const executionStore = useExecutionStore()
const executionId = computed(() => String(route.params.id))
const trace = computed(() => executionStore.currentTrace?.execution_id === executionId.value ? executionStore.currentTrace : null)
const active = computed(() => ['queued', 'running'].includes(trace.value?.status || ''))
const selectedNode = ref<ExecutionStep | null>(null)
const drawerOpen = ref(false)
let timer: number | null = null
let alive = true

function stopTimer() {
  if (timer !== null) window.clearTimeout(timer)
  timer = null
}

async function load() {
  stopTimer()
  try {
    const value = await executionStore.fetchTrace(executionId.value)
    if (selectedNode.value) selectedNode.value = value.nodes.find((node) => node.id === selectedNode.value?.id) || null
  } catch {
    return
  }
  if (alive && active.value) timer = window.setTimeout(load, 3000)
}

function inspectNode(node: ExecutionStep) {
  selectedNode.value = node
  drawerOpen.value = true
}

watch(executionId, () => {
  selectedNode.value = null
  drawerOpen.value = false
  load()
})
onMounted(load)
onBeforeUnmount(() => {
  alive = false
  stopTimer()
})
</script>

<template>
  <div>
    <PageHeader title="Trace Detail" description="按时间顺序检查结构化节点的状态、输入、输出、延迟和错误。">
      <template #actions>
        <NButton @click="router.push({ name: 'execution-trace' })"><template #icon><NIcon :component="ArrowLeft" /></template>返回 Trace</NButton>
        <NButton @click="router.push({ name: 'execution-detail', params: { id: executionId } })"><template #icon><NIcon :component="ListCheck" /></template>执行详情</NButton>
        <NButton :loading="executionStore.loading" @click="load"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
      </template>
    </PageHeader>

    <div v-if="executionStore.error" class="error-panel execution-page-error">{{ executionStore.error }}</div>
    <div v-if="executionStore.loading && !trace" class="detail-loading-grid"><div v-for="index in 8" :key="index" class="skeleton-line" /></div>

    <template v-else-if="trace">
      <section class="surface trace-detail-header">
        <div><strong class="mono">{{ trace.execution_id }}</strong><p>{{ trace.agent_name }} / {{ trace.agent_id }}</p></div>
        <StatusTag :status="trace.status" />
      </section>

      <NAlert v-if="trace.error" type="error" :title="trace.error" class="execution-detail-alert" />

      <section class="execution-metric-grid trace-detail-metrics" aria-label="Trace 指标">
        <ExecutionMetricCard label="Nodes" :value="trace.metrics.total_nodes" note="结构化执行节点" />
        <ExecutionMetricCard label="Failed Nodes" :value="trace.metrics.failed_nodes" tone="danger" note="用于定位失败阶段" />
        <ExecutionMetricCard label="MCP / Model" :value="`${trace.metrics.mcp_calls} / ${trace.metrics.model_calls}`" tone="active" note="真实调用节点" />
        <ExecutionMetricCard label="Slowest Node" :value="formatDurationMs(trace.metrics.slowest_node_ms)" note="节点记录中的最大延迟" />
      </section>

      <div class="trace-detail-layout">
        <section class="surface trace-timeline-panel">
          <div class="section-heading"><div><h2>Trace Timeline</h2><p>选择节点查看完整输入与输出</p></div><span class="trace-latency-total">节点累计 {{ formatDurationMs(trace.metrics.total_latency_ms) }}</span></div>
          <TraceTimeline :nodes="trace.nodes" :selected-id="selectedNode?.id" :active="active" @select="inspectNode" />
        </section>

        <aside class="surface trace-context-panel">
          <div class="section-heading"><div><h2>执行上下文</h2><p>Trace 与 Execution 的关联信息</p></div></div>
          <dl class="execution-definition-list">
            <div><dt>Session</dt><dd class="mono">{{ trace.memory_session_id || trace.session_id || '--' }}</dd></div>
            <div><dt>Agent Version</dt><dd class="mono">{{ trace.agent_version || trace.agent_version_id || '--' }}</dd></div>
            <div><dt>Model</dt><dd class="mono">{{ trace.model || '--' }}</dd></div>
            <div><dt>Adapter</dt><dd>{{ trace.model_adapter || '--' }}</dd></div>
            <div><dt>Token</dt><dd>{{ formatCount(trace.token_usage) }}</dd></div>
            <div><dt>Duration</dt><dd>{{ formatDurationMs(trace.duration_ms) }}</dd></div>
            <div><dt>Started</dt><dd>{{ formatDate(trace.started_at) }}</dd></div>
            <div><dt>Finished</dt><dd>{{ formatDate(trace.finished_at) }}</dd></div>
            <div><dt>Artifacts</dt><dd>{{ trace.artifacts.length }}</dd></div>
          </dl>
        </aside>
      </div>

      <TraceDetailDrawer v-model:show="drawerOpen" :node="selectedNode" :trace="trace" />
    </template>
  </div>
</template>
