import type { DialogApi } from 'naive-ui'

import type { AgentStatus } from '@/types/api'

export function isAgentConfigurationLocked(
  status: AgentStatus | null | undefined,
  currentVersionId?: string | null,
): boolean {
  return status === 'published' || status === 'archived' || Boolean(currentVersionId)
}

export function agentConfigurationLockMessage(status: AgentStatus | null | undefined): string {
  if (status === 'archived') {
    return '已归档 Agent 为只读状态，不能再修改配置、Schema 或资源绑定。'
  }
  return '已发布 Agent 的线上配置已锁定。请创建并编辑新的 Agent Version。'
}

export function isValidClientRateLimit(value: number | null | undefined): value is number {
  return Number.isInteger(value) && value! >= 1 && value! <= 100_000
}

export function confirmAgentRollback(
  dialog: Pick<DialogApi, 'warning'>,
  version: string,
  performRollback: () => void | Promise<void>,
): void {
  dialog.warning({
    title: '确认回滚 Agent',
    content: `确认回滚到 ${version}？Prompt、模型、Skill、MCP 和 Schema 将恢复为该版本快照。`,
    positiveText: '确认回滚',
    negativeText: '取消',
    onPositiveClick: performRollback,
  })
}
