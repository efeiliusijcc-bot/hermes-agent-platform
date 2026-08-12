import { apiClient } from './client'
import type {
  Agent,
  AgentCreatePayload,
  AgentRunPayload,
  AgentRunResponse,
  ExecutionLog,
  HealthStatus,
  KnowledgeSource,
  MCPServer,
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
      `/api/agents/${encodeURIComponent(agentId)}/run`,
      payload,
    )
    return data
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
