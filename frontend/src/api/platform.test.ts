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

  it('updates the persisted prompt builder and model adapter configuration', async () => {
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })
    const payload = {
      system_prompt: 'Use verified data.',
      model: 'qwen-32b',
      prompt_template: 'Analyze {{topic}}.',
      model_adapter: 'qwen' as const,
      model_config: { temperature: 0.1 },
    }
    await platformApi.updateAgentConfiguration('agent-a', payload)
    expect(put).toHaveBeenCalledWith('/api/agents/agent-a/configuration', payload)
  })

  it('uses the Runtime registry and health endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { status: 'online' } })
    await platformApi.listRuntimes('pi')
    await platformApi.checkRuntime('runtime a')
    expect(get).toHaveBeenCalledWith('/api/runtimes', { params: { type: 'pi' } })
    expect(post).toHaveBeenCalledWith('/api/runtimes/runtime%20a/health')
  })

  it('uses the Phase 3 task, session and artifact endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'task-1' } })

    await platformApi.submitAgentTask('agent-a', { input: '生成报告', session_id: 'phase3', priority: 7 })
    await platformApi.listTasks('agent-a')
    await platformApi.listSessions('agent-a')
    await platformApi.listArtifacts('agent-a')

    expect(post).toHaveBeenCalledWith('/api/agents/agent-a/tasks', { input: '生成报告', session_id: 'phase3', priority: 7 })
    expect(get).toHaveBeenNthCalledWith(1, '/api/tasks', { params: { agent_id: 'agent-a' } })
    expect(get).toHaveBeenNthCalledWith(2, '/api/sessions', { params: { agent_id: 'agent-a' } })
    expect(get).toHaveBeenNthCalledWith(3, '/api/artifacts', { params: { agent_id: 'agent-a' } })
  })

  it('uses the Multi-Agent Team, Workflow, Run and approval endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'run-1' } })
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: { id: 'team-1' } })

    await platformApi.listAgentTeams()
    await platformApi.upsertTeamMember('team a', 'agent a', { role: '分析', priority: 70 })
    await platformApi.listWorkflows('team a')
    await platformApi.runWorkflow('workflow a', { input: '分析行业', session_id: 'multi-1', priority: 8 })
    await platformApi.listWorkflowRunTasks('run a')
    await platformApi.reviewHumanTask('task a', true, '通过')

    expect(get).toHaveBeenNthCalledWith(1, '/api/agent-teams')
    expect(put).toHaveBeenCalledWith('/api/agent-teams/team%20a/members/agent%20a', { role: '分析', priority: 70 })
    expect(get).toHaveBeenNthCalledWith(2, '/api/workflows', { params: { team_id: 'team a' } })
    expect(post).toHaveBeenNthCalledWith(1, '/api/workflows/workflow%20a/runs', {
      input: '分析行业', session_id: 'multi-1', priority: 8,
    })
    expect(get).toHaveBeenNthCalledWith(3, '/api/workflow-runs/run%20a/tasks')
    expect(post).toHaveBeenNthCalledWith(2, '/api/tasks/task%20a/approval', { approved: true, note: '通过' })
  })

  it('uses execution history, independent trace detail and retry endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: { items: [], total: 0, limit: 25, offset: 0 } })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: { id: 'task-2' } })

    await platformApi.listExecutions({ agent_id: 'agent a', status: 'failed', search: '年度报告', limit: 25 })
    await platformApi.getExecution('execution a')
    await platformApi.getExecutionTrace('execution a')
    await platformApi.retryExecution('execution a', { priority: 8, session_id: 'retry-1' })

    expect(get).toHaveBeenNthCalledWith(1, '/api/executions', {
      params: { agent_id: 'agent a', status: 'failed', search: '年度报告', limit: 25 },
    })
    expect(get).toHaveBeenNthCalledWith(2, '/api/executions/execution%20a')
    expect(get).toHaveBeenNthCalledWith(3, '/api/executions/execution%20a/trace')
    expect(post).toHaveBeenCalledWith('/api/executions/execution%20a/retry', {
      priority: 8,
      session_id: 'retry-1',
    })
  })

  it('uses Phase 3.1 Schema and API version endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })
    const put = vi.spyOn(apiClient, 'put').mockResolvedValue({ data: {} })
    const remove = vi.spyOn(apiClient, 'delete').mockResolvedValue({ data: {} })
    await platformApi.listSchemaVersions('agent-a')
    await platformApi.createSchemaVersion('agent-a', { version: 'v2', input_schema: {}, output_schema: {} })
    await platformApi.updateSchemaVersion('agent-a', 'v2', { input_schema: { type: 'object' }, output_schema: {} })
    await platformApi.updateSchemaVersionStatus('agent-a', 'v2', 'testing')
    await platformApi.listAPIVersions('agent-a')
    await platformApi.createAPIVersion('agent-a', { api_version: 'v2', schema_version: 'v2' })
    await platformApi.updateAPIVersionBinding('agent-a', 'v2', 'v2')
    await platformApi.updateAPIVersionStatus('agent-a', 'v2', 'testing')
    await platformApi.deleteAPIVersion('agent-a', 'v2')
    await platformApi.deleteSchemaVersion('agent-a', 'v2')
    expect(get).toHaveBeenNthCalledWith(1, '/api/agents/agent-a/schema-versions')
    expect(get).toHaveBeenNthCalledWith(2, '/api/agents/agent-a/api-versions')
    expect(post).toHaveBeenNthCalledWith(1, '/api/agents/agent-a/schema-versions', { version: 'v2', input_schema: {}, output_schema: {} })
    expect(post).toHaveBeenNthCalledWith(2, '/api/agents/agent-a/api-versions', { api_version: 'v2', schema_version: 'v2' })
    expect(put).toHaveBeenNthCalledWith(1, '/api/agents/agent-a/schema-versions/v2', { input_schema: { type: 'object' }, output_schema: {} })
    expect(put).toHaveBeenNthCalledWith(2, '/api/agents/agent-a/schema-versions/v2/status', { status: 'testing' })
    expect(put).toHaveBeenNthCalledWith(3, '/api/agents/agent-a/api-versions/v2/binding', { schema_version: 'v2' })
    expect(put).toHaveBeenNthCalledWith(4, '/api/agents/agent-a/api-versions/v2/status', { status: 'testing' })
    expect(remove).toHaveBeenNthCalledWith(1, '/api/agents/agent-a/api-versions/v2')
    expect(remove).toHaveBeenNthCalledWith(2, '/api/agents/agent-a/schema-versions/v2')
  })

  it('uses the Phase 4 lifecycle, health, version, publish and rollback endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })

    await platformApi.updateAgentLifecycle('agent a', 'inactive')
    await platformApi.getAgentHealth('agent a')
    await platformApi.listAgentVersions('agent a')
    await platformApi.createAgentVersion('agent a', { version: 'v2', notes: 'candidate' })
    await platformApi.updateAgentVersion('agent a', 'v2', { notes: 'edited' })
    await platformApi.updateAgentVersionStatus('agent a', 'v2', 'testing')
    await platformApi.runAgentVersion('agent a', 'v2', { input: 'validate', session_id: 'version-v2' })
    await platformApi.publishAgent('agent a', { version: 'v2', notes: 'release' })
    await platformApi.rollbackAgent('agent a', 'v1 stable')

    expect(patch).toHaveBeenCalledWith('/api/agents/agent%20a/lifecycle', { status: 'inactive' })
    expect(get).toHaveBeenNthCalledWith(1, '/api/agents/agent%20a/health')
    expect(get).toHaveBeenNthCalledWith(2, '/api/agents/agent%20a/versions')
    expect(post).toHaveBeenNthCalledWith(1, '/api/agents/agent%20a/versions', { version: 'v2', notes: 'candidate' })
    expect(patch).toHaveBeenNthCalledWith(2, '/api/agents/agent%20a/versions/v2', { notes: 'edited' })
    expect(patch).toHaveBeenNthCalledWith(3, '/api/agents/agent%20a/versions/v2/status', { status: 'testing' })
    expect(post).toHaveBeenNthCalledWith(2, '/api/agents/agent%20a/versions/v2/run', { input: 'validate', session_id: 'version-v2' })
    expect(post).toHaveBeenNthCalledWith(3, '/api/agents/agent%20a/publish', { version: 'v2', notes: 'release' })
    expect(post).toHaveBeenNthCalledWith(4, '/api/agents/agent%20a/versions/v1%20stable/rollback')
  })

  it('uses Phase 4 API client, one-time key and agent binding endpoints', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    const post = vi.spyOn(apiClient, 'post').mockResolvedValue({ data: {} })
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })
    const remove = vi.spyOn(apiClient, 'delete').mockResolvedValue({ data: {} })

    await platformApi.listAPIClients()
    await platformApi.getAPIClient('client a')
    await platformApi.createAPIClient({ name: 'ERP', owner: 'ops', rate_limit_per_minute: 120 })
    await platformApi.updateAPIClient('client a', { status: 'suspended', rate_limit_per_minute: 30 })
    await platformApi.listAPIKeys('client a')
    await platformApi.createAPIKey('client a', { name: 'prod', expires_at: null })
    await platformApi.updateAPIKey('client a', 'key 1', { status: 'revoked' })
    await platformApi.revokeAPIKey('client a', 'key 2')
    await platformApi.listAPIClientBindings('client a')
    await platformApi.bindAPIClientAgent('client a', 'agent a')
    await platformApi.unbindAPIClientAgent('client a', 'agent a')
    await platformApi.deleteAPIClient('client a')

    expect(get).toHaveBeenNthCalledWith(1, '/api/api-clients')
    expect(get).toHaveBeenNthCalledWith(2, '/api/api-clients/client%20a')
    expect(get).toHaveBeenNthCalledWith(3, '/api/api-clients/client%20a/keys')
    expect(get).toHaveBeenNthCalledWith(4, '/api/api-clients/client%20a/agents')
    expect(post).toHaveBeenNthCalledWith(1, '/api/api-clients', {
      name: 'ERP',
      owner: 'ops',
      rate_limit_per_minute: 120,
    })
    expect(post).toHaveBeenNthCalledWith(2, '/api/api-clients/client%20a/keys', { name: 'prod', expires_at: null })
    expect(post).toHaveBeenNthCalledWith(3, '/api/api-clients/client%20a/agents', { agent_id: 'agent a', permission: 'invoke' })
    expect(patch).toHaveBeenNthCalledWith(1, '/api/api-clients/client%20a', {
      status: 'suspended',
      rate_limit_per_minute: 30,
    })
    expect(patch).toHaveBeenNthCalledWith(2, '/api/api-clients/client%20a/keys/key%201', { status: 'revoked' })
    expect(remove).toHaveBeenNthCalledWith(1, '/api/api-clients/client%20a/keys/key%202')
    expect(remove).toHaveBeenNthCalledWith(2, '/api/api-clients/client%20a/agents/agent%20a')
    expect(remove).toHaveBeenNthCalledWith(3, '/api/api-clients/client%20a')
  })

  it('uses authoritative metrics and audit endpoints without client-side synthesis', async () => {
    const get = vi.spyOn(apiClient, 'get').mockResolvedValue({ data: [] })
    await platformApi.getMetricsSummary()
    await platformApi.listAgentMetrics()
    await platformApi.listAuditLogs({ agent_id: 'agent-a', status: 'failed', limit: 25 })
    expect(get).toHaveBeenNthCalledWith(1, '/api/metrics/summary')
    expect(get).toHaveBeenNthCalledWith(2, '/api/metrics/agents')
    expect(get).toHaveBeenNthCalledWith(3, '/api/audit-logs', {
      params: { agent_id: 'agent-a', status: 'failed', limit: 25 },
    })
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
