import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { platformApi } from '@/api/platform'
import type {
  Agent,
  AgentTask,
  ExecutionDetail,
  ExecutionSummary,
  WorkflowRun,
} from '@/types/api'
import TeamRunWorkspace from './TeamRunWorkspace.vue'

const run: WorkflowRun = {
  id: 'run-1',
  workflow_id: null,
  team_id: 'team-1',
  session_id: 'legacy-run-1',
  status: 'succeeded',
  input: '请根据授权材料生成编报',
  output: JSON.stringify({
    status: 'blocked',
    title: '欧洲热点编报',
    summary: '授权材料不足',
    report_markdown: null,
    blocking_reasons: ['未找到原始材料'],
    information_gaps: ['缺少时间与信源'],
  }),
  error: null,
  created_at: '2026-08-18T01:00:00Z',
  started_at: '2026-08-18T01:00:01Z',
  finished_at: '2026-08-18T01:01:00Z',
}

function task(values: Partial<AgentTask>): AgentTask {
  return {
    id: 'task-manager',
    parent_task_id: null,
    workflow_id: null,
    workflow_run_id: 'run-1',
    node_key: '__manager__',
    node_type: 'agent',
    depends_on: [],
    input_data: { role: 'manager' },
    output_data: {},
    agent_id: 'manager-agent',
    session_id: 'session-manager',
    execution_id: 'execution-manager',
    priority: 5,
    status: 'succeeded',
    attempt: 1,
    max_attempts: 3,
    worker_id: null,
    error: null,
    created_at: '2026-08-18T01:00:00Z',
    started_at: '2026-08-18T01:00:01Z',
    finished_at: '2026-08-18T01:01:00Z',
    ...values,
  }
}

const managerTask = task({})
const workerTask = task({
  id: 'task-worker',
  parent_task_id: 'task-manager',
  node_key: 'worker-analysis',
  input_data: { role: '材料分析', original_input: run.input },
  agent_id: 'worker-agent',
  session_id: 'session-worker',
  execution_id: 'execution-worker',
})

const agents = [
  { id: 'manager-agent', name: '编报 Manager', runtime_type: 'hermes' },
  { id: 'worker-agent', name: '材料 Worker', runtime_type: 'deepseek' },
] as Agent[]

function summary(id: string, agentId: string): ExecutionSummary {
  return {
    id,
    agent_id: agentId,
    agent_name: agentId === 'worker-agent' ? '材料 Worker' : '编报 Manager',
    session_id: `session-${id}`,
    memory_session_id: null,
    status: 'succeeded',
    task: '历史任务',
    response_mode: 'async',
    runtime_type: agentId === 'worker-agent' ? 'deepseek' : 'hermes',
    runtime_id: null,
    runtime_version: null,
    priority: 5,
    duration_ms: 1000,
    token_usage: null,
    skill_count: 0,
    mcp_call_count: 0,
    memory_read_count: 0,
    artifact_count: 0,
    trace_step_count: 3,
    failed_step_count: 0,
    model_call_count: 1,
    retry_of_execution_id: null,
    agent_version_id: null,
    agent_version: null,
    started_at: '2026-08-18T01:00:00Z',
    finished_at: '2026-08-18T01:00:01Z',
  }
}

function detail(id: string, agentId: string, output: string): ExecutionDetail {
  return {
    ...summary(id, agentId),
    input: agentId === 'worker-agent' ? '分析团队材料' : '汇总 Worker 结果',
    input_json: { task: '任务' },
    output,
    output_json: agentId === 'manager-agent' ? JSON.parse(run.output!) : null,
    error: null,
    details: {},
    model: 'test-model',
    model_adapter: 'test-adapter',
    schema_version: null,
    steps: [],
    artifacts: [{
      id: `artifact-${id}`,
      agent_id: agentId,
      session_id: `session-${id}`,
      filename: `${agentId}-result.json`,
      storage_type: 'minio',
      storage_path: `${agentId}/result.json`,
      content_type: 'application/json',
      artifact_type: 'json',
      runtime_source: 'platform',
      size_bytes: 1024,
      sha256: 'abc',
      created_at: '2026-08-18T01:01:00Z',
    }],
    queue_task: null,
  }
}

function mountWorkspace(overrides: Partial<{
  runs: WorkflowRun[]
  tasks: AgentTask[]
  agents: Agent[]
  selectedRunId: string | null
}> = {}) {
  return mount(TeamRunWorkspace, {
    props: {
      runs: [run],
      tasks: [managerTask, workerTask],
      agents,
      selectedRunId: run.id,
      loading: false,
      ...overrides,
    },
    global: {
      stubs: {
        NIcon: { template: '<span><slot /></span>' },
        NButton: {
          emits: ['click'],
          template: '<button @click="$emit(\'click\')"><slot name="icon" /><slot /></button>',
        },
        StatusTag: {
          props: ['status'],
          template: '<span class="status-stub">{{ status }}</span>',
        },
        AgentConversationPanel: {
          props: ['executions', 'agentName'],
          template: '<div class="history-stub">{{ agentName }} {{ executions.length }} 条历史</div>',
        },
      },
    },
  })
}

