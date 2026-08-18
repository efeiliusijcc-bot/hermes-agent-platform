<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  AlertCircle,
  Clock,
  Download,
  FileText,
  History,
  ListDetails,
  Messages,
  Refresh,
  Robot,
  User,
} from '@vicons/tabler'

import AgentConversationPanel from '@/components/agent/AgentConversationPanel.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { parseSafeMarkdown } from '@/utils/executionStudio'
import { formatDate } from '@/utils/format'
import { presentTeamRunResult } from '@/utils/teamRunResult'
import type {
  Agent,
  AgentTask,
  ExecutionDetail,
  ExecutionSummary,
  WorkflowRun,
} from '@/types/api'

type WorkspaceView = 'team' | 'agent'
type AgentScope = 'current' | 'history'
type OutputMode = 'readable' | 'structured' | 'raw'

const props = withDefaults(defineProps<{
  runs: WorkflowRun[]
  tasks: AgentTask[]
  agents: Agent[]
  selectedRunId: string | null
  loading?: boolean
}>(), {
  loading: false,
})

const emit = defineEmits<{
  selectRun: [runId: string]
  refresh: []
  review: [task: AgentTask, approved: boolean]
  openExecution: [executionId: string]
  openTrace: [executionId: string]
}>()

const activeView = ref<WorkspaceView>('team')
const agentScope = ref<AgentScope>('current')
const teamOutputMode = ref<OutputMode>('readable')
const agentOutputMode = ref<OutputMode>('readable')
const selectedTaskId = ref<string | null>(null)
const managerExecution = ref<ExecutionDetail | null>(null)
const selectedExecution = ref<ExecutionDetail | null>(null)
const managerLoading = ref(false)
const selectedExecutionLoading = ref(false)
const managerError = ref<string | null>(null)
const selectedExecutionError = ref<string | null>(null)
const historyExecutions = ref<ExecutionSummary[]>([])
const historyLoading = ref(false)
const historyError = ref<string | null>(null)

const detailCache = new Map<string, ExecutionDetail>()
const detailRequests = new Map<string, Promise<ExecutionDetail>>()
const historyCache = new Map<string, ExecutionSummary[]>()
let managerRequestSerial = 0
let selectedRequestSerial = 0
let historyRequestSerial = 0

const terminalStatuses = new Set(['succeeded', 'failed', 'cancelled'])

const selectedRun = computed(() => props.runs.find((run) => run.id === props.selectedRunId) || null)
const orderedTasks = computed(() => [...props.tasks].sort((left, right) => {
  if (left.parent_task_id === null && right.parent_task_id !== null) return -1
  if (left.parent_task_id !== null && right.parent_task_id === null) return 1
  return Date.parse(left.created_at) - Date.parse(right.created_at)
}))
const managerTask = computed(() => orderedTasks.value.find((task) => task.node_key === '__manager__') || null)
const selectedTask = computed(() => orderedTasks.value.find((task) => task.id === selectedTaskId.value) || null)
const selectedAgent = computed(() => props.agents.find((agent) => agent.id === selectedTask.value?.agent_id) || null)
const selectedAgentId = computed(() => selectedTask.value?.agent_id || null)
const selectedAgentName = computed(() => selectedAgent.value?.name || selectedTask.value?.agent_id || 'Agent')

const managerExecutionKey = computed(() => {
  const task = managerTask.value
  return task ? `${task.id}|${task.execution_id || ''}|${task.status}` : ''
})
const selectedExecutionKey = computed(() => {
  const task = selectedTask.value
  return task ? `${task.id}|${task.execution_id || ''}|${task.status}` : ''
})

const teamPresentation = computed(() => presentTeamRunResult(
  managerExecution.value?.output || selectedRun.value?.output,
  managerExecution.value?.output_json,
))
const selectedPresentation = computed(() => presentTeamRunResult(
  selectedExecution.value?.output,
  selectedExecution.value?.output_json,
))

const teamOutputText = computed(() => outputText(teamPresentation.value, teamOutputMode.value))
const agentOutputText = computed(() => outputText(selectedPresentation.value, agentOutputMode.value))
const teamOutputModes = computed(() => availableOutputModes(teamPresentation.value))
const agentOutputModes = computed(() => availableOutputModes(selectedPresentation.value))
const selectedInput = computed(() => {
  if (selectedExecution.value?.input) return selectedExecution.value.input
  const original = selectedTask.value?.input_data?.original_input
  if (typeof original === 'string' && original.trim()) return original
  return selectedRun.value?.input || ''
})

