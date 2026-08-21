<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NIcon } from 'naive-ui'
import {
  ArrowDown,
  GitBranch,
  Menu2,
  Messages,
  PlayerStop,
  Plus,
  Refresh,
  Search,
  Send,
  Users,
  X,
} from '@vicons/tabler'

import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import StatusTag from '@/components/StatusTag.vue'
import TeamChatRun from '@/components/agent/TeamChatRun.vue'
import { useChatThreadViewport } from '@/composables/useChatThreadViewport'
import type {
  AgentTeam,
  TeamConversationSummary,
  Workflow,
  WorkflowRun,
} from '@/types/api'
import { formatDate } from '@/utils/format'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const conversationsLoading = ref(false)
const runsLoading = ref(false)
const sending = ref(false)
const error = ref('')
const sendError = ref('')
const teams = ref<AgentTeam[]>([])
const workflows = ref<Workflow[]>([])
const conversations = ref<TeamConversationSummary[]>([])
const runs = ref<WorkflowRun[]>([])
const selectedTeamId = ref('')
const selectedSessionId = ref('')
const selectedWorkflowValue = ref('direct')
const composer = ref('')
const teamSearch = ref('')
const refreshTick = ref(0)
const mobilePanel = ref<'teams' | 'sessions' | null>(null)
const detailRunId = ref('')
const workspaceElement = ref<HTMLElement | null>(null)
const panelTrigger = ref<HTMLElement | null>(null)
const detailTrigger = ref<HTMLElement | null>(null)
const detailActionLoading = ref(false)
let conversationSerial = 0
let runSerial = 0
let pollTimer: number | null = null
let pollInFlight = false
let initialized = false

const {
  threadElement,
  latestAvailable,
  rememberThreadPosition,
  handleThreadScroll,
  jumpToLatest,
  restoreSessionPosition,
  contentChanged,
} = useChatThreadViewport(selectedSessionId)
void threadElement

const activeStatuses = new Set(['pending', 'running', 'human_review'])
const activeTeams = computed(() => teams.value.filter((team) => team.status === 'active'))
const filteredTeams = computed(() => {
  const query = teamSearch.value.trim().toLocaleLowerCase()
  if (!query) return activeTeams.value
  return activeTeams.value.filter((team) => [team.name, team.description, team.id]
    .some((value) => String(value || '').toLocaleLowerCase().includes(query)))
})
const selectedTeam = computed(() => teams.value.find((team) => team.id === selectedTeamId.value) || null)
const selectedConversation = computed(() => conversations.value.find(
  (conversation) => conversation.session_id === selectedSessionId.value,
) || null)
const selectedDetailRun = computed(() => runs.value.find((run) => run.id === detailRunId.value) || null)
const teamWorkflows = computed(() => workflows.value.filter(
  (workflow) => workflow.team_id === selectedTeamId.value && workflow.status === 'active',
))
const workflowOptions = computed(() => [
  { label: '直接协作', value: 'direct' },
  ...teamWorkflows.value.map((workflow) => ({ label: workflow.name, value: workflow.id })),
])
const hasActiveRun = computed(() => runs.value.some((run) => activeStatuses.has(run.status)))
const conversationLocked = computed(() => Boolean(selectedConversation.value || runs.value.length))
const selectedWorkflowName = computed(() => {
  if (selectedWorkflowValue.value === 'direct') return '直接协作'
  return teamWorkflows.value.find((workflow) => workflow.id === selectedWorkflowValue.value)?.name || '已停用 Workflow'
})
const composerDisabledReason = computed(() => {
  if (!selectedTeam.value) return '请先选择一个 Agent Team'
  if (selectedTeam.value.status !== 'active') return '当前 Agent Team 已停用'
  if (hasActiveRun.value) return '当前会话仍有运行中的任务，请等待完成后继续'
  if (selectedWorkflowValue.value !== 'direct' && !teamWorkflows.value.some((workflow) => workflow.id === selectedWorkflowValue.value)) {
    return '当前 Workflow 已停用，请切换执行方式后新建聊天'
  }
  return ''
})

function routeString(name: 'team' | 'session' | 'workflow'): string {
  const value = route.query[name]
  return typeof value === 'string' ? value : ''
}

