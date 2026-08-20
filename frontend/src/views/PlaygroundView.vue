<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { NCollapse, NCollapseItem, NForm, NFormItem, NIcon, NInputNumber, useMessage } from 'naive-ui'
import { ArrowLeft, PlayerPlay, Settings } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import SchemaForm from '@/components/execution/SchemaForm.vue'
import ExecutionTimeline from '@/components/execution/ExecutionTimeline.vue'
import ResultViewer from '@/components/execution/ResultViewer.vue'
import RuntimeMetrics from '@/components/execution/RuntimeMetrics.vue'
import { platformApi } from '@/api/platform'
import { getApiErrorMessage } from '@/api/client'
import { useAgentStore } from '@/stores/agents'
import { useExecutionStore } from '@/stores/executions'
import { buildSchemaParameters, createInitialSchemaValues, formatJson } from '@/utils/executionStudio'
import type { AgentTask, AgentVersion } from '@/types/api'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const agentStore = useAgentStore()
const executionStore = useExecutionStore()
const agentId = computed(() => String(route.params.id))
const task = ref('')
const sessionId = ref('default')
const mode = ref<'sync' | 'stream' | 'async'>('sync')
const priority = ref(5)
const temperature = ref<number | null>(null)
const parameters = ref<Record<string, unknown>>({})
const parameterErrors = ref<Record<string, string>>({})
const submittedTask = ref<AgentTask | null>(null)
const versions = ref<AgentVersion[]>([])
const localError = ref<string | null>(null)

const agent = computed(() => agentStore.currentAgent)
const execution = computed(() => executionStore.currentExecution)
const executable = computed(() => agent.value?.status === 'active')
const currentVersion = computed(() => versions.value.find((item) => item.status === 'published') || versions.value[0] || null)
const schemaVersion = computed(() => String(currentVersion.value?.snapshot.schema?.version || execution.value?.schema_version || '--'))
const isActive = computed(() => executionStore.running || ['queued', 'running'].includes(execution.value?.status || ''))
const visibleOutput = computed(() => execution.value?.output || executionStore.streamedOutput || null)

async function load() {
  localError.value = null
  submittedTask.value = null
  executionStore.currentExecution = null
  try {
    const [, versionResult] = await Promise.all([
      agentStore.fetchAgentDetail(agentId.value),
      platformApi.listAgentVersions(agentId.value).catch(() => []),
    ])
    versions.value = versionResult
    mode.value = agent.value?.response_mode || 'sync'
    parameters.value = createInitialSchemaValues(agent.value?.input_schema || {})
    parameterErrors.value = {}
  } catch (error) {
    localError.value = getApiErrorMessage(error)
  }
}

async function submitRun() {
  localError.value = null
  if (!task.value.trim()) {
    message.warning('请输入需要 Agent 执行的任务')
    return
  }
  const built = buildSchemaParameters(agent.value?.input_schema || {}, parameters.value)
  parameterErrors.value = built.errors
  if (Object.keys(built.errors).length) {
    message.warning('请修正 Schema 输入字段')
    return
  }

  try {
    submittedTask.value = null
    if (mode.value === 'async') {
      const created = await platformApi.submitAgentTask(agentId.value, {
        input: task.value.trim(),
        session_id: sessionId.value.trim() || 'default',
        priority: priority.value,
        parameters: built.parameters,
        ...(temperature.value === null ? {} : { temperature: temperature.value }),
      })
      submittedTask.value = created
      if (created.execution_id) await executionStore.fetchExecution(created.execution_id)
      message.success('任务已进入 Worker 队列')
      return
    }
    await executionStore.runAgent(
      agentId.value,
      task.value.trim(),
      sessionId.value.trim() || 'default',
      mode.value as 'sync' | 'stream',
      built.parameters,
      temperature.value,
    )
    message.success(mode.value === 'stream' ? '流式执行完成' : 'Agent 执行成功')
  } catch (error) {
    localError.value = executionStore.error || getApiErrorMessage(error)
    message.error(localError.value, { duration: 7000 })
  }
}

watch(agentId, load)
onMounted(load)
</script>

