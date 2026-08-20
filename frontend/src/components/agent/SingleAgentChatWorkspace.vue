<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { NIcon, useMessage } from 'naive-ui'
import {
  Activity,
  Download,
  ExternalLink,
  ListDetails,
  Menu2,
  Messages,
  Plus,
  Robot,
  Search,
  Send,
  User,
  X,
} from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import PageHeader from '@/components/PageHeader.vue'
import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { buildConversationSessions, executionReplyText } from '@/utils/agentConversation'
import { parseSafeMarkdown } from '@/utils/executionStudio'
import { formatDate } from '@/utils/format'
import type { Agent, ExecutionDetail, ExecutionSummary } from '@/types/api'

type SingleAgentMobilePanel = 'agents' | 'sessions' | null

const route = useRoute()
const router = useRouter()
const message = useMessage()
const agents = ref<Agent[]>([])
const agentSearch = ref('')
const agentsLoading = ref(false)
const agentsError = ref<string | null>(null)
const selectedAgentId = ref('')
const histories = ref<ExecutionSummary[]>([])
const historyLoading = ref(false)
const historyError = ref<string | null>(null)
const activeSessionId = ref('')
const transcript = ref<ExecutionDetail[]>([])
const transcriptLoading = ref(false)
const transcriptError = ref<string | null>(null)
const composer = ref('')
const sending = ref(false)
const pendingInput = ref('')
const streamedOutput = ref('')
const sendError = ref<string | null>(null)
const failedTurn = ref<{ input: string; error: string } | null>(null)
const mobilePanel = ref<SingleAgentMobilePanel>(null)
const threadElement = ref<HTMLElement | null>(null)
const detailCache = new Map<string, ExecutionDetail>()
let initialized = false
let historySerial = 0
let transcriptSerial = 0

const sortedAgents = computed(() => [...agents.value].sort((left, right) => {
  if ((left.status === 'active') !== (right.status === 'active')) return left.status === 'active' ? -1 : 1
  return left.name.localeCompare(right.name, 'zh-CN')
}))
const filteredAgents = computed(() => {
  const query = agentSearch.value.trim().toLocaleLowerCase()
  if (!query) return sortedAgents.value
  return sortedAgents.value.filter((agent) => [agent.name, agent.id, agent.model, agent.runtime_type]
    .some((value) => String(value).toLocaleLowerCase().includes(query)))
})
const selectedAgent = computed(() => agents.value.find((agent) => agent.id === selectedAgentId.value) || null)
const sessions = computed(() => buildConversationSessions(histories.value))
const selectedSession = computed(() => sessions.value.find((session) => (
  session.sessionId === activeSessionId.value || session.key === activeSessionId.value
)) || null)
const requiredFields = computed(() => {
  const required = selectedAgent.value?.input_schema?.required
  return Array.isArray(required) ? required.map(String).filter(Boolean) : []
})
const blockedReason = computed(() => {
  if (!selectedAgent.value) return '请先选择一个 Agent'
  if (selectedAgent.value.status !== 'active') return `当前 Agent 状态为 ${selectedAgent.value.status}，不能执行`
  if (requiredFields.value.length) return `该 Agent 需要必填参数：${requiredFields.value.join('、')}`
  return null
})

function createSessionId(): string {
  const nativeId = globalThis.crypto?.randomUUID?.()
  const fallbackId = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
  return `chat-${nativeId || fallbackId}`
}

function messageBlocks(value: string) {
  return parseSafeMarkdown(value)
}

async function scrollThreadToBottom() {
  await nextTick()
  if (threadElement.value) threadElement.value.scrollTop = threadElement.value.scrollHeight
}

async function loadAgents() {
  agentsLoading.value = true
  agentsError.value = null
  try {
    agents.value = await platformApi.listAgents()
  } catch (error) {
    agentsError.value = getApiErrorMessage(error)
  } finally {
    agentsLoading.value = false
  }
}

async function loadHistory(agentId: string) {
  const serial = ++historySerial
  historyLoading.value = true
  historyError.value = null
  try {
    const result = await platformApi.listExecutions({ agent_id: agentId, limit: 50 })
    if (serial === historySerial && selectedAgentId.value === agentId) histories.value = result.items
  } catch (error) {
    if (serial === historySerial) {
      histories.value = []
      historyError.value = getApiErrorMessage(error)
    }
  } finally {
    if (serial === historySerial) historyLoading.value = false
  }
}

