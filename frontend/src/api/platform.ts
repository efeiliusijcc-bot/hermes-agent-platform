import { apiClient } from './client'
import type {
  Agent,
  AgentSession,
  AgentTask,
  AgentTaskSubmitPayload,
  AgentWorkspace,
  Artifact,
  AgentCreatePayload,
  AgentRunPayload,
  AgentRunResponse,
  AgentStreamEvent,
  AgentSchemaVersion,
  AgentAPIVersion,
  AgentAPIClientBinding,
  AgentClientPermission,
  AgentHealth,
  AgentLifecycleStatus,
  AgentMetric,
  LifecycleStatus,
  AgentVersion,
  APIClient,
  APIKey,
  APIKeySecret,
  APIKeyStatus,
  AuditLog,
  ExecutionLog,
  ExecutionDetail,
  ExecutionTrace,
  ExecutionList,
  HealthStatus,
  KnowledgeSource,
  MCPServer,
  MCPServerCreatePayload,
  MCPServerTestResult,
  ResponseMode,
  ModelAdapterName,
  MetricsSummary,
  Skill,
} from '@/types/api'

export const platformApi = {
  async health(): Promise<HealthStatus> {
    const { data } = await apiClient.get<HealthStatus>('/health')
    return data
  },

  async listAgents(): Promise<Agent[]> {
    const { data } = await apiClient.get<Agent[]>('/api/agents')
    return data
  },

  async getAgent(agentId: string): Promise<Agent> {
    const { data } = await apiClient.get<Agent>(`/api/agents/${encodeURIComponent(agentId)}`)
    return data
  },

  async createAgent(payload: AgentCreatePayload): Promise<Agent> {
    const { data } = await apiClient.post<Agent>('/api/agents', payload)
    return data
  },

  async deleteAgent(agentId: string): Promise<void> {
    await apiClient.delete(`/api/agents/${encodeURIComponent(agentId)}`)
  },

  async updateAgentLifecycle(agentId: string, status: AgentLifecycleStatus): Promise<Agent> {
    const { data } = await apiClient.patch<Agent>(
      `/api/agents/${encodeURIComponent(agentId)}/lifecycle`,
      { status },
    )
    return data
  },

  async getAgentHealth(agentId: string): Promise<AgentHealth> {
    const { data } = await apiClient.get<AgentHealth>(
      `/api/agents/${encodeURIComponent(agentId)}/health`,
    )
    return data
  },

  async listAgentVersions(agentId: string): Promise<AgentVersion[]> {
    const { data } = await apiClient.get<AgentVersion[]>(
      `/api/agents/${encodeURIComponent(agentId)}/versions`,
    )
    return data
  },

  async createAgentVersion(
    agentId: string,
    payload: { version?: string; notes?: string; created_by?: string },
  ): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/versions`,
      payload,
    )
    return data
  },

  async updateAgentVersion(
    agentId: string,
    version: string,
    payload: { snapshot?: AgentVersion['snapshot']; notes?: string | null },
  ): Promise<AgentVersion> {
    const { data } = await apiClient.patch<AgentVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/versions/${encodeURIComponent(version)}`,
      payload,
    )
    return data
  },

  async updateAgentVersionStatus(
    agentId: string,
    version: string,
    status: 'development' | 'testing' | 'release_candidate',
  ): Promise<AgentVersion> {
    const { data } = await apiClient.patch<AgentVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/versions/${encodeURIComponent(version)}/status`,
      { status },
    )
    return data
  },

  async runAgentVersion(
    agentId: string,
    version: string,
    payload: AgentRunPayload,
  ): Promise<AgentRunResponse> {
    const { data } = await apiClient.post<AgentRunResponse>(
      `/api/agents/${encodeURIComponent(agentId)}/versions/${encodeURIComponent(version)}/run`,
      payload,
    )
    return data
  },

  async publishAgent(
    agentId: string,
    payload: { version?: string; notes?: string },
  ): Promise<AgentVersion> {
    const { data } = await apiClient.post<AgentVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/publish`,
      payload,
    )
    return data
  },

  async rollbackAgent(agentId: string, version: string): Promise<Agent> {
    const { data } = await apiClient.post<Agent>(
      `/api/agents/${encodeURIComponent(agentId)}/versions/${encodeURIComponent(version)}/rollback`,
    )
    return data
  },

  async runAgent(agentId: string, payload: AgentRunPayload): Promise<AgentRunResponse> {
    const { data } = await apiClient.post<AgentRunResponse>(
      `/api/agents/${encodeURIComponent(agentId)}/run?response_mode=sync`,
      payload,
    )
    return data
  },

  async streamAgent(
    agentId: string,
    payload: AgentRunPayload,
    onEvent: (event: AgentStreamEvent) => void,
  ): Promise<void> {
    const response = await fetch(
      `/api/agents/${encodeURIComponent(agentId)}/run?response_mode=stream`,
      {
        method: 'POST',
        headers: { Accept: 'text/event-stream', 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      },
    )
    if (!response.ok) throw new Error(await readFetchError(response))
    if (!response.body) throw new Error('后端未返回流式响应体')
    await consumeSSE(response.body, onEvent)
  },

  async listAgentRuns(agentId: string): Promise<ExecutionLog[]> {
    const { data } = await apiClient.get<ExecutionLog[]>(
      `/api/agents/${encodeURIComponent(agentId)}/runs`,
    )
    return data
  },

  async listExecutions(params: {
    agent_id?: string
    status?: string
    search?: string
    started_from?: string
    started_to?: string
    limit?: number
    offset?: number
  } = {}): Promise<ExecutionList> {
    const { data } = await apiClient.get<ExecutionList>('/api/executions', { params })
    return data
  },

  async getExecution(executionId: string): Promise<ExecutionDetail> {
    const { data } = await apiClient.get<ExecutionDetail>(
      `/api/executions/${encodeURIComponent(executionId)}`,
    )
    return data
  },

  async getExecutionTrace(executionId: string): Promise<ExecutionTrace> {
    const { data } = await apiClient.get<ExecutionTrace>(
      `/api/executions/${encodeURIComponent(executionId)}/trace`,
    )
    return data
  },

  async retryExecution(
    executionId: string,
    payload: { session_id?: string; priority?: number } = {},
  ): Promise<AgentTask> {
    const { data } = await apiClient.post<AgentTask>(
      `/api/executions/${encodeURIComponent(executionId)}/retry`,
      payload,
    )
    return data
  },

  async submitAgentTask(agentId: string, payload: AgentTaskSubmitPayload): Promise<AgentTask> {
    const { data } = await apiClient.post<AgentTask>(
      `/api/agents/${encodeURIComponent(agentId)}/tasks`,
      payload,
    )
    return data
  },

  async listTasks(agentId?: string): Promise<AgentTask[]> {
    const { data } = await apiClient.get<AgentTask[]>('/api/tasks', { params: { agent_id: agentId } })
    return data
  },

  async getTask(taskId: string): Promise<AgentTask> {
    const { data } = await apiClient.get<AgentTask>(`/api/tasks/${encodeURIComponent(taskId)}`)
    return data
  },

  async cancelTask(taskId: string): Promise<void> {
    await apiClient.delete(`/api/tasks/${encodeURIComponent(taskId)}`)
  },

  async listSessions(agentId?: string): Promise<AgentSession[]> {
    const { data } = await apiClient.get<AgentSession[]>('/api/sessions', { params: { agent_id: agentId } })
    return data
  },

  async listArtifacts(agentId?: string): Promise<Artifact[]> {
    const { data } = await apiClient.get<Artifact[]>('/api/artifacts', { params: { agent_id: agentId } })
    return data
  },

  async getWorkspace(agentId: string): Promise<AgentWorkspace> {
    const { data } = await apiClient.get<AgentWorkspace>(`/api/agents/${encodeURIComponent(agentId)}/workspace`)
    return data
  },

  artifactDownloadUrl(artifactId: string): string {
    return `/api/artifacts/${encodeURIComponent(artifactId)}/download`
  },

  async listSkills(): Promise<Skill[]> {
    const { data } = await apiClient.get<Skill[]>('/api/skills')
    return data
  },

  async uploadSkill(file: File): Promise<Skill> {
    const form = new FormData()
    form.append('file', file)
    const { data } = await apiClient.post<Skill>('/api/skills/upload', form)
    return data
  },

  async deleteSkill(skillId: string): Promise<void> {
    await apiClient.delete(`/api/skills/${encodeURIComponent(skillId)}`)
  },

  async listAgentSkills(agentId: string): Promise<Skill[]> {
    const { data } = await apiClient.get<Skill[]>(
      `/api/agents/${encodeURIComponent(agentId)}/skills`,
    )
    return data
  },

  async bindAgentSkill(agentId: string, skillId: string): Promise<void> {
    await apiClient.put(
      `/api/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillId)}`,
    )
  },

  async unbindAgentSkill(agentId: string, skillId: string): Promise<void> {
    await apiClient.delete(
      `/api/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillId)}`,
    )
  },

  async listMCPServers(): Promise<MCPServer[]> {
    const { data } = await apiClient.get<MCPServer[]>('/api/mcp-servers')
    return data
  },

  async createMCPServer(payload: MCPServerCreatePayload): Promise<MCPServer> {
    const { data } = await apiClient.post<MCPServer>('/api/mcp-servers', payload)
    return data
  },

  async updateMCPServer(mcpId: string, payload: Omit<MCPServerCreatePayload, 'id'>): Promise<MCPServer> {
    const { data } = await apiClient.put<MCPServer>(
      `/api/mcp-servers/${encodeURIComponent(mcpId)}`,
      payload,
    )
    return data
  },

  async testMCPServer(mcpId: string): Promise<MCPServerTestResult> {
    const { data } = await apiClient.post<MCPServerTestResult>(
      `/api/mcp-servers/${encodeURIComponent(mcpId)}/test`,
    )
    return data
  },

  async deleteMCPServer(mcpId: string): Promise<void> {
    await apiClient.delete(`/api/mcp-servers/${encodeURIComponent(mcpId)}`)
  },

  async updateAgentSchema(
    agentId: string,
    inputSchema: Record<string, unknown>,
    outputSchema: Record<string, unknown>,
  ): Promise<Agent> {
    const { data } = await apiClient.put<Agent>(`/api/agents/${encodeURIComponent(agentId)}/schema`, {
      input_schema: inputSchema,
      output_schema: outputSchema,
    })
    return data
  },

  async updateAgentResponseMode(agentId: string, responseMode: ResponseMode): Promise<Agent> {
    const { data } = await apiClient.put<Agent>(
      `/api/agents/${encodeURIComponent(agentId)}/response-mode`,
      { response_mode: responseMode },
    )
    return data
  },

  async updateAgentConfiguration(
    agentId: string,
    payload: {
      system_prompt: string
      model: string
      prompt_template: string
      model_adapter: ModelAdapterName
      model_config: Record<string, unknown>
    },
  ): Promise<Agent> {
    const { data } = await apiClient.put<Agent>(
      `/api/agents/${encodeURIComponent(agentId)}/configuration`,
      payload,
    )
    return data
  },

  async listAPIClients(): Promise<APIClient[]> {
    const { data } = await apiClient.get<APIClient[]>('/api/api-clients')
    return data
  },

  async getAPIClient(clientId: string): Promise<APIClient> {
    const { data } = await apiClient.get<APIClient>(
      `/api/api-clients/${encodeURIComponent(clientId)}`,
    )
    return data
  },

  async createAPIClient(payload: {
    name: string
    owner: string
    rate_limit_per_minute: number
  }): Promise<APIClient> {
    const { data } = await apiClient.post<APIClient>('/api/api-clients', payload)
    return data
  },

  async updateAPIClient(
    clientId: string,
    payload: Partial<Pick<APIClient, 'name' | 'owner' | 'status' | 'rate_limit_per_minute'>>,
  ): Promise<APIClient> {
    const { data } = await apiClient.patch<APIClient>(
      `/api/api-clients/${encodeURIComponent(clientId)}`,
      payload,
    )
    return data
  },

  async deleteAPIClient(clientId: string): Promise<void> {
    await apiClient.delete(`/api/api-clients/${encodeURIComponent(clientId)}`)
  },

  async listAPIKeys(clientId: string): Promise<APIKey[]> {
    const { data } = await apiClient.get<APIKey[]>(
      `/api/api-clients/${encodeURIComponent(clientId)}/keys`,
    )
    return data
  },

  async createAPIKey(
    clientId: string,
    payload: { name: string; expires_at?: string | null },
  ): Promise<APIKeySecret> {
    const { data } = await apiClient.post<APIKeySecret>(
      `/api/api-clients/${encodeURIComponent(clientId)}/keys`,
      payload,
    )
    return data
  },

  async updateAPIKey(
    clientId: string,
    keyId: string,
    payload: { status: APIKeyStatus },
  ): Promise<APIKey> {
    const { data } = await apiClient.patch<APIKey>(
      `/api/api-clients/${encodeURIComponent(clientId)}/keys/${encodeURIComponent(keyId)}`,
      payload,
    )
    return data
  },

  async revokeAPIKey(clientId: string, keyId: string): Promise<APIKey> {
    const { data } = await apiClient.delete<APIKey>(
      `/api/api-clients/${encodeURIComponent(clientId)}/keys/${encodeURIComponent(keyId)}`,
    )
    return data
  },

  async listAPIClientBindings(clientId: string): Promise<AgentAPIClientBinding[]> {
    const { data } = await apiClient.get<AgentAPIClientBinding[]>(
      `/api/api-clients/${encodeURIComponent(clientId)}/agents`,
    )
    return data
  },

  async bindAPIClientAgent(
    clientId: string,
    agentId: string,
    permission: AgentClientPermission = 'invoke',
  ): Promise<AgentAPIClientBinding> {
    const { data } = await apiClient.post<AgentAPIClientBinding>(
      `/api/api-clients/${encodeURIComponent(clientId)}/agents`,
      { agent_id: agentId, permission },
    )
    return data
  },

  async unbindAPIClientAgent(clientId: string, agentId: string): Promise<void> {
    await apiClient.delete(
      `/api/api-clients/${encodeURIComponent(clientId)}/agents/${encodeURIComponent(agentId)}`,
    )
  },

  async getMetricsSummary(): Promise<MetricsSummary> {
    const { data } = await apiClient.get<MetricsSummary>('/api/metrics/summary')
    return data
  },

  async listAgentMetrics(): Promise<AgentMetric[]> {
    const { data } = await apiClient.get<AgentMetric[]>('/api/metrics/agents')
    return data
  },

  async listAuditLogs(params: {
    agent_id?: string
    client_id?: string
    status?: AuditLog['status']
    limit?: number
  } = {}): Promise<AuditLog[]> {
    const { data } = await apiClient.get<AuditLog[]>('/api/audit-logs', { params })
    return data
  },

  async listSchemaVersions(agentId: string): Promise<AgentSchemaVersion[]> {
    const { data } = await apiClient.get<AgentSchemaVersion[]>(
      `/api/agents/${encodeURIComponent(agentId)}/schema-versions`,
    )
    return data
  },

  async createSchemaVersion(
    agentId: string,
    payload: { version: string; input_schema: Record<string, unknown>; output_schema: Record<string, unknown> },
  ): Promise<AgentSchemaVersion> {
    const { data } = await apiClient.post<AgentSchemaVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/schema-versions`, payload,
    )
    return data
  },

  async updateSchemaVersion(
    agentId: string,
    version: string,
    payload: { input_schema: Record<string, unknown>; output_schema: Record<string, unknown> },
  ): Promise<AgentSchemaVersion> {
    const { data } = await apiClient.put<AgentSchemaVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/schema-versions/${encodeURIComponent(version)}`,
      payload,
    )
    return data
  },

  async deleteSchemaVersion(agentId: string, version: string): Promise<void> {
    await apiClient.delete(
      `/api/agents/${encodeURIComponent(agentId)}/schema-versions/${encodeURIComponent(version)}`,
    )
  },

  async updateSchemaVersionStatus(
    agentId: string, version: string, status: LifecycleStatus,
  ): Promise<AgentSchemaVersion> {
    const { data } = await apiClient.put<AgentSchemaVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/schema-versions/${encodeURIComponent(version)}/status`,
      { status },
    )
    return data
  },

  async listAPIVersions(agentId: string): Promise<AgentAPIVersion[]> {
    const { data } = await apiClient.get<AgentAPIVersion[]>(
      `/api/agents/${encodeURIComponent(agentId)}/api-versions`,
    )
    return data
  },

  async createAPIVersion(
    agentId: string, payload: { api_version: string; schema_version: string },
  ): Promise<AgentAPIVersion> {
    const { data } = await apiClient.post<AgentAPIVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/api-versions`, payload,
    )
    return data
  },

  async updateAPIVersionBinding(
    agentId: string, apiVersion: string, schemaVersion: string,
  ): Promise<AgentAPIVersion> {
    const { data } = await apiClient.put<AgentAPIVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/api-versions/${encodeURIComponent(apiVersion)}/binding`,
      { schema_version: schemaVersion },
    )
    return data
  },

  async deleteAPIVersion(agentId: string, apiVersion: string): Promise<void> {
    await apiClient.delete(
      `/api/agents/${encodeURIComponent(agentId)}/api-versions/${encodeURIComponent(apiVersion)}`,
    )
  },

  async updateAPIVersionStatus(
    agentId: string, apiVersion: string, status: LifecycleStatus,
  ): Promise<AgentAPIVersion> {
    const { data } = await apiClient.put<AgentAPIVersion>(
      `/api/agents/${encodeURIComponent(agentId)}/api-versions/${encodeURIComponent(apiVersion)}/status`,
      { status },
    )
    return data
  },

  async listAgentMCPServers(agentId: string): Promise<MCPServer[]> {
    const { data } = await apiClient.get<MCPServer[]>(
      `/api/agents/${encodeURIComponent(agentId)}/mcp-servers`,
    )
    return data
  },

  async bindAgentMCPServer(agentId: string, mcpId: string): Promise<void> {
    await apiClient.put(
      `/api/agents/${encodeURIComponent(agentId)}/mcp-servers/${encodeURIComponent(mcpId)}`,
    )
  },

  async unbindAgentMCPServer(agentId: string, mcpId: string): Promise<void> {
    await apiClient.delete(
      `/api/agents/${encodeURIComponent(agentId)}/mcp-servers/${encodeURIComponent(mcpId)}`,
    )
  },

  async listKnowledgeSources(): Promise<KnowledgeSource[]> {
    const { data } = await apiClient.get<KnowledgeSource[]>('/api/knowledge-sources')
    return data
  },

  async listAgentKnowledgeSources(agentId: string): Promise<KnowledgeSource[]> {
    const { data } = await apiClient.get<KnowledgeSource[]>(
      `/api/agents/${encodeURIComponent(agentId)}/knowledge-sources`,
    )
    return data
  },

  async bindAgentKnowledgeSource(agentId: string, sourceId: string): Promise<void> {
    await apiClient.put(
      `/api/agents/${encodeURIComponent(agentId)}/knowledge-sources/${encodeURIComponent(sourceId)}`,
    )
  },

  async unbindAgentKnowledgeSource(agentId: string, sourceId: string): Promise<void> {
    await apiClient.delete(
      `/api/agents/${encodeURIComponent(agentId)}/knowledge-sources/${encodeURIComponent(sourceId)}`,
    )
  },
}

export async function consumeSSE(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: AgentStreamEvent) => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) emitSSEFrame(frame, onEvent)
    if (done) break
  }
  if (buffer.trim()) emitSSEFrame(buffer, onEvent)
}

function emitSSEFrame(frame: string, onEvent: (event: AgentStreamEvent) => void): void {
  const lines = frame.split('\n')
  const name = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
  const raw = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trimStart()).join('\n')
  if (!raw) return
  const value = JSON.parse(raw) as AgentStreamEvent
  if (name && !value.event) value.event = name as AgentStreamEvent['event']
  onEvent(value)
}

async function readFetchError(response: Response): Promise<string> {
  try {
    const body = await response.json() as { detail?: string }
    return body.detail || `请求失败（HTTP ${response.status}）`
  } catch {
    return `请求失败（HTTP ${response.status}）`
  }
}
