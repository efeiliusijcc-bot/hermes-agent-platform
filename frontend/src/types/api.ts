export type AgentLifecycleStatus = 'active' | 'inactive' | 'archived'
export type LegacyAgentStatus = 'draft' | 'testing' | 'published' | 'suspended' | 'disabled'
export type AgentStatus = AgentLifecycleStatus | LegacyAgentStatus
export type ExecutionStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type TaskStatus = 'pending' | 'running' | 'waiting_child' | 'human_review' | 'retrying' | 'succeeded' | 'failed' | 'cancelled'
export type SessionStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
export type ResponseMode = 'sync' | 'stream'
export type ModelAdapterName = 'hermes' | 'qwen' | 'deepseek' | 'gpt' | 'claude'
export type AgentType = 'manager' | 'worker'
export type RuntimeType = 'hermes' | 'pi'
export type RuntimeStatus = 'unknown' | 'online' | 'offline' | 'disabled'
export type ModelProvider = 'qwen' | 'deepseek' | 'openai' | 'claude' | 'custom'
export type ModelRegistryStatus = 'unknown' | 'online' | 'offline'
export type LifecycleStatus = 'draft' | 'testing' | 'published' | 'deprecated' | 'disabled'

export interface Agent {
  id: string
  name: string
  description: string | null
  agent_type: AgentType
  parent_agent_id: string | null
  role: string
  system_prompt: string
  model_config: Record<string, unknown>
  model: string
  prompt_template: string
  model_adapter: ModelAdapterName
  runtime_type: RuntimeType
  runtime_config: Record<string, unknown>
  api_enabled: boolean
  status: AgentStatus
  response_mode: ResponseMode
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  current_version_id: string | null
  created_at: string
  updated_at: string
}

export interface AgentCreatePayload {
  id: string
  name: string
  description: string | null
  agent_type?: AgentType
  parent_agent_id?: string | null
  role: string
  system_prompt: string
  model_config: Record<string, unknown>
  model?: string
  prompt_template?: string
  model_adapter?: ModelAdapterName
  runtime_type?: RuntimeType
  runtime_config?: Record<string, unknown>
  status: AgentLifecycleStatus
  response_mode?: ResponseMode
  input_schema?: Record<string, unknown>
  output_schema?: Record<string, unknown>
}

export interface AgentRunPayload {
  input: string
  session_id: string
  parameters?: Record<string, unknown>
  temperature?: number | null
}

export interface AgentTaskSubmitPayload extends AgentRunPayload {
  priority: number
  user_id?: string | null
}