function newSessionId(): string {
  const uuid = globalThis.crypto?.randomUUID?.()
  return `team-chat-${uuid || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`
}

async function writeRoute(push = false) {
  const method = push ? router.push : router.replace
  await method({
    name: 'agent-chat',
    query: {
      mode: 'team',
      team: selectedTeamId.value || undefined,
      session: selectedSessionId.value || undefined,
      workflow: selectedWorkflowValue.value,
    },
  })
}

function stopPolling() {
  if (pollTimer !== null) window.clearTimeout(pollTimer)
  pollTimer = null
}

function schedulePolling(delay = 3000) {
  stopPolling()
  if (!hasActiveRun.value || document.hidden) return
  pollTimer = window.setTimeout(async () => {
    if (pollInFlight) {
      schedulePolling()
      return
    }
    pollInFlight = true
    try {
      await loadRuns(true)
      refreshTick.value += 1
      if (!hasActiveRun.value) await refreshConversationSummaries()
    } finally {
      pollInFlight = false
      schedulePolling()
    }
  }, delay)
}

function handleVisibilityChange() {
  if (document.hidden) stopPolling()
  else if (hasActiveRun.value) schedulePolling(0)
}

async function loadRuns(silent = false) {
  const teamId = selectedTeamId.value
  const sessionId = selectedSessionId.value
  const serial = ++runSerial
  if (!teamId || !sessionId) {
    runs.value = []
    return
  }
  if (!silent || !runs.value.length) runsLoading.value = true
  try {
    const result = await platformApi.listTeamConversationRuns(teamId, sessionId, { limit: 50, offset: 0 })
    if (serial !== runSerial || teamId !== selectedTeamId.value || sessionId !== selectedSessionId.value) return
    runs.value = [...result.items].sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at))
    if (runs.value.length) {
      const fixedWorkflow = runs.value[0].workflow_id || 'direct'
      selectedWorkflowValue.value = fixedWorkflow
    }
    error.value = ''
    schedulePolling()
    await contentChanged()
  } catch (value) {
    if (serial === runSerial) error.value = getApiErrorMessage(value)
  } finally {
    if (serial === runSerial) runsLoading.value = false
  }
}

async function openConversation(conversation: TeamConversationSummary, push = true) {
  rememberThreadPosition()
  stopPolling()
  selectedSessionId.value = conversation.session_id
  selectedWorkflowValue.value = conversation.workflow_id || 'direct'
  runs.value = []
  sendError.value = ''
  if (push) await writeRoute(true)
  await loadRuns()
  await restoreSessionPosition()
  mobilePanel.value = null
  detailRunId.value = ''
}

async function startNewChat(workflowValue = 'direct', push = true) {
  rememberThreadPosition()
  stopPolling()
  selectedSessionId.value = newSessionId()
  selectedWorkflowValue.value = workflowValue
  runs.value = []
  composer.value = ''
  sendError.value = ''
  if (push) await writeRoute(true)
  await jumpToLatest()
  mobilePanel.value = null
  detailRunId.value = ''
}

async function loadConversations(silent = false, requestedSession = '') {
  const teamId = selectedTeamId.value
  const serial = ++conversationSerial
  if (!teamId) {
    conversations.value = []
    return
  }
  if (!silent || !conversations.value.length) conversationsLoading.value = true
  try {
    const result = await platformApi.listTeamConversations(teamId, { limit: 50, offset: 0 })
    if (serial !== conversationSerial || teamId !== selectedTeamId.value) return
    conversations.value = result.items
    const requested = requestedSession || selectedSessionId.value
    const matched = result.items.find((conversation) => conversation.session_id === requested)
    if (matched) {
      await openConversation(matched, false)
    } else if (requested && requested.startsWith('team-chat-')) {
      selectedSessionId.value = requested
      selectedWorkflowValue.value = routeString('workflow') || 'direct'
      runs.value = []
    } else if (result.items[0]) {
      await openConversation(result.items[0], false)
    } else {
      await startNewChat(routeString('workflow') || 'direct', false)
    }
    await writeRoute(false)
    error.value = ''
  } catch (value) {
    if (serial === conversationSerial) error.value = getApiErrorMessage(value)
  } finally {
    if (serial === conversationSerial) conversationsLoading.value = false
  }
}

