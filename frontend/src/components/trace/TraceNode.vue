<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { Activity, Api, Archive, Database, Hierarchy, PlugConnected, Robot, Settings } from '@vicons/tabler'

import StatusTag from '@/components/StatusTag.vue'
import { formatDurationMs } from '@/utils/executionStudio'
import type { ExecutionStep } from '@/types/api'

const props = defineProps<{
  node: ExecutionStep
  selected?: boolean
}>()

const emit = defineEmits<{ select: [node: ExecutionStep] }>()

const icon = computed(() => ({
  request: Api,
  schema: Settings,
  memory: Database,
  skill: Hierarchy,
  mcp: PlugConnected,
  knowledge: Database,
  model: Robot,
  artifact: Archive,
  runtime: Activity,
})[props.node.step_type] || Activity)

const typeLabel = computed(() => ({
  request: 'Request',
  schema: 'Schema',
  memory: 'Memory',
  skill: 'Skill',
  mcp: 'MCP',
  knowledge: 'Knowledge',
  model: 'Model',
  artifact: 'Artifact',
  runtime: props.node.step_key.startsWith('hermes_runtime') ? 'Model Runtime' : 'Runtime',
})[props.node.step_type] || props.node.step_type)
</script>

<template>
  <article class="trace-node" :data-status="node.status" :data-selected="selected ? 'true' : 'false'">
    <div class="trace-node-marker"><NIcon :component="icon" size="16" /></div>
    <button type="button" class="trace-node-content" :aria-pressed="selected" @click="emit('select', node)">
      <span class="trace-node-type">{{ typeLabel }}</span>
      <div class="trace-node-heading"><strong>{{ node.step_name }}</strong><StatusTag :status="node.status" /></div>
      <div class="trace-node-meta"><span class="mono">{{ node.step_key }}</span><span class="mono">{{ formatDurationMs(node.latency_ms) }}</span></div>
      <p v-if="node.error">{{ node.error }}</p>
    </button>
  </article>
</template>
