import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { setManagementKey } from '@/api/managementKey'


export const useManagementStore = defineStore('platform-management', () => {
  const key = ref('')
  const unlocked = computed(() => Boolean(key.value))

  function unlock(value: string) {
    key.value = value.trim()
    setManagementKey(key.value)
  }

  function lock() {
    key.value = ''
    setManagementKey('')
  }

  function headers(): Record<string, string> {
    return key.value ? { 'X-Platform-Management-Key': key.value } : {}
  }

  return { key, unlocked, unlock, lock, headers }
})