export interface AgentTask {
  id: string
  parent_task_id: string | null
  workflow_id: string | null
  workflow_run_id: string | null
  node_key: string | null
  node_type: string
  depends_on: string[]
  input_data: Record<string, unknown>
  output_data: Record<string, unknown>
  agent_id: string
  session_id: string
  execution_id: string | null
  priority: number
  status: TaskStatus
  attempt: number
  max_attempts: number
  worker_id: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface AgentSession {
  id: string
  agent_id: string
  user_id: string | null
  memory_session_id: string
  runtime_type: RuntimeType
  runtime_session_id: string | null
  status: SessionStatus
  input: string
  output: string | null
  workspace_path: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface Artifact {
  id: string
  agent_id: string
  session_id: string
  filename: string
  storage_type: string
  storage_path: string
  content_type: string
  size_bytes: number
  sha256: string
  created_at: string
}

export interface AgentWorkspace {
  agent_id: string
  root: string
  session_count: number
  artifact_count: number
  size_bytes: number
}

export type AgentTeamStatus = 'active' | 'inactive' | 'archived'
export type WorkflowStatus = 'draft' | 'active' | 'inactive' | 'archived'
export type WorkflowRunStatus = 'pending' | 'running' | 'human_review' | 'succeeded' | 'failed' | 'cancelled'
export type WorkflowNodeType = 'agent' | 'tool' | 'skill' | 'condition' | 'human_approval'

export interface AgentTeamMember {
  agent_id: string
  agent_name: string
  agent_type: AgentType
  runtime_type: RuntimeType
  role: string
  priority: number
}

export interface AgentTeam {
  id: string
  name: string
  description: string | null
  owner_agent_id: string
  status: AgentTeamStatus
  members: AgentTeamMember[]
  created_at: string
  updated_at: string
}

export interface WorkflowNode {
  key: string
  type: WorkflowNodeType
  name: string
  agent_id: string | null
  depends_on: string[]
  config: Record<string, unknown>
}

export interface Workflow {
  id: string
  team_id: string
  name: string
  description: string | null
  status: WorkflowStatus
  nodes: WorkflowNode[]
  created_at: string
  updated_at: string
}

export interface WorkflowRun {
  id: string
  workflow_id: string | null
  team_id: string
  status: WorkflowRunStatus
  input: string
  output: string | null
  error: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface MultiAgentRunPayload {
  input: string
  session_id: string
  priority: number
  user_id?: string | null
  parameters?: Record<string, unknown>
}

export interface AgentMessage {
  id: string
  from_agent: string
  to_agent: string
  message_type: 'task' | 'result' | 'event' | 'error'
  payload: Record<string, unknown>
  task_id: string | null
  created_at: string
}

export interface AgentRunResponse {
  execution_id: string
  agent_id: string
  session_id: string
  status: 'succeeded'
  output: string
  hermes_run_id: string | null
  runtime: RuntimeType
  runtime_run_id: string | null
}

export interface AgentRuntime {
  id: string
  name: string
  type: RuntimeType
  version: string
  endpoint: string
  config: Record<string, unknown>
  status: RuntimeStatus
  last_health_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface RuntimeHealth {
  id: string
  status: 'online' | 'offline'
  version: string | null
  latency_ms: number
  detail: string
}

export interface RegisteredModel {
  id: string
  display_name: string
  provider: ModelProvider
  adapter: ModelAdapterName
  base_url: string
  upstream_model: string
  api_key_configured: boolean
  is_enabled: boolean
  is_default: boolean
  timeout_seconds: number
  max_retries: number
  status: ModelRegistryStatus
  last_health_at: string | null
  last_error: string | null
  created_at: string
  updated_at: string
}

export interface ModelCreatePayload {
  id: string
  display_name: string
  provider: ModelProvider
  adapter: ModelAdapterName
  base_url: string
  upstream_model: string
  api_key?: string | null
  is_enabled: boolean
  is_default: boolean
  timeout_seconds: number
  max_retries: number
}

export interface ModelUpdatePayload {
  display_name?: string
  provider?: ModelProvider
  adapter?: ModelAdapterName
  base_url?: string
  upstream_model?: string
  api_key?: string | null
  clear_api_key?: boolean
  is_enabled?: boolean
  is_default?: boolean
  timeout_seconds?: number
  max_retries?: number
}

export interface ModelConnectivity {
  id: string
  status: 'online' | 'offline'
  latency_ms: number
  detail: string
}

export interface MCPCall {
  mcp_id?: string | null
  tool?: string
  status?: string
  input?: Record<string, unknown>
  result?: Record<string, unknown>
  started_at?: string
  finished_at?: string
}

export interface ExecutionDetails {
  phase?: string
  skills_loaded?: string[]
  mcp_loaded?: string[]
  mcp_calls?: MCPCall[]
  knowledge_loaded?: string[]
  knowledge_hits?: Array<Record<string, unknown>>
  memory_scope?: {
    namespace?: string
    agent_id?: string
    session_id?: string
    history_messages_loaded?: number
  }
  hermes_run_id?: string | null
  hermes_status?: string
  runtime_type?: RuntimeType
  runtime_run_id?: string | null
  runtime_status?: string
  runtime_version?: string | null
  [key: string]: unknown
}

export interface ExecutionLog {
  id: string
  agent_id: string
  session_id: string | null
  status: ExecutionStatus
  input: string
  input_json: ExecutionInput
  output: string | null
  output_json: unknown | null
  error: string | null
  details: ExecutionDetails
  response_mode: 'sync' | 'stream' | 'async'
  priority: number | null
  duration_ms: number | null
  token_usage: number | null
  runtime_type: RuntimeType
  runtime_id: string | null
  runtime_version: string | null
  retry_of_execution_id: string | null
  agent_version_id: string | null
  started_at: string
  finished_at: string | null
}

export interface ExecutionInput {
  task?: string
  parameters?: Record<string, unknown>
  runtime_options?: { temperature?: number }
  [key: string]: unknown
}

export type ExecutionStepStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'skipped' | 'cancelled'
export type ExecutionStepType = 'request' | 'schema' | 'memory' | 'skill' | 'mcp' | 'knowledge' | 'model' | 'artifact' | 'runtime'

export interface ExecutionStep {
  id: string
  execution_id: string
  step_key: string
  sequence: number
  step_type: ExecutionStepType
  step_name: string
  status: ExecutionStepStatus
  input_data: Record<string, unknown>
  output_data: Record<string, unknown>
  error: string | null
  latency_ms: number | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface ExecutionMetrics {
  total_executions: number
  running: number
  succeeded: number
  failed: number
  cancelled: number
  success_rate: number | null
}

export interface ExecutionSummary {
  id: string
  agent_id: string
  agent_name: string
  session_id: string | null
  memory_session_id: string | null
  status: ExecutionStatus
  task: string
  response_mode: 'sync' | 'stream' | 'async'
  runtime_type: RuntimeType
  runtime_id: string | null
  runtime_version: string | null
  priority: number | null
  duration_ms: number | null
  token_usage: number | null
  skill_count: number
  mcp_call_count: number
  memory_read_count: number
  artifact_count: number
  trace_step_count: number
  failed_step_count: number
  model_call_count: number
  retry_of_execution_id: string | null
  agent_version_id: string | null
  agent_version: string | null
  started_at: string
  finished_at: string | null
}

export interface ExecutionList {
  items: ExecutionSummary[]
  total: number
  limit: number
  offset: number
  metrics: ExecutionMetrics
}

export interface ExecutionDetail extends ExecutionSummary {
  input: string
  input_json: ExecutionInput
  output: string | null
  output_json: unknown | null
  error: string | null
  details: ExecutionDetails
  model: string | null
  model_adapter: string | null
  schema_version: string | null
  steps: ExecutionStep[]
  artifacts: Artifact[]
  queue_task: AgentTask | null
}

export interface TraceMetrics {
  total_nodes: number
  failed_nodes: number
  skill_nodes: number
  mcp_calls: number
  model_calls: number
  artifact_nodes: number
  total_latency_ms: number
  slowest_node_ms: number | null
}

export interface ExecutionTrace {
  execution_id: string
  agent_id: string
  agent_name: string
  agent_version_id: string | null
  agent_version: string | null
  session_id: string | null
  memory_session_id: string | null
  status: ExecutionStatus
  runtime_type: RuntimeType
  runtime_id: string | null
  runtime_version: string | null
  model: string | null
  model_adapter: string | null
  token_usage: number | null
  duration_ms: number | null
  error: string | null
  started_at: string
  finished_at: string | null
  nodes: ExecutionStep[]
  artifacts: Artifact[]
  metrics: TraceMetrics
}

export interface Skill {
  id: string
  name: string
  description: string | null
  path: string
  version: string
  manifest: Record<string, unknown>
  runtime_support: RuntimeType[]
  package_sha256: string | null
  created_at: string
  updated_at: string
}

export interface MCPServer {
  id: string
  name: string
  endpoint: string
  config: {
    kind: 'filesystem' | 'database'
    read_only: true
    [key: string]: unknown
  }
  permission: 'read_only'
  status: 'unknown' | 'online' | 'offline'
  created_at: string
  updated_at: string
}

export interface MCPServerCreatePayload {
  id: string
  name: string
  endpoint: string
  permission: 'read_only'
  config: { kind: 'filesystem' | 'database'; read_only: true }
}

export interface MCPServerTestResult {
  id: string
  status: 'online' | 'offline'
  latency_ms: number
  detail: string
}

export interface AgentSchemaVersion {
  id: string
  agent_id: string
  version: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  status: LifecycleStatus
  created_at: string
  published_at: string | null
}

export interface AgentAPIVersion {
  id: string
  agent_id: string
  api_version: string
  schema_version_id: string
  schema_version: AgentSchemaVersion
  status: LifecycleStatus
  endpoint: string
  created_at: string
  published_at: string | null
}

export type APIClientStatus = 'active' | 'suspended' | 'revoked'
export type APIKeyStatus = 'active' | 'revoked'
export type AgentClientPermission = 'invoke'

export interface APIClient {
  id: string
  name: string
  owner: string
  status: APIClientStatus
  rate_limit_per_minute: number
  key_count: number
  agent_count: number
  call_count: number
  last_called_at: string | null
  created_at: string
  updated_at: string
}

export interface APIKey {
  id: string
  client_id: string
  name: string
  prefix: string
  status: APIKeyStatus
  call_count: number
  last_used_at: string | null
  expires_at: string | null
  created_at: string
  revoked_at: string | null
}

export interface APIKeySecret extends APIKey {
  api_key: string
}

export interface AgentAPIClientBinding {
  client_id: string
  agent_id: string
  permission: AgentClientPermission
  created_at: string
}

export type AgentHealthState = 'healthy' | 'degraded' | 'unhealthy' | 'unknown'

export interface AgentHealthComponent {
  status: AgentHealthState
  detail: string
}

export interface AgentHealth {
  agent_id: string
  status: AgentHealthState
  checks: Record<string, AgentHealthComponent>
  checked_at: string
}

export interface AgentVersionSnapshot {
  format_version?: number
  prompt?: {
    role?: string
    system_prompt?: string
    prompt_template?: string
  }
  model?: {
    name?: string
    adapter?: ModelAdapterName
    config?: Record<string, unknown>
  }
  skill_ids?: string[]
  mcp_ids?: string[]
  schema?: {
    version?: string | null
    input_schema?: Record<string, unknown>
    output_schema?: Record<string, unknown>
  }
  runtime?: { response_mode?: ResponseMode; runtime_type?: RuntimeType }
  [key: string]: unknown
}

export interface AgentVersion {
  id: string
  agent_id: string
  version: string
  snapshot: AgentVersionSnapshot
  status: 'development' | 'testing' | 'release_candidate' | 'published' | 'deprecated'
  description: string | null
  created_by: string
  created_at: string
  updated_at: string
  published_at: string | null
  deprecated_at: string | null
}

export interface AgentMetric {
  agent_id: string
  agent_name: string | null
  call_count: number
  success_count: number
  failure_count: number
  success_rate: number | null
  average_latency_ms: number | null
  token_usage: number | null
  mcp_call_count: number
  metric_date: string | null
}

export interface MetricsSummary {
  agent_count: number
  published_agent_count: number
  call_count: number
  success_count: number
  failure_count: number
  success_rate: number | null
  error_rate: number | null
  average_latency_ms: number | null
  token_usage: number | null
  mcp_call_count: number
  updated_at: string | null
}

export interface AuditLog {
  id: string
  request_id: string
  client_id: string | null
  api_key_id: string | null
  agent_id: string | null
  status: 'succeeded' | 'failed' | 'rejected'
  latency_ms: number
  token_usage: number | null
  mcp_call_count: number
  error_code: string | null
  created_at: string
}

export type AgentStreamEventName = 'start' | 'trace' | 'tool' | 'token' | 'end' | 'error' | 'keepalive'

export interface AgentStreamEvent {
  event: AgentStreamEventName
  [key: string]: unknown
}

export interface KnowledgeSource {
  id: string
  name: string
  description: string | null
  config: Record<string, unknown>
  status: 'active' | 'disabled'
  created_at: string
  updated_at: string
}

export interface HealthStatus {
  status: string
  database: string
  memory: string
  knowledge: string
  queue: string
  agent_message_bus: string
  artifact_storage: string
}

export interface CreateAgentWorkflowPayload {
  agent: AgentCreatePayload
  skillIds: string[]
  mcpIds: string[]
}

export interface CreateAgentWorkflowResult {
  agent: Agent
  bindingErrors: string[]
}
