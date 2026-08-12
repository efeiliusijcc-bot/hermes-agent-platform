import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiClient } from './client'
import { consumeSSE, platformApi } from './platform'

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
      input_schema: {},
      output_schema: {},
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
    expect(post).toHaveBeenCalledWith('/api/agents/agent-a/run?response_mode=sync', { input: '分析数据', session_id: 'review' })
  })

  it('updates the persisted default response mode', async () => {
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })
    await platformApi.updateAgentResponseMode('agent-a', 'stream')
    expect(put).toHaveBeenCalledWith('/api/agents/agent-a/response-mode', { response_mode: 'stream' })
  })

  it('parses fragmented SSE events without losing token boundaries', async () => {
    const encoder = new TextEncoder()
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('event: token\ndata: {"event":"token","text":"分析"}\n'))
        controller.enqueue(encoder.encode('\nevent: end\ndata: {"event":"end","status":"success"}\n\n'))
        controller.close()
      },
    })
    const events: Array<Record<string, unknown>> = []
    await consumeSSE(body, (event) => events.push(event))
    expect(events).toEqual([
      { event: 'token', text: '分析' },
      { event: 'end', status: 'success' },
    ])
  })

  it('requests the internal stream endpoint with an explicit mode override', async () => {
    const encoder = new TextEncoder()
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(encoder.encode('event: end\ndata: {"event":"end","status":"success"}\n\n'))
          controller.close()
        },
      }),
      { status: 200, headers: { 'content-type': 'text/event-stream' } },
    ))
    const events: Array<Record<string, unknown>> = []
    await platformApi.streamAgent('agent-a', { input: '分析', session_id: 'review' }, (event) => events.push(event))
    expect(fetchMock).toHaveBeenCalledWith('/api/agents/agent-a/run?response_mode=stream', expect.objectContaining({
      method: 'POST',
      body: JSON.stringify({ input: '分析', session_id: 'review' }),
    }))
    expect(events).toEqual([{ event: 'end', status: 'success' }])
  })
})
