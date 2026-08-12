import { defineStore } from 'pinia'
import { ref } from 'vue'

import { getApiErrorMessage } from '@/api/client'
import { platformApi } from '@/api/platform'
import type { HealthStatus } from '@/types/api'

export const useSystemStore = defineStore('system', () => {
  const health = ref<HealthStatus | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function fetchHealth(): Promise<void> {
    loading.value = true
    error.value = null
    try {
      health.value = await platformApi.health()
    } catch (cause) {
      health.value = null
      error.value = getApiErrorMessage(cause)
      throw cause
    } finally {
      loading.value = false
    }
  }

  return { health, loading, error, fetchHealth }
})
