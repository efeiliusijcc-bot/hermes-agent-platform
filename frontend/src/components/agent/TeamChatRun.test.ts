import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('naive-ui', () => ({ NIcon: { template: '<span><slot /></span>' } }))

import { platformApi } from '@/api/platform'
import router from '@/router'
import type { AgentTask, AgentTeam, ExecutionDetail, WorkflowRun } from '@/types/api'
import TeamChatRun from './TeamChatRun.vue'

const team: AgentTeam = {
  id: 'team-a',
  name: '内网编报 Team',
  description: null,
  owner_agent_id: 'manager-a',
  status: 'active',
  members: [
    { agent_id: 'manager-a', agent_name: '编报 Manager', agent_type: 'manager', runtime_type: 'hermes', role: 'manager', priority: 100 },
    { agent_id: 'worker-a', agent_name: '材料分析 Agent', agent_type: 'worker', runtime_type: 'pi', role: '材料分析', priority: 50 },
  ],
  created_at: '2026-08-20T01:00:00Z',
  updated_at: '2026-08-20T01:00:00Z',
}

const run: WorkflowRun = {
  id: 'run-a',
  workflow_id: null,
  team_id: team.id,
  session_id: 'team-chat-a',
  status: 'succeeded',
  input: '根据内网材料生成编报',
  output: JSON.stringify({ status: 'completed', title: '编报结果', report_markdown: '# 最终报告\n已完成。' }),
  error: null,
  created_at: '2026-08-20T01:00:00Z',
  started_at: '2026-08-20T01:00:01Z',
  finished_at: '2026-08-20T01:01:00Z',
}

function task(overrides: Partial<AgentTask> = {}): AgentTask {
  return {
    id: 'task-manager',
    parent_task_id: null,
    workflow_id: null,
    workflow_run_id: run.id,
    node_key: '__manager__',
    node_type: 'agent',
    depends_on: [],
    input_data: { role: 'manager', original_input: run.input },
    output_data: {},
    agent_id: 'manager-a',
    session_id: 'runtime-session-a',
    execution_id: 'execution-manager',
    priority: 5,
    status: 'succeeded',
    attempt: 1,
    max_attempts: 3,
    worker_id: null,
    error: null,
    created_at: '2026-08-20T01:00:00Z',
    started_at: '2026-08-20T01:00:01Z',
    finished_at: '2026-08-20T01:01:00Z',
    ...overrides,
  }
}

function execution(id: string, agentId: string, output: string): ExecutionDetail {
  return {
    id,
    agent_id: agentId,
    agent_name: agentId === 'manager-a' ? '编报 Manager' : '材料分析 Agent',
    session_id: `session-${id}`,
    memory_session_id: 'team-memory',
    status: 'succeeded',
    task: run.input,
    response_mode: 'sync',
    runtime_type: agentId === 'manager-a' ? 'hermes' : 'pi',
    runtime_id: null,
    runtime_version: null,
    priority: 5,
    duration_ms: 120,
    token_usage: 12,
    skill_count: 0,
    mcp_call_count: 0,
    memory_read_count: 1,
    artifact_count: 1,
    trace_step_count: 2,
    failed_step_count: 0,
    model_call_count: 1,
    retry_of_execution_id: null,
    agent_version_id: null,
    agent_version: null,
    started_at: '2026-08-20T01:00:01Z',
    finished_at: '2026-08-20T01:01:00Z',
    input: run.input,
    input_json: { task: run.input },
    output,
    output_json: null,
    error: null,
    details: {},
    model: 'test-model',
    model_adapter: 'hermes',
    schema_version: null,
    steps: [],
    artifacts: [{
      id: `artifact-${id}`,
      agent_id: agentId,
      session_id: `session-${id}`,
      filename: 'result.md',
      storage_type: 'filesystem',
      storage_path: 'result.md',
      content_type: 'text/markdown',
      artifact_type: 'report',
      runtime_source: agentId === 'manager-a' ? 'hermes' : 'pi',
      size_bytes: 128,
      sha256: 'abc',
      created_at: '2026-08-20T01:01:00Z',
    }],
    queue_task: null,
  }
}