function availableOutputModes(presentation: ReturnType<typeof presentTeamRunResult>): OutputMode[] {
  const modes: OutputMode[] = ['readable']
  if (presentation.structured !== null) modes.push('structured')
  if (presentation.raw.trim()) modes.push('raw')
  return modes
}

function outputText(
  presentation: ReturnType<typeof presentTeamRunResult>,
  mode: OutputMode,
): string {
  if (mode === 'structured') return presentation.structuredText
  if (mode === 'raw') return presentation.raw
  return presentation.readable
}

function outputModeLabel(mode: OutputMode): string {
  if (mode === 'structured') return '结构化数据'
  if (mode === 'raw') return '原始输出'
  return '可读结果'
}

function taskTitle(task: AgentTask): string {
  if (task.node_key === '__manager__') return 'Manager 汇总'
  const agent = props.agents.find((item) => item.id === task.agent_id)
  const role = task.input_data?.role
  if (typeof role === 'string' && role.trim()) return role
  return agent?.name || task.node_key || task.agent_id
}

function taskAgentName(task: AgentTask): string {
  return props.agents.find((agent) => agent.id === task.agent_id)?.name || task.agent_id
}

function taskRuntime(task: AgentTask): string {
  return props.agents.find((agent) => agent.id === task.agent_id)?.runtime_type || '-'
}

