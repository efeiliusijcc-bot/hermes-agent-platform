import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import type {
  AgentRunResponse,
  AgentStreamEvent,
  ExecutionDetail,
  ExecutionLog,
  ExecutionMetrics,
  ExecutionSummary,
  ExecutionTrace,
  ResponseMode,
} from '@/types/api'

export const useExecutionStore = defineStore('executions', () => {
  const runs = ref<ExecutionLog[]>([])
  const histories = ref<ExecutionSummary[]>([])
  const total = ref(0)
  const currentRun = ref<ExecutionLog | null>(null)
  const currentExecution = ref<ExecutionDetail | null>(null)
  const currentTrace = ref<ExecutionTrace | null>(null)
  const metrics = ref<ExecutionMetrics>({
    total_executions: 0,
    running: 0,
    succeeded: 0,
    failed: 0,
    cancelled: 0,
    success_rate: null,
  })
  const currentResult = ref<AgentRunResponse | null>(null)
  const streamEvents = ref<AgentStreamEvent[]>([])
  const streamedOutput = ref('')
  const loading = ref(false)
  const running = ref(false)
  const retrying = ref(false)
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

  async function fetchHistories(params: {
    agent_id?: string
    status?: string
    search?: string
    started_from?: string
    started_to?: string
    limit?: number
    offset?: number
  } = {}): Promise<void> {
    loading.value = true
    error.value = null
    try {
      const result = await platformApi.listExecutions(params)
      histories.value = result.items
      total.value = result.total
      metrics.value = result.metrics
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function fetchTrace(executionId: string): Promise<ExecutionTrace> {
    loading.value = true
    error.value = null
    try {
      currentTrace.value = await platformApi.getExecutionTrace(executionId)
      return currentTrace.value
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function fetchExecution(executionId: string): Promise<ExecutionDetail> {
    loading.value = true
    error.value = null
    try {
      currentExecution.value = await platformApi.getExecution(executionId)
      return currentExecution.value
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      loading.value = false
    }
  }

  async function runAgent(
    agentId: string,
    input: string,
    sessionId: string,
    responseMode: ResponseMode = 'sync',
    parameters?: Record<string, unknown>,
    temperature?: number | null,
  ): Promise<AgentRunResponse | null> {
    running.value = true
    error.value = null
    currentResult.value = null
    currentRun.value = null
    currentExecution.value = null
    streamEvents.value = []
    streamedOutput.value = ''
    const payload = {
      input,
      session_id: sessionId,
      ...(parameters ? { parameters } : {}),
      ...(temperature === null || temperature === undefined ? {} : { temperature }),
    }
    try {
      if (responseMode === 'stream') {
        let streamError: Error | null = null
        await platformApi.streamAgent(agentId, payload, (event) => {
          streamEvents.value.push(event)
          if (event.event === 'token') streamedOutput.value += String(event.text || '')
          if (event.event === 'error') streamError = new Error(String(event.message || '流式执行失败'))
        })
        if (streamError) throw streamError
        const executionId = String(streamEvents.value.find((event) => event.event === 'start')?.execution_id || '')
        if (executionId) currentExecution.value = await platformApi.getExecution(executionId)
        return null
      }
      const result = await platformApi.runAgent(agentId, payload)
      currentResult.value = result
      currentExecution.value = await platformApi.getExecution(result.execution_id)
      return result
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      running.value = false
    }
  }

  async function retryExecution(executionId: string, priority?: number): Promise<string> {
    retrying.value = true
    error.value = null
    try {
      const task = await platformApi.retryExecution(
        executionId,
        priority === undefined ? {} : { priority },
      )
      return task.execution_id || task.id
    } catch (cause) {
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      retrying.value = false
    }
  }

  function selectRun(run: ExecutionLog): void {
    currentRun.value = run
  }

  return {
    runs,
    histories,
    total,
    currentRun,
    currentExecution,
    currentTrace,
    metrics,
    currentResult,
    streamEvents,
    streamedOutput,
    loading,
    running,
    retrying,
    error,
    fetchRuns,
    fetchHistories,
    fetchExecution,
    fetchTrace,
    runAgent,
    retryExecution,
    selectRun,
  }
})
