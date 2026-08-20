import type { ExecutionDetail, ExecutionSummary } from '@/types/api'

export interface AgentConversationSession {
  key: string
  sessionId: string | null
  title: string
  latestAt: string
  status: ExecutionSummary['status']
  items: ExecutionSummary[]
}

function sessionKey(item: ExecutionSummary): string {
  return item.memory_session_id || item.session_id || `execution:${item.id}`
}

export function conversationPreview(value: string, maxLength = 52): string {
  const normalized = value.replace(/\s+/g, ' ').trim()
  if (!normalized) return '未命名会话'
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength)}...` : normalized
}

export function buildConversationSessions(executions: ExecutionSummary[]): AgentConversationSession[] {
  const grouped = new Map<string, ExecutionSummary[]>()
  for (const execution of executions) {
    const key = sessionKey(execution)
    grouped.set(key, [...(grouped.get(key) || []), execution])
  }

  return [...grouped.entries()]
    .map(([key, items]) => {
      const ordered = [...items].sort((left, right) => Date.parse(left.started_at) - Date.parse(right.started_at))
      const latest = ordered[ordered.length - 1]
      return {
        key,
        sessionId: latest.memory_session_id || latest.session_id,
        title: conversationPreview(ordered[0].task),
        latestAt: latest.started_at,
        status: latest.status,
        items: ordered,
      }
    })
    .sort((left, right) => Date.parse(right.latestAt) - Date.parse(left.latestAt))
}

export function executionReplyText(execution: ExecutionDetail): string {
  if (execution.output?.trim()) return execution.output
  if (execution.output_json !== null && execution.output_json !== undefined) {
    return `\`\`\`json\n${JSON.stringify(execution.output_json, null, 2)}\n\`\`\``
  }
  if (execution.error?.trim()) return `执行失败：${execution.error}`
  if (['queued', 'running'].includes(execution.status)) return 'Agent 正在处理中，完成后将在此显示回复。'
  return '本次执行未返回文本回复。'
}
