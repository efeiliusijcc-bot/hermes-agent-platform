<script setup lang="ts">
import { NIcon } from 'naive-ui'
import { ArrowRight } from '@vicons/tabler'

import StatusTag from '@/components/StatusTag.vue'
import { formatDate } from '@/utils/format'
import { formatCount, formatDurationMs } from '@/utils/executionStudio'
import type { ExecutionSummary } from '@/types/api'

defineProps<{
  items: ExecutionSummary[]
  loading?: boolean
}>()

const emit = defineEmits<{ select: [executionId: string] }>()
</script>

<template>
  <div class="execution-table-head execution-table-refactored" aria-hidden="true">
    <span>Execution ID</span><span>Agent</span><span>Version</span><span>Session</span><span>Status</span><span>Duration</span><span>Token</span><span>Created Time</span><span></span>
  </div>
  <div v-if="loading" class="execution-table-loading" aria-label="正在加载执行记录">
    <div v-for="index in 6" :key="index" class="skeleton-line" />
  </div>
  <div v-else-if="items.length" class="execution-table-body">
    <button
      v-for="item in items"
      :key="item.id"
      type="button"
      class="execution-history-row execution-row-refactored"
      :aria-label="`查看执行 ${item.id}`"
      @click="emit('select', item.id)"
    >
      <span class="execution-id-cell"><strong class="mono">{{ item.id }}</strong><small>{{ item.task }}</small></span>
      <span class="execution-id-cell"><strong>{{ item.agent_name }}</strong><small class="mono">{{ item.agent_id }} · {{ item.runtime_type }}{{ item.runtime_version ? `/${item.runtime_version}` : '' }}</small></span>
      <span class="mono">{{ item.agent_version || item.agent_version_id || '--' }}</span>
      <span class="mono">{{ item.memory_session_id || item.session_id || '--' }}</span>
      <span><StatusTag :status="item.status" /></span>
      <span class="mono">{{ formatDurationMs(item.duration_ms) }}</span>
      <span class="mono">{{ formatCount(item.token_usage) }}</span>
      <span>{{ formatDate(item.started_at) }}</span>
      <NIcon :component="ArrowRight" />
    </button>
  </div>
  <div v-else class="empty-state">
    <slot name="empty"><div><h3>没有匹配的执行记录</h3><p>调整筛选条件，或先从执行工作台提交任务。</p></div></slot>
  </div>
</template>
