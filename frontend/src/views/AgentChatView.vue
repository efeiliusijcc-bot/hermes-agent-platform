<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { NIcon } from 'naive-ui'
import { Robot, Users } from '@vicons/tabler'
import { useRoute, useRouter } from 'vue-router'

import SingleAgentChatWorkspace from '@/components/agent/SingleAgentChatWorkspace.vue'
import TeamAgentChatWorkspace from '@/components/agent/TeamAgentChatWorkspace.vue'

type ChatMode = 'agent' | 'team'

const route = useRoute()
const router = useRouter()
const lastAgentQuery = ref<Record<string, string>>({ mode: 'agent' })
const lastTeamQuery = ref<Record<string, string>>({ mode: 'team' })
const mode = computed<ChatMode>(() => route.query.mode === 'team' ? 'team' : 'agent')

function normalizedQuery(): Record<string, string> {
  return Object.fromEntries(
    Object.entries(route.query)
      .filter(([, value]) => typeof value === 'string')
      .map(([key, value]) => [key, String(value)]),
  )
}

watch(() => route.query, () => {
  if (mode.value === 'team') lastTeamQuery.value = { ...normalizedQuery(), mode: 'team' }
  else lastAgentQuery.value = { ...normalizedQuery(), mode: 'agent' }
}, { deep: true, immediate: true })

function switchMode(value: ChatMode) {
  if (value === mode.value) return
  void router.push({
    name: 'agent-chat',
    query: value === 'team' ? lastTeamQuery.value : lastAgentQuery.value,
  })
}
</script>

<template>
  <div class="chat-mode-page">
    <header class="chat-mode-bar">
      <nav class="chat-mode-switch" aria-label="智能体聊天模式">
        <button type="button" :class="{ active: mode === 'agent' }" :aria-pressed="mode === 'agent'" @click="switchMode('agent')">
          <NIcon :component="Robot" />单 Agent
        </button>
        <button type="button" :class="{ active: mode === 'team' }" :aria-pressed="mode === 'team'" @click="switchMode('team')">
          <NIcon :component="Users" />Agent Team
        </button>
      </nav>
      <span>{{ mode === 'agent' ? '独立智能体会话' : '多智能体协作会话' }}</span>
    </header>

    <div class="chat-workspace-stage">
      <SingleAgentChatWorkspace v-if="mode === 'agent'" />
      <TeamAgentChatWorkspace v-else />
    </div>
  </div>
</template>

<style scoped>
.chat-mode-page{container:chat-workbench / inline-size;display:grid;grid-template-rows:auto minmax(0,1fr);gap:10px;min-width:0;min-height:0;height:100%;overflow:hidden}.chat-mode-bar{display:flex;min-height:42px;align-items:center;justify-content:space-between;gap:16px}.chat-mode-bar>span{overflow:hidden;color:var(--muted);font-size:9px;text-overflow:ellipsis;white-space:nowrap}.chat-mode-switch{display:inline-flex;width:fit-content;padding:3px;border:1px solid var(--line);border-radius:9px;background:var(--surface-subtle)}.chat-mode-switch button{display:flex;min-width:124px;align-items:center;justify-content:center;gap:7px;padding:7px 13px;border:0;border-radius:6px;color:var(--muted);background:transparent;font:600 11px/1.2 inherit;cursor:pointer}.chat-mode-switch button.active{color:#171717;background:var(--accent)}.chat-mode-switch button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}.chat-workspace-stage{min-width:0;min-height:0;height:100%;overflow:hidden}@media(max-width:620px){.chat-mode-page{gap:0}.chat-mode-bar{min-height:48px;padding:6px 10px;border-bottom:1px solid var(--line);background:#202020}.chat-mode-bar>span{display:none}.chat-mode-switch{width:100%}.chat-mode-switch button{flex:1;min-width:0}}
</style>