async function refreshConversationSummaries() {
  const teamId = selectedTeamId.value
  const serial = ++conversationSerial
  if (!teamId) return
  try {
    const result = await platformApi.listTeamConversations(teamId, { limit: 50, offset: 0 })
    if (serial === conversationSerial && teamId === selectedTeamId.value) conversations.value = result.items
  } catch (value) {
    if (serial === conversationSerial) error.value = getApiErrorMessage(value)
  }
}

async function selectTeam(teamId: string, push = true) {
  if (!teamId || teamId === selectedTeamId.value && conversations.value.length) return
  rememberThreadPosition()
  stopPolling()
  selectedTeamId.value = teamId
  selectedSessionId.value = ''
  selectedWorkflowValue.value = 'direct'
  conversations.value = []
  runs.value = []
  sendError.value = ''
  if (push) await writeRoute(true)
  await loadConversations(false)
  mobilePanel.value = null
  detailRunId.value = ''
}

async function changeWorkflow(value: string) {
  if (value === selectedWorkflowValue.value) return
  if (conversationLocked.value) {
    await startNewChat(value, true)
    return
  }
  selectedWorkflowValue.value = value
  await writeRoute(false)
}

async function sendMessage() {
  const input = composer.value.trim()
  if (!input || sending.value || composerDisabledReason.value || !selectedTeamId.value) return
  sending.value = true
  sendError.value = ''
  try {
    const run = await platformApi.sendTeamConversationMessage(
      selectedTeamId.value,
      selectedSessionId.value,
      {
        input,
        workflow_id: selectedWorkflowValue.value === 'direct' ? null : selectedWorkflowValue.value,
        priority: 5,
        parameters: {},
      },
    )
    composer.value = ''
    runs.value = [...runs.value, run].sort((left, right) => Date.parse(left.created_at) - Date.parse(right.created_at))
    await writeRoute(false)
    await jumpToLatest()
    schedulePolling()
    void refreshConversationSummaries()
  } catch (value) {
    sendError.value = getApiErrorMessage(value)
  } finally {
    sending.value = false
  }
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void sendMessage()
}

function openMobilePanel(panel: 'teams' | 'sessions', event?: MouseEvent) {
  panelTrigger.value = event?.currentTarget as HTMLElement || document.activeElement as HTMLElement | null
  mobilePanel.value = panel
  void nextTick(() => {
    workspaceElement.value?.querySelector<HTMLElement>(`.${panel === 'teams' ? 'team-picker-pane' : 'team-session-pane'} .team-mobile-close`)?.focus()
  })
}

function closeMobilePanel(restoreFocus = true) {
  if (!mobilePanel.value) return
  mobilePanel.value = null
  if (restoreFocus) void nextTick(() => panelTrigger.value?.focus())
}

function openRunDetails(runId: string, trigger?: HTMLElement) {
  detailTrigger.value = trigger || document.activeElement as HTMLElement | null
  detailRunId.value = runId
  void nextTick(() => {
    workspaceElement.value?.querySelector<HTMLElement>('button[aria-label="关闭团队协作详情"]')?.focus()
  })
}

function closeRunDetails() {
  if (!detailRunId.value) return
  detailRunId.value = ''
  void nextTick(() => detailTrigger.value?.focus())
}

async function cancelDetailRun() {
  const run = selectedDetailRun.value
  if (!run || !activeStatuses.has(run.status) || detailActionLoading.value) return
  detailActionLoading.value = true
  try {
    await platformApi.cancelWorkflowRun(run.id)
    await refreshCurrent()
  } catch (value) {
    error.value = getApiErrorMessage(value)
  } finally {
    detailActionLoading.value = false
  }
}

function handleEscape(event: KeyboardEvent) {
  if (event.key !== 'Escape') return
  if (detailRunId.value) {
    event.preventDefault()
    closeRunDetails()
  } else if (mobilePanel.value) {
    event.preventDefault()
    closeMobilePanel()
  }
}