function mountRun(values: WorkflowRun = run) {
  return mount(TeamChatRun, {
    props: { run: values, team },
    global: {
      plugins: [router],
      stubs: {
        StatusTag: { props: ['status'], template: '<span>{{ status }}</span>' },
        AgentConversationPanel: { props: ['executions'], template: '<div class="history-stub">历史 {{ executions.length }}</div>' },
        NButton: {
          props: ['disabled', 'loading'],
          emits: ['click'],
          template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot name="icon" /><slot /></button>',
        },
      },
    },
  })
}

describe('TeamChatRun', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders Manager output first and lazily loads tasks then the selected Execution', async () => {
    const manager = task()
    const worker = task({ id: 'task-worker', parent_task_id: manager.id, node_key: 'materials', agent_id: 'worker-a', execution_id: 'execution-worker', input_data: { role: '材料分析', original_input: run.input } })
    const listTasks = vi.spyOn(platformApi, 'listWorkflowRunTasks').mockResolvedValue([manager, worker])
    const getExecution = vi.spyOn(platformApi, 'getExecution').mockImplementation(async (id) => execution(id, id === 'execution-worker' ? 'worker-a' : 'manager-a', id === 'execution-worker' ? 'Worker 输出' : 'Manager 输出'))
    const listHistory = vi.spyOn(platformApi, 'listExecutions').mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0, metrics: { total_executions: 0, running: 0, succeeded: 0, failed: 0, cancelled: 0, success_rate: null } })
    const wrapper = mountRun()
    await flushPromises()

    expect(wrapper.text()).toContain('最终报告')
    expect(listTasks).not.toHaveBeenCalled()
    expect(getExecution).not.toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text().includes('查看协作过程'))!.trigger('click')
    await flushPromises()
    expect(listTasks).toHaveBeenCalledWith('run-a')
    expect(getExecution).toHaveBeenCalledWith('execution-manager')

    await wrapper.findAll('.team-task-list button').find((button) => button.text().includes('材料分析'))!.trigger('click')
    await flushPromises()
    expect(getExecution).toHaveBeenCalledWith('execution-worker')
    expect(wrapper.text()).toContain('Worker 输出')
    expect(wrapper.text()).toContain('result.md')

    await wrapper.findAll('button').find((button) => button.text().includes('全部历史'))!.trigger('click')
    await flushPromises()
    expect(listHistory).toHaveBeenCalledWith({ agent_id: 'worker-a', limit: 50, offset: 0 })
    expect(wrapper.text()).toContain('历史 0')
    wrapper.unmount()
  })

  it('offers real approval and cancellation actions for active runs', async () => {
    const reviewTask = task({ id: 'task-review', node_key: 'approval', node_type: 'human_approval', execution_id: null, status: 'human_review' })
    vi.spyOn(platformApi, 'listWorkflowRunTasks').mockResolvedValue([reviewTask])
    const review = vi.spyOn(platformApi, 'reviewHumanTask').mockResolvedValue({ ...reviewTask, status: 'succeeded' })
    const cancel = vi.spyOn(platformApi, 'cancelWorkflowRun').mockResolvedValue()
    const wrapper = mountRun({ ...run, status: 'human_review', output: null, finished_at: null })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('取消运行'))!.trigger('click')
    await flushPromises()
    expect(cancel).toHaveBeenCalledWith('run-a')

    await wrapper.findAll('button').find((button) => button.text().includes('查看协作过程'))!.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text() === '通过')!.trigger('click')
    await flushPromises()
    expect(review).toHaveBeenCalledWith('task-review', true, '聊天工作台审批通过')
    wrapper.unmount()
  })
})
