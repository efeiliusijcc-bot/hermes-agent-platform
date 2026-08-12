<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const type = computed(() => {
  if (['active', 'succeeded', 'ok'].includes(props.status)) return 'success'
  if (props.status === 'running') return 'info'
  if (['failed', 'disabled'].includes(props.status)) return 'error'
  return 'warning'
})

const label = computed(() => {
  const labels: Record<string, string> = {
    active: '已启用',
    draft: '草稿',
    disabled: '已禁用',
    running: '执行中',
    succeeded: '成功',
    failed: '失败',
    ok: '正常',
  }
  return labels[props.status] || props.status
})
</script>

<template>
  <NTag :type="type" size="small" :bordered="false" round>{{ label }}</NTag>
</template>
