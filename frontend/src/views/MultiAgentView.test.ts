import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { platformApi } from '@/api/platform'
import router from '@/router'
import type { Agent, AgentTeam, Workflow, WorkflowRun } from '@/types/api'
import MultiAgentView from './MultiAgentView.vue'

const teams = [
  {
    id: 'team-a',
    name: '团队 A',
    description: null,
    owner_agent_id: 'manager-a',
    status: 'active',
    members: [],
    created_at: '2026-08-18T01:00:00Z',
    updated_at: '2026-08-18T01:00:00Z',
  },
  {
    id: 'team-b',
    name: '团队 B',
    description: null,
    owner_agent_id: 'manager-b',
    status: 'active',
    members: [],
    created_at: '2026-08-18T02:00:00Z',
    updated_at: '2026-08-18T02:00:00Z',
  },
] as AgentTeam[]

function run(teamId: string, suffix = teamId, createdAt = '2026-08-18T01:00:00Z'): WorkflowRun {
  return {
    id: `run-${suffix}`,
    workflow_id: null,
    team_id: teamId,
    session_id: `legacy-run-${suffix}`,
    status: 'succeeded',
    input: `${teamId} 任务`,
    output: 'ok',
    error: null,
    created_at: createdAt,
    started_at: '2026-08-18T01:00:01Z',
    finished_at: '2026-08-18T01:00:02Z',
  }
}