function messageBlocks(value: string) {
  return parseSafeMarkdown(value)
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

async function requestExecution(task: AgentTask, force = false): Promise<ExecutionDetail | null> {
  if (!task.execution_id) return null
  const cached = detailCache.get(task.execution_id)
  if (!force && cached && terminalStatuses.has(task.status) && cached.status === task.status) return cached
  const pending = detailRequests.get(task.execution_id)
  if (pending) return pending

  const request = platformApi.getExecution(task.execution_id)
  detailRequests.set(task.execution_id, request)
  try {
    const detail = await request
    detailCache.set(task.execution_id, detail)
    return detail
  } finally {
    detailRequests.delete(task.execution_id)
  }
}

async function loadManagerExecution(force = false) {
  const serial = ++managerRequestSerial
  const task = managerTask.value
  if (!task?.execution_id) {
    managerExecution.value = null
    managerError.value = null
    return
  }
  managerLoading.value = true
  managerError.value = null
  try {
    const detail = await requestExecution(task, force)
    if (serial === managerRequestSerial) managerExecution.value = detail
  } catch (error) {
    if (serial === managerRequestSerial) {
      managerExecution.value = null
      managerError.value = getApiErrorMessage(error)
    }
  } finally {
    if (serial === managerRequestSerial) managerLoading.value = false
  }
}

async function loadSelectedExecution(force = false) {
  const serial = ++selectedRequestSerial
  const task = selectedTask.value
  if (!task?.execution_id) {
    selectedExecution.value = null
    selectedExecutionError.value = null
    return
  }
  selectedExecutionLoading.value = true
  selectedExecutionError.value = null
  try {
    const detail = await requestExecution(task, force)
    if (serial === selectedRequestSerial) selectedExecution.value = detail
  } catch (error) {
    if (serial === selectedRequestSerial) {
      selectedExecution.value = null
      selectedExecutionError.value = getApiErrorMessage(error)
    }
  } finally {
    if (serial === selectedRequestSerial) selectedExecutionLoading.value = false
  }
}

async function loadHistory(force = false) {
  const serial = ++historyRequestSerial
  const agentId = selectedAgentId.value
  if (!agentId) {
    historyExecutions.value = []
    historyError.value = null
    return
  }
  const cached = historyCache.get(agentId)
  if (!force && cached) {
    historyExecutions.value = cached
    historyError.value = null
    return
  }
  historyLoading.value = true
  historyError.value = null
  try {
    const result = await platformApi.listExecutions({ agent_id: agentId, limit: 50, offset: 0 })
    historyCache.set(agentId, result.items)
    if (serial === historyRequestSerial) historyExecutions.value = result.items
  } catch (error) {
    if (serial === historyRequestSerial) {
      historyExecutions.value = []
      historyError.value = getApiErrorMessage(error)
    }
  } finally {
    if (serial === historyRequestSerial) historyLoading.value = false
  }
}

function selectTask(task: AgentTask) {
  selectedTaskId.value = task.id
  activeView.value = 'agent'
  agentScope.value = 'current'
}

function refreshWorkspace() {
  detailCache.clear()
  historyCache.clear()
  emit('refresh')
  void loadManagerExecution(true)
  if (activeView.value === 'agent') void loadSelectedExecution(true)
  if (agentScope.value === 'history') void loadHistory(true)
}

watch(() => props.selectedRunId, () => {
  activeView.value = 'team'
  agentScope.value = 'current'
  teamOutputMode.value = 'readable'
  agentOutputMode.value = 'readable'
  selectedTaskId.value = null
  managerExecution.value = null
  selectedExecution.value = null
  managerError.value = null
  selectedExecutionError.value = null
})

watch(orderedTasks, (tasks) => {
  if (!tasks.length) {
    selectedTaskId.value = null
    return
  }
  if (!tasks.some((task) => task.id === selectedTaskId.value)) {
    selectedTaskId.value = managerTask.value?.id || tasks[0].id
  }
}, { immediate: true })

watch(managerExecutionKey, () => { void loadManagerExecution() }, { immediate: true })
watch(selectedExecutionKey, () => {
  agentOutputMode.value = 'readable'
  void loadSelectedExecution()
}, { immediate: true })
watch([agentScope, selectedAgentId], ([scope]) => {
  if (scope === 'history') void loadHistory()
})
</script>

<template>
  <section class="team-run-workspace" aria-label="Agent Team 运行工作台">
    <header class="workspace-heading">
      <div>
        <span class="workspace-step">04</span>
        <div>
          <h2>团队运行工作台</h2>
          <p>查看 Team 最终结果、每个 Agent 的本次输出与历史对话</p>
        </div>
      </div>
      <NButton secondary :loading="loading || managerLoading || selectedExecutionLoading" @click="refreshWorkspace">
        <template #icon><NIcon :component="Refresh" /></template>刷新
      </NButton>
    </header>

    <div class="workspace-shell">
      <aside class="run-history-pane">
        <header>
          <div><History size="17" /><strong>运行历史</strong></div>
          <span>当前团队 {{ runs.length }} 次</span>
        </header>
        <div v-if="loading && !runs.length" class="workspace-skeleton compact" aria-label="正在加载运行历史">
          <div v-for="index in 5" :key="index" class="skeleton-line" />
        </div>
        <div v-else-if="runs.length" class="run-history-list" role="listbox" aria-label="团队运行历史">
          <button
            v-for="run in runs.slice(0, 20)"
            :key="run.id"
            type="button"
            role="option"
            :aria-selected="run.id === selectedRunId"
            :class="{ active: run.id === selectedRunId }"
            @click="emit('selectRun', run.id)"
          >
            <span class="run-history-meta"><StatusTag :status="run.status" /><time>{{ formatDate(run.created_at) }}</time></span>
            <strong>{{ run.input }}</strong>
            <span class="mono">{{ run.id }}</span>
          </button>
        </div>
        <div v-else class="workspace-empty compact">
          <NIcon :component="History" size="26" />
          <strong>暂无团队运行</strong>
          <p>启动一次多 Agent 执行后，结果会显示在这里。</p>
        </div>
      </aside>

      <main class="run-workspace-main">
        <div v-if="selectedRun" class="workspace-tabs" role="tablist" aria-label="运行详情视图">
          <button type="button" role="tab" :aria-selected="activeView === 'team'" :class="{ active: activeView === 'team' }" @click="activeView = 'team'">
            <Messages size="16" />团队结果
          </button>
          <button type="button" role="tab" :aria-selected="activeView === 'agent'" :class="{ active: activeView === 'agent' }" @click="activeView = 'agent'">
            <Robot size="16" />Agent 对话
          </button>
          <span class="workspace-run-id mono">Run {{ selectedRun.id }}</span>
        </div>

        <div v-if="!selectedRun" class="workspace-empty workspace-empty-main">
          <NIcon :component="Messages" size="32" />
          <strong>请选择一次团队运行</strong>
          <p>选中左侧运行后，可查看 Manager 结果和每个 Agent 的完整输出。</p>
        </div>

        <section v-else-if="activeView === 'team'" class="team-result-view">
          <header class="run-context-header">
            <div>
              <span>团队会话</span>
              <strong>{{ teamPresentation.title || '团队执行结果' }}</strong>
            </div>
            <div class="run-status-group">
              <span>技术状态 <StatusTag :status="selectedRun.status" /></span>
              <span v-if="teamPresentation.businessStatus">业务结果 <StatusTag :status="teamPresentation.businessStatus" /></span>
            </div>
          </header>

          <div class="team-conversation">
            <article class="run-message run-message-user">
              <span class="run-avatar"><NIcon :component="User" size="18" /></span>
              <div class="run-message-body">
                <header><strong>用户任务</strong><time>{{ formatDate(selectedRun.created_at) }}</time></header>
                <div class="run-copy run-copy-user">{{ selectedRun.input }}</div>
              </div>
            </article>

            <article class="run-message run-message-agent">
              <span class="run-avatar"><NIcon :component="Robot" size="18" /></span>
              <div class="run-message-body">
                <header>
                  <strong>{{ managerExecution?.agent_name || 'Manager Agent' }}</strong>
                  <time>{{ formatDate(selectedRun.finished_at || selectedRun.started_at) }}</time>
                </header>

                <div v-if="teamOutputModes.length > 1" class="output-mode-tabs" role="tablist" aria-label="团队输出格式">
                  <button
                    v-for="mode in teamOutputModes"
                    :key="mode"
                    type="button"
                    role="tab"
                    :aria-selected="teamOutputMode === mode"
                    :class="{ active: teamOutputMode === mode }"
                    @click="teamOutputMode = mode"
                  >{{ outputModeLabel(mode) }}</button>
                </div>

                <div v-if="managerLoading && !teamOutputText" class="workspace-skeleton result">
                  <div v-for="index in 6" :key="index" class="skeleton-line" />
                </div>
                <div v-else-if="managerError && !selectedRun.output" class="workspace-inline-error">
                  <NIcon :component="AlertCircle" size="22" />
                  <div><strong>Manager 输出加载失败</strong><p>{{ managerError }}</p></div>
                </div>
                <div v-else-if="teamOutputText" class="run-copy run-copy-agent">
                  <pre v-if="teamOutputMode !== 'readable'"><code>{{ teamOutputText }}</code></pre>
                  <template v-else v-for="(block, index) in messageBlocks(teamOutputText)" :key="index">
                    <h3 v-if="block.kind === 'heading'">{{ block.text }}</h3>
                    <p v-else-if="block.kind === 'paragraph'">{{ block.text }}</p>
                    <div v-else-if="block.kind === 'list'" class="run-list-item">{{ block.text }}</div>
                    <pre v-else><code>{{ block.text }}</code></pre>
                  </template>
                </div>
                <div v-else-if="['pending', 'running', 'human_review'].includes(selectedRun.status)" class="workspace-empty result-empty">
                  <NIcon :component="Clock" size="26" />
                  <strong>Manager 正在汇总团队结果</strong>
                  <p>完成后会在此显示最终输出。</p>
                </div>
                <div v-else class="workspace-inline-error">
                  <NIcon :component="AlertCircle" size="22" />
                  <div><strong>本次运行没有可展示的最终输出</strong><p>{{ selectedRun.error || '后端未返回输出内容。' }}</p></div>
                </div>

                <footer v-if="managerTask?.execution_id" class="run-message-footer">
                  <span class="mono">Execution {{ managerTask.execution_id }}</span>
                  <div>
                    <NButton text size="tiny" @click="emit('openExecution', managerTask.execution_id!)">执行详情</NButton>
                    <NButton text size="tiny" @click="emit('openTrace', managerTask.execution_id!)">查看 Trace</NButton>
                  </div>
                </footer>

                <div v-if="managerExecution?.artifacts.length" class="run-artifacts">
                  <header><FileText size="15" /><strong>Manager 产物</strong><span>{{ managerExecution.artifacts.length }} 个</span></header>
                  <a v-for="artifact in managerExecution.artifacts" :key="artifact.id" :href="platformApi.artifactDownloadUrl(artifact.id)">
                    <span><strong>{{ artifact.filename }}</strong><small>{{ artifact.artifact_type }} · {{ formatBytes(artifact.size_bytes) }}</small></span>
                    <NIcon :component="Download" size="17" />
                  </a>
                </div>
              </div>
            </article>
          </div>
        </section>

        <section v-else class="agent-conversation-view">
          <aside class="agent-task-pane">
            <header><ListDetails size="17" /><strong>Agent 节点</strong><span>{{ orderedTasks.length }}</span></header>
            <div v-if="orderedTasks.length" class="agent-task-list">
              <button
                v-for="task in orderedTasks"
                :key="task.id"
                type="button"
                :class="{ active: task.id === selectedTaskId }"
                @click="selectTask(task)"
              >
                <span class="agent-task-title"><strong>{{ taskTitle(task) }}</strong><StatusTag :status="task.status" /></span>
                <span>{{ taskAgentName(task) }}</span>
                <small>{{ taskRuntime(task) }} · {{ task.node_type }}</small>
              </button>
            </div>
            <div v-else class="workspace-empty compact"><strong>暂无 Agent 节点</strong></div>
          </aside>

          <div class="agent-detail-pane">
            <div v-if="selectedTask" class="agent-detail-header">
              <div>
                <span>{{ taskTitle(selectedTask) }}</span>
                <strong>{{ selectedAgentName }}</strong>
                <small class="mono">{{ selectedTask.agent_id }}</small>
              </div>
              <StatusTag :status="selectedTask.status" />
            </div>

            <div v-if="selectedTask" class="agent-scope-tabs" role="tablist" aria-label="Agent 对话范围">
              <button type="button" role="tab" :aria-selected="agentScope === 'current'" :class="{ active: agentScope === 'current' }" @click="agentScope = 'current'">本次执行</button>
              <button type="button" role="tab" :aria-selected="agentScope === 'history'" :class="{ active: agentScope === 'history' }" @click="agentScope = 'history'">全部历史</button>
            </div>

            <div v-if="!selectedTask" class="workspace-empty workspace-empty-main">
              <NIcon :component="Robot" size="30" />
              <strong>请选择一个 Agent 节点</strong>
            </div>

            <div v-else-if="agentScope === 'current'" class="current-agent-conversation">
              <article class="run-message run-message-user">
                <span class="run-avatar"><NIcon :component="User" size="18" /></span>
                <div class="run-message-body">
                  <header><strong>实际运行输入</strong><time>{{ formatDate(selectedTask.started_at || selectedTask.created_at) }}</time></header>
                  <div class="run-copy run-copy-user">
                    <template v-for="(block, index) in messageBlocks(selectedInput)" :key="index">
                      <h3 v-if="block.kind === 'heading'">{{ block.text }}</h3>
                      <p v-else-if="block.kind === 'paragraph'">{{ block.text }}</p>
                      <div v-else-if="block.kind === 'list'" class="run-list-item">{{ block.text }}</div>
                      <pre v-else><code>{{ block.text }}</code></pre>
                    </template>
                  </div>
                </div>
              </article>

              <article class="run-message run-message-agent">
                <span class="run-avatar"><NIcon :component="Robot" size="18" /></span>
                <div class="run-message-body">
                  <header><strong>{{ selectedAgentName }}</strong><time>{{ formatDate(selectedTask.finished_at || selectedTask.started_at) }}</time></header>

                  <div v-if="agentOutputModes.length > 1" class="output-mode-tabs" role="tablist" aria-label="Agent 输出格式">
                    <button
                      v-for="mode in agentOutputModes"
                      :key="mode"
                      type="button"
                      role="tab"
                      :aria-selected="agentOutputMode === mode"
                      :class="{ active: agentOutputMode === mode }"
                      @click="agentOutputMode = mode"
                    >{{ outputModeLabel(mode) }}</button>
                  </div>

                  <div v-if="selectedExecutionLoading" class="workspace-skeleton result">
                    <div v-for="index in 5" :key="index" class="skeleton-line" />
                  </div>
                  <div v-else-if="selectedExecutionError" class="workspace-inline-error">
                    <NIcon :component="AlertCircle" size="22" />
                    <div><strong>Agent 输出加载失败</strong><p>{{ selectedExecutionError }}</p></div>
                  </div>
                  <div v-else-if="agentOutputText" class="run-copy run-copy-agent">
                    <pre v-if="agentOutputMode !== 'readable'"><code>{{ agentOutputText }}</code></pre>
                    <template v-else v-for="(block, index) in messageBlocks(agentOutputText)" :key="index">
                      <h3 v-if="block.kind === 'heading'">{{ block.text }}</h3>
                      <p v-else-if="block.kind === 'paragraph'">{{ block.text }}</p>
                      <div v-else-if="block.kind === 'list'" class="run-list-item">{{ block.text }}</div>
                      <pre v-else><code>{{ block.text }}</code></pre>
                    </template>
                  </div>
                  <div v-else-if="['pending', 'running', 'retrying', 'waiting_child'].includes(selectedTask.status)" class="workspace-empty result-empty">
                    <NIcon :component="Clock" size="24" />
                    <strong>Agent 正在处理</strong><p>完成后会在此显示输出。</p>
                  </div>
                  <div v-else class="workspace-inline-error">
                    <NIcon :component="AlertCircle" size="22" />
                    <div><strong>本节点没有可展示的输出</strong><p>{{ selectedTask.error || selectedExecution?.error || '后端未返回输出内容。' }}</p></div>
                  </div>

                  <div v-if="selectedTask.status === 'human_review'" class="approval-actions">
                    <NButton size="small" type="primary" @click="emit('review', selectedTask, true)">通过</NButton>
                    <NButton size="small" type="error" secondary @click="emit('review', selectedTask, false)">拒绝</NButton>
                  </div>

                  <footer v-if="selectedTask.execution_id" class="run-message-footer">
                    <span class="mono">Execution {{ selectedTask.execution_id }}</span>
                    <div>
                      <NButton text size="tiny" @click="emit('openExecution', selectedTask.execution_id)">执行详情</NButton>
                      <NButton text size="tiny" @click="emit('openTrace', selectedTask.execution_id)">查看 Trace</NButton>
                    </div>
                  </footer>

                  <div v-if="selectedExecution?.artifacts.length" class="run-artifacts">
                    <header><FileText size="15" /><strong>Agent 产物</strong><span>{{ selectedExecution.artifacts.length }} 个</span></header>
                    <a v-for="artifact in selectedExecution.artifacts" :key="artifact.id" :href="platformApi.artifactDownloadUrl(artifact.id)">
                      <span><strong>{{ artifact.filename }}</strong><small>{{ artifact.artifact_type }} · {{ formatBytes(artifact.size_bytes) }}</small></span>
                      <NIcon :component="Download" size="17" />
                    </a>
                  </div>
                </div>
              </article>
            </div>

            <div v-else class="run-agent-history">
              <AgentConversationPanel
                :executions="historyExecutions"
                :loading="historyLoading"
                :history-error="historyError"
                :agent-name="selectedAgentName"
                @refresh="loadHistory(true)"
                @open-trace="emit('openTrace', $event)"
              />
            </div>
          </div>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.team-run-workspace { grid-column: 1 / -1; overflow: hidden; border: 1px solid var(--line); border-radius: 12px; background: var(--surface); box-shadow: 0 8px 24px rgba(0, 0, 0, .14); }
.workspace-heading { display: flex; min-height: 78px; align-items: center; justify-content: space-between; gap: 18px; padding: 18px 20px; border-bottom: 1px solid var(--line); }
.workspace-heading > div { display: flex; align-items: center; gap: 12px; }
.workspace-step { display: grid; width: 30px; height: 30px; place-items: center; border-radius: 7px; color: #171717; background: var(--accent); font: 700 10px/1 "SFMono-Regular", Consolas, monospace; }
.workspace-heading h2 { margin: 0; font-size: 17px; }
.workspace-heading p { margin: 4px 0 0; color: var(--muted); font-size: 11px; }
.workspace-shell { display: grid; grid-template-columns: 300px minmax(0, 1fr); min-height: 760px; }
.run-history-pane { min-width: 0; border-right: 1px solid var(--line); background: var(--surface-subtle); }
.run-history-pane > header, .agent-task-pane > header { display: flex; min-height: 58px; align-items: center; justify-content: space-between; gap: 10px; padding: 13px 15px; border-bottom: 1px solid var(--line); }
.run-history-pane > header > div, .agent-task-pane > header { color: var(--ink); }
.run-history-pane > header > div { display: flex; align-items: center; gap: 8px; }
.run-history-pane > header strong, .agent-task-pane > header strong { font-size: 12px; }
.run-history-pane > header span, .agent-task-pane > header span { color: var(--muted); font-size: 9px; }
.run-history-list { display: grid; max-height: 830px; overflow-y: auto; }
.run-history-list > button { display: grid; gap: 8px; width: 100%; padding: 13px 15px; border: 0; border-bottom: 1px solid var(--line); color: var(--ink); background: transparent; text-align: left; cursor: pointer; }
.run-history-list > button:hover { background: #303030; }
.run-history-list > button.active { background: #343434; box-shadow: inset 3px 0 0 var(--accent); }
.run-history-list > button:focus-visible, .workspace-tabs button:focus-visible, .agent-task-list button:focus-visible, .agent-scope-tabs button:focus-visible, .output-mode-tabs button:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.run-history-meta { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.run-history-meta time, .run-history-list .mono { color: var(--muted); font-size: 9px; }
.run-history-list strong { display: -webkit-box; overflow: hidden; font-size: 11px; line-height: 1.5; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.run-history-list .mono { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-workspace-main { min-width: 0; background: #242424; }
.workspace-tabs { display: flex; min-height: 58px; align-items: end; gap: 4px; padding: 0 18px; border-bottom: 1px solid var(--line); background: #292929; }
.workspace-tabs button { display: flex; height: 58px; align-items: center; gap: 7px; padding: 0 14px; border: 0; border-bottom: 2px solid transparent; color: var(--muted); background: transparent; font-size: 11px; cursor: pointer; }
.workspace-tabs button.active { color: var(--ink); border-bottom-color: var(--accent); font-weight: 650; }
.workspace-run-id { min-width: 0; margin: auto 0 auto auto; overflow: hidden; color: var(--muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.run-context-header { display: flex; min-height: 74px; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 22px; border-bottom: 1px solid var(--line); }
.run-context-header > div:first-child { display: grid; min-width: 0; gap: 4px; }
.run-context-header > div:first-child > span { color: var(--muted); font-size: 9px; text-transform: uppercase; }
.run-context-header > div:first-child strong { overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.run-status-group { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }
.run-status-group > span { display: flex; align-items: center; gap: 6px; color: var(--muted); font-size: 9px; }
.team-conversation, .current-agent-conversation { display: grid; width: min(100%, 1120px); gap: 28px; margin-inline: auto; padding: 28px clamp(20px, 4vw, 54px) 46px; }
.run-message { display: grid; grid-template-columns: 34px minmax(0, 1fr); gap: 12px; align-items: start; }
.run-avatar { display: grid; width: 34px; height: 34px; place-items: center; border: 1px solid #505050; border-radius: 8px; color: var(--muted); background: #303030; }
.run-message-user .run-avatar { color: #1a1a1a; border-color: #d4d4d4; background: var(--accent); }
.run-message-body { min-width: 0; }
.run-message-body > header { display: flex; min-height: 25px; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 7px; }
.run-message-body > header strong { font-size: 12px; }
.run-message-body > header time { color: var(--muted); font: 9px/1.4 "SFMono-Regular", Consolas, monospace; }
.run-copy { padding: 15px 17px; border: 1px solid var(--line); border-radius: 8px; color: #d6d6d6; background: #202020; font-size: 13px; line-height: 1.74; overflow-wrap: anywhere; }
.run-copy-user { width: fit-content; max-width: min(92%, 820px); margin-left: auto; border-color: #505050; background: #343434; white-space: pre-wrap; }
.run-copy h3 { margin: 18px 0 8px; color: var(--ink); font-size: 15px; }
.run-copy h3:first-child { margin-top: 0; }
.run-copy p { margin: 0; white-space: pre-wrap; }
.run-copy p + p, .run-copy p + .run-list-item, .run-list-item + p { margin-top: 9px; }
.run-list-item { position: relative; padding-left: 15px; }
.run-list-item::before { content: ""; position: absolute; top: .72em; left: 2px; width: 4px; height: 4px; border-radius: 50%; background: var(--muted); }
.run-copy pre { max-width: 100%; margin: 12px 0 0; overflow: auto; padding: 14px; border: 1px solid #404040; border-radius: 6px; color: #dcdcdc; background: #171717; font: 11px/1.65 "SFMono-Regular", Consolas, monospace; white-space: pre; }
.run-copy > pre:first-child { margin-top: 0; }
.output-mode-tabs, .agent-scope-tabs { display: flex; flex-wrap: wrap; gap: 4px; }
.output-mode-tabs { margin: 0 0 8px; }
.output-mode-tabs button, .agent-scope-tabs button { padding: 6px 10px; border: 1px solid var(--line); border-radius: 6px; color: var(--muted); background: transparent; font-size: 9px; cursor: pointer; }
.output-mode-tabs button.active, .agent-scope-tabs button.active { color: #171717; border-color: var(--accent); background: var(--accent); font-weight: 700; }
.run-message-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 8px; color: var(--muted); font-size: 9px; }
.run-message-footer > span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.run-message-footer > div { display: flex; gap: 8px; }
.run-artifacts { display: grid; gap: 6px; margin-top: 13px; padding-top: 12px; border-top: 1px solid var(--line); }
.run-artifacts > header { display: flex; align-items: center; gap: 7px; color: var(--muted); }
.run-artifacts > header strong { color: var(--ink); font-size: 10px; }
.run-artifacts > header span { margin-left: auto; font-size: 9px; }
.run-artifacts > a { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 11px; border-radius: 6px; background: #303030; }
.run-artifacts > a:hover { background: #373737; }
.run-artifacts > a > span { display: grid; min-width: 0; gap: 3px; }
.run-artifacts > a strong { overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }
.run-artifacts > a small { color: var(--muted); font-size: 8px; }
.workspace-inline-error { display: flex; min-height: 120px; align-items: flex-start; gap: 12px; padding: 18px; border: 1px solid rgba(239, 83, 80, .3); border-radius: 8px; color: #ff8a87; background: rgba(239, 83, 80, .06); }
.workspace-inline-error strong { color: #ffaaa7; font-size: 12px; }
.workspace-inline-error p { margin: 5px 0 0; font-size: 10px; line-height: 1.6; }
.workspace-empty { display: grid; min-height: 260px; place-content: center; justify-items: center; padding: 24px; color: var(--muted); text-align: center; }
.workspace-empty strong { margin-top: 9px; color: var(--ink); font-size: 12px; }
.workspace-empty p { max-width: 340px; margin: 6px 0 0; font-size: 10px; line-height: 1.55; }
.workspace-empty.compact { min-height: 230px; }
.workspace-empty-main { min-height: 650px; }
.result-empty { min-height: 300px; border: 1px solid var(--line); border-radius: 8px; background: #202020; }
.workspace-skeleton { display: grid; gap: 12px; padding: 22px; }
.workspace-skeleton.compact { padding: 16px; }
.workspace-skeleton.result { min-height: 280px; align-content: start; border: 1px solid var(--line); border-radius: 8px; background: #202020; }
.agent-conversation-view { display: grid; grid-template-columns: 270px minmax(0, 1fr); min-height: 700px; }
.agent-task-pane { min-width: 0; border-right: 1px solid var(--line); background: var(--surface-subtle); }
.agent-task-pane > header { justify-content: flex-start; }
.agent-task-pane > header span { margin-left: auto; }
.agent-task-list { display: grid; max-height: 780px; overflow-y: auto; }
.agent-task-list button { display: grid; gap: 5px; width: 100%; padding: 13px 14px; border: 0; border-bottom: 1px solid var(--line); color: var(--ink); background: transparent; text-align: left; cursor: pointer; }
.agent-task-list button:hover { background: #303030; }
.agent-task-list button.active { background: #343434; box-shadow: inset 3px 0 0 var(--accent); }
.agent-task-title { display: flex; align-items: center; justify-content: space-between; gap: 9px; }
.agent-task-title strong { min-width: 0; overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.agent-task-list button > span:not(.agent-task-title), .agent-task-list small { overflow: hidden; color: var(--muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.agent-detail-pane { min-width: 0; }
.agent-detail-header { display: flex; min-height: 74px; align-items: center; justify-content: space-between; gap: 12px; padding: 13px 20px; border-bottom: 1px solid var(--line); }
.agent-detail-header > div { display: grid; min-width: 0; gap: 3px; }
.agent-detail-header > div > span { color: var(--muted); font-size: 9px; }
.agent-detail-header strong { overflow: hidden; font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.agent-detail-header small { overflow: hidden; color: var(--muted); font-size: 8px; text-overflow: ellipsis; white-space: nowrap; }
.agent-scope-tabs { min-height: 48px; align-items: center; padding: 8px 20px; border-bottom: 1px solid var(--line); background: #292929; }
.current-agent-conversation { padding-top: 24px; }
.run-agent-history { padding: 14px; }
.run-agent-history :deep(.conversation-workspace) { min-height: 640px; }
.approval-actions { display: flex; gap: 8px; margin-top: 12px; }
.mono { font-family: "SFMono-Regular", Consolas, monospace; }

@media (max-width: 1180px) {
  .workspace-shell { grid-template-columns: 1fr; }
  .run-history-pane { border-right: 0; border-bottom: 1px solid var(--line); }
  .run-history-list { grid-template-columns: repeat(2, minmax(0, 1fr)); max-height: 320px; }
  .run-history-list > button:nth-child(odd) { border-right: 1px solid var(--line); }
  .agent-conversation-view { grid-template-columns: 230px minmax(0, 1fr); }
}

@media (max-width: 820px) {
  .workspace-heading, .run-context-header { align-items: flex-start; flex-direction: column; }
  .workspace-heading .n-button { width: 100%; }
  .run-status-group { justify-content: flex-start; }
  .workspace-tabs { padding-inline: 8px; }
  .workspace-run-id { display: none; }
  .run-history-list, .agent-conversation-view { grid-template-columns: 1fr; }
  .run-history-list > button:nth-child(odd) { border-right: 0; }
  .agent-task-pane { border-right: 0; border-bottom: 1px solid var(--line); }
  .agent-task-list { grid-template-columns: 1fr 1fr; max-height: 300px; }
  .agent-task-list button:nth-child(odd) { border-right: 1px solid var(--line); }
}

@media (max-width: 620px) {
  .workspace-heading { padding: 15px; }
  .workspace-heading p { line-height: 1.5; }
  .workspace-tabs button { flex: 1; justify-content: center; }
  .team-conversation, .current-agent-conversation { padding: 20px 13px 30px; }
  .run-message { grid-template-columns: 30px minmax(0, 1fr); gap: 9px; }
  .run-avatar { width: 30px; height: 30px; }
  .run-message-body > header, .run-message-footer { align-items: flex-start; flex-direction: column; }
  .run-copy-user { max-width: 100%; }
  .agent-task-list { grid-template-columns: 1fr; }
  .agent-task-list button:nth-child(odd) { border-right: 0; }
  .run-agent-history { padding: 0; }
}
</style>