async function refreshCurrent() {
  if (!selectedTeamId.value) return
  await Promise.all([
    refreshConversationSummaries(),
    loadRuns(true),
  ])
  refreshTick.value += 1
}

async function initialize() {
  loading.value = true
  try {
    const [teamValues, workflowValues] = await Promise.all([
      platformApi.listAgentTeams(),
      platformApi.listWorkflows(),
    ])
    teams.value = teamValues
    workflows.value = workflowValues
    const requestedTeam = routeString('team')
    const initialTeam = activeTeams.value.find((team) => team.id === requestedTeam)?.id || activeTeams.value[0]?.id || ''
    if (initialTeam) {
      selectedTeamId.value = initialTeam
      await loadConversations(false, routeString('session'))
    }
    error.value = ''
  } catch (value) {
    error.value = getApiErrorMessage(value)
  } finally {
    loading.value = false
    initialized = true
  }
}

async function syncRouteState() {
  const requestedTeam = routeString('team')
  if (requestedTeam && requestedTeam !== selectedTeamId.value && activeTeams.value.some((team) => team.id === requestedTeam)) {
    stopPolling()
    selectedTeamId.value = requestedTeam
    selectedSessionId.value = ''
    conversations.value = []
    runs.value = []
    await loadConversations(false, routeString('session'))
    return
  }

  const requestedSession = routeString('session')
  if (requestedSession && requestedSession !== selectedSessionId.value) {
    const conversation = conversations.value.find((item) => item.session_id === requestedSession)
    if (conversation) await openConversation(conversation, false)
    else if (requestedSession.startsWith('team-chat-')) {
      stopPolling()
      selectedSessionId.value = requestedSession
      selectedWorkflowValue.value = routeString('workflow') || 'direct'
      runs.value = []
    }
    return
  }

  const requestedWorkflow = routeString('workflow')
  if (!conversationLocked.value && requestedWorkflow && requestedWorkflow !== selectedWorkflowValue.value) {
    selectedWorkflowValue.value = requestedWorkflow
  }
}

watch(
  () => [route.query.team, route.query.session, route.query.workflow],
  () => { if (initialized) void syncRouteState() },
)

onMounted(() => {
  document.addEventListener('visibilitychange', handleVisibilityChange)
  document.addEventListener('keydown', handleEscape)
  void initialize()
})
onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', handleVisibilityChange)
  document.removeEventListener('keydown', handleEscape)
  stopPolling()
})
</script>

