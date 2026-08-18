<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { AlertCircle, Messages, Refresh, Robot, User } from '@vicons/tabler'

import StatusTag from '@/components/StatusTag.vue'
import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import { buildConversationSessions, executionReplyText } from '@/utils/agentConversation'
import { parseSafeMarkdown } from '@/utils/executionStudio'
import { formatDate } from '@/utils/format'
import type { ExecutionDetail, ExecutionSummary } from '@/types/api'

const props = defineProps<{
  executions: ExecutionSummary[]
  loading: boolean
  historyError?: string | null
  agentName?: string | null
}>()

const emit = defineEmits<{
  refresh: []
  openTrace: [executionId: string]
}>()

const selectedSessionKey = ref<string | null>(null)
const transcript = ref<ExecutionDetail[]>([])
const transcriptLoading = ref(false)
const transcriptError = ref<string | null>(null)
const detailCache = new Map<string, ExecutionDetail>()
let requestSerial = 0

const sessions = computed(() => buildConversationSessions(props.executions))
const selectedSession = computed(() => sessions.value.find((item) => item.key === selectedSessionKey.value) || null)
const selectedExecutionIds = computed(() => selectedSession.value?.items.map((item) => item.id).join('|') || '')

function messageBlocks(value: string) {
  return parseSafeMarkdown(value)
}

async function loadTranscript(force = false) {
  const serial = ++requestSerial
  const session = selectedSession.value
  if (!session) {
    transcript.value = []
    transcriptError.value = null
    return
  }

  transcriptLoading.value = true
  transcriptError.value = null
  try {
    const details = await Promise.all(session.items.map(async (item) => {
      if (!force && detailCache.has(item.id)) return detailCache.get(item.id)!
      const detail = await platformApi.getExecution(item.id)
      detailCache.set(item.id, detail)
      return detail
    }))
    if (serial === requestSerial) transcript.value = details
  } catch (error) {
    if (serial === requestSerial) {
      transcript.value = []
      transcriptError.value = getApiErrorMessage(error)
    }
  } finally {
    if (serial === requestSerial) transcriptLoading.value = false
  }
}

function refreshConversation() {
  detailCache.clear()
  emit('refresh')
  void loadTranscript(true)
}

watch(sessions, (items) => {
  if (!items.length) {
    selectedSessionKey.value = null
    return
  }
  if (!items.some((item) => item.key === selectedSessionKey.value)) selectedSessionKey.value = items[0].key
}, { immediate: true })

watch(selectedExecutionIds, () => { void loadTranscript() }, { immediate: true })
</script>

