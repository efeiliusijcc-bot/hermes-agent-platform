import { apiClient } from './client'
import type {
  Agent,
  AgentCreatePayload,
  AgentRunPayload,
  AgentRunResponse,
  AgentStreamEvent,
  AgentPublication,
  AgentPublicationSecret,
  ExecutionLog,
  HealthStatus,
  KnowledgeSource,
  MCPServer,
  MCPServerCreatePayload,
  MCPServerTestResult,
  PublicationStatus,
  ResponseMode,
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

  async listPublications(): Promise<AgentPublication[]> {
    const { data } = await apiClient.get<AgentPublication[]>('/api/agent-publications')
    return data
  },

  async getPublication(agentId: string): Promise<AgentPublication> {
    const { data } = await apiClient.get<AgentPublication>(
      `/api/agents/${encodeURIComponent(agentId)}/publication`,
    )
    return data
  },

  async updatePublication(agentId: string, status: PublicationStatus): Promise<AgentPublication> {
    const { data } = await apiClient.put<AgentPublication>(
      `/api/agents/${encodeURIComponent(agentId)}/publication`,
      { status },
    )
    return data
  },

  async rotatePublicationKey(agentId: string): Promise<AgentPublicationSecret> {
    const { data } = await apiClient.post<AgentPublicationSecret>(
      `/api/agents/${encodeURIComponent(agentId)}/publication/api-key`,
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
