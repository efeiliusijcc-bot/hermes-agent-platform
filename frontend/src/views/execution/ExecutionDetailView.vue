<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import { Activity, ArrowLeft, Copy, Refresh } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import ExecutionTimeline from '@/components/execution/ExecutionTimeline.vue'
import ResultViewer from '@/components/execution/ResultViewer.vue'
import RuntimeMetrics from '@/components/execution/RuntimeMetrics.vue'
import { useExecutionStore } from '@/stores/executions'
import { formatDate } from '@/utils/format'
import { formatJson } from '@/utils/executionStudio'

type Section = 'overview' | 'input' | 'output' | 'artifacts' | 'trace' | 'logs'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const executionStore = useExecutionStore()
const executionId = computed(() => String(route.params.id))
const section = ref<Section>('overview')
const execution = computed(() => executionStore.currentExecution)
const active = computed(() => ['queued', 'running'].includes(execution.value?.status || ''))
const newExecutionId = ref<string | null>(null)
let timer: number | null = null
let alive = true

function stopTimer() {
  if (timer !== null) window.clearTimeout(timer)
  timer = null
}

async function load() {
  stopTimer()
  try {
    await executionStore.fetchExecution(executionId.value)
  } catch {
    return
  }
  if (alive && active.value) timer = window.setTimeout(load, 3000)
}

async function retry() {
  try {
    const id = await executionStore.retryExecution(executionId.value, execution.value?.priority ?? undefined)
    newExecutionId.value = id
    message.success('重跑任务已进入队列')
  } catch {
    message.error(executionStore.error || '重跑失败')
  }
}

async function copyId() {
  try {
    await navigator.clipboard.writeText(executionId.value)
    message.success('Execution ID 已复制')
  } catch {
    message.error('复制失败')
  }
}

