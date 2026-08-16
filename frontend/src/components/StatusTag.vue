<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const type = computed(() => {
  if (['active', 'published', 'healthy', 'succeeded', 'ok', 'online'].includes(props.status)) return 'success'
  if (['running', 'testing', 'release_candidate', 'manager'].includes(props.status)) return 'info'
  if (['failed', 'disabled', 'inactive', 'unhealthy', 'archived', 'revoked', 'offline'].includes(props.status)) return 'error'
  return 'warning'
})

const label = computed(() => {
  const labels: Record<string, string> = {
    active: '已启用',
    inactive: '已停用',
    draft: '草稿',
    testing: '测试中',
    published: '已发布',
    suspended: '已暂停',
    archived: '已归档',
    disabled: '已禁用',
    healthy: '健康',
    degraded: '降级',
    unhealthy: '异常',
    unknown: '未知',
    revoked: '已撤销',
    expired: '已过期',
    snapshot: '快照',
    superseded: '历史版本',
    development: '开发中',
    release_candidate: '候选发布',
    deprecated: '已弃用',
    running: '执行中',
    succeeded: '成功',
    failed: '失败',
    queued: '排队中',
    pending: '等待中',
    retrying: '重试中',
    waiting_child: '等待子任务',
    human_review: '待人工审批',
    manager: 'Manager',
    worker: 'Worker',
    skipped: '已跳过',
    cancelled: '已取消',
    ok: '正常',
    online: '在线',
    offline: '离线',
  }
  return labels[props.status] || props.status
})
</script>

<template>
  <NTag :type="type" size="small" :bordered="false" round>{{ label }}</NTag>
</template>
