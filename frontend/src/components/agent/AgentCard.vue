<script setup lang="ts">
import { NIcon } from 'naive-ui'
import { TestPipe } from '@vicons/tabler'

import StatusTag from '@/components/StatusTag.vue'
import type { ConsoleAgentSummary } from '@/types/api'

defineProps<{
  agent: ConsoleAgentSummary
}>()

defineEmits<{
  view: []
  run: []
  remove: []
}>()
</script>

<template>
  <article class="agent-card surface">
    <div class="agent-card-top">
      <div>
        <h2>{{ agent.name }}</h2>
        <div class="agent-card-id mono">{{ agent.id }}</div>
      </div>
      <StatusTag :status="agent.status" />
    </div>
    <p class="agent-card-description">{{ agent.description || agent.role }}</p>
    <dl class="agent-card-facts">
      <div><dt>Version</dt><dd class="mono">{{ agent.version || '未发布' }}</dd></div>
      <div><dt>Model</dt><dd class="mono">{{ agent.model }}</dd></div>
    </dl>
    <div class="agent-capability-groups">
      <div>
        <span>Skills</span>
        <div v-if="agent.skills.length" class="capability-tags">
          <NTag v-for="skill in agent.skills.slice(0, 3)" :key="skill.id" size="small" :bordered="false">{{ skill.name }}</NTag>
          <NTag v-if="agent.skills.length > 3" size="small" :bordered="false">+{{ agent.skills.length - 3 }}</NTag>
        </div>
        <span v-else class="capability-empty">未绑定</span>
      </div>
      <div>
        <span>MCP</span>
        <div v-if="agent.mcps.length" class="capability-tags">
          <NTag v-for="server in agent.mcps.slice(0, 3)" :key="server.id" size="small" :bordered="false">{{ server.name }}</NTag>
          <NTag v-if="agent.mcps.length > 3" size="small" :bordered="false">+{{ agent.mcps.length - 3 }}</NTag>
        </div>
        <span v-else class="capability-empty">未绑定</span>
      </div>
    </div>
    <div class="agent-card-actions">
      <NButton size="small" secondary @click="$emit('view')">详情</NButton>
      <NButton size="small" type="primary" :disabled="agent.status !== 'active'" @click="$emit('run')">
        <template #icon><NIcon :component="TestPipe" /></template>运行
      </NButton>
      <NButton size="small" text type="error" @click="$emit('remove')">删除</NButton>
    </div>
  </article>
</template>
