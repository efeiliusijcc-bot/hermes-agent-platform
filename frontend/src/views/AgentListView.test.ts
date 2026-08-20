import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('naive-ui', () => ({
  NIcon: { template: '<span><slot /></span>' },
  useDialog: () => ({ warning: vi.fn() }),
  useMessage: () => ({ success: vi.fn(), error: vi.fn() }),
}))

import { platformApi } from '@/api/platform'
import router from '@/router'
import type { ConsoleAgentSummary } from '@/types/api'
import AgentListView from './AgentListView.vue'

function summary(id: string): ConsoleAgentSummary {
  return {
    id,
    name: `Agent ${id}`,
    description: '测试 Agent',
    agent_type: 'worker',
    role: '分析员',
    model: 'deepseek-test',
    status: 'active',
    runtime_type: 'deepseek',
    current_version_id: 'version-id',
    version: 'v1',
    skills: [{ id: 'skill-a', name: 'Skill A' }],
    mcps: [{ id: 'mcp-a', name: 'MCP A' }],
    preflight_state: null,
    updated_at: '2026-08-20T00:00:00Z',
  }
}

describe('AgentListView summary loading', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders all cards from one BFF request without per-Agent binding calls', async () => {
    await router.push('/agents')
    await router.isReady()
    vi.spyOn(platformApi, 'listConsoleAgents').mockResolvedValue([summary('a'), summary('b')])
    const skills = vi.spyOn(platformApi, 'listAgentSkills')
    const mcps = vi.spyOn(platformApi, 'listAgentMCPServers')
    const versions = vi.spyOn(platformApi, 'listAgentVersions')

    const wrapper = mount(AgentListView, {
      global: {
        plugins: [router],
        stubs: {
          PageHeader: { template: '<header><slot name="actions" /></header>' },
          StatusTag: true,
          NButton: { template: '<button><slot name="icon" /><slot /></button>' },
          NInput: { template: '<input />' },
          NTag: { template: '<span><slot /></span>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.findAll('.agent-card')).toHaveLength(2)
    expect(skills).not.toHaveBeenCalled()
    expect(mcps).not.toHaveBeenCalled()
    expect(versions).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
