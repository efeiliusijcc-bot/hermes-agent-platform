import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const warning = vi.fn()
vi.mock('naive-ui', () => ({
  NIcon: { template: '<span><slot /></span>' },
  useMessage: () => ({ warning, success: vi.fn(), error: vi.fn() }),
}))

import { platformApi } from '@/api/platform'
import router from '@/router'
import type { Agent, AgentRunResponse, ExecutionDetail, ExecutionList, ExecutionSummary } from '@/types/api'
import AgentChatView from './AgentChatView.vue'

function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    id: 'agent-a',
    name: '分析 Agent',
    description: '用于测试聊天',
    agent_type: 'worker',
    parent_agent_id: null,
    role: '分析员',
    system_prompt: '分析任务',
    model_config: {},
    model: 'test-model',
    prompt_template: '{{input}}',
    model_adapter: 'hermes',
    runtime_type: 'hermes',
    runtime_id: null,
    runtime_config: {},
    capability_profile: { workspace_type: 'document', required_tools: [], artifact_types: [] },
    api_enabled: true,
    status: 'active',
    response_mode: 'sync',
    input_schema: {},
    output_schema: {},
    current_version_id: 'version-a',
    created_at: '2026-08-20T01:00:00Z',
    updated_at: '2026-08-20T01:00:00Z',
    ...overrides,
  }
}

function summary(overrides: Partial<ExecutionSummary> = {}): ExecutionSummary {
  return {
    id: 'execution-1',
    agent_id: 'agent-a',
    agent_name: '分析 Agent',
    session_id: 'internal-1',
    memory_session_id: 'chat-a',
    status: 'succeeded',
    task: '第一轮问题',
    response_mode: 'sync',
    runtime_type: 'hermes',
    runtime_id: null,
    runtime_version: null,
    priority: null,
    duration_ms: 300,
    token_usage: 10,
    skill_count: 0,
    mcp_call_count: 0,
    memory_read_count: 0,
    artifact_count: 0,
    trace_step_count: 3,
    failed_step_count: 0,
    model_call_count: 1,
    retry_of_execution_id: null,
    agent_version_id: 'version-a',
    agent_version: 'v1',
    started_at: '2026-08-20T01:00:00Z',
    finished_at: '2026-08-20T01:00:01Z',
    ...overrides,
  }
}

function detail(item: ExecutionSummary, output = '第一轮回复'): ExecutionDetail {
  return {
    ...item,
    input: item.task,
    input_json: { task: item.task, parameters: {} },
    output,
    output_json: null,
    error: null,
    details: {},
    model: 'test-model',
    model_adapter: 'hermes',
    schema_version: null,
    steps: [],
    artifacts: [],
    queue_task: null,
  }
}

function executionList(items: ExecutionSummary[]): ExecutionList {
  return {
    items,
    total: items.length,
    limit: 50,
    offset: 0,
    metrics: { total_executions: items.length, running: 0, succeeded: items.length, failed: 0, cancelled: 0, success_rate: items.length ? 1 : null },
  }
}

function mountChat() {
  return mount(AgentChatView, {
    global: {
      plugins: [router],
      stubs: {
        PageHeader: { template: '<header><slot name="actions" /></header>' },
        StatusTag: { props: ['status'], template: '<span class="status-stub">{{ status }}</span>' },
        NAlert: { template: '<div><slot /></div>' },
        NButton: {
          props: ['disabled', 'loading'],
          emits: ['click'],
          template: '<button :disabled="disabled" @click="$emit(\'click\', $event)"><slot name="icon" /><slot /></button>',
        },
        NInput: {
          props: ['value', 'type', 'disabled', 'placeholder'],
          emits: ['update:value', 'keydown'],
          template: `<textarea
            v-if="type === 'textarea'"
            :value="value"
            :disabled="disabled"
            :placeholder="placeholder"
            @input="$emit('update:value', $event.target.value)"
            @keydown="$emit('keydown', $event)"
          /><input
            v-else
            :value="value"
            :disabled="disabled"
            :placeholder="placeholder"
            @input="$emit('update:value', $event.target.value)"
          />`,
        },
      },
    },
  })
}

