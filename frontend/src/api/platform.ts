import { apiClient } from './client'
import type {
  Agent,
  AgentRuntime,
  AgentSession,
  AgentTask,
  AgentTaskSubmitPayload,
  AgentWorkspace,
  AgentTeam,
  AgentTeamStatus,
  AgentMessage,
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
  RuntimeHealth,
  RuntimeType,
  ModelAdapterName,
  ModelConnectivity,
  ModelCreatePayload,
  ModelUpdatePayload,
  RegisteredModel,
  MetricsSummary,
  MultiAgentRunPayload,
  Skill,
  Workflow,
  WorkflowNode,
  WorkflowRun,
  WorkflowStatus,
  AgentEditorModel,
  AvailableComponents,
  CapabilityBindingWrite,
  CapabilityCatalogItem,
  CapabilityRecord,
  CapabilityResolution,
  CredentialRecord,
  PlatformConnection,
  ResourceScopeRecord,
  DatabaseConnectionPayload,
  DatabaseConnectionDetail,
  DatabaseConnectionSummary,
  DatabaseDiscovery,
  DatabaseEndpoint,
  DatabaseOperation,
  DatabaseResourceRecord,
  DatabaseScopePayload,
  ConsoleAgentSummary,
  TeamConversationList,
  TeamConversationMessagePayload,
  WorkflowRunList,
} from '@/types/api'

const consoleAgentCache = new Map<string, { expiresAt: number; value: ConsoleAgentSummary[] }>()
const consoleAgentRequests = new Map<string, Promise<ConsoleAgentSummary[]>>()
let consoleAgentCacheGeneration = 0

function invalidateConsoleAgentCache() {
  consoleAgentCacheGeneration += 1
  consoleAgentCache.clear()
  consoleAgentRequests.clear()
}