describe('MultiAgentView team run filtering', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('loads only the selected Team runs and resets to the newest run after switching Team', async () => {
    vi.useFakeTimers()
    await router.push('/orchestration')
    await router.isReady()
    vi.spyOn(platformApi, 'listAgents').mockResolvedValue([])
    vi.spyOn(platformApi, 'listAgentTeams').mockResolvedValue(teams)
    vi.spyOn(platformApi, 'listWorkflows').mockResolvedValue([])
    const listRuns = vi.spyOn(platformApi, 'listWorkflowRuns').mockImplementation(async ({ team_id } = {}) => {
      if (team_id === 'team-a') {
        return [
          run(team_id, 'team-a-old', '2026-08-18T01:00:00Z'),
          run(team_id, 'team-a-newest', '2026-08-18T03:00:00Z'),
        ]
      }
      return team_id ? [run(team_id)] : []
    })
    vi.spyOn(platformApi, 'listWorkflowRunTasks').mockResolvedValue([])

    const wrapper = mount(MultiAgentView, {
      global: {
        plugins: [router],
        stubs: {
          teleport: true,
          PageHeader: { template: '<header><slot name="actions" /></header>' },
          TeamRunWorkspace: {
            props: ['runs', 'selectedRunId'],
            template: '<div class="workspace-stub">{{ selectedRunId }} {{ runs.map((item) => item.id).join(\',\') }}</div>',
          },
          StatusTag: { props: ['status'], template: '<span>{{ status }}</span>' },
          NIcon: { template: '<span><slot /></span>' },
          NButton: { template: '<button><slot name="icon" /><slot /></button>' },
          NAlert: { template: '<div><slot /></div>' },
          NDivider: { template: '<div><slot /></div>' },
          NInput: { props: ['value'], emits: ['update:value'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
          NInputNumber: { props: ['value'], emits: ['update:value'], template: '<input :value="value" />' },
          NCheckbox: { props: ['checked'], emits: ['update:checked'], template: '<label><input type="checkbox" :checked="checked" @change="$emit(\'update:checked\', $event.target.checked)" /><slot /></label>' },
          NEmpty: { template: '<div />' },
          NSelect: {
            props: ['value', 'options'],
            emits: ['update:value'],
            template: '<button class="select-stub" @click="$emit(\'update:value\', options?.[0]?.value || \'\')">{{ value }}</button>',
          },
          NModal: { props: ['show', 'title'], template: '<section v-if="show" class="modal-stub"><h2>{{ title }}</h2><slot /><footer><slot name="footer" /></footer></section>' },
        },
      },
    })
    await flushPromises()

    expect(listRuns).toHaveBeenCalledWith({ team_id: 'team-a' })
    await wrapper.findAll('button').find((button) => button.text().includes('运行结果'))!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.workspace-stub').text()).toContain('run-team-a-newest')

    await wrapper.findAll('.team-list button').find((button) => button.text().includes('团队 B'))!.trigger('click')
    await flushPromises()

    expect(listRuns).toHaveBeenCalledWith({ team_id: 'team-b' })
    await wrapper.findAll('button').find((button) => button.text().includes('运行结果'))!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.workspace-stub').text()).toContain('run-team-b')
    expect(wrapper.find('.workspace-stub').text()).not.toContain('run-team-a')
    wrapper.unmount()
  })

  it('uses focused dialogs for team, member, and ordered Workflow creation', async () => {
    await router.push('/orchestration')
    await router.isReady()
    const agents = [
      {
        id: 'manager-a', name: 'Manager A', agent_type: 'manager', status: 'active', runtime_type: 'hermes',
        role: '团队负责人', model: 'model-a',
      },
      {
        id: 'worker-a', name: 'Worker A', agent_type: 'worker', status: 'active', runtime_type: 'pi',
        role: '材料分析', model: 'model-b',
      },
      {
        id: 'worker-b', name: 'Worker B', agent_type: 'worker', status: 'active', runtime_type: 'deepseek',
        role: '事实核验', model: 'model-c',
      },
    ] as Agent[]
    const team = {
      ...teams[0],
      members: [
        { agent_id: 'manager-a', agent_name: 'Manager A', agent_type: 'manager', runtime_type: 'hermes', role: '团队负责人', priority: 100 },
        { agent_id: 'worker-a', agent_name: 'Worker A', agent_type: 'worker', runtime_type: 'pi', role: '材料分析', priority: 50 },
      ],
    } as AgentTeam
    vi.spyOn(platformApi, 'listAgents').mockResolvedValue(agents)
    vi.spyOn(platformApi, 'listAgentTeams').mockResolvedValue([team])
    vi.spyOn(platformApi, 'listWorkflows').mockResolvedValue([])
    vi.spyOn(platformApi, 'listWorkflowRuns').mockResolvedValue([])
    vi.spyOn(platformApi, 'listWorkflowRunTasks').mockResolvedValue([])
    const createWorkflow = vi.spyOn(platformApi, 'createWorkflow').mockImplementation(async (payload) => ({
      id: 'workflow-new', description: null, created_at: '2026-08-20T01:00:00Z', updated_at: '2026-08-20T01:00:00Z', ...payload,
    }) as Workflow)

    const wrapper = mount(MultiAgentView, {
      global: {
        plugins: [router],
        stubs: {
          teleport: true,
          PageHeader: { template: '<header><slot name="actions" /></header>' },
          TeamRunWorkspace: { template: '<div />' },
          StatusTag: { props: ['status'], template: '<span>{{ status }}</span>' },
          NIcon: { template: '<span><slot /></span>' },
          NButton: { template: '<button><slot name="icon" /><slot /></button>' },
          NAlert: { template: '<div><slot /></div>' },
          NInput: { props: ['value'], emits: ['update:value'], template: '<input :value="value" @input="$emit(\'update:value\', $event.target.value)" />' },
          NInputNumber: { props: ['value'], template: '<input :value="value" />' },
          NCheckbox: { props: ['checked'], emits: ['update:checked'], template: '<label><input type="checkbox" :checked="checked" @change="$emit(\'update:checked\', $event.target.checked)" /><slot /></label>' },
          NEmpty: { template: '<div />' },
          NSelect: { props: ['value', 'options'], emits: ['update:value'], template: '<button class="select-stub" @click="$emit(\'update:value\', options?.[0]?.value || \'\')">{{ value }}</button>' },
          NModal: { props: ['show', 'title'], template: '<section v-if="show" class="modal-stub"><h2>{{ title }}</h2><slot /><footer><slot name="footer" /></footer></section>' },
        },
      },
    })
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('新建'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('先确定团队边界')
    await wrapper.findAll('button').find((button) => button.text() === '取消')!.trigger('click')

    await wrapper.findAll('button').find((button) => button.text().includes('新增成员'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('仅显示 active 且尚未加入当前团队的 Agent')
    expect(wrapper.text()).toContain('Worker B')
    await wrapper.findAll('button').find((button) => button.text() === '取消')!.trigger('click')

    await wrapper.findAll('button').find((button) => button.text().includes('创建 Workflow'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('这个流程解决什么任务')
    await wrapper.findAll('input').at(-1)!.setValue('材料分析流程')
    await wrapper.findAll('button').find((button) => button.text().includes('继续'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('添加 Agent 节点')
    await wrapper.findAll('.select-stub').at(-1)!.trigger('click')
    await wrapper.findAll('button').find((button) => button.text().includes('添加到流程'))!.trigger('click')
    await wrapper.findAll('button').find((button) => button.text().includes('继续'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('准备保存')
    await wrapper.findAll('button').find((button) => button.text().includes('保存 Workflow'))!.trigger('click')
    await flushPromises()

    expect(createWorkflow).toHaveBeenCalledWith(expect.objectContaining({
      team_id: 'team-a',
      name: '材料分析流程',
      nodes: [expect.objectContaining({ agent_id: 'manager-a', depends_on: [] })],
    }))
    wrapper.unmount()
  })
})
