import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import type { KnowledgeSource, MCPServer, Skill } from '@/types/api'

export const useResourceStore = defineStore('resources', () => {
  const skills = ref<Skill[]>([])
  const mcpServers = ref<MCPServer[]>([])
  const knowledgeSources = ref<KnowledgeSource[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchAll(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const [skillList, mcpList, knowledgeList] = await Promise.all([
        platformApi.listSkills(),
        platformApi.listMCPServers(),
        platformApi.listKnowledgeSources(),
      ])
      skills.value = skillList
      mcpServers.value = mcpList
      knowledgeSources.value = knowledgeList
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      loading.value = false
    }
  }

  return { skills, mcpServers, knowledgeSources, loading, error, fetchAll }
})
