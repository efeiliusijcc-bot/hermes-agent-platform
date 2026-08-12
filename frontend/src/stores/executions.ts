import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import type { AgentRunResponse, ExecutionLog } from '@/types/api'

export const useExecutionStore = defineStore('executions', () => {
  const runs = ref<ExecutionLog[]>([])
  const currentRun = ref<ExecutionLog | null>(null)
  const currentResult = ref<AgentRunResponse | null>(null)
  const loading = ref(false)
  const running = ref(false)
  const error = ref<string | null>(null)

  async function fetchRuns(agentId: string): Promise<void> {
    loading.value = true
    error.value = null
    try {
      runs.value = await platformApi.listAgentRuns(agentId)
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function runAgent(agentId: string, input: string, sessionId: string): Promise<AgentRunResponse> {
    running.value = true
    error.value = null
    currentResult.value = null
    currentRun.value = null
    try {
      const result = await platformApi.runAgent(agentId, { input, session_id: sessionId })
      currentResult.value = result
      runs.value = await platformApi.listAgentRuns(agentId)
      currentRun.value = runs.value.find((run) => run.id === result.execution_id) || null
      return result
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      try {
        runs.value = await platformApi.listAgentRuns(agentId)
        currentRun.value = runs.value[0] || null
      } catch {
        // The primary execution error remains the useful message.
      }
      throw cause
    } finally {
      running.value = false
    }
  }

  function selectRun(run: ExecutionLog): void {
    currentRun.value = run
  }

  return {
    runs,
    currentRun,
    currentResult,
    loading,
    running,
    error,
    fetchRuns,
    runAgent,
    selectRun,
  }
})