<template>
  <section class="conversation-workspace surface" aria-label="Agent 聊天记录">
    <aside class="conversation-session-pane">
      <header class="conversation-pane-header">
        <div>
          <h2>聊天记录</h2>
          <p>{{ sessions.length }} 个会话，最多显示最近 50 次执行</p>
        </div>
        <NButton quaternary circle aria-label="刷新聊天记录" :loading="loading || transcriptLoading" @click="refreshConversation">
          <template #icon><NIcon :component="Refresh" /></template>
        </NButton>
      </header>

      <div v-if="loading" class="conversation-session-skeleton" aria-label="正在加载聊天记录">
        <div v-for="index in 5" :key="index" class="skeleton-line" />
      </div>
      <div v-else-if="historyError" class="conversation-state conversation-state-error">
        <NIcon :component="AlertCircle" size="24" />
        <strong>聊天记录加载失败</strong>
        <p>{{ historyError }}</p>
        <NButton secondary size="small" @click="emit('refresh')">重新加载</NButton>
      </div>
      <div v-else-if="!sessions.length" class="conversation-state">
        <NIcon :component="Messages" size="28" />
        <strong>暂无聊天记录</strong>
        <p>在执行台运行此 Agent 后，会话内容会按 Session 显示在这里。</p>
      </div>
      <div v-else class="conversation-session-list" role="listbox" aria-label="会话列表">
        <button
          v-for="session in sessions"
          :key="session.key"
          type="button"
          role="option"
          :aria-selected="selectedSessionKey === session.key"
          :class="{ active: selectedSessionKey === session.key }"
          @click="selectedSessionKey = session.key"
        >
          <span class="conversation-session-title">{{ session.title }}</span>
          <span class="conversation-session-meta">
            <time>{{ formatDate(session.latestAt) }}</time>
            <span>{{ session.items.length }} 轮</span>
          </span>
          <StatusTag :status="session.status" />
        </button>
      </div>
    </aside>

    <div class="conversation-transcript-pane">
      <header v-if="selectedSession" class="conversation-transcript-header">
        <div>
          <span>当前会话</span>
          <strong>{{ selectedSession.title }}</strong>
          <small class="mono">{{ selectedSession.sessionId || selectedSession.key }}</small>
        </div>
        <span>{{ selectedSession.items.length }} 轮对话</span>
      </header>

      <div v-if="transcriptLoading" class="conversation-transcript-skeleton" aria-label="正在加载会话正文">
        <div v-for="index in 4" :key="index" class="skeleton-line" />
      </div>
      <div v-else-if="transcriptError" class="conversation-state conversation-state-error conversation-state-wide">
        <NIcon :component="AlertCircle" size="26" />
        <strong>会话正文加载失败</strong>
        <p>{{ transcriptError }}</p>
        <NButton secondary size="small" @click="loadTranscript(true)">重试</NButton>
      </div>
      <div v-else-if="transcript.length" class="conversation-transcript" aria-live="polite">
        <article v-for="execution in transcript" :key="execution.id" class="conversation-turn">
          <div class="conversation-message conversation-message-user">
            <span class="conversation-avatar"><NIcon :component="User" size="18" /></span>
            <div class="conversation-message-content">
              <header><strong>用户</strong><time>{{ formatDate(execution.started_at) }}</time></header>
              <div class="conversation-copy">
                <template v-for="(block, index) in messageBlocks(execution.input || execution.task)" :key="index">
                  <h3 v-if="block.kind === 'heading'">{{ block.text }}</h3>
                  <p v-else-if="block.kind === 'paragraph'">{{ block.text }}</p>
                  <div v-else-if="block.kind === 'list'" class="conversation-list-item">{{ block.text }}</div>
                  <pre v-else><code>{{ block.text }}</code></pre>
                </template>
              </div>
            </div>
          </div>

          <div class="conversation-message conversation-message-agent">
            <span class="conversation-avatar"><NIcon :component="Robot" size="18" /></span>
            <div class="conversation-message-content">
              <header>
                <strong>{{ agentName || 'Agent' }}</strong>
                <span><StatusTag :status="execution.status" /><time>{{ formatDate(execution.finished_at || execution.started_at) }}</time></span>
              </header>
              <div class="conversation-copy">
                <template v-for="(block, index) in messageBlocks(executionReplyText(execution))" :key="index">
                  <h3 v-if="block.kind === 'heading'">{{ block.text }}</h3>
                  <p v-else-if="block.kind === 'paragraph'">{{ block.text }}</p>
                  <div v-else-if="block.kind === 'list'" class="conversation-list-item">{{ block.text }}</div>
                  <pre v-else><code>{{ block.text }}</code></pre>
                </template>
              </div>
              <footer>
                <span class="mono">Execution {{ execution.id }}</span>
                <NButton text size="tiny" @click="emit('openTrace', execution.id)">查看 Trace</NButton>
              </footer>
            </div>
          </div>
        </article>
      </div>
      <div v-else class="conversation-state conversation-state-wide">
        <NIcon :component="Messages" size="28" />
        <strong>请选择一个会话</strong>
        <p>左侧会话列表用于切换聊天正文。</p>
      </div>
    </div>
  </section>
</template>
