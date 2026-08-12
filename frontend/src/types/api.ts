export type AgentStatus = 'draft' | 'active' | 'disabled'
export type ExecutionStatus = 'running' | 'succeeded' | 'failed'

export interface Agent {
  id: string
  name: string
  description: string | null
  role: string
  system_prompt: string
  model_config: Record<string, unknown>
  status: AgentStatus
  created_at: string
  updated_at: string
}

export interface AgentCreatePayload {
  id: string
  name: string
  description: string | null
  role: string
  system_prompt: string
  model_config: Record<string, unknown>
  status: AgentStatus
}

export interface AgentRunPayload {
  input: string
  session_id: string
}

export interface AgentRunResponse {
  execution_id: string
  agent_id: string
  session_id: string
  status: 'succeeded'
  output: string
  hermes_run_id: string | null
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
  [key: string]: unknown
}

export interface ExecutionLog {
  id: string
  agent_id: string
  status: ExecutionStatus
  input: string
  output: string | null
  error: string | null
  details: ExecutionDetails
  started_at: string
  finished_at: string | null
}

export interface Skill {
  id: string
  name: string
  description: string | null
  path: string
  created_at: string
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
  created_at: string
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
