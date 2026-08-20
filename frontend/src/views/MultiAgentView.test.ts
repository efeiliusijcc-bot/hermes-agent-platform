import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { platformApi } from '@/api/platform'
import router from '@/router'
import type { AgentTeam, WorkflowRun } from '@/types/api'
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
          NInput: { props: ['value'], template: '<input />' },
          NInputNumber: { props: ['value'], template: '<input />' },
          NCheckbox: { props: ['checked'], template: '<input type="checkbox" />' },
          NEmpty: { template: '<div />' },
          NSelect: {
            props: ['value'],
            emits: ['update:value'],
            template: '<button class="select-stub" @click="$emit(\'update:value\', \'team-b\')">{{ value }}</button>',
          },
        },
      },
    })
    await flushPromises()

    expect(listRuns).toHaveBeenCalledWith({ team_id: 'team-a' })
    expect(wrapper.find('.workspace-stub').text()).toContain('run-team-a-newest')

    await wrapper.findAll('.select-stub')[0].trigger('click')
    await flushPromises()

    expect(listRuns).toHaveBeenCalledWith({ team_id: 'team-b' })
    expect(wrapper.find('.workspace-stub').text()).toContain('run-team-b')
    expect(wrapper.find('.workspace-stub').text()).not.toContain('run-team-a')
    wrapper.unmount()
  })
})
