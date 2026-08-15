<script setup lang="ts">
import { formatCount, formatDurationMs } from '@/utils/executionStudio'

defineProps<{
  durationMs?: number | null
  tokenUsage?: number | null
  skillCount?: number
  mcpCallCount?: number
  memoryReadCount?: number
  artifactCount?: number
}>()
</script>

<template>
  <div class="runtime-metrics">
    <div><span>耗时</span><strong>{{ formatDurationMs(durationMs) }}</strong></div>
    <div><span>Token</span><strong>{{ formatCount(tokenUsage) }}</strong></div>
    <div><span>Skill</span><strong>{{ formatCount(skillCount) }}</strong></div>
    <div><span>MCP 调用</span><strong>{{ formatCount(mcpCallCount) }}</strong></div>
    <div><span>记忆读取</span><strong>{{ formatCount(memoryReadCount) }}</strong></div>
    <div><span>Artifact</span><strong>{{ formatCount(artifactCount) }}</strong></div>
  </div>
</template>