<template>
  <section class="team-chat-page">
    <NAlert v-if="error" type="error" closable class="team-chat-alert" @close="error = ''">{{ error }}</NAlert>

    <section v-if="activeTeams.length" ref="workspaceElement" class="team-chat-workspace">
      <div v-if="mobilePanel" class="team-mobile-scrim" @click="closeMobilePanel()" />
      <aside class="team-picker-pane" :class="{ 'mobile-open': mobilePanel === 'teams' }" aria-label="Agent Team 选择面板">
        <header><div><span>Teams</span><strong>Agent Team</strong></div><small>{{ activeTeams.length }} 个可用</small><button class="team-mobile-close" type="button" aria-label="关闭 Agent Team 列表" @click="closeMobilePanel()"><NIcon :component="X" /></button></header>
        <div class="team-chat-search"><NInput v-model:value="teamSearch" clearable size="small" placeholder="搜索 Team"><template #prefix><NIcon :component="Search" /></template></NInput></div>
        <div v-if="filteredTeams.length" class="team-picker-list" role="listbox" aria-label="Agent Team 列表">
          <button v-for="team in filteredTeams" :key="team.id" type="button" role="option" :aria-selected="team.id === selectedTeamId" :class="{ active: team.id === selectedTeamId }" @click="selectTeam(team.id)">
            <span class="team-picker-icon"><NIcon :component="Users" size="19" /></span>
            <span><strong>{{ team.name }}</strong><small>{{ team.members.length }} 个成员</small><em>{{ team.description || '未填写团队说明' }}</em></span>
          </button>
        </div>
        <div v-else class="team-chat-empty compact">没有匹配的 Agent Team</div>
        <footer><NButton block secondary @click="router.push({ name: 'multi-agent' })"><template #icon><NIcon :component="GitBranch" /></template>管理团队编排</NButton></footer>
      </aside>

      <aside class="team-session-pane" :class="{ 'mobile-open': mobilePanel === 'sessions' }" aria-label="团队会话选择面板">
        <header><div><span>Conversations</span><strong>团队会话</strong></div><NButton quaternary circle size="small" aria-label="新建团队聊天" :disabled="!selectedTeam" @click="startNewChat()"><template #icon><NIcon :component="Plus" /></template></NButton><button class="team-mobile-close" type="button" aria-label="关闭团队会话列表" @click="closeMobilePanel()"><NIcon :component="X" /></button></header>
        <div v-if="conversationsLoading && !conversations.length" class="team-chat-skeleton"><span v-for="index in 5" :key="index" /></div>
        <div v-else-if="conversations.length" class="team-session-list" role="listbox" aria-label="团队会话列表">
          <button v-for="conversation in conversations" :key="conversation.session_id" type="button" role="option" :aria-selected="conversation.session_id === selectedSessionId" :class="{ active: conversation.session_id === selectedSessionId }" @click="openConversation(conversation)">
            <strong>{{ conversation.title }}</strong>
            <span><time>{{ formatDate(conversation.updated_at) }}</time><small>{{ conversation.run_count }} 轮</small></span>
            <div><StatusTag :status="conversation.latest_status" /><em>{{ conversation.workflow_name || '直接协作' }}</em></div>
          </button>
        </div>
        <div v-else class="team-chat-empty"><NIcon :component="Messages" size="26" /><strong>暂无历史会话</strong><span>发送第一条消息后，会话会显示在这里。</span></div>
        <footer><NButton block secondary :disabled="!selectedTeam" @click="startNewChat()"><template #icon><NIcon :component="Plus" /></template>新建聊天</NButton></footer>
      </aside>

      <main class="team-thread-pane">
        <header class="team-thread-header">
          <div class="team-mobile-tools"><NButton class="team-picker-toggle" quaternary circle aria-label="打开 Agent Team 列表" @click="openMobilePanel('teams', $event)"><template #icon><NIcon :component="Menu2" /></template></NButton><NButton class="team-session-toggle" quaternary circle aria-label="打开团队会话列表" @click="openMobilePanel('sessions', $event)"><template #icon><NIcon :component="Messages" /></template></NButton></div>
          <span class="team-thread-avatar"><NIcon :component="Users" size="21" /></span>
          <div class="team-thread-identity"><strong>{{ selectedTeam?.name || '请选择 Agent Team' }}</strong><span v-if="selectedTeam">{{ selectedTeam.members.length }} 个成员，{{ runs.length }} 轮对话</span></div>
          <div class="team-workflow-control">
            <label for="team-workflow-select">执行方式</label>
            <NSelect id="team-workflow-select" :value="selectedWorkflowValue" :options="workflowOptions" size="small" :disabled="sending" @update:value="changeWorkflow" />
            <small v-if="conversationLocked">已固定为 {{ selectedWorkflowName }}，切换会新建聊天</small>
          </div>
          <NButton quaternary circle aria-label="刷新团队聊天" :loading="loading || conversationsLoading || runsLoading" @click="refreshCurrent"><template #icon><NIcon :component="Refresh" /></template></NButton>
        </header>

        <div ref="threadElement" class="team-thread" aria-live="polite" @scroll.passive="handleThreadScroll">
          <div v-if="runsLoading && !runs.length" class="team-thread-skeleton"><span v-for="index in 6" :key="index" /></div>
          <template v-else-if="runs.length">
            <TeamChatRun v-for="run in runs" :key="run.id" :run="run" :team="selectedTeam!" :refresh-tick="refreshTick" @refresh="refreshCurrent" @open-details="openRunDetails" />
          </template>
          <div v-else class="team-chat-welcome">
            <span><NIcon :component="Messages" size="29" /></span>
            <strong>开始新的 Team 对话</strong>
            <p>选择执行方式并发送任务。同一聊天中的稳定节点会复用各自的 Agent Memory。</p>
          </div>
        </div>

        <footer class="team-composer-shell">
          <div v-if="latestAvailable" class="team-latest-row"><NButton secondary size="small" @click="jumpToLatest"><template #icon><NIcon :component="ArrowDown" /></template>回到最新消息</NButton></div>
          <NAlert v-if="composerDisabledReason" type="warning" :bordered="false" class="team-composer-alert">{{ composerDisabledReason }}</NAlert>
          <div v-if="sendError" class="team-send-error">{{ sendError }}</div>
          <div class="team-composer">
            <NInput v-model:value="composer" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" maxlength="100000" placeholder="输入团队任务，Enter 发送，Shift + Enter 换行" :disabled="sending || Boolean(composerDisabledReason)" @keydown="handleComposerKeydown" />
            <NButton type="primary" circle size="large" aria-label="发送团队消息" :loading="sending" :disabled="!composer.trim() || Boolean(composerDisabledReason)" @click="sendMessage"><template #icon><NIcon :component="Send" /></template></NButton>
          </div>
          <div class="team-composer-meta"><span class="mono">Session {{ selectedSessionId || '--' }}</span><span>{{ selectedWorkflowName }}</span></div>
        </footer>
      </main>

      <div v-if="selectedDetailRun" class="team-detail-scrim" @click="closeRunDetails" />
      <aside v-if="selectedDetailRun" class="team-run-detail-panel" role="dialog" aria-modal="true" aria-label="团队协作详情">
        <header><div><strong>团队协作详情</strong><span class="mono">Run {{ selectedDetailRun.id }}</span></div><div><NButton v-if="activeStatuses.has(selectedDetailRun.status)" text type="error" :loading="detailActionLoading" @click="cancelDetailRun"><template #icon><NIcon :component="PlayerStop" /></template>取消运行</NButton><NButton quaternary circle aria-label="关闭团队协作详情" @click="closeRunDetails"><template #icon><NIcon :component="X" /></template></NButton></div></header>
        <div class="team-run-detail-scroll"><TeamChatRun :run="selectedDetailRun" :team="selectedTeam!" :refresh-tick="refreshTick" detail-only @refresh="refreshCurrent" /></div>
      </aside>
    </section>

    <section v-else-if="!loading" class="team-chat-no-teams surface">
      <NIcon :component="Users" size="34" />
      <strong>没有可用的 Agent Team</strong>
      <p>请先在团队编排中创建并启用 Team。</p>
      <NButton type="primary" @click="router.push({ name: 'multi-agent' })">前往团队编排</NButton>
    </section>
  </section>
