import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useManagementStore } from './management'


describe('management store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('keeps the management key only in memory and clears it when locked', () => {
    const store = useManagementStore()
    store.unlock(' admin-secret ')
    expect(store.headers()).toEqual({ 'X-Platform-Management-Key': 'admin-secret' })
    expect(localStorage.length).toBe(0)
    store.lock()
    expect(store.headers()).toEqual({})
  })
})
