<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import {
  Activity,
  AlertCircle,
  ChevronDown,
  Clock,
  Download,
  FileText,
  ListDetails,
  Robot,
  User,
} from '@vicons/tabler'

import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import AgentConversationPanel from '@/components/agent/AgentConversationPanel.vue'
import StatusTag from '@/components/StatusTag.vue'
import type {
  AgentTask,
  AgentTeam,
  ExecutionDetail,
  ExecutionSummary,
  WorkflowRun,
} from '@/types/api'
import { parseSafeMarkdown } from '@/utils/executionStudio'
import { formatDate } from '@/utils/format'
import { presentTeamRunResult } from '@/utils/teamRunResult'

type OutputMode = 'readable' | 'structured' | 'raw'
type AgentScope = 'current' | 'history'

const props = defineProps<{
  run: WorkflowRun
  team: AgentTeam
  refreshTick?: number
  detailOnly?: boolean
}>()

const emit = defineEmits<{
  refresh: []
  openDetails: [runId: string, trigger?: HTMLElement]
}>()

const router = useRouter()
const expanded = ref(Boolean(props.detailOnly))
const tasks = ref<AgentTask[]>([])
const tasksLoading = ref(false)
const tasksError = ref('')
const selectedTaskId = ref<string | null>(null)
const selectedExecution = ref<ExecutionDetail | null>(null)
const executionLoading = ref(false)
const executionError = ref('')
const outputMode = ref<OutputMode>('readable')
const agentOutputMode = ref<OutputMode>('readable')
const agentScope = ref<AgentScope>('current')
const historyExecutions = ref<ExecutionSummary[]>([])
const historyLoading = ref(false)
const historyError = ref('')
const actionLoading = ref(false)
let taskRequestSerial = 0
let executionRequestSerial = 0
let historyRequestSerial = 0

const terminalTaskStatuses = new Set(['succeeded', 'failed', 'cancelled'])
const executionCache = new Map<string, ExecutionDetail>()
const historyCache = new Map<string, ExecutionSummary[]>()

const presentation = computed(() => presentTeamRunResult(props.run.output))
const outputModes = computed<OutputMode[]>(() => {
  const modes: OutputMode[] = ['readable']
  if (presentation.value.structured !== null) modes.push('structured')
  if (presentation.value.raw.trim()) modes.push('raw')
  return modes
})
const outputText = computed(() => {
  if (!props.detailOnly) return presentation.value.readable
  if (outputMode.value === 'structured') return presentation.value.structuredText
  if (outputMode.value === 'raw') return presentation.value.raw
  return presentation.value.readable
})
const orderedTasks = computed(() => [...tasks.value].sort((left, right) => {
  if (left.node_key === '__manager__' && right.node_key !== '__manager__') return -1
  if (left.node_key !== '__manager__' && right.node_key === '__manager__') return 1
  return Date.parse(left.created_at) - Date.parse(right.created_at)
}))
const selectedTask = computed(() => orderedTasks.value.find((task) => task.id === selectedTaskId.value) || null)
const selectedAgentName = computed(() => {
  if (selectedTask.value?.node_key === '__manager__') {
    return props.team.members.find((member) => member.agent_id === props.team.owner_agent_id)?.agent_name || 'Manager Agent'
  }
  return props.team.members.find((member) => member.agent_id === selectedTask.value?.agent_id)?.agent_name
    || selectedExecution.value?.agent_name
    || selectedTask.value?.agent_id
    || 'Agent'
})
const selectedAgentRuntime = computed(() => props.team.members.find(
  (member) => member.agent_id === selectedTask.value?.agent_id,
)?.runtime_type || selectedExecution.value?.runtime_type || '-')
const selectedInput = computed(() => {
  if (selectedExecution.value?.input) return selectedExecution.value.input
  const input = selectedTask.value?.input_data?.original_input
  return typeof input === 'string' && input.trim() ? input : props.run.input
})
const agentPresentation = computed(() => presentTeamRunResult(
  selectedExecution.value?.output,
  selectedExecution.value?.output_json,
))
const agentOutputModes = computed<OutputMode[]>(() => {
  const modes: OutputMode[] = ['readable']
  if (agentPresentation.value.structured !== null) modes.push('structured')
  if (agentPresentation.value.raw.trim()) modes.push('raw')
  return modes
})
const agentOutputText = computed(() => {
  if (agentOutputMode.value === 'structured') return agentPresentation.value.structuredText
  if (agentOutputMode.value === 'raw') return agentPresentation.value.raw
  return agentPresentation.value.readable
})