export const platformApi = {
  async getConsoleWorkbench(): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get<Record<string, unknown>>('/api/console/workbench')
    return data
  },

  async listConsoleAgents(includePreflight = false, force = false): Promise<ConsoleAgentSummary[]> {
    const key = includePreflight ? 'preflight' : 'summary'
    if (force) {
      consoleAgentCacheGeneration += 1
      consoleAgentCache.delete(key)
      consoleAgentRequests.delete(key)
    }
    const cached = consoleAgentCache.get(key)
    if (!force && cached && cached.expiresAt > Date.now()) return cached.value
    const pending = consoleAgentRequests.get(key)
    if (!force && pending) return pending
    const requestGeneration = consoleAgentCacheGeneration
    const request = apiClient.get<ConsoleAgentSummary[]>('/api/console/agents', {
      params: includePreflight ? { include_preflight: true } : undefined,
    }).then(({ data }) => {
      if (requestGeneration === consoleAgentCacheGeneration) {
        consoleAgentCache.set(key, { expiresAt: Date.now() + 5000, value: data })
      }
      return data
    }).finally(() => {
      if (consoleAgentRequests.get(key) === request) consoleAgentRequests.delete(key)
    })
    consoleAgentRequests.set(key, request)
    return request
  },

  async getConsoleExecution(executionId: string): Promise<{ execution: Record<string, unknown>; timeline: Array<Record<string, unknown>> }> {
    const { data } = await apiClient.get(`/api/console/executions/${encodeURIComponent(executionId)}`)
    return data
  },

  async getAgentEditor(agentId: string): Promise<AgentEditorModel> {
    const { data } = await apiClient.get<AgentEditorModel>(`/api/console/agents/${encodeURIComponent(agentId)}/editor`)
    return data
  },

  async updateAgentEditorSection(agentId: string, section: string, payload: Record<string, unknown>): Promise<AgentEditorModel> {
    const { data } = await apiClient.patch<AgentEditorModel>(
      `/api/console/agents/${encodeURIComponent(agentId)}/editor/${encodeURIComponent(section)}`,
      payload,
    )
    return data
  },

  async getAvailableComponents(agentId: string): Promise<AvailableComponents> {
    const { data } = await apiClient.get<AvailableComponents>(`/api/console/agents/${encodeURIComponent(agentId)}/available-components`)
    return data
  },

  async preflightAgent(agentId: string): Promise<CapabilityResolution> {
    const { data } = await apiClient.post<CapabilityResolution>(`/api/console/agents/${encodeURIComponent(agentId)}/preflight`)
    return data
  },

  async testAgentDraft(agentId: string, payload: AgentRunPayload): Promise<AgentRunResponse> {
    const { data } = await apiClient.post<AgentRunResponse>(
      `/api/console/agents/${encodeURIComponent(agentId)}/test`,
      payload,
    )
    return data
  },

  async publishAgentDraft(agentId: string): Promise<{ id: string; version: string; status: string; resolution_digest: string }> {
    const { data } = await apiClient.post(
      `/api/console/agents/${encodeURIComponent(agentId)}/publish`,
    )
    return data
  },

  async updateCapabilityBindings(agentId: string, bindings: CapabilityBindingWrite[]): Promise<unknown[]> {
    const { data } = await apiClient.put<unknown[]>(
      `/api/agents/${encodeURIComponent(agentId)}/draft/capability-bindings`,
      { bindings },
    )
    return data
  },

  async listCapabilityCatalog(agentId: string): Promise<CapabilityCatalogItem[]> {
    const { data } = await apiClient.get<CapabilityCatalogItem[]>(`/api/agents/${encodeURIComponent(agentId)}/available-capabilities`)
    return data
  },

  async listCapabilityCatalogGlobal(): Promise<CapabilityCatalogItem[]> {
    const { data } = await apiClient.get<CapabilityCatalogItem[]>('/api/capability-catalog')
    return data
  },

  async listCapabilities(): Promise<CapabilityRecord[]> {
    const { data } = await apiClient.get<CapabilityRecord[]>('/api/capabilities')
    return data
  },

  async listCredentials(): Promise<CredentialRecord[]> {
    const { data } = await apiClient.get<CredentialRecord[]>('/api/credentials')
    return data
  },

  async listResourceScopes(): Promise<ResourceScopeRecord[]> {
    const { data } = await apiClient.get<ResourceScopeRecord[]>('/api/resource-scopes')
    return data
  },

  async listPlatformConnections(): Promise<PlatformConnection[]> {
    const { data } = await apiClient.get<PlatformConnection[]>('/api/console/platform/connections')
    return data
  },

  async listDatabaseConnections(): Promise<DatabaseConnectionSummary[]> {
    const { data } = await apiClient.get<DatabaseConnectionSummary[]>('/api/console/platform/database-connections')
    return data
  },

  async getDatabaseConnection(connectionId: string): Promise<DatabaseConnectionDetail> {
    const { data } = await apiClient.get<DatabaseConnectionDetail>(
      `/api/console/platform/database-connections/${encodeURIComponent(connectionId)}`,
    )
    return data
  },

  async testDatabaseConnection(
    endpoint: DatabaseEndpoint,
    credential: { username: string; password: string },
  ): Promise<DatabaseDiscovery> {
    const { data } = await apiClient.post<DatabaseDiscovery>(
      '/api/console/platform/database-connections/test',
      { endpoint, credential },
    )
    return data
  },

  async createDatabaseConnection(payload: DatabaseConnectionPayload): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post<Record<string, unknown>>(
      '/api/console/platform/database-connections',
      payload,
    )
    return data
  },

  async testSavedDatabaseConnection(connectionId: string): Promise<DatabaseDiscovery> {
    const { data } = await apiClient.post<DatabaseDiscovery>(
      `/api/console/platform/database-connections/${encodeURIComponent(connectionId)}/test`,
    )
    return data
  },

  async updateDatabaseConnection(
    connectionId: string,
    payload: { name?: string; environment?: string; enabled?: boolean; endpoint?: DatabaseEndpoint },
  ): Promise<DatabaseConnectionDetail> {
    const { data } = await apiClient.patch<DatabaseConnectionDetail>(
      `/api/console/platform/database-connections/${encodeURIComponent(connectionId)}`,
      payload,
    )
    return data
  },

  async discoverDatabaseConnection(connectionId: string): Promise<DatabaseDiscovery> {
    const { data } = await apiClient.post<DatabaseDiscovery>(
      `/api/console/platform/database-connections/${encodeURIComponent(connectionId)}/discover`,
    )
    return data
  },

  async listDatabaseResources(connectionId: string): Promise<DatabaseResourceRecord[]> {
    const { data } = await apiClient.get<DatabaseResourceRecord[]>(
      `/api/console/platform/database-connections/${encodeURIComponent(connectionId)}/resources`,
    )
    return data
  },

  async createDatabaseScope(connectionId: string, scope: DatabaseScopePayload): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post<Record<string, unknown>>(
      `/api/console/platform/database-connections/${encodeURIComponent(connectionId)}/scopes`,
      { scope },
    )
    return data
  },

  async replaceDatabaseCredential(
    connectionId: string,
    credential: { username: string; password: string },
  ): Promise<{ credential_configured: boolean; masked_username: string; password_updated_at: string }> {
    const { data } = await apiClient.post(
      `/api/console/platform/database-connections/${encodeURIComponent(connectionId)}/credentials/replace`,
      credential,
    )
    return data
  },

  async disableDatabaseConnection(connectionId: string): Promise<void> {
    await apiClient.delete(`/api/console/platform/database-connections/${encodeURIComponent(connectionId)}`)
  },

  async updateDatabaseBindings(
    agentId: string,
    bindings: Array<{ scope_revision_id: string; tool_prefix: string; operations: DatabaseOperation[] }>,
  ): Promise<Array<Record<string, unknown>>> {
    const { data } = await apiClient.put<Array<Record<string, unknown>>>(
      `/api/console/agents/${encodeURIComponent(agentId)}/database-bindings`,
      { bindings },
    )
    return data
  },

  async createCredential(payload: { name: string; credential_type: string; secret: string; masked_label?: string }): Promise<CredentialRecord> {
    const { data } = await apiClient.post<CredentialRecord>('/api/credentials', payload)
    return data
  },

  async createCapability(payload: { namespace: string; key: string; display_name: string; description?: string; risk_level: 'LOW' | 'MEDIUM' | 'HIGH' }): Promise<CapabilityRecord> {
    const { data } = await apiClient.post<CapabilityRecord>('/api/capabilities', payload)
    return data
  },

  async createConnector(payload: { key: string; display_name: string; type: 'internal_rest' | 'mcp' | 'postgresql_mcp' | 'database_mcp'; description?: string }): Promise<{ id: string }> {
    const { data } = await apiClient.post<{ id: string }>('/api/connectors', payload)
    return data
  },

  async createConnectorInstance(connectorId: string, payload: { name: string; environment: string }): Promise<{ id: string }> {
    const { data } = await apiClient.post<{ id: string }>(`/api/connectors/${encodeURIComponent(connectorId)}/instances`, payload)
    return data
  },

  async createConnectorRevision(instanceId: string, payload: Record<string, unknown>): Promise<{ id: string }> {
    const { data } = await apiClient.post<{ id: string }>(`/api/connector-instances/${encodeURIComponent(instanceId)}/revisions`, payload)
    return data
  },

  async testConnectorRevision(revisionId: string): Promise<{ status: string; latency_ms: number; error_code: string | null }> {
    const { data } = await apiClient.post(`/api/connector-instance-revisions/${encodeURIComponent(revisionId)}/test`)
    return data
  },

  async createConnectorOperation(connectorId: string, payload: Record<string, unknown>): Promise<{ id: string }> {
    const { data } = await apiClient.post<{ id: string }>(`/api/connectors/${encodeURIComponent(connectorId)}/operations`, payload)
    return data
  },

  async createCapabilityVersion(capabilityId: string, payload: Record<string, unknown>): Promise<{ id: string }> {
    const { data } = await apiClient.post<{ id: string }>(`/api/capabilities/${encodeURIComponent(capabilityId)}/versions`, payload)
    return data
  },

  async testCapabilityVersion(versionId: string): Promise<void> {
    await apiClient.post(`/api/capability-versions/${encodeURIComponent(versionId)}/test`)
  },

  async publishCapabilityVersion(versionId: string): Promise<void> {
    await apiClient.post(`/api/capability-versions/${encodeURIComponent(versionId)}/publish`)
  },

  async createCapabilityImplementation(payload: Record<string, unknown>): Promise<void> {
    await apiClient.post('/api/capability-implementations', payload)
  },
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

  async listRuntimes(type?: RuntimeType): Promise<AgentRuntime[]> {
    const { data } = await apiClient.get<AgentRuntime[]>('/api/runtimes', {
      params: { type },
    })
    return data
  },

  async checkRuntime(runtimeId: string): Promise<RuntimeHealth> {
    const { data } = await apiClient.post<RuntimeHealth>(
      `/api/runtimes/${encodeURIComponent(runtimeId)}/health`,
    )
    return data
  },

  async createRuntime(payload: Omit<AgentRuntime, 'id' | 'last_health_at' | 'last_error' | 'created_at' | 'updated_at'>): Promise<AgentRuntime> {
    const { data } = await apiClient.post<AgentRuntime>('/api/runtimes', payload)
    return data
  },

  async updateRuntime(runtimeId: string, payload: Partial<Pick<AgentRuntime, 'name' | 'version' | 'endpoint' | 'config' | 'status'>>): Promise<AgentRuntime> {
    const { data } = await apiClient.patch<AgentRuntime>(
      `/api/runtimes/${encodeURIComponent(runtimeId)}`,
      payload,
    )
    return data
  },

  async listModels(enabledOnly = false): Promise<RegisteredModel[]> {
    const { data } = await apiClient.get<RegisteredModel[]>('/api/models', {
      params: { enabled_only: enabledOnly },
    })
    return data
  },

  async createModel(payload: ModelCreatePayload): Promise<RegisteredModel> {
    const { data } = await apiClient.post<RegisteredModel>('/api/models', payload)
    return data
  },

  async updateModel(modelId: string, payload: ModelUpdatePayload): Promise<RegisteredModel> {
    const { data } = await apiClient.patch<RegisteredModel>(
      `/api/models/${encodeURIComponent(modelId)}`,
      payload,
    )
    return data
  },

  async setDefaultModel(modelId: string): Promise<RegisteredModel> {
    const { data } = await apiClient.post<RegisteredModel>(
      `/api/models/${encodeURIComponent(modelId)}/default`,
    )
    return data
  },

  async testModel(modelId: string): Promise<ModelConnectivity> {
    const { data } = await apiClient.post<ModelConnectivity>(
      `/api/models/${encodeURIComponent(modelId)}/test`,
    )
    return data
  },

  async deleteModel(modelId: string): Promise<void> {
    await apiClient.delete(`/api/models/${encodeURIComponent(modelId)}`)
  },

  async createAgent(payload: AgentCreatePayload): Promise<Agent> {
    const { data } = await apiClient.post<Agent>('/api/agents', payload)
    invalidateConsoleAgentCache()
    return data
  },

  async deleteAgent(agentId: string): Promise<void> {
    await apiClient.delete(`/api/agents/${encodeURIComponent(agentId)}`)
    invalidateConsoleAgentCache()
  },

  async updateAgentLifecycle(agentId: string, status: AgentLifecycleStatus): Promise<Agent> {
    const { data } = await apiClient.patch<Agent>(
      `/api/agents/${encodeURIComponent(agentId)}/lifecycle`,
      { status },
    )
    invalidateConsoleAgentCache()
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

  async listAgentTeams(): Promise<AgentTeam[]> {
    const { data } = await apiClient.get<AgentTeam[]>('/api/agent-teams')
    return data
  },

  async createAgentTeam(payload: {
    name: string
    description?: string | null
    owner_agent_id: string
    status?: AgentTeamStatus
  }): Promise<AgentTeam> {
    const { data } = await apiClient.post<AgentTeam>('/api/agent-teams', payload)
    return data
  },

  async updateAgentTeam(
    teamId: string,
    payload: { name?: string; description?: string | null; status?: AgentTeamStatus },
  ): Promise<AgentTeam> {
    const { data } = await apiClient.patch<AgentTeam>(
      `/api/agent-teams/${encodeURIComponent(teamId)}`,
      payload,
    )
    return data
  },

  async deleteAgentTeam(teamId: string): Promise<void> {
    await apiClient.delete(`/api/agent-teams/${encodeURIComponent(teamId)}`)
  },

  async upsertTeamMember(
    teamId: string,
    agentId: string,
    payload: { role: string; priority: number },
  ): Promise<AgentTeam> {
    const { data } = await apiClient.put<AgentTeam>(
      `/api/agent-teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(agentId)}`,
      payload,
    )
    return data
  },

  async removeTeamMember(teamId: string, agentId: string): Promise<void> {
    await apiClient.delete(
      `/api/agent-teams/${encodeURIComponent(teamId)}/members/${encodeURIComponent(agentId)}`,
    )
  },

  async listWorkflows(teamId?: string): Promise<Workflow[]> {
    const { data } = await apiClient.get<Workflow[]>('/api/workflows', {
      params: { team_id: teamId },
    })
    return data
  },

  async createWorkflow(payload: {
    team_id: string
    name: string
    description?: string | null
    status?: WorkflowStatus
    nodes: WorkflowNode[]
  }): Promise<Workflow> {
    const { data } = await apiClient.post<Workflow>('/api/workflows', payload)
    return data
  },

  async updateWorkflow(
    workflowId: string,
    payload: { name?: string; description?: string | null; status?: WorkflowStatus; nodes?: WorkflowNode[] },
  ): Promise<Workflow> {
    const { data } = await apiClient.patch<Workflow>(
      `/api/workflows/${encodeURIComponent(workflowId)}`,
      payload,
    )
    return data
  },

  async runAgentTeam(teamId: string, payload: MultiAgentRunPayload): Promise<WorkflowRun> {
    const { data } = await apiClient.post<WorkflowRun>(
      `/api/agent-teams/${encodeURIComponent(teamId)}/runs`,
      payload,
    )
    return data
  },

  async runWorkflow(workflowId: string, payload: MultiAgentRunPayload): Promise<WorkflowRun> {
    const { data } = await apiClient.post<WorkflowRun>(
      `/api/workflows/${encodeURIComponent(workflowId)}/runs`,
      payload,
    )
    return data
  },

  async listWorkflowRuns(params: { team_id?: string; workflow_id?: string } = {}): Promise<WorkflowRun[]> {
    const { data } = await apiClient.get<WorkflowRun[]>('/api/workflow-runs', { params })
    return data
  },

  async listWorkflowRunTasks(runId: string): Promise<AgentTask[]> {
    const { data } = await apiClient.get<AgentTask[]>(
      `/api/workflow-runs/${encodeURIComponent(runId)}/tasks`,
    )
    return data
  },

  async listTeamConversations(
    teamId: string,
    params: { limit?: number; offset?: number } = {},
  ): Promise<TeamConversationList> {
    const { data } = await apiClient.get<TeamConversationList>(
      `/api/agent-teams/${encodeURIComponent(teamId)}/conversations`,
      { params },
    )
    return data
  },

  async listTeamConversationRuns(
    teamId: string,
    sessionId: string,
    params: { limit?: number; offset?: number } = {},
  ): Promise<WorkflowRunList> {
    const { data } = await apiClient.get<WorkflowRunList>(
      `/api/agent-teams/${encodeURIComponent(teamId)}/conversations/${encodeURIComponent(sessionId)}/runs`,
      { params },
    )
    return data
  },

  async sendTeamConversationMessage(
    teamId: string,
    sessionId: string,
    payload: TeamConversationMessagePayload,
  ): Promise<WorkflowRun> {
    const { data } = await apiClient.post<WorkflowRun>(
      `/api/agent-teams/${encodeURIComponent(teamId)}/conversations/${encodeURIComponent(sessionId)}/messages`,
      payload,
    )
    return data
  },

  async cancelWorkflowRun(runId: string): Promise<void> {
    await apiClient.delete(`/api/workflow-runs/${encodeURIComponent(runId)}`)
  },

  async reviewHumanTask(taskId: string, approved: boolean, note?: string): Promise<AgentTask> {
    const { data } = await apiClient.post<AgentTask>(
      `/api/tasks/${encodeURIComponent(taskId)}/approval`,
      { approved, note },
    )
    return data
  },

  async listAgentMessages(toAgent?: string): Promise<AgentMessage[]> {
    const { data } = await apiClient.get<AgentMessage[]>('/api/agent-messages', {
      params: { to_agent: toAgent },
    })
    return data
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
    invalidateConsoleAgentCache()
  },

  async unbindAgentSkill(agentId: string, skillId: string): Promise<void> {
    await apiClient.delete(
      `/api/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillId)}`,
    )
    invalidateConsoleAgentCache()
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
      runtime_type?: RuntimeType
      runtime_id?: string | null
      runtime_config?: Record<string, unknown>
      capability_profile?: {
        workspace_type: 'document' | 'repository'
        required_tools: string[]
        artifact_types: string[]
      }
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
    invalidateConsoleAgentCache()
  },

  async unbindAgentMCPServer(agentId: string, mcpId: string): Promise<void> {
    await apiClient.delete(
      `/api/agents/${encodeURIComponent(agentId)}/mcp-servers/${encodeURIComponent(mcpId)}`,
    )
    invalidateConsoleAgentCache()
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