</template>

<style scoped>
.team-chat-page{display:flex;width:100%;max-width:none;height:100%;min-height:0;flex-direction:column;overflow:hidden}.team-chat-alert{max-height:96px;flex:0 0 auto;margin-bottom:12px;overflow:auto}.team-chat-workspace{position:relative;display:grid;grid-template-columns:250px 270px minmax(0,1fr);min-height:0;flex:1;overflow:hidden;border:1px solid var(--line);border-radius:11px;background:#222}.team-picker-pane,.team-session-pane,.team-thread-pane{min-width:0;min-height:0}.team-picker-pane,.team-session-pane{display:flex;flex-direction:column;border-right:1px solid var(--line);background:var(--surface-subtle)}.team-session-pane{background:#282828}.team-picker-pane>header,.team-session-pane>header,.team-thread-header{display:flex;min-height:70px;align-items:center;gap:12px;padding:14px 15px;border-bottom:1px solid var(--line)}.team-picker-pane>header,.team-session-pane>header{justify-content:space-between}.team-picker-pane>header>div,.team-session-pane>header>div{display:grid;gap:3px}.team-picker-pane>header span,.team-session-pane>header span{color:#777;font-size:8px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.team-picker-pane>header strong,.team-session-pane>header strong{font-size:12px}.team-picker-pane>header small{color:var(--muted);font-size:8px}.team-chat-search{padding:11px;border-bottom:1px solid var(--line)}.team-picker-list,.team-session-list{flex:1;overflow:auto;padding:7px}.team-picker-list>button,.team-session-list>button{width:100%;border:1px solid transparent;border-radius:8px;color:var(--ink);background:transparent;text-align:left;cursor:pointer}.team-picker-list>button{display:grid;grid-template-columns:38px minmax(0,1fr);gap:9px;align-items:center;padding:10px}.team-picker-list>button:hover,.team-session-list>button:hover{background:#323232}.team-picker-list>button.active,.team-session-list>button.active{border-color:#555;background:#383838}.team-picker-icon,.team-thread-avatar{display:grid;width:36px;height:36px;place-items:center;border-radius:9px;background:#3a3a3a}.team-picker-list>button>span:last-child{display:grid;min-width:0;gap:2px}.team-picker-list strong,.team-picker-list small,.team-picker-list em{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.team-picker-list strong{font-size:11px}.team-picker-list small{color:#aaa;font-size:8px}.team-picker-list em{color:#777;font-size:8px;font-style:normal}.team-picker-pane>footer,.team-session-pane>footer{padding:11px;border-top:1px solid var(--line)}.team-session-list>button{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px;padding:11px}.team-session-list>button>strong{grid-column:1/-1;overflow:hidden;font-size:11px;text-overflow:ellipsis;white-space:nowrap}.team-session-list>button>span{display:flex;gap:7px;color:var(--muted);font-size:8px}.team-session-list>button>div{display:flex;min-width:0;align-items:center;justify-content:flex-end;gap:6px}.team-session-list em{overflow:hidden;color:#888;font-size:8px;font-style:normal;text-overflow:ellipsis;white-space:nowrap}.team-chat-empty{display:grid;flex:1;place-content:center;justify-items:center;gap:6px;padding:20px;color:var(--muted);font-size:9px;text-align:center}.team-chat-empty.compact{display:block;flex:0;padding:20px}.team-chat-empty strong{color:var(--ink);font-size:11px}.team-chat-skeleton,.team-thread-skeleton{display:grid;gap:8px;padding:12px}.team-chat-skeleton span{height:64px;border-radius:7px;background:#353535;animation:team-workspace-pulse 1.3s ease-in-out infinite}.team-thread-pane{position:relative;display:grid;height:100%;min-height:0;grid-template-rows:auto minmax(0,1fr) auto}.team-thread-header{background:#292929}.team-workflow-control{display:grid;width:min(300px,38%);grid-template-columns:auto minmax(130px,1fr);align-items:center;gap:4px 8px}.team-workflow-control label{color:var(--muted);font-size:9px}.team-workflow-control small{grid-column:1/-1;color:#7f7f7f;font-size:8px;text-align:right}.team-thread{min-height:0;overflow:auto;padding:26px clamp(14px,3vw,44px);scroll-behavior:smooth;overscroll-behavior:contain}.team-thread-skeleton{max-width:900px;margin:auto}.team-thread-skeleton span{height:58px;border-radius:8px;background:#303030;animation:team-workspace-pulse 1.3s ease-in-out infinite}.team-chat-welcome{display:grid;min-height:100%;place-content:center;justify-items:center;padding:28px;color:var(--muted);text-align:center}.team-chat-welcome>span{display:grid;width:58px;height:58px;place-items:center;border-radius:14px;background:#303030}.team-chat-welcome strong{margin-top:13px;color:var(--ink);font-size:15px}.team-chat-welcome p{max-width:480px;margin:7px 0;font-size:10px;line-height:1.65}.team-composer-shell{padding:13px clamp(14px,3vw,40px) 11px;border-top:1px solid var(--line);background:#292929}.team-composer{display:flex;max-width:1040px;margin:auto;align-items:flex-end;gap:10px}.team-composer :deep(.n-input){border-radius:9px}.team-composer-alert,.team-send-error{max-width:1040px;max-height:96px;margin:0 auto 8px;overflow:auto}.team-send-error{color:#ff8a87;font-size:10px}.team-composer-meta{display:flex;justify-content:space-between;gap:14px;max-width:1040px;margin:7px auto 0;color:#777;font-size:8px}.team-chat-no-teams{display:grid;min-height:0;flex:1;place-content:center;justify-items:center;gap:9px;overflow:auto;text-align:center}.team-chat-no-teams p{margin:0 0 6px;color:var(--muted);font-size:11px}@keyframes team-workspace-pulse{0%,100%{opacity:.48}50%{opacity:1}}@media(prefers-reduced-motion:reduce){.team-chat-skeleton span,.team-thread-skeleton span{animation:none}.team-thread{scroll-behavior:auto}}
/* Full-height Team workspace. Lists, thread and detail panel scroll independently. */
.team-thread-identity{display:grid;min-width:0;flex:1;gap:3px}.team-thread-identity strong,.team-thread-identity span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.team-thread-identity strong{font-size:13px}.team-thread-identity span{color:var(--muted);font-size:9px}.team-latest-row{display:flex;max-width:1040px;margin:0 auto 8px;justify-content:flex-end}.team-mobile-tools,.team-mobile-close,.team-mobile-scrim{display:none}.team-detail-scrim{position:absolute;z-index:6;inset:0;background:rgba(0,0,0,.38)}.team-run-detail-panel{container:team-run-detail / inline-size;position:absolute;z-index:7;inset:0 0 0 auto;display:grid;width:min(620px,48%);grid-template-rows:auto minmax(0,1fr);border-left:1px solid var(--line);background:#242424;box-shadow:-20px 0 48px rgba(0,0,0,.42)}.team-run-detail-panel>header{display:flex;min-height:64px;align-items:center;justify-content:space-between;gap:12px;padding:11px 14px;border-bottom:1px solid var(--line);background:#292929}.team-run-detail-panel>header>div{display:flex;min-width:0;align-items:center;gap:10px}.team-run-detail-panel>header>div:first-child{display:grid;gap:2px}.team-run-detail-panel>header strong{font-size:12px}.team-run-detail-panel>header span{overflow:hidden;color:var(--muted);font-size:8px;text-overflow:ellipsis;white-space:nowrap}.team-run-detail-scroll{min-height:0;overflow:auto;overscroll-behavior:contain;padding:12px}
@container chat-workbench (max-width:1180px){.team-chat-workspace{grid-template-columns:250px minmax(0,1fr)}.team-picker-pane{position:absolute;z-index:5;inset:0 auto 0 0;width:min(86cqw,320px);transform:translateX(-105%);transition:transform 180ms ease;box-shadow:18px 0 40px rgba(0,0,0,.36)}.team-picker-pane.mobile-open{transform:translateX(0)}.team-mobile-scrim{position:absolute;z-index:4;inset:0;display:block;background:rgba(0,0,0,.62)}.team-mobile-tools{display:flex;gap:2px}.team-picker-toggle{display:inline-flex!important}.team-session-toggle{display:none!important}.team-mobile-close{display:grid;width:30px;height:30px;place-items:center;border:0;border-radius:6px;color:var(--muted);background:transparent}.team-picker-pane>header{grid-template-columns:minmax(0,1fr) auto auto}.team-picker-pane>footer{display:block}.team-picker-list,.team-session-list{display:block;max-height:none;overflow:auto}.team-run-detail-panel{width:min(620px,58%)}.team-thread{padding-inline:14px}}
@container chat-workbench (max-width:820px){.team-chat-workspace{grid-template-columns:minmax(0,1fr)}.team-session-pane{position:absolute;z-index:5;inset:0 auto 0 0;width:min(86cqw,320px);transform:translateX(-105%);transition:transform 180ms ease;box-shadow:18px 0 40px rgba(0,0,0,.36)}.team-session-pane.mobile-open{transform:translateX(0)}.team-session-toggle{display:inline-flex!important}.team-session-pane>header{grid-template-columns:minmax(0,1fr) auto auto}.team-session-pane>footer{display:block}.team-run-detail-panel{width:100%}}
@container chat-workbench (max-width:620px){.team-chat-workspace{border-radius:0}.team-thread-header{align-items:center;min-height:62px;flex-wrap:nowrap;padding:9px}.team-thread-avatar{display:none}.team-thread-identity span{display:none}.team-workflow-control{width:auto;min-width:120px;grid-template-columns:minmax(100px,1fr)}.team-workflow-control label,.team-workflow-control small{display:none}.team-thread{padding:18px 9px}.team-composer-shell{padding:10px}.team-composer-meta{display:none}.team-run-detail-panel>header{min-height:56px}.team-run-detail-scroll{padding:8px}}
</style>