function outputModeLabel(mode: OutputMode): string {
  if (mode === 'structured') return '结构化数据'
  if (mode === 'raw') return '原始输出'
  return '可读结果'
}

function taskTitle(task: AgentTask): string {
  if (task.node_key === '__manager__') return 'Manager 汇总'
  if (task.node_type === 'human_approval') return '人工审批'
  const role = task.input_data?.role
  if (typeof role === 'string' && role.trim()) return role
  return props.team.members.find((member) => member.agent_id === task.agent_id)?.role
    || task.node_key
    || task.agent_id
}

function messageBlocks(value: string) {
  return parseSafeMarkdown(value)
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

async function loadTasks(silent = false) {
  if (!expanded.value) return
  const serial = ++taskRequestSerial
  if (!silent || !tasks.value.length) tasksLoading.value = true
  tasksError.value = ''
  try {
    const values = await platformApi.listWorkflowRunTasks(props.run.id)
    if (serial !== taskRequestSerial) return
    tasks.value = values
    if (!values.some((task) => task.id === selectedTaskId.value)) {
      selectedTaskId.value = values.find((task) => task.node_key === '__manager__')?.id || values[0]?.id || null
    }
  } catch (error) {
    if (serial === taskRequestSerial) tasksError.value = getApiErrorMessage(error)
  } finally {
    if (serial === taskRequestSerial) tasksLoading.value = false
  }
}

async function toggleExpanded(event?: MouseEvent) {
  const trigger = event?.currentTarget
  if (trigger instanceof HTMLElement) emit('openDetails', props.run.id, trigger)
  else emit('openDetails', props.run.id)
}

async function loadExecution() {
  const serial = ++executionRequestSerial
  const task = selectedTask.value
  selectedExecution.value = null
  executionError.value = ''
  agentOutputMode.value = 'readable'
  agentScope.value = 'current'
  if (!task?.execution_id) return

  const cached = executionCache.get(task.execution_id)
  if (cached && terminalTaskStatuses.has(task.status)) {
    selectedExecution.value = cached
    return
  }

  executionLoading.value = true
  try {
    const detail = await platformApi.getExecution(task.execution_id)
    if (terminalTaskStatuses.has(detail.status)) executionCache.set(task.execution_id, detail)
    if (serial === executionRequestSerial) selectedExecution.value = detail
  } catch (error) {
    if (serial === executionRequestSerial) executionError.value = getApiErrorMessage(error)
  } finally {
    if (serial === executionRequestSerial) executionLoading.value = false
  }
}

async function loadHistory() {
  const serial = ++historyRequestSerial
  const agentId = selectedTask.value?.agent_id
  if (!agentId || selectedTask.value?.node_type === 'human_approval') {
    historyExecutions.value = []
    return
  }
  const cached = historyCache.get(agentId)
  if (cached) {
    historyExecutions.value = cached
    historyError.value = ''
    return
  }
  historyLoading.value = true
  historyError.value = ''
  try {
    const result = await platformApi.listExecutions({ agent_id: agentId, limit: 50, offset: 0 })
    historyCache.set(agentId, result.items)
    if (serial === historyRequestSerial) historyExecutions.value = result.items
  } catch (error) {
    if (serial === historyRequestSerial) historyError.value = getApiErrorMessage(error)
  } finally {
    if (serial === historyRequestSerial) historyLoading.value = false
  }
}

async function review(task: AgentTask, approved: boolean) {
  if (actionLoading.value) return
  actionLoading.value = true
  try {
    await platformApi.reviewHumanTask(task.id, approved, approved ? '聊天工作台审批通过' : '聊天工作台审批拒绝')
    await loadTasks(true)
    emit('refresh')
  } catch (error) {
    tasksError.value = getApiErrorMessage(error)
  } finally {
    actionLoading.value = false
  }
}

watch(selectedTaskId, () => { void loadExecution() })
watch(agentScope, (scope) => {
  if (scope === 'history') void loadHistory()
})
watch(() => props.refreshTick, () => {
  if (expanded.value && ['pending', 'running', 'human_review'].includes(props.run.status)) void loadTasks(true)
})
watch(() => props.run.status, (next, previous) => {
  if (expanded.value && next !== previous) void loadTasks(true)
})
watch(() => props.detailOnly, (detailOnly) => {
  expanded.value = Boolean(detailOnly)
  if (detailOnly && !tasks.value.length) void loadTasks()
}, { immediate: true })
</script>

<template>
  <article class="team-chat-turn" :class="{ 'team-chat-detail-only': detailOnly }" :data-run-id="run.id">
    <section class="team-chat-message team-chat-message-user">
      <span class="team-chat-avatar"><NIcon :component="User" size="17" /></span>
      <div class="team-chat-bubble">
        <header><strong>你</strong><time>{{ formatDate(run.created_at) }}</time></header>
        <div class="team-chat-copy">{{ run.input }}</div>
      </div>
    </section>

    <section class="team-chat-message team-chat-message-manager">
      <span class="team-chat-avatar"><NIcon :component="Robot" size="17" /></span>
      <div class="team-chat-bubble">
        <header>
          <strong>Manager 回复</strong>
          <span><StatusTag :status="run.status" /><time>{{ formatDate(run.finished_at || run.started_at || run.created_at) }}</time></span>
        </header>

        <div v-if="detailOnly && outputModes.length > 1" class="team-output-tabs" role="tablist" aria-label="Manager 输出格式">
          <button v-for="mode in outputModes" :key="mode" type="button" role="tab" :aria-selected="outputMode === mode" :class="{ active: outputMode === mode }" @click="outputMode = mode">
            {{ outputModeLabel(mode) }}
          </button>
        </div>

        <div v-if="outputText" class="team-chat-copy team-chat-result">
          <pre v-if="outputMode !== 'readable'"><code>{{ outputText }}</code></pre>
          <template v-else v-for="(block, index) in messageBlocks(outputText)" :key="index">
            <h3 v-if="block.kind === 'heading'">{{ block.text }}</h3>
            <p v-else-if="block.kind === 'paragraph'">{{ block.text }}</p>
            <div v-else-if="block.kind === 'list'" class="team-chat-list-item">{{ block.text }}</div>
            <pre v-else><code>{{ block.text }}</code></pre>
          </template>
        </div>
        <div v-else-if="['pending', 'running'].includes(run.status)" class="team-run-state team-run-waiting">
          <NIcon :component="Clock" size="21" />
          <div><strong>团队正在协作</strong><span>Manager 完成汇总后会在这里显示回复。</span></div>
        </div>
        <div v-else-if="run.status === 'human_review'" class="team-run-state team-run-review">
          <NIcon :component="Clock" size="21" />
          <div><strong>等待人工审批</strong><span>展开协作过程，在对应审批节点完成操作。</span></div>
        </div>
        <div v-else class="team-run-state team-run-error">
          <NIcon :component="AlertCircle" size="21" />
          <div>
            <strong>{{ run.status === 'cancelled' ? '本次运行已取消' : run.status === 'failed' ? '团队运行失败' : '没有可展示的输出' }}</strong>
            <span>{{ run.error || '后端未返回 Manager 输出。' }}</span>
          </div>
        </div>

        <footer class="team-run-actions">
          <span class="mono">Run {{ run.id }}</span>
          <div>
            <NButton text size="tiny" @click="toggleExpanded">
              <template #icon><NIcon :component="ChevronDown" /></template>
              查看协作详情
            </NButton>
          </div>
        </footer>

        <section v-if="expanded" class="team-collaboration" aria-label="协作过程">
          <div v-if="tasksError" class="team-inline-error">
            <NIcon :component="AlertCircle" /><span>{{ tasksError }}</span><NButton text size="tiny" @click="loadTasks()">重试</NButton>
          </div>
          <div v-if="tasksLoading && !tasks.length" class="team-task-skeleton" aria-label="正在加载 Agent 节点">
            <span v-for="index in 4" :key="index" />
          </div>
          <template v-else>
            <nav v-if="orderedTasks.length" class="team-task-list" aria-label="Agent 节点">
              <button v-for="task in orderedTasks" :key="task.id" type="button" :class="{ active: task.id === selectedTaskId }" @click="selectedTaskId = task.id">
                <span><strong>{{ taskTitle(task) }}</strong><StatusTag :status="task.status" /></span>
                <small>{{ team.members.find((member) => member.agent_id === task.agent_id)?.agent_name || task.agent_id }}</small>
              </button>
            </nav>
            <div v-else class="team-task-empty">当前运行尚未生成 Agent 节点。</div>

            <section v-if="selectedTask" class="team-agent-detail">
              <header>
                <div><strong>{{ selectedAgentName }}</strong><span>{{ selectedAgentRuntime }} / {{ selectedTask.node_type }}</span></div>
                <StatusTag :status="selectedTask.status" />
              </header>

              <div v-if="selectedTask.node_type !== 'human_approval'" class="team-agent-scope-tabs" role="tablist" aria-label="Agent 对话范围">
                <button type="button" role="tab" :aria-selected="agentScope === 'current'" :class="{ active: agentScope === 'current' }" @click="agentScope = 'current'">本次执行</button>
                <button type="button" role="tab" :aria-selected="agentScope === 'history'" :class="{ active: agentScope === 'history' }" @click="agentScope = 'history'">全部历史</button>
              </div>

              <div v-if="selectedTask.status === 'human_review'" class="team-approval-actions">
                <p>该节点需要人工确认后才能继续执行。</p>
                <div><NButton size="small" type="primary" :loading="actionLoading" @click="review(selectedTask, true)">通过</NButton><NButton size="small" type="error" secondary :disabled="actionLoading" @click="review(selectedTask, false)">拒绝</NButton></div>
              </div>

              <AgentConversationPanel
                v-else-if="agentScope === 'history'"
                :executions="historyExecutions"
                :loading="historyLoading"
                :history-error="historyError"
                :agent-name="selectedAgentName"
                @refresh="loadHistory"
                @open-trace="(executionId) => router.push({ name: 'trace-detail', params: { id: executionId } })"
              />

              <div v-else class="team-agent-current">
                <section class="team-agent-input"><strong>实际输入</strong><div>{{ selectedInput }}</div></section>
                <div v-if="executionLoading" class="team-task-skeleton result"><span v-for="index in 4" :key="index" /></div>
                <div v-else-if="executionError" class="team-inline-error"><NIcon :component="AlertCircle" /><span>{{ executionError }}</span></div>
                <template v-else-if="selectedExecution">
                  <div v-if="agentOutputModes.length > 1" class="team-output-tabs" role="tablist" aria-label="Agent 输出格式">
                    <button v-for="mode in agentOutputModes" :key="mode" type="button" role="tab" :aria-selected="agentOutputMode === mode" :class="{ active: agentOutputMode === mode }" @click="agentOutputMode = mode">{{ outputModeLabel(mode) }}</button>
                  </div>
                  <div v-if="agentOutputText" class="team-chat-copy team-agent-output">
                    <pre v-if="agentOutputMode !== 'readable'"><code>{{ agentOutputText }}</code></pre>
                    <template v-else v-for="(block, index) in messageBlocks(agentOutputText)" :key="index">
                      <h3 v-if="block.kind === 'heading'">{{ block.text }}</h3>
                      <p v-else-if="block.kind === 'paragraph'">{{ block.text }}</p>
                      <div v-else-if="block.kind === 'list'" class="team-chat-list-item">{{ block.text }}</div>
                      <pre v-else><code>{{ block.text }}</code></pre>
                    </template>
                  </div>
                  <div v-else class="team-run-state team-run-error"><NIcon :component="AlertCircle" /><div><strong>本节点没有输出</strong><span>{{ selectedExecution.error || selectedTask.error || '后端未返回内容。' }}</span></div></div>

                  <div v-if="selectedExecution.artifacts.length" class="team-agent-artifacts">
                    <header><NIcon :component="FileText" /><strong>产物</strong><span>{{ selectedExecution.artifacts.length }} 个</span></header>
                    <a v-for="artifact in selectedExecution.artifacts" :key="artifact.id" :href="platformApi.artifactDownloadUrl(artifact.id)">
                      <span><strong>{{ artifact.filename }}</strong><small>{{ artifact.artifact_type }} / {{ formatBytes(artifact.size_bytes) }}</small></span>
                      <NIcon :component="Download" />
                    </a>
                  </div>
                  <footer class="team-agent-links">
                    <NButton text size="tiny" @click="router.push({ name: 'execution-detail', params: { id: selectedExecution.id } })"><template #icon><NIcon :component="ListDetails" /></template>执行详情</NButton>
                    <NButton text size="tiny" @click="router.push({ name: 'trace-detail', params: { id: selectedExecution.id } })"><template #icon><NIcon :component="Activity" /></template>查看 Trace</NButton>
                  </footer>
                </template>
                <div v-else-if="!selectedTask.execution_id" class="team-run-state team-run-waiting"><NIcon :component="Clock" /><div><strong>尚未创建 Execution</strong><span>{{ selectedTask.error || '节点排队或等待依赖。' }}</span></div></div>
              </div>
            </section>
          </template>
        </section>
      </div>
    </section>
  </article>
</template>

<style scoped>
.team-chat-turn{display:grid;gap:14px;max-width:1100px;margin:0 auto 30px}.team-chat-message{display:flex;gap:10px;align-items:flex-start}.team-chat-message-user{padding-left:clamp(36px,10vw,140px)}.team-chat-message-manager{padding-right:clamp(12px,4vw,56px)}.team-chat-avatar{display:grid;width:32px;height:32px;flex:0 0 auto;place-items:center;border-radius:9px;color:var(--ink);background:#3a3a3a}.team-chat-message-user .team-chat-avatar{order:2;color:#202020;background:#d8d8d8}.team-chat-message-user .team-chat-bubble{max-width:70%;margin-left:auto;background:#363636}.team-chat-bubble{min-width:0;max-width:100%;flex:1;padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:#2b2b2b}.team-chat-bubble>header{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:10px}.team-chat-bubble>header strong{font-size:11px}.team-chat-bubble>header>span{display:flex;align-items:center;gap:8px}.team-chat-bubble time{color:#888;font-size:9px}.team-chat-copy{max-width:100%;color:#d6d6d6;font-size:13px;line-height:1.72;white-space:pre-wrap;overflow-wrap:anywhere}.team-chat-copy h3,.team-chat-copy p{margin:0 0 9px}.team-chat-copy h3{font-size:15px}.team-chat-copy pre{max-width:100%;margin:7px 0;padding:12px;overflow:auto;border:1px solid #3a3a3a;border-radius:7px;background:#1c1c1c;font-size:11px;white-space:pre-wrap}.team-chat-copy table{display:block;max-width:100%;overflow-x:auto}.team-chat-list-item{padding-left:14px}.team-chat-list-item:before{content:'•';margin-left:-12px;margin-right:7px}.team-output-tabs,.team-agent-scope-tabs{display:flex;flex-wrap:wrap;gap:4px;margin-bottom:12px}.team-output-tabs button,.team-agent-scope-tabs button{padding:5px 9px;border:1px solid transparent;border-radius:6px;color:var(--muted);background:transparent;font:600 9px/1.2 inherit;cursor:pointer}.team-output-tabs button.active,.team-agent-scope-tabs button.active{border-color:#555;color:var(--ink);background:#383838}.team-output-tabs button:focus-visible,.team-agent-scope-tabs button:focus-visible,.team-task-list button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.team-run-state{display:flex;align-items:flex-start;gap:9px;padding:12px;border:1px solid var(--line);border-radius:8px;color:var(--muted);background:#252525}.team-run-state div{display:grid;gap:3px}.team-run-state strong{color:var(--ink);font-size:11px}.team-run-state span{font-size:10px;line-height:1.5}.team-run-error{border-color:rgba(239,83,80,.34);color:#ff8a87;background:rgba(239,83,80,.06)}.team-run-review{border-color:rgba(240,180,41,.3)}.team-run-actions{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:13px;padding-top:10px;border-top:1px solid var(--line)}.team-run-actions>span{min-width:0;overflow:hidden;color:#757575;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.team-run-actions>div{display:flex;gap:8px}.team-collaboration{display:grid;grid-template-columns:minmax(190px,240px) minmax(0,1fr);margin:12px -4px -4px;padding-top:12px;border-top:1px solid var(--line)}.team-task-list{display:grid;align-content:start;max-height:520px;overflow:auto;border-right:1px solid var(--line)}.team-task-list button{display:grid;gap:4px;padding:10px;border:0;border-bottom:1px solid #363636;color:var(--muted);background:transparent;text-align:left;cursor:pointer}.team-task-list button:hover,.team-task-list button.active{color:var(--ink);background:#353535}.team-task-list button>span{display:flex;align-items:center;justify-content:space-between;gap:7px}.team-task-list strong{overflow:hidden;font-size:10px;text-overflow:ellipsis;white-space:nowrap}.team-task-list small{overflow:hidden;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.team-agent-detail{min-width:0;padding:2px 0 2px 14px}.team-agent-detail>header{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}.team-agent-detail>header>div{display:grid;min-width:0;gap:2px}.team-agent-detail>header strong{font-size:12px}.team-agent-detail>header span{color:var(--muted);font-size:9px}.team-agent-input{display:grid;gap:6px;margin-bottom:12px;padding:10px;border-radius:7px;background:#242424}.team-agent-input>strong{font-size:9px}.team-agent-input>div{max-height:180px;overflow:auto;color:#bcbcbc;font-size:10px;line-height:1.6;white-space:pre-wrap}.team-agent-output{max-height:460px;overflow:auto;padding:2px}.team-agent-links{display:flex;justify-content:flex-end;gap:8px;margin-top:10px;padding-top:9px;border-top:1px solid var(--line)}.team-agent-artifacts{display:grid;gap:5px;margin-top:12px}.team-agent-artifacts>header{display:flex;align-items:center;gap:6px}.team-agent-artifacts>header strong{font-size:10px}.team-agent-artifacts>header span{margin-left:auto;color:var(--muted);font-size:8px}.team-agent-artifacts>a{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px;border:1px solid var(--line);border-radius:7px;color:var(--ink);background:#252525}.team-agent-artifacts>a>span{display:grid;min-width:0;gap:2px}.team-agent-artifacts>a strong,.team-agent-artifacts>a small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.team-agent-artifacts>a strong{font-size:9px}.team-agent-artifacts>a small{color:var(--muted);font-size:8px}.team-inline-error{grid-column:1/-1;display:flex;align-items:center;gap:8px;padding:9px;color:#ff8a87;font-size:10px}.team-task-skeleton{grid-column:1/-1;display:grid;gap:7px;padding:10px}.team-task-skeleton span{height:38px;border-radius:6px;background:#353535;animation:team-chat-pulse 1.3s ease-in-out infinite}.team-task-skeleton.result span{height:18px}.team-task-empty{grid-column:1/-1;padding:24px;color:var(--muted);font-size:10px;text-align:center}.team-approval-actions{display:grid;gap:10px;padding:13px;border:1px solid rgba(240,180,41,.3);border-radius:8px}.team-approval-actions p{margin:0;color:var(--muted);font-size:10px}.team-approval-actions>div{display:flex;gap:8px}@keyframes team-chat-pulse{0%,100%{opacity:.5}50%{opacity:1}}@media(prefers-reduced-motion:reduce){.team-task-skeleton span{animation:none}}@media(max-width:760px){.team-chat-message-user{padding-left:20px}.team-chat-message-manager{padding-right:0}.team-collaboration{grid-template-columns:1fr}.team-task-list{grid-template-columns:repeat(2,minmax(0,1fr));max-height:260px;border-right:0;border-bottom:1px solid var(--line)}.team-task-list button:nth-child(odd){border-right:1px solid #363636}.team-agent-detail{padding:14px 0 0}.team-run-actions{align-items:flex-start;flex-direction:column}.team-run-actions>div{width:100%;justify-content:flex-end}}@media(max-width:520px){.team-chat-turn{margin-bottom:22px}.team-chat-message-user{padding-left:8px}.team-chat-message-user .team-chat-bubble{max-width:86%}.team-chat-avatar{width:28px;height:28px}.team-chat-bubble{padding:11px 12px}.team-task-list{grid-template-columns:1fr}.team-task-list button:nth-child(odd){border-right:0}.team-chat-bubble>header{align-items:flex-start;flex-direction:column}.team-run-actions>div{flex-wrap:wrap;justify-content:flex-start}.team-agent-links{justify-content:flex-start}}
.team-chat-detail-only{max-width:none;margin:0}.team-chat-detail-only>.team-chat-message-user{display:none}.team-chat-detail-only>.team-chat-message-manager{padding:0}.team-chat-detail-only>.team-chat-message-manager>.team-chat-avatar{display:none}.team-chat-detail-only>.team-chat-message-manager>.team-chat-bubble{border:0;border-radius:0;background:transparent}.team-chat-detail-only .team-run-actions{display:none}.team-chat-detail-only .team-collaboration{grid-template-columns:minmax(160px,210px) minmax(0,1fr);margin-inline:0}.team-chat-detail-only .team-task-list,.team-chat-detail-only .team-agent-output{max-height:none}.team-chat-detail-only :deep(.conversation-workspace){grid-template-columns:180px minmax(0,1fr);min-height:520px}.team-chat-detail-only :deep(.conversation-session-list),.team-chat-detail-only :deep(.conversation-transcript){max-height:520px}@media(max-width:760px){.team-chat-detail-only .team-collaboration{grid-template-columns:1fr}.team-chat-detail-only :deep(.conversation-workspace){grid-template-columns:1fr}.team-chat-detail-only :deep(.conversation-session-list){max-height:220px}}@container team-run-detail (max-width:520px){.team-chat-detail-only .team-collaboration{grid-template-columns:1fr}.team-chat-detail-only :deep(.conversation-workspace){grid-template-columns:1fr}.team-chat-detail-only :deep(.conversation-session-list){max-height:220px}}
</style>
