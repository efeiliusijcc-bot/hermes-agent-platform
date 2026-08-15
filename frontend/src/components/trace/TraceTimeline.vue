<script setup lang="ts">
import TraceNode from './TraceNode.vue'
import type { ExecutionStep } from '@/types/api'

defineProps<{
  nodes: ExecutionStep[]
  selectedId?: string | null
  active?: boolean
}>()

const emit = defineEmits<{ select: [node: ExecutionStep] }>()
</script>

<template>
  <div v-if="nodes.length" class="trace-timeline" aria-label="Trace 执行链">
    <TraceNode
      v-for="node in nodes"
      :key="node.id"
      :node="node"
      :selected="selectedId === node.id"
      @select="emit('select', $event)"
    />
  </div>
  <div v-else class="empty-state empty-state-compact">
    <div>
      <h3>{{ active ? '等待 Trace 节点' : '没有 Trace 记录' }}</h3>
      <p>{{ active ? '执行开始后会逐步记录结构化节点。' : '旧执行可能没有结构化 Trace 数据。' }}</p>
    </div>
  </div>
</template>
