import { describe, expect, it } from 'vitest'

import type { ExecutionDetail, ExecutionSummary } from '@/types/api'
import { buildConversationSessions, executionReplyText } from './agentConversation'

function summary(overrides: Partial<ExecutionSummary>): ExecutionSummary {
  return {
    id: 'execution-1',
    agent_id: '666',
    agent_name: '编报 Agent',
    session_id: 'session-a',
    memory_session_id: null,
    status: 'succeeded',
    task: '分析授权材料并生成报告',
    response_mode: 'sync',
    runtime_type: 'hermes',
    runtime_id: null,
    runtime_version: null,
    priority: null,
    duration_ms: 1200,
    token_usage: null,
    skill_count: 1,
    mcp_call_count: 1,
    memory_read_count: 0,
    artifact_count: 1,
    trace_step_count: 4,
    failed_step_count: 0,
    model_call_count: 1,
    retry_of_execution_id: null,
    agent_version_id: null,
    agent_version: null,
    started_at: '2026-08-18T01:00:00Z',
    finished_at: '2026-08-18T01:00:01Z',
    ...overrides,
  }
}

describe('agent conversation helpers', () => {
  it('groups executions by session and keeps messages in chronological order', () => {
    const sessions = buildConversationSessions([
      summary({ id: 'execution-2', started_at: '2026-08-18T02:00:00Z', task: '继续补充第二部分' }),
      summary({ id: 'execution-3', session_id: 'session-b', started_at: '2026-08-18T03:00:00Z' }),
      summary({ id: 'execution-1', started_at: '2026-08-18T01:00:00Z' }),
    ])

    expect(sessions.map((item) => item.key)).toEqual(['session-b', 'session-a'])
    expect(sessions[1].items.map((item) => item.id)).toEqual(['execution-1', 'execution-2'])
    expect(sessions[1].title).toBe('分析授权材料并生成报告')
  })

  it('groups by the user memory session instead of the per-run internal session', () => {
    const sessions = buildConversationSessions([
      summary({ id: 'execution-1', session_id: 'internal-1', memory_session_id: 'chat-a' }),
      summary({ id: 'execution-2', session_id: 'internal-2', memory_session_id: 'chat-a', started_at: '2026-08-18T02:00:00Z' }),
    ])

    expect(sessions).toHaveLength(1)
    expect(sessions[0].key).toBe('chat-a')
    expect(sessions[0].sessionId).toBe('chat-a')
    expect(sessions[0].items.map((item) => item.id)).toEqual(['execution-1', 'execution-2'])
  })

  it('uses structured output and explicit status fallbacks when text is unavailable', () => {
    const base = summary({}) as ExecutionDetail
    expect(executionReplyText({ ...base, output: null, output_json: { result: 'ok' }, error: null })).toBe('```json\n{\n  "result": "ok"\n}\n```')
    expect(executionReplyText({ ...base, status: 'running', output: null, output_json: null, error: null })).toContain('正在处理中')
    expect(executionReplyText({ ...base, status: 'failed', output: null, output_json: null, error: '模型超时' })).toBe('执行失败：模型超时')
  })
})
