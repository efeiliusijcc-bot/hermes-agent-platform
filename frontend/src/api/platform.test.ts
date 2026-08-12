import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './client'
import { platformApi } from './platform'

describe('platformApi contract', () => {
  beforeEach(() => vi.restoreAllMocks())

  it('uses the actual MCP registry endpoint', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    await platformApi.listMCPServers()
    expect(get).toHaveBeenCalledWith('/api/mcp-servers')
  })

  it('sends agent creation fields without embedding bindings', async () => {
    const payload = {
      id: 'knowledge-agent',
      name: '知识 Agent',
      description: null,
      role: '知识分析专家',
      system_prompt: '只根据可靠数据回答',
      model_config: { model: 'qwen-300b' },
      status: 'active' as const,
    }
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: payload })
    await platformApi.createAgent(payload)
    expect(post).toHaveBeenCalledWith('/api/agents', payload)
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty('skills')
    expect(post.mock.calls[0]?.[1]).not.toHaveProperty('mcps')
  })

  it('uses independent binding endpoints and run session payload', async () => {
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({
      data: { execution_id: 'run-1', agent_id: 'agent-a', session_id: 'review', status: 'succeeded', output: 'ok', hermes_run_id: null },
    })

    await platformApi.bindAgentSkill('agent-a', 'knowledge-analysis')
    await platformApi.bindAgentMCPServer('agent-a', 'database-mcp')
    await platformApi.runAgent('agent-a', { input: '分析数据', session_id: 'review' })

    expect(put).toHaveBeenNthCalledWith(1, '/api/agents/agent-a/skills/knowledge-analysis')
    expect(put).toHaveBeenNthCalledWith(2, '/api/agents/agent-a/mcp-servers/database-mcp')
    expect(post).toHaveBeenCalledWith('/api/agents/agent-a/run', { input: '分析数据', session_id: 'review' })
  })
})