watch(executionId, () => {
  newExecutionId.value = null
  section.value = 'overview'
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
    <PageHeader title="执行详情" description="查看一次任务的输入、输出、Artifact、Trace 和生命周期元数据。">
      <template #actions>
        <NButton @click="router.push({ name: 'executions' })"><template #icon><NIcon :component="ArrowLeft" /></template>返回历史</NButton>
        <NButton :loading="executionStore.loading" @click="load"><template #icon><NIcon :component="Refresh" /></template>刷新</NButton>
        <NButton type="primary" :loading="executionStore.retrying" :disabled="!execution || active" @click="retry">重跑</NButton>
      </template>
    </PageHeader>

    <div v-if="executionStore.error" class="error-panel execution-page-error">{{ executionStore.error }}</div>
    <div v-if="executionStore.loading && !execution" class="detail-loading-grid"><div v-for="index in 8" :key="index" class="skeleton-line" /></div>

    <template v-else-if="execution">
      <section class="surface execution-detail-header">
        <div>
          <div class="execution-detail-id"><strong class="mono">{{ execution.id }}</strong><NButton text aria-label="复制 Execution ID" @click="copyId"><NIcon :component="Copy" /></NButton></div>
          <p>{{ execution.agent_name }} / {{ execution.agent_id }}</p>
        </div>
        <StatusTag :status="execution.status" />
      </section>

      <RuntimeMetrics
        :duration-ms="execution.duration_ms"
        :token-usage="execution.token_usage"
        :skill-count="execution.skill_count"
        :mcp-call-count="execution.mcp_call_count"
        :memory-read-count="execution.memory_read_count"
        :artifact-count="execution.artifact_count"
      />

      <nav class="detail-tabs execution-detail-tabs" aria-label="执行详情导航">
        <button v-for="item in [
          ['overview', 'Overview'], ['input', 'Input'], ['output', 'Output'], ['artifacts', 'Artifacts'], ['trace', 'Trace'], ['logs', 'Logs'],
        ]" :key="item[0]" type="button" :class="{ active: section === item[0] }" @click="section = item[0] as Section">{{ item[1] }}</button>
      </nav>

      <NAlert v-if="execution.error" type="error" :title="execution.error" class="execution-detail-alert" />
      <NAlert v-if="newExecutionId" type="success" class="execution-detail-alert">
        新 Execution 已创建：<NButton text type="primary" @click="router.push({ name: 'execution-detail', params: { id: newExecutionId } })"><span class="mono">{{ newExecutionId }}</span></NButton>
      </NAlert>

      <div class="execution-detail-grid">
        <div class="execution-detail-main">
          <section v-show="section === 'overview'" class="surface execution-detail-section">
            <div class="section-heading"><div><h2>执行概览</h2><p>任务、结果状态与完整链路入口</p></div></div>
            <div class="execution-task-block">{{ execution.input_json.task || execution.input }}</div>
            <dl class="execution-overview-grid">
              <div><dt>Trace 节点</dt><dd>{{ execution.trace_step_count }}</dd></div>
              <div><dt>失败节点</dt><dd>{{ execution.failed_step_count }}</dd></div>
              <div><dt>输出</dt><dd>{{ execution.output ? '已生成' : active ? '等待中' : '无' }}</dd></div>
              <div><dt>Artifact</dt><dd>{{ execution.artifact_count }}</dd></div>
            </dl>
            <NButton type="primary" secondary @click="router.push({ name: 'trace-detail', params: { id: execution.id } })">
              <template #icon><NIcon :component="Activity" /></template>在 Trace Center 查看完整链路
            </NButton>
          </section>

          <section v-show="section === 'input'" class="surface execution-detail-section">
            <div class="section-heading"><div><h2>输入</h2><p>自然语言任务与 Schema 参数</p></div></div>
            <div class="execution-task-block">{{ execution.input_json.task || execution.input }}</div>
            <pre class="json-viewer">{{ formatJson(execution.input_json.parameters || {}) }}</pre>
          </section>

          <section v-show="section === 'output'" class="surface execution-detail-section">
            <div class="section-heading"><div><h2>输出</h2><p>安全文本渲染，不注入模型 HTML</p></div></div>
            <ResultViewer :output="execution.output" :output-json="execution.output_json" :artifacts="execution.artifacts" :steps="execution.steps" :details="execution.details" :active="active" />
          </section>

          <section v-show="section === 'artifacts'" class="surface execution-detail-section">
            <div class="section-heading"><div><h2>Artifacts</h2><p>下载产物并核对大小与 SHA-256</p></div></div>
            <ResultViewer :output="execution.output" :output-json="execution.output_json" :artifacts="execution.artifacts" :steps="execution.steps" :details="execution.details" :active="active" initial-tab="artifacts" />
          </section>

          <section v-show="section === 'trace'" class="surface execution-detail-section">
            <div class="section-heading"><div><h2>关联 Trace</h2><p>{{ execution.steps.length }} 个结构化节点</p></div><NButton secondary @click="router.push({ name: 'trace-detail', params: { id: execution.id } })">完整分析</NButton></div>
            <ExecutionTimeline :steps="execution.steps" :active="active" />
          </section>

          <section v-show="section === 'logs'" class="surface execution-detail-section">
            <div class="section-heading"><div><h2>Execution Logs</h2><p>当前控制面可查询的持久化 details</p></div></div>
            <NAlert type="info" :bordered="false" style="margin-bottom: 14px">容器标准输出尚未通过控制面 API 暴露；这里不使用伪造日志替代。</NAlert>
            <pre class="json-viewer">{{ formatJson(execution.details) }}</pre>
          </section>
        </div>

        <aside class="surface execution-detail-section execution-detail-aside">
          <div class="section-heading"><div><h2>运行信息</h2><p>Execution 生命周期元数据</p></div></div>
          <dl class="execution-definition-list">
            <div><dt>状态</dt><dd><StatusTag :status="execution.status" /></dd></div>
            <div><dt>模式</dt><dd>{{ execution.response_mode }}</dd></div>
            <div><dt>Session</dt><dd class="mono">{{ execution.memory_session_id || execution.session_id || '--' }}</dd></div>
            <div><dt>模型</dt><dd class="mono">{{ execution.model || '--' }}</dd></div>
            <div><dt>适配器</dt><dd>{{ execution.model_adapter || '--' }}</dd></div>
            <div><dt>Schema 版本</dt><dd class="mono">{{ execution.schema_version || '--' }}</dd></div>
            <div><dt>Agent Version</dt><dd class="mono">{{ execution.agent_version || execution.agent_version_id || '历史记录未归属版本' }}</dd></div>
            <div><dt>优先级</dt><dd>{{ execution.priority ?? '--' }}</dd></div>
            <div><dt>开始时间</dt><dd>{{ formatDate(execution.started_at) }}</dd></div>
            <div><dt>结束时间</dt><dd>{{ formatDate(execution.finished_at) }}</dd></div>
            <div><dt>来源 Execution</dt><dd class="mono">{{ execution.retry_of_execution_id || '--' }}</dd></div>
            <div><dt>Queue Task</dt><dd class="mono">{{ execution.queue_task?.id || '--' }}</dd></div>
          </dl>
        </aside>
      </div>
    </template>
  </div>
</template>