async function loadTranscript() {
  const serial = ++transcriptSerial
  const session = selectedSession.value
  transcriptError.value = null
  if (!session) {
    transcript.value = []
    transcriptLoading.value = false
    return
  }
  transcriptLoading.value = true
  try {
    const details = await Promise.all(session.items.map(async (item) => {
      if (detailCache.has(item.id)) return detailCache.get(item.id)!
      const detail = await platformApi.getExecution(item.id)
      detailCache.set(item.id, detail)
      return detail
    }))
    if (serial === transcriptSerial) transcript.value = details
  } catch (error) {
    if (serial === transcriptSerial) {
      transcript.value = []
      transcriptError.value = getApiErrorMessage(error)
    }
  } finally {
    if (serial === transcriptSerial) transcriptLoading.value = false
  }
  await scrollThreadToBottom()
}

async function normalizeRouteSelection() {
  if (!agents.value.length) return
  const requestedAgentId = String(route.query.agent || '')
  const agent = agents.value.find((item) => item.id === requestedAgentId)
    || sortedAgents.value.find((item) => item.status === 'active')
    || sortedAgents.value[0]
  if (!agent) return

  if (requestedAgentId !== agent.id) {
    await router.replace({ name: 'agent-chat', query: { agent: agent.id } })
    return
  }

  let agentChanged = false
  if (selectedAgentId.value !== agent.id) {
    agentChanged = true
    selectedAgentId.value = agent.id
    histories.value = []
    transcript.value = []
    detailCache.clear()
    sendError.value = null
    failedTurn.value = null
    await loadHistory(agent.id)
  }

  const requestedSessionId = String(route.query.session || '')
  if (!requestedSessionId) {
    const sessionId = sessions.value[0]?.sessionId || sessions.value[0]?.key || createSessionId()
    await router.replace({ name: 'agent-chat', query: { agent: agent.id, session: sessionId } })
    return
  }

  if (activeSessionId.value !== requestedSessionId) {
    activeSessionId.value = requestedSessionId
    pendingInput.value = ''
    streamedOutput.value = ''
    sendError.value = null
    failedTurn.value = null
    await loadTranscript()
  } else if (agentChanged) {
    await loadTranscript()
  }
}

function selectAgent(agent: Agent) {
  if (sending.value || agent.id === selectedAgentId.value) {
    mobilePanel.value = null
    return
  }
  void router.push({ name: 'agent-chat', query: { agent: agent.id } })
  mobilePanel.value = null
}

function selectSession(sessionId: string) {
  if (sending.value || sessionId === activeSessionId.value) {
    mobilePanel.value = null
    return
  }
  void router.push({ name: 'agent-chat', query: { agent: selectedAgentId.value, session: sessionId } })
  mobilePanel.value = null
}

function startNewChat() {
  if (sending.value || !selectedAgent.value) return
  void router.push({
    name: 'agent-chat',
    query: { agent: selectedAgent.value.id, session: createSessionId() },
  })
  mobilePanel.value = null
}

async function refreshCurrentConversation() {
  const agentId = selectedAgentId.value
  if (!agentId) return
  await loadHistory(agentId)
  await loadTranscript()
}

async function sendMessage() {
  const input = composer.value.trim()
  if (!input) {
    message.warning('请输入消息')
    return
  }
  if (sending.value || blockedReason.value || !selectedAgent.value || !activeSessionId.value) return

  sending.value = true
  pendingInput.value = input
  streamedOutput.value = ''
  sendError.value = null
  failedTurn.value = null
  composer.value = ''
  await scrollThreadToBottom()
  let executionId = ''

  try {
    const payload = { input, session_id: activeSessionId.value, parameters: {} }
    if (selectedAgent.value.response_mode === 'stream') {
      let streamFailure = ''
      await platformApi.streamAgent(selectedAgent.value.id, payload, (event) => {
        if (event.event === 'start' || event.event === 'end') {
          executionId = String(event.execution_id || executionId)
        }
        if (event.event === 'token') streamedOutput.value += String(event.text || '')
        if (event.event === 'error') streamFailure = String(event.message || '流式执行失败')
        void scrollThreadToBottom()
      })
      if (streamFailure) throw new Error(streamFailure)
    } else {
      const result = await platformApi.runAgent(selectedAgent.value.id, payload)
      executionId = result.execution_id
    }
    if (executionId) {
      const detail = await platformApi.getExecution(executionId)
      detailCache.set(detail.id, detail)
    }
    await refreshCurrentConversation()
  } catch (error) {
    const detail = getApiErrorMessage(error)
    sendError.value = detail
    failedTurn.value = { input, error: detail }
    await loadHistory(selectedAgent.value.id).catch(() => undefined)
    await loadTranscript().catch(() => undefined)
  } finally {
    sending.value = false
    pendingInput.value = ''
    streamedOutput.value = ''
    await scrollThreadToBottom()
  }
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return
  event.preventDefault()
  void sendMessage()
}

