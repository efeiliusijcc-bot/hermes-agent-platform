import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { platformApi } from '@/api/platform'
import { useAgentStore } from './agents'

const agent = {
  id: 'knowledge-agent',
  name: '知识 Agent',
  description: null,
  agent_type: 'worker' as const,
  parent_agent_id: null,
  role: '知识分析专家',
  system_prompt: '只根据可靠数据回答',
  model_config: {},
  model: 'qwen-300b',
  prompt_template: '{{input}}',
  model_adapter: 'qwen' as const,
  runtime_type: 'hermes' as const,
  runtime_config: {},
  api_enabled: false,
  status: 'active' as const,
  response_mode: 'sync' as const,
  input_schema: {},
  output_schema: {},
  current_version_id: null,
  created_at: '2026-08-12T00:00:00Z',
  updated_at: '2026-08-12T00:00:00Z',
}

describe('agent creation workflow', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('creates first and reports partial binding failures explicitly', async () => {
    vi.spyOn(platformApi, 'createAgent').mockResolvedValue(agent)
    vi.spyOn(platformApi, 'bindAgentSkill').mockResolvedValue()
    vi.spyOn(platformApi, 'bindAgentMCPServer').mockRejectedValue(new Error('gateway rejected'))

    const store = useAgentStore()
    const result = await store.createAgentWorkflow({
      agent: {
        id: agent.id,
        name: agent.name,
        description: null,
        role: agent.role,
        system_prompt: agent.system_prompt,
        model_config: {},
        status: 'active',
      },
      skillIds: ['knowledge-analysis'],
      mcpIds: ['database-mcp'],
    })

    expect(platformApi.createAgent).toHaveBeenCalledOnce()
    expect(platformApi.bindAgentSkill).toHaveBeenCalledWith(agent.id, 'knowledge-analysis')
    expect(platformApi.bindAgentMCPServer).toHaveBeenCalledWith(agent.id, 'database-mcp')
    expect(result.agent.id).toBe(agent.id)
    expect(result.bindingErrors).toEqual(['MCP database-mcp: gateway rejected'])
  })
})
