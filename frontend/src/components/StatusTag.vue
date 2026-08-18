<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ status: string }>()

const type = computed(() => {
  if (['active', 'published', 'healthy', 'succeeded', 'completed', 'ok', 'online', 'READY', 'SUCCEEDED'].includes(props.status)) return 'success'
  if (['running', 'testing', 'release_candidate', 'manager'].includes(props.status)) return 'info'
  if (['failed', 'disabled', 'inactive', 'unhealthy', 'archived', 'revoked', 'offline', 'UNAVAILABLE', 'FAILED', 'DENIED'].includes(props.status)) return 'error'
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
    completed: '业务完成',
    blocked: '业务阻塞',
    needs_more_info: '待补充信息',
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
    READY: '已就绪',
    NEEDS_CONFIGURATION: '需要配置',
    UNAVAILABLE: '暂不可用',
    DISABLED: '未启用',
    SUCCEEDED: '成功',
    FAILED: '失败',
    DENIED: '已拒绝',
    PENDING: '等待中',
  }
  return labels[props.status] || props.status
})
</script>

<template>
  <NTag :type="type" size="small" :bordered="false" round>{{ label }}</NTag>
</template>
