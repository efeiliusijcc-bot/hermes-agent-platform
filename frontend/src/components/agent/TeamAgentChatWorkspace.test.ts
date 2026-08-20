import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('naive-ui', () => ({ NIcon: { template: '<span><slot /></span>' } }))

import { platformApi } from '@/api/platform'
import router from '@/router'
import type {
  AgentTeam,
  TeamConversationList,
  Workflow,
  WorkflowRun,
  WorkflowRunList,
} from '@/types/api'
import TeamAgentChatWorkspace from './TeamAgentChatWorkspace.vue'

const team: AgentTeam = {
  id: 'team-a',
  name: '内网编报 Team',
  description: '使用内网材料编写报告',
  owner_agent_id: 'manager-a',
  status: 'active',
  members: [{ agent_id: 'manager-a', agent_name: '编报 Manager', agent_type: 'manager', runtime_type: 'hermes', role: 'manager', priority: 100 }],
  created_at: '2026-08-20T01:00:00Z',
  updated_at: '2026-08-20T01:00:00Z',
}

const workflow: Workflow = {
  id: 'workflow-a',
  team_id: team.id,
  name: '审核编报流程',
  description: null,
  status: 'active',
  nodes: [],
  created_at: '2026-08-20T01:00:00Z',
  updated_at: '2026-08-20T01:00:00Z',
}

function run(overrides: Partial<WorkflowRun> = {}): WorkflowRun {
  return {
    id: 'run-a',
    workflow_id: null,
    team_id: team.id,
    session_id: 'team-chat-a',
    status: 'succeeded',
    input: '生成第一版编报',
    output: '第一版已经完成',
    error: null,
    created_at: '2026-08-20T01:00:00Z',
    started_at: '2026-08-20T01:00:01Z',
    finished_at: '2026-08-20T01:01:00Z',
    ...overrides,
  }
}

function conversations(): TeamConversationList {
  return {
    items: [{
      team_id: team.id,
      session_id: 'team-chat-a',
      workflow_id: null,
      workflow_name: null,
      title: '生成第一版编报',
      latest_run_id: 'run-a',
      latest_status: 'succeeded',
      run_count: 1,
      created_at: '2026-08-20T01:00:00Z',
      updated_at: '2026-08-20T01:01:00Z',
    }],
    total: 1,
    limit: 50,
    offset: 0,
  }
}

function runList(items = [run()]): WorkflowRunList {
  return { items, total: items.length, limit: 50, offset: 0 }
}

function mountWorkspace() {
  return mount(TeamAgentChatWorkspace, {
    global: {
      plugins: [router],
      stubs: {
        PageHeader: { template: '<header><slot name="actions" /></header>' },
        StatusTag: { props: ['status'], template: '<span>{{ status }}</span>' },
        TeamChatRun: { props: ['run'], template: '<article class="run-stub">{{ run.input }} / {{ run.output }}</article>' },
        NAlert: { template: '<div><slot /></div>' },
        NButton: {
          props: ['disabled', 'loading'],
          emits: ['click'],
          template: '<button :disabled="disabled" @click="$emit(\'click\')"><slot name="icon" /><slot /></button>',
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
        NSelect: {
          props: ['value', 'options', 'disabled'],
          emits: ['update:value'],
          template: '<select :value="value" :disabled="disabled" @change="$emit(\'update:value\', $event.target.value)"><option v-for="item in options" :key="item.value" :value="item.value">{{ item.label }}</option></select>',
        },
      },
    },
  })
}

describe('TeamAgentChatWorkspace', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('loads the URL-selected Team conversation and sends the next message in the same session', async () => {
    vi.spyOn(platformApi, 'listAgentTeams').mockResolvedValue([team])
    vi.spyOn(platformApi, 'listWorkflows').mockResolvedValue([workflow])
    vi.spyOn(platformApi, 'listTeamConversations').mockResolvedValue(conversations())
    vi.spyOn(platformApi, 'listTeamConversationRuns').mockResolvedValue(runList())
    const send = vi.spyOn(platformApi, 'sendTeamConversationMessage').mockResolvedValue(run({
      id: 'run-b',
      input: '继续完善摘要',
      output: null,
      status: 'running',
      finished_at: null,
    }))
    await router.push('/chat?mode=team&team=team-a&session=team-chat-a&workflow=direct')
    const wrapper = mountWorkspace()
    await flushPromises()

    expect(platformApi.listTeamConversationRuns).toHaveBeenCalledWith('team-a', 'team-chat-a', { limit: 50, offset: 0 })
    expect(wrapper.text()).toContain('生成第一版编报 / 第一版已经完成')

    await wrapper.get('textarea').setValue('继续完善摘要')
    await wrapper.get('button[aria-label="发送团队消息"]').trigger('click')
    await flushPromises()

    expect(send).toHaveBeenCalledWith('team-a', 'team-chat-a', {
      input: '继续完善摘要',
      workflow_id: null,
      priority: 5,
      parameters: {},
    })
    expect(wrapper.text()).toContain('继续完善摘要')
    expect(wrapper.get('textarea').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('starts a new conversation when an existing conversation changes Workflow', async () => {
    vi.stubGlobal('crypto', { randomUUID: () => 'new-session' })
    vi.spyOn(platformApi, 'listAgentTeams').mockResolvedValue([team])
    vi.spyOn(platformApi, 'listWorkflows').mockResolvedValue([workflow])
    vi.spyOn(platformApi, 'listTeamConversations').mockResolvedValue(conversations())
    vi.spyOn(platformApi, 'listTeamConversationRuns').mockResolvedValue(runList())
    await router.push('/chat?mode=team&team=team-a&session=team-chat-a&workflow=direct')
    const wrapper = mountWorkspace()
    await flushPromises()

    await wrapper.get('select').setValue('workflow-a')
    await flushPromises()

    expect(router.currentRoute.value.query.session).toBe('team-chat-new-session')
    expect(router.currentRoute.value.query.workflow).toBe('workflow-a')
    expect(wrapper.text()).toContain('开始新的 Team 对话')
    wrapper.unmount()
  })
})