describe('TeamRunWorkspace', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders team input, Manager business result and downloadable artifacts', async () => {
    vi.spyOn(platformApi, 'getExecution').mockImplementation(async (id) => (
      id === 'execution-worker'
        ? detail(id, 'worker-agent', '# Worker 输出\n已完成材料分析')
        : detail(id, 'manager-agent', run.output!)
    ))

    const wrapper = mountWorkspace()
    await flushPromises()

    expect(wrapper.text()).toContain('请根据授权材料生成编报')
    expect(wrapper.text()).toContain('授权材料不足')
    expect(wrapper.text()).toContain('未找到原始材料')
    expect(wrapper.text()).toContain('业务结果')
    expect(wrapper.find('.run-artifacts a').attributes('href')).toBe('/api/artifacts/artifact-execution-manager/download')
  })

  it('shows a selected Worker output, trace controls and all Agent history', async () => {
    vi.spyOn(platformApi, 'getExecution').mockImplementation(async (id) => (
      id === 'execution-worker'
        ? detail(id, 'worker-agent', '# Worker 输出\n已完成材料分析')
        : detail(id, 'manager-agent', run.output!)
    ))
    vi.spyOn(platformApi, 'listExecutions').mockResolvedValue({
      items: [summary('history-1', 'worker-agent')],
      total: 1,
      limit: 50,
      offset: 0,
      metrics: { total_executions: 1, running: 0, succeeded: 1, failed: 0, cancelled: 0, success_rate: 1 },
    })

    const wrapper = mountWorkspace()
    await flushPromises()
    await wrapper.findAll('.workspace-tabs button')[1].trigger('click')
    await wrapper.findAll('.agent-task-list button')[1].trigger('click')
    await flushPromises()

    expect(platformApi.getExecution).toHaveBeenCalledWith('execution-worker')
    expect(wrapper.text()).toContain('已完成材料分析')
    expect(wrapper.text()).toContain('Execution execution-worker')
    expect(wrapper.find('.run-artifacts a').attributes('href')).toBe('/api/artifacts/artifact-execution-worker/download')

    const detailActions = wrapper.findAll('.run-message-footer button')
    await detailActions[0].trigger('click')
    await detailActions[1].trigger('click')
    expect(wrapper.emitted('openExecution')).toEqual([['execution-worker']])
    expect(wrapper.emitted('openTrace')).toEqual([['execution-worker']])

    await wrapper.findAll('.agent-scope-tabs button')[1].trigger('click')
    await flushPromises()

    expect(platformApi.listExecutions).toHaveBeenCalledWith({ agent_id: 'worker-agent', limit: 50, offset: 0 })
    expect(wrapper.find('.history-stub').text()).toContain('材料 Worker 1 条历史')
  })

  it('shows a waiting state while the Manager output is still running', async () => {
    const wrapper = mountWorkspace({
      runs: [{ ...run, status: 'running', output: null, finished_at: null }],
      tasks: [{ ...managerTask, status: 'running', execution_id: null, finished_at: null }],
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Manager 正在汇总团队结果')
    expect(wrapper.text()).toContain('完成后会在此显示最终输出')
  })

  it('shows the real failure and keeps approval actions on the matching node', async () => {
    const approvalTask = task({
      id: 'task-approval',
      parent_task_id: 'task-manager',
      node_key: 'human-approval',
      node_type: 'human_approval',
      status: 'human_review',
      execution_id: null,
      error: null,
      finished_at: null,
    })
    const wrapper = mountWorkspace({
      runs: [{ ...run, status: 'failed', output: null, error: 'Manager 汇总失败' }],
      tasks: [{ ...managerTask, status: 'failed', execution_id: null, error: '模型调用失败' }, approvalTask],
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Manager 汇总失败')
    await wrapper.findAll('.workspace-tabs button')[1].trigger('click')
    await wrapper.findAll('.agent-task-list button')[1].trigger('click')
    await flushPromises()

    const approvalActions = wrapper.findAll('.approval-actions button')
    expect(approvalActions).toHaveLength(2)
    await approvalActions[0].trigger('click')
    await approvalActions[1].trigger('click')
    expect(wrapper.emitted('review')).toEqual([
      [approvalTask, true],
      [approvalTask, false],
    ])
  })
})