describe('AgentChatView', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    warning.mockReset()
  })

  it('defaults to single Agent mode and switches to the independent Team workspace', async () => {
    await router.push('/chat')
    const wrapper = mount(AgentChatView, {
      global: {
        plugins: [router],
        stubs: {
          SingleAgentChatWorkspace: { template: '<div>单 Agent 工作区</div>' },
          TeamAgentChatWorkspace: { template: '<div>Agent Team 工作区</div>' },
        },
      },
    })

    expect(wrapper.text()).toContain('单 Agent 工作区')
    expect(router.currentRoute.value.query.mode).toBeUndefined()

    await wrapper.findAll('.chat-mode-switch button').find((button) => button.text().includes('Agent Team'))!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.mode).toBe('team')
    expect(wrapper.text()).toContain('Agent Team 工作区')
    wrapper.unmount()
  })

  it('loads every Agent and groups multiple internal runs into one memory conversation', async () => {
    const second = summary({ id: 'execution-2', session_id: 'internal-2', task: '第二轮问题', started_at: '2026-08-20T02:00:00Z' })
    vi.spyOn(platformApi, 'listAgents').mockResolvedValue([agent(), agent({ id: 'agent-b', name: '写作 Agent', runtime_type: 'pi' })])
    vi.spyOn(platformApi, 'listExecutions').mockResolvedValue(executionList([second, summary()]))
    vi.spyOn(platformApi, 'getExecution').mockImplementation(async (id) => detail(id === second.id ? second : summary(), id === second.id ? '第二轮回复' : '第一轮回复'))
    await router.push('/chat?agent=agent-a&session=chat-a')

    const wrapper = mountChat()
    await flushPromises()

    expect(platformApi.listExecutions).toHaveBeenCalledWith({ agent_id: 'agent-a', limit: 50 })
    expect(wrapper.text()).toContain('分析 Agent')
    expect(wrapper.text()).toContain('写作 Agent')
    expect(wrapper.text()).toContain('2 轮')
    expect(wrapper.text()).toContain('第一轮问题')
    expect(wrapper.text()).toContain('第二轮回复')
    expect(platformApi.getExecution).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('switches Agent from the left list and restores the selected Agent in the URL', async () => {
    vi.stubGlobal('crypto', {})
    const agents = [agent(), agent({ id: 'agent-b', name: '写作 Agent', runtime_type: 'pi' })]
    vi.spyOn(platformApi, 'listAgents').mockResolvedValue(agents)
    const list = vi.spyOn(platformApi, 'listExecutions').mockResolvedValue(executionList([]))
    await router.push('/chat?agent=agent-a&session=chat-a')
    const wrapper = mountChat()
    await flushPromises()

    const target = wrapper.findAll('[role="option"]').find((item) => item.text().includes('写作 Agent'))
    expect(target).toBeDefined()
    await target!.trigger('click')
    await flushPromises()

    expect(list).toHaveBeenCalledWith({ agent_id: 'agent-b', limit: 50 })
    expect(router.currentRoute.value.query.agent).toBe('agent-b')
    expect(String(router.currentRoute.value.query.session)).toMatch(/^chat-/)
    wrapper.unmount()
  })

  it('opens responsive Agent and session drawers and closes them with Escape', async () => {
    vi.spyOn(platformApi, 'listAgents').mockResolvedValue([agent()])
    vi.spyOn(platformApi, 'listExecutions').mockResolvedValue(executionList([]))
    await router.push('/chat?agent=agent-a&session=chat-a')
    const wrapper = mountChat()
    await flushPromises()
    const focus = vi.spyOn(HTMLElement.prototype, 'focus')

    const agentOpener = wrapper.get('button[aria-label="打开 Agent 列表"]')
    await agentOpener.trigger('click')
    expect(wrapper.get('.chat-agent-pane').classes()).toContain('mobile-open')
    expect(focus.mock.contexts).toContain(wrapper.get('button[aria-label="关闭 Agent 列表"]').element)
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(wrapper.get('.chat-agent-pane').classes()).not.toContain('mobile-open')
    expect(focus.mock.contexts).toContain(agentOpener.element)

    const sessionOpener = wrapper.get('button[aria-label="打开会话列表"]')
    await sessionOpener.trigger('click')
    expect(wrapper.get('.chat-session-pane').classes()).toContain('mobile-open')
    expect(focus.mock.contexts).toContain(wrapper.get('button[aria-label="关闭会话列表"]').element)
    await wrapper.get('button[aria-label="关闭会话列表"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('.chat-session-pane').classes()).not.toContain('mobile-open')
    expect(focus.mock.contexts).toContain(sessionOpener.element)
    wrapper.unmount()
  })

  it('sends natural language with the active memory session in sync mode', async () => {
    const created = summary({ id: 'execution-new', task: '继续分析', session_id: 'internal-new' })
    let completed = false
    vi.spyOn(platformApi, 'listAgents').mockResolvedValue([agent()])
    vi.spyOn(platformApi, 'listExecutions').mockImplementation(async () => executionList(completed ? [created] : []))
    const run = vi.spyOn(platformApi, 'runAgent').mockImplementation(async () => {
      completed = true
      return { execution_id: created.id } as AgentRunResponse
    })
    vi.spyOn(platformApi, 'getExecution').mockResolvedValue(detail(created, '继续分析完成'))
    await router.push('/chat?agent=agent-a&session=chat-a')
    const wrapper = mountChat()
    await flushPromises()

    await wrapper.get('textarea').setValue('继续分析')
    await wrapper.get('button[aria-label="发送消息"]').trigger('click')
    await flushPromises()

    expect(run).toHaveBeenCalledWith('agent-a', { input: '继续分析', session_id: 'chat-a', parameters: {} })
    expect(wrapper.text()).toContain('继续分析完成')
    wrapper.unmount()
  })

  it('streams replies and blocks Agents that require Schema parameters', async () => {
    const streamAgent = agent({ response_mode: 'stream' })
    const streamed = summary({ id: 'execution-stream', task: '流式问题', response_mode: 'stream' })
    vi.spyOn(platformApi, 'listAgents').mockResolvedValue([streamAgent])
    vi.spyOn(platformApi, 'listExecutions').mockResolvedValue(executionList([]))
    const stream = vi.spyOn(platformApi, 'streamAgent').mockImplementation(async (_id, _payload, onEvent) => {
      onEvent({ event: 'start', execution_id: streamed.id })
      onEvent({ event: 'token', text: '实时回复' })
      onEvent({ event: 'end', execution_id: streamed.id })
    })
    vi.spyOn(platformApi, 'getExecution').mockResolvedValue(detail(streamed, '实时回复'))
    await router.push('/chat?agent=agent-a&session=chat-a')
    const wrapper = mountChat()
    await flushPromises()

    await wrapper.get('textarea').setValue('流式问题')
    await wrapper.get('button[aria-label="发送消息"]').trigger('click')
    await flushPromises()
    expect(stream).toHaveBeenCalledWith('agent-a', { input: '流式问题', session_id: 'chat-a', parameters: {} }, expect.any(Function))

    wrapper.unmount()
    vi.restoreAllMocks()
    vi.spyOn(platformApi, 'listAgents').mockResolvedValue([agent({ input_schema: { type: 'object', required: ['topic'] } })])
    vi.spyOn(platformApi, 'listExecutions').mockResolvedValue(executionList([]))
    await router.push('/chat?agent=agent-a&session=chat-required')
    const blocked = mountChat()
    await flushPromises()

    expect(blocked.text()).toContain('该 Agent 需要必填参数：topic')
    expect(blocked.get('textarea').attributes('disabled')).toBeDefined()
    expect(blocked.text()).toContain('前往执行工作台')
    blocked.unmount()
  })
})
