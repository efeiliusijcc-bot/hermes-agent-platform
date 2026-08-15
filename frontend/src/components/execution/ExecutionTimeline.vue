<script setup lang="ts">
import { ref } from 'vue'
import { NIcon } from 'naive-ui'
import { Check, Clock, PlayerPlay, X } from '@vicons/tabler'

import StatusTag from '@/components/StatusTag.vue'
import { formatDurationMs } from '@/utils/executionStudio'
import type { ExecutionStep } from '@/types/api'

defineProps<{ steps: ExecutionStep[]; active?: boolean }>()
const selectedStep = ref<ExecutionStep | null>(null)

function icon(status: string) {
  if (status === 'succeeded') return Check
  if (status === 'failed' || status === 'cancelled') return X
  if (status === 'running') return PlayerPlay
  return Clock
}
</script>

<template>
  <div v-if="steps.length" class="execution-timeline">
    <article v-for="step in steps" :key="step.id" class="timeline-step" :data-status="step.status">
      <div class="timeline-marker"><NIcon :component="icon(step.status)" size="14" /></div>
      <button class="timeline-content" type="button" @click="selectedStep = selectedStep?.id === step.id ? null : step">
        <div class="timeline-heading">
          <div><strong>{{ step.step_name }}</strong><span class="mono">{{ step.step_key }}</span></div>
          <StatusTag :status="step.status" />
        </div>
        <p v-if="step.error" class="timeline-error">{{ step.error }}</p>
        <div class="timeline-meta">
          <span>{{ step.step_type }}</span>
          <span>{{ formatDurationMs(step.latency_ms) }} · {{ selectedStep?.id === step.id ? '收起' : '查看' }}</span>
        </div>
        <div v-if="selectedStep?.id === step.id" class="timeline-inspector">
          <div><span>输入</span><pre>{{ JSON.stringify(step.input_data, null, 2) }}</pre></div>
          <div><span>输出</span><pre>{{ JSON.stringify(step.output_data, null, 2) }}</pre></div>
          <dl><div><dt>开始</dt><dd>{{ step.started_at || '--' }}</dd></div><div><dt>结束</dt><dd>{{ step.finished_at || '--' }}</dd></div></dl>
        </div>
      </button>
    </article>
  </div>
  <div v-else class="empty-state empty-state-compact">
    <div>
      <h3>{{ active ? '等待 Trace 数据' : '没有 Trace 记录' }}</h3>
      <p>{{ active ? '执行开始后会在这里显示结构化步骤。' : '旧执行可能仅保存了基础运行记录。' }}</p>
    </div>
  </div>
</template>