<template>
  <div>
    <PageHeader title="执行工作台" description="以 Agent Schema 构造输入，统一查看同步、流式和异步执行的 Trace 与产物。">
      <template #actions>
        <NButton @click="router.push({ name: 'agent-detail', params: { id: agentId } })">
          <template #icon><NIcon :component="ArrowLeft" /></template>返回 Agent
        </NButton>
      </template>
    </PageHeader>

    <section class="surface execution-studio-header">
      <div class="execution-agent-identity">
        <div>
          <div class="execution-agent-title"><h2>{{ agent?.name || agentId }}</h2><StatusTag v-if="agent" :status="agent.status" /></div>
          <p>{{ agent?.description || '当前 Agent 没有说明。' }}</p>
        </div>
      </div>
      <dl class="execution-agent-meta">
        <div><dt>模型</dt><dd class="mono">{{ agent?.model || '--' }}</dd></div>
        <div><dt>适配器</dt><dd>{{ agent?.model_adapter || '--' }}</dd></div>
        <div><dt>Schema</dt><dd class="mono">{{ schemaVersion }}</dd></div>
        <div><dt>当前版本</dt><dd class="mono">{{ currentVersion?.version || '--' }}</dd></div>
      </dl>
    </section>

    <div v-if="localError || agentStore.error" class="error-panel execution-page-error">{{ localError || agentStore.error }}</div>

    <div class="execution-studio-grid">
      <section class="surface execution-input-panel">
        <div class="section-heading"><div><h2>输入</h2><p>任务与 Schema 参数分开传递</p></div></div>
        <NForm label-placement="top" @submit.prevent="submitRun">
          <NFormItem label="自然语言任务" required>
            <NInput v-model:value="task" type="textarea" :rows="6" maxlength="100000" show-count placeholder="描述需要 Agent 完成的任务" :disabled="executionStore.running" />
          </NFormItem>

          <div class="subsection-title">Schema 参数</div>
          <SchemaForm
            :schema="agent?.input_schema || {}"
            :values="parameters"
            :errors="parameterErrors"
            :disabled="executionStore.running"
            @update:values="parameters = $event"
          />

          <NCollapse class="execution-advanced">
            <NCollapseItem title="高级配置" name="advanced">
              <template #header-extra><NIcon :component="Settings" /></template>
              <NFormItem label="Session ID"><NInput v-model:value="sessionId" maxlength="128" :disabled="executionStore.running" /></NFormItem>
              <NFormItem label="执行模式">
                <NSelect v-model:value="mode" :disabled="executionStore.running" :options="[
                  { label: 'Sync 同步', value: 'sync' },
                  { label: 'Stream 流式', value: 'stream' },
                  { label: 'Async 异步队列', value: 'async' },
                ]" />
              </NFormItem>
              <NFormItem v-if="mode === 'async'" label="优先级 0-9"><NInputNumber v-model:value="priority" :min="0" :max="9" /></NFormItem>
              <NFormItem label="Temperature">
                <NInputNumber v-model:value="temperature" :min="0" :max="2" :step="0.1" clearable placeholder="使用模型默认值" />
              </NFormItem>
            </NCollapseItem>
          </NCollapse>

          <NAlert v-if="agent && !executable" type="warning" :bordered="false">当前 Agent 状态为 {{ agent.status }}，只有测试中或已发布的 Agent 可执行。</NAlert>
          <div class="execution-submit-row">
            <span>{{ mode === 'async' ? '提交后由 Worker Pool 执行' : mode === 'stream' ? '实时接收 SSE 增量事件' : '等待完整响应后返回' }}</span>
            <NButton type="primary" attr-type="submit" :loading="executionStore.running" :disabled="!executable">
              <template #icon><NIcon :component="PlayerPlay" /></template>{{ mode === 'async' ? '提交任务' : '运行 Agent' }}
            </NButton>
          </div>
        </NForm>
      </section>

      <section class="surface execution-trace-panel">
        <div class="section-heading">
          <div><h2>Trace Timeline</h2><p>最终状态以 Execution Detail 为准</p></div>
          <StatusTag v-if="execution" :status="execution.status" />
        </div>
        <div v-if="executionStore.running && !execution" class="loading-stack"><div v-for="index in 5" :key="index" class="skeleton-line" /></div>
        <ExecutionTimeline v-else :steps="execution?.steps || []" :active="isActive" />
        <NCollapse v-if="executionStore.streamEvents.length" class="stream-event-log">
          <NCollapseItem :title="`SSE 事件 ${executionStore.streamEvents.length}`" name="events">
            <pre class="json-viewer">{{ formatJson(executionStore.streamEvents.filter((item) => item.event !== 'token' && item.event !== 'keepalive')) }}</pre>
          </NCollapseItem>
        </NCollapse>
      </section>

      <section class="surface execution-result-panel">
        <div class="section-heading">
          <div><h2>输出</h2><p v-if="execution" class="mono">{{ execution.id }}</p><p v-else>等待本次执行结果</p></div>
          <NButton v-if="execution" text type="primary" @click="router.push({ name: 'execution-detail', params: { id: execution.id } })">打开详情</NButton>
        </div>
        <RuntimeMetrics
          :duration-ms="execution?.duration_ms"
          :token-usage="execution?.token_usage"
          :skill-count="execution?.skill_count"
          :mcp-call-count="execution?.mcp_call_count"
          :memory-read-count="execution?.memory_read_count"
          :artifact-count="execution?.artifact_count"
        />
        <NAlert v-if="execution?.error" type="error" :title="execution.error" class="execution-result-error" />
        <NAlert v-if="submittedTask" type="info" :bordered="false" class="execution-result-error">异步任务 {{ submittedTask.id }} 已创建，Execution 状态会由 Worker 更新。</NAlert>
        <ResultViewer
          :output="visibleOutput"
          :output-json="execution?.output_json"
          :artifacts="execution?.artifacts || []"
          :steps="execution?.steps || []"
          :details="execution?.details"
          :active="isActive"
        />
      </section>
    </div>
  </div>
</template>
