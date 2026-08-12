import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import type {
  Agent,
  CreateAgentWorkflowPayload,
  CreateAgentWorkflowResult,
  KnowledgeSource,
  MCPServer,
  Skill,
} from '@/types/api'

export const useAgentStore = defineStore('agents', () => {
  const agents = ref<Agent[]>([])
  const currentAgent = ref<Agent | null>(null)
  const currentSkills = ref<Skill[]>([])
  const currentMCPServers = ref<MCPServer[]>([])
  const currentKnowledgeSources = ref<KnowledgeSource[]>([])
  const loading = ref(false)
  const detailLoading = ref(false)
  const error = ref<string | null>(null)

  const activeAgentCount = computed(() => agents.value.filter((agent) => agent.status === 'active').length)

  async function fetchAgents(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      agents.value = await platformApi.listAgents()
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function fetchAgentDetail(agentId: string): Promise<void> {
    detailLoading.value = true
    error.value = null
    const requestedId = agentId
    try {
      const [agent, skills, mcpServers, knowledgeSources] = await Promise.all([
        platformApi.getAgent(agentId),
        platformApi.listAgentSkills(agentId),
        platformApi.listAgentMCPServers(agentId),
        platformApi.listAgentKnowledgeSources(agentId),
      ])
      if (requestedId !== agentId) return
      currentAgent.value = agent
      currentSkills.value = skills
      currentMCPServers.value = mcpServers
      currentKnowledgeSources.value = knowledgeSources
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      detailLoading.value = false
    }
  }

  async function createAgentWorkflow(
    payload: CreateAgentWorkflowPayload,
  ): Promise<CreateAgentWorkflowResult> {
    const agent = await platformApi.createAgent(payload.agent)
    const bindingErrors: string[] = []

    const bindings = [
      ...payload.skillIds.map((id) => ({ kind: 'Skill', id, request: platformApi.bindAgentSkill(agent.id, id) })),
      ...payload.mcpIds.map((id) => ({ kind: 'MCP', id, request: platformApi.bindAgentMCPServer(agent.id, id) })),
    ]
    const results = await Promise.allSettled(bindings.map((binding) => binding.request))
    results.forEach((result, index) => {
      if (result.status === 'rejected') {
        const binding = bindings[index]
        bindingErrors.push(`${binding.kind} ${binding.id}: ${getApiErrorMessage(result.reason)}`)
      }
    })
    agents.value.push(agent)
    return { agent, bindingErrors }
  }

  async function removeAgent(agentId: string): Promise<void> {
    await platformApi.deleteAgent(agentId)
    agents.value = agents.value.filter((agent) => agent.id !== agentId)
    if (currentAgent.value?.id === agentId) currentAgent.value = null
  }

  async function syncSkills(agentId: string, selectedIds: string[]): Promise<void> {
    const currentIds = new Set(currentSkills.value.map((skill) => skill.id))
    const selected = new Set(selectedIds)
    await Promise.all([
      ...selectedIds.filter((id) => !currentIds.has(id)).map((id) => platformApi.bindAgentSkill(agentId, id)),
      ...[...currentIds].filter((id) => !selected.has(id)).map((id) => platformApi.unbindAgentSkill(agentId, id)),
    ])
    currentSkills.value = await platformApi.listAgentSkills(agentId)
  }

  async function syncMCPServers(agentId: string, selectedIds: string[]): Promise<void> {
    const currentIds = new Set(currentMCPServers.value.map((server) => server.id))
    const selected = new Set(selectedIds)
    await Promise.all([
      ...selectedIds
        .filter((id) => !currentIds.has(id))
        .map((id) => platformApi.bindAgentMCPServer(agentId, id)),
      ...[...currentIds]
        .filter((id) => !selected.has(id))
        .map((id) => platformApi.unbindAgentMCPServer(agentId, id)),
    ])
    currentMCPServers.value = await platformApi.listAgentMCPServers(agentId)
  }

  async function syncKnowledgeSources(agentId: string, selectedIds: string[]): Promise<void> {
    const currentIds = new Set(currentKnowledgeSources.value.map((source) => source.id))
    const selected = new Set(selectedIds)
    await Promise.all([
      ...selectedIds
        .filter((id) => !currentIds.has(id))
        .map((id) => platformApi.bindAgentKnowledgeSource(agentId, id)),
      ...[...currentIds]
        .filter((id) => !selected.has(id))
        .map((id) => platformApi.unbindAgentKnowledgeSource(agentId, id)),
    ])
    currentKnowledgeSources.value = await platformApi.listAgentKnowledgeSources(agentId)
  }

  return {
    agents,
    currentAgent,
    currentSkills,
    currentMCPServers,
    currentKnowledgeSources,
    loading,
    detailLoading,
    error,
    activeAgentCount,
    fetchAgents,
    fetchAgentDetail,
    createAgentWorkflow,
    removeAgent,
    syncSkills,
    syncMCPServers,
    syncKnowledgeSources,
  }
})