watch(() => [route.query.agent, route.query.session], () => {
  if (initialized) void normalizeRouteSelection()
})

onMounted(async () => {
  await loadAgents()
  initialized = true
  await normalizeRouteSelection()
})
</script>

<template>
  <div class="agent-chat-page">
    <PageHeader title="智能体聊天" description="选择任意 Agent，按会话连续对话；所有消息、产物和 Trace 均来自真实 Execution。" />

    <div v-if="agentsError" class="error-panel chat-load-error">{{ agentsError }}</div>
    <section class="agent-chat-workspace surface" aria-label="智能体聊天工作台">
      <div v-if="mobilePanel" class="chat-mobile-scrim" @click="mobilePanel = null" />

      <aside class="chat-agent-pane" :class="{ 'mobile-open': mobilePanel === 'agents' }">
        <header class="chat-pane-header">
          <div><span>Agents</span><strong>选择智能体</strong></div>
          <button class="chat-mobile-close" type="button" aria-label="关闭 Agent 列表" @click="mobilePanel = null"><NIcon :component="X" /></button>
        </header>
        <div class="chat-search"><NInput v-model:value="agentSearch" clearable placeholder="搜索名称、ID、模型"><template #prefix><NIcon :component="Search" /></template></NInput></div>
        <div v-if="agentsLoading" class="chat-list-skeleton"><div v-for="index in 6" :key="index" class="skeleton-line" /></div>
        <div v-else-if="filteredAgents.length" class="chat-agent-list" role="listbox" aria-label="Agent 列表">
          <button
            v-for="agent in filteredAgents"
            :key="agent.id"
            type="button"
            role="option"
            :aria-selected="selectedAgentId === agent.id"
            :class="{ active: selectedAgentId === agent.id, unavailable: agent.status !== 'active' }"
            :disabled="sending"
            @click="selectAgent(agent)"
          >
            <span class="chat-agent-avatar"><NIcon :component="Robot" size="19" /></span>
            <span class="chat-agent-copy"><strong>{{ agent.name }}</strong><small class="mono">{{ agent.id }}</small><span>{{ agent.runtime_type }} · {{ agent.model }}</span></span>
            <StatusTag :status="agent.status" />
          </button>
        </div>
        <div v-else class="chat-pane-empty">没有匹配的 Agent</div>
      </aside>

      <aside class="chat-session-pane" :class="{ 'mobile-open': mobilePanel === 'sessions' }">
        <header class="chat-pane-header">
          <div><span>Sessions</span><strong>会话记录</strong></div>
          <div class="chat-pane-actions">
            <NButton quaternary circle size="small" aria-label="新建对话" :disabled="sending || !selectedAgent" @click="startNewChat"><template #icon><NIcon :component="Plus" /></template></NButton>
            <button class="chat-mobile-close" type="button" aria-label="关闭会话列表" @click="mobilePanel = null"><NIcon :component="X" /></button>
          </div>
        </header>
        <div v-if="historyLoading" class="chat-list-skeleton"><div v-for="index in 5" :key="index" class="skeleton-line" /></div>
        <div v-else-if="historyError" class="chat-pane-state"><strong>会话加载失败</strong><span>{{ historyError }}</span><NButton size="small" secondary @click="loadHistory(selectedAgentId)">重试</NButton></div>
        <div v-else-if="sessions.length" class="chat-session-list" role="listbox" aria-label="会话列表">
          <button
            v-for="session in sessions"
            :key="session.key"
            type="button"
            role="option"
            :aria-selected="activeSessionId === (session.sessionId || session.key)"
            :class="{ active: activeSessionId === (session.sessionId || session.key) }"
            :disabled="sending"
            @click="selectSession(session.sessionId || session.key)"
          >
            <strong>{{ session.title }}</strong>
            <span><time>{{ formatDate(session.latestAt) }}</time><small>{{ session.items.length }} 轮</small></span>
            <StatusTag :status="session.status" />
          </button>
        </div>
        <div v-else class="chat-pane-state"><NIcon :component="Messages" size="26" /><strong>暂无历史会话</strong><span>发送第一条消息后，会话会保存在这里。</span></div>
        <footer><NButton block secondary :disabled="sending || !selectedAgent" @click="startNewChat"><template #icon><NIcon :component="Plus" /></template>新建对话</NButton></footer>
      </aside>

      <main class="chat-thread-pane">
        <header class="chat-thread-header">
          <div class="chat-mobile-tools">
            <NButton quaternary circle aria-label="打开 Agent 列表" @click="mobilePanel = 'agents'"><template #icon><NIcon :component="Menu2" /></template></NButton>
            <NButton quaternary circle aria-label="打开会话列表" @click="mobilePanel = 'sessions'"><template #icon><NIcon :component="Messages" /></template></NButton>
          </div>
          <span class="chat-agent-avatar chat-agent-avatar-large"><NIcon :component="Robot" size="21" /></span>
          <div class="chat-thread-identity"><strong>{{ selectedAgent?.name || '请选择 Agent' }}</strong><span v-if="selectedAgent">{{ selectedAgent.runtime_type }} · {{ selectedAgent.model }} · {{ selectedAgent.response_mode.toUpperCase() }}</span></div>
          <StatusTag v-if="selectedAgent" :status="selectedAgent.status" />
          <NButton v-if="selectedAgent" text size="small" @click="router.push({ name: 'agent-playground', params: { id: selectedAgent.id } })"><template #icon><NIcon :component="ExternalLink" /></template>高级执行台</NButton>
        </header>

        <div ref="threadElement" class="chat-thread" aria-live="polite">
          <div v-if="transcriptLoading" class="chat-thread-loading"><div v-for="index in 5" :key="index" class="skeleton-line" /></div>
          <div v-else-if="transcriptError" class="chat-thread-state"><strong>对话正文加载失败</strong><p>{{ transcriptError }}</p><NButton secondary @click="loadTranscript">重新加载</NButton></div>
          <template v-else>
            <article v-for="execution in transcript" :key="execution.id" class="chat-turn">
              <div class="chat-message chat-message-user">
                <span class="chat-message-avatar"><NIcon :component="User" size="17" /></span>
                <div class="chat-bubble"><header><strong>你</strong><time>{{ formatDate(execution.started_at) }}</time></header><div class="chat-copy"><template v-for="(block,index) in messageBlocks(execution.input || execution.task)" :key="index"><h3 v-if="block.kind==='heading'">{{ block.text }}</h3><p v-else-if="block.kind==='paragraph'">{{ block.text }}</p><div v-else-if="block.kind==='list'" class="chat-list-line">{{ block.text }}</div><pre v-else><code>{{ block.text }}</code></pre></template></div></div>
              </div>
              <div class="chat-message chat-message-agent">
                <span class="chat-message-avatar"><NIcon :component="Robot" size="17" /></span>
                <div class="chat-bubble"><header><strong>{{ selectedAgent?.name || execution.agent_name }}</strong><span><StatusTag :status="execution.status" /><time>{{ formatDate(execution.finished_at || execution.started_at) }}</time></span></header><div class="chat-copy"><template v-for="(block,index) in messageBlocks(executionReplyText(execution))" :key="index"><h3 v-if="block.kind==='heading'">{{ block.text }}</h3><p v-else-if="block.kind==='paragraph'">{{ block.text }}</p><div v-else-if="block.kind==='list'" class="chat-list-line">{{ block.text }}</div><pre v-else><code>{{ block.text }}</code></pre></template></div><div v-if="execution.artifacts.length" class="chat-artifacts"><a v-for="artifact in execution.artifacts" :key="artifact.id" :href="platformApi.artifactDownloadUrl(artifact.id)"><NIcon :component="Download" />{{ artifact.filename }}</a></div><footer><span class="mono">{{ execution.id }}</span><NButton text size="tiny" @click="router.push({name:'execution-detail',params:{id:execution.id}})"><template #icon><NIcon :component="ListDetails" /></template>执行详情</NButton><NButton text size="tiny" @click="router.push({name:'trace-detail',params:{id:execution.id}})"><template #icon><NIcon :component="Activity" /></template>Trace</NButton></footer></div>
              </div>
            </article>

            <article v-if="pendingInput" class="chat-turn chat-turn-pending">
              <div class="chat-message chat-message-user"><span class="chat-message-avatar"><NIcon :component="User" size="17" /></span><div class="chat-bubble"><header><strong>你</strong><span>刚刚</span></header><div class="chat-copy"><p>{{ pendingInput }}</p></div></div></div>
              <div class="chat-message chat-message-agent"><span class="chat-message-avatar"><NIcon :component="Robot" size="17" /></span><div class="chat-bubble"><header><strong>{{ selectedAgent?.name }}</strong><span class="chat-thinking"><i /><i /><i /></span></header><div v-if="streamedOutput" class="chat-copy"><template v-for="(block,index) in messageBlocks(streamedOutput)" :key="index"><p v-if="block.kind!=='code'">{{ block.text }}</p><pre v-else><code>{{ block.text }}</code></pre></template></div><p v-else class="chat-waiting">正在处理你的消息…</p></div></div>
            </article>

            <article v-if="failedTurn" class="chat-turn">
              <div class="chat-message chat-message-user"><span class="chat-message-avatar"><NIcon :component="User" size="17" /></span><div class="chat-bubble"><header><strong>你</strong></header><div class="chat-copy"><p>{{ failedTurn.input }}</p></div></div></div>
              <div class="chat-message chat-message-agent"><span class="chat-message-avatar"><NIcon :component="Robot" size="17" /></span><div class="chat-bubble chat-bubble-error"><header><strong>执行失败</strong></header><p>{{ failedTurn.error }}</p></div></div>
            </article>

            <div v-if="!transcript.length && !pendingInput && !failedTurn" class="chat-thread-state chat-thread-welcome"><span><NIcon :component="Messages" size="28" /></span><strong>{{ selectedAgent ? `开始与 ${selectedAgent.name} 对话` : '选择一个 Agent' }}</strong><p>{{ selectedAgent ? '输入自然语言消息，后续提问会沿用当前会话上下文。' : '从左侧列表选择需要调用的智能体。' }}</p></div>
          </template>
        </div>

        <footer class="chat-composer-shell">
          <NAlert v-if="blockedReason" type="warning" :bordered="false" class="chat-blocked-alert">
            {{ blockedReason }}
            <NButton v-if="selectedAgent && requiredFields.length" text type="primary" @click="router.push({name:'agent-playground',params:{id:selectedAgent.id}})">前往执行工作台</NButton>
          </NAlert>
          <div v-if="sendError" class="chat-send-error">{{ sendError }}</div>
          <div class="chat-composer">
            <NInput v-model:value="composer" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" maxlength="100000" placeholder="输入消息，Enter 发送，Shift + Enter 换行" :disabled="sending || Boolean(blockedReason)" @keydown="handleComposerKeydown" />
            <NButton type="primary" circle size="large" aria-label="发送消息" :loading="sending" :disabled="!composer.trim() || Boolean(blockedReason)" @click="sendMessage"><template #icon><NIcon :component="Send" /></template></NButton>
          </div>
          <div class="chat-composer-meta"><span class="mono">Session {{ activeSessionId || '--' }}</span><span>回复模式：{{ selectedAgent?.response_mode || '--' }}</span></div>
        </footer>
      </main>
    </section>
  </div>
