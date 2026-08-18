import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { platformApi } from '@/api/platform'
import type { ExecutionDetail, ExecutionSummary } from '@/types/api'
import AgentConversationPanel from './AgentConversationPanel.vue'

const execution: ExecutionSummary = {
  id: 'execution-1',
  agent_id: '666',
  agent_name: '编报 Agent',
  session_id: 'session-a',
  memory_session_id: null,
  status: 'succeeded',
  task: '根据材料编写报告',
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
}

function mountPanel(props: { executions: ExecutionSummary[]; loading?: boolean; historyError?: string | null }) {
  return mount(AgentConversationPanel, {
    props: { loading: false, agentName: '编报 Agent', ...props },
    global: {
      stubs: {
        NIcon: { template: '<span><slot /></span>' },
        NButton: { template: '<button><slot name="icon" /><slot /></button>' },
        StatusTag: { props: ['status'], template: '<span class="status-stub">{{ status }}</span>' },
      },
    },
  })
}

describe('AgentConversationPanel', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders a wide transcript with user and Agent messages from execution detail', async () => {
    vi.spyOn(platformApi, 'getExecution').mockResolvedValue({
      ...execution,
      input: '请读取材料并输出 JSON',
      input_json: { input: '请读取材料并输出 JSON' },
      output: '处理完成\n```json\n{"status":"ok"}\n```',
      output_json: { status: 'ok' },
      error: null,
      details: {},
      model: 'deepseek-chat',
      model_adapter: 'deepseek',
      schema_version: null,
      steps: [],
      artifacts: [],
      queue_task: null,
    } as ExecutionDetail)

    const wrapper = mountPanel({ executions: [execution] })
    await flushPromises()

    expect(platformApi.getExecution).toHaveBeenCalledWith('execution-1')
    expect(wrapper.text()).toContain('1 个会话')
    expect(wrapper.text()).toContain('1 轮对话')
    expect(wrapper.text()).toContain('请读取材料并输出 JSON')
    expect(wrapper.text()).toContain('处理完成')
    expect(wrapper.find('pre code').text()).toBe('{"status":"ok"}')
    expect(wrapper.text()).toContain('Execution execution-1')
  })

  it('shows actionable error and empty states without requesting execution detail', async () => {
    const getExecution = vi.spyOn(platformApi, 'getExecution')
    const errorWrapper = mountPanel({ executions: [], historyError: '后端暂不可用' })
    const emptyWrapper = mountPanel({ executions: [] })
    await flushPromises()

    expect(errorWrapper.text()).toContain('聊天记录加载失败')
    expect(errorWrapper.text()).toContain('重新加载')
    expect(emptyWrapper.text()).toContain('暂无聊天记录')
    expect(getExecution).not.toHaveBeenCalled()
  })
})