</template>

<style scoped>
.agent-chat-page{width:100%!important;max-width:none!important}.agent-chat-page :deep(.page-header){margin-bottom:18px}.chat-load-error{margin-bottom:12px}.agent-chat-workspace{position:relative;display:grid;grid-template-columns:270px 260px minmax(0,1fr);height:calc(100dvh - 190px);min-height:650px;overflow:hidden}.chat-agent-pane,.chat-session-pane,.chat-thread-pane{min-width:0;min-height:0}.chat-agent-pane,.chat-session-pane{display:flex;flex-direction:column;border-right:1px solid var(--line);background:var(--surface-subtle)}.chat-session-pane{background:#282828}.chat-pane-header,.chat-thread-header{display:flex;min-height:70px;align-items:center;gap:12px;padding:14px 16px;border-bottom:1px solid var(--line)}.chat-pane-header{justify-content:space-between}.chat-pane-header>div:first-child{display:grid;gap:3px}.chat-pane-header span{color:#777;font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.chat-pane-header strong{font-size:13px}.chat-pane-actions{display:flex!important;align-items:center;gap:4px}.chat-search{padding:12px;border-bottom:1px solid var(--line)}.chat-agent-list,.chat-session-list{flex:1;overflow:auto;padding:8px}.chat-agent-list>button,.chat-session-list>button{position:relative;width:100%;border:1px solid transparent;border-radius:7px;color:var(--ink);background:transparent;text-align:left;cursor:pointer}.chat-agent-list>button{display:grid;grid-template-columns:38px minmax(0,1fr) auto;gap:9px;align-items:center;padding:10px}.chat-agent-list>button:hover,.chat-session-list>button:hover{background:#323232}.chat-agent-list>button.active,.chat-session-list>button.active{border-color:#555;background:#373737}.chat-agent-list>button.unavailable{opacity:.62}.chat-agent-avatar,.chat-message-avatar{display:grid;flex:0 0 auto;place-items:center;border-radius:9px;color:var(--ink);background:#3a3a3a}.chat-agent-avatar{width:36px;height:36px}.chat-agent-avatar-large{width:40px;height:40px}.chat-agent-copy{display:grid;min-width:0;gap:2px}.chat-agent-copy strong,.chat-agent-copy small,.chat-agent-copy span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.chat-agent-copy strong{font-size:12px}.chat-agent-copy small{color:#8d8d8d;font-size:9px}.chat-agent-copy span{color:var(--muted);font-size:10px}.chat-session-list>button{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;padding:12px}.chat-session-list strong{grid-column:1/-1;overflow:hidden;font-size:12px;text-overflow:ellipsis;white-space:nowrap}.chat-session-list>button>span{display:flex;gap:7px;color:var(--muted);font-size:9px}.chat-session-list small{font-size:9px}.chat-session-pane>footer{padding:12px;border-top:1px solid var(--line)}.chat-list-skeleton{display:grid;gap:8px;padding:12px}.chat-list-skeleton .skeleton-line{height:58px}.chat-pane-state,.chat-pane-empty{display:grid;flex:1;place-content:center;gap:7px;padding:20px;color:var(--muted);text-align:center}.chat-pane-state strong{color:var(--ink);font-size:12px}.chat-pane-state span,.chat-pane-empty{font-size:10px;line-height:1.5}.chat-thread-pane{display:grid;grid-template-rows:auto minmax(0,1fr) auto;background:#222}.chat-thread-header{background:#292929}.chat-thread-identity{display:grid;min-width:0;flex:1;gap:3px}.chat-thread-identity strong{overflow:hidden;font-size:14px;text-overflow:ellipsis;white-space:nowrap}.chat-thread-identity span{overflow:hidden;color:var(--muted);font-size:10px;text-overflow:ellipsis;white-space:nowrap}.chat-thread{overflow:auto;padding:26px clamp(18px,4vw,54px);scroll-behavior:smooth}.chat-thread-loading{display:grid;gap:12px;max-width:760px;margin:auto}.chat-turn{display:grid;gap:18px;max-width:920px;margin:0 auto 28px}.chat-message{display:flex;gap:10px;align-items:flex-start}.chat-message-user{padding-left:clamp(24px,8vw,110px)}.chat-message-agent{padding-right:clamp(12px,5vw,70px)}.chat-message-avatar{width:32px;height:32px;margin-top:2px}.chat-message-user .chat-message-avatar{order:2;background:#d8d8d8;color:#222}.chat-message-user .chat-bubble{margin-left:auto;background:#363636}.chat-bubble{min-width:0;max-width:min(100%,760px);padding:14px 16px;border:1px solid var(--line);border-radius:10px;background:#2b2b2b}.chat-bubble>header{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:9px}.chat-bubble header strong{font-size:11px}.chat-bubble header time,.chat-bubble header>span{color:#888;font-size:9px}.chat-bubble header>span{display:flex;align-items:center;gap:8px}.chat-copy{display:grid;gap:8px;color:#d6d6d6;font-size:13px;line-height:1.7}.chat-copy h3,.chat-copy p{margin:0}.chat-copy h3{font-size:15px}.chat-copy pre{max-width:100%;margin:2px 0;padding:12px;overflow:auto;border:1px solid #383838;border-radius:6px;background:#1b1b1b;font-size:11px;white-space:pre-wrap}.chat-list-line{padding-left:13px}.chat-list-line:before{content:'•';margin-left:-12px;margin-right:7px}.chat-bubble>footer{display:flex;align-items:center;gap:8px;margin-top:12px;padding-top:9px;border-top:1px solid var(--line)}.chat-bubble>footer>span{min-width:0;flex:1;overflow:hidden;color:#777;font-size:8px;text-overflow:ellipsis;white-space:nowrap}.chat-artifacts{display:flex;flex-wrap:wrap;gap:6px;margin-top:11px}.chat-artifacts a{display:flex;align-items:center;gap:5px;padding:5px 8px;border:1px solid var(--line);border-radius:6px;color:#c8c8c8;background:#252525;font-size:9px}.chat-bubble-error{border-color:rgba(239,83,80,.45);color:#ff8a87;background:rgba(239,83,80,.07)}.chat-bubble-error p,.chat-waiting{margin:0;font-size:12px;line-height:1.55}.chat-waiting{color:var(--muted)}.chat-thinking{display:flex!important;gap:3px!important}.chat-thinking i{width:4px;height:4px;border-radius:50%;background:#aaa;animation:chat-pulse 1s ease infinite}.chat-thinking i:nth-child(2){animation-delay:.15s}.chat-thinking i:nth-child(3){animation-delay:.3s}@keyframes chat-pulse{0%,100%{opacity:.25;transform:translateY(0)}50%{opacity:1;transform:translateY(-2px)}}.chat-thread-state{display:grid;min-height:100%;place-content:center;justify-items:center;padding:30px;color:var(--muted);text-align:center}.chat-thread-state>span{display:grid;width:56px;height:56px;place-items:center;border-radius:14px;background:#303030}.chat-thread-state strong{margin-top:13px;color:var(--ink);font-size:15px}.chat-thread-state p{max-width:420px;margin:7px 0 14px;font-size:11px;line-height:1.6}.chat-composer-shell{padding:14px clamp(16px,4vw,48px) 12px;border-top:1px solid var(--line);background:#292929}.chat-composer{display:flex;align-items:flex-end;gap:10px;max-width:940px;margin:auto}.chat-composer :deep(.n-input){border-radius:9px}.chat-composer-meta{display:flex;justify-content:space-between;gap:16px;max-width:940px;margin:7px auto 0;color:#777;font-size:8px}.chat-blocked-alert,.chat-send-error{max-width:940px;margin:0 auto 9px}.chat-send-error{color:#ff8a87;font-size:10px}.chat-mobile-tools,.chat-mobile-close,.chat-mobile-scrim{display:none}
@media(max-width:1050px){.agent-chat-workspace{grid-template-columns:230px 220px minmax(0,1fr)}.chat-agent-copy span{display:none}.chat-thread{padding-inline:18px}.chat-message-user{padding-left:24px}.chat-message-agent{padding-right:12px}}
@media(max-width:820px){.agent-chat-workspace{display:block;height:calc(100dvh - 170px);min-height:580px}.chat-thread-pane{height:100%}.chat-agent-pane,.chat-session-pane{position:absolute;z-index:5;inset:0 auto 0 0;width:min(86vw,310px);transform:translateX(-105%);transition:transform 180ms ease;box-shadow:18px 0 40px rgba(0,0,0,.36)}.chat-agent-pane.mobile-open,.chat-session-pane.mobile-open{transform:translateX(0)}.chat-mobile-scrim{position:absolute;z-index:4;inset:0;display:block;background:rgba(0,0,0,.62)}.chat-mobile-tools{display:flex;gap:2px}.chat-mobile-close{display:grid;width:30px;height:30px;place-items:center;border:0;border-radius:6px;color:var(--muted);background:transparent}.chat-thread-header>.n-button:last-child{display:none}}
@media(max-width:600px){.agent-chat-page :deep(.page-header){display:none}.agent-chat-workspace{height:calc(100dvh - 92px);min-height:520px;border-radius:0}.chat-thread-header{min-height:62px;padding:10px}.chat-agent-avatar-large{display:none}.chat-thread{padding:18px 10px}.chat-message-user{padding-left:16px}.chat-message-agent{padding-right:0}.chat-message-avatar{width:28px;height:28px}.chat-bubble{padding:11px 12px}.chat-composer-shell{padding:10px}.chat-composer-meta{display:none}}
</style>
