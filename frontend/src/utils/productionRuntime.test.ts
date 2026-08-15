import { describe, expect, it, vi } from 'vitest'

import {
  agentConfigurationLockMessage,
  confirmAgentRollback,
  isAgentConfigurationLocked,
  isValidClientRateLimit,
} from './productionRuntime'

describe('Phase 4 frontend production safeguards', () => {
  it('locks the live configuration when a Version is published or the Agent is archived', () => {
    expect(isAgentConfigurationLocked('draft')).toBe(false)
    expect(isAgentConfigurationLocked('testing')).toBe(false)
    expect(isAgentConfigurationLocked('suspended')).toBe(false)
    expect(isAgentConfigurationLocked('published')).toBe(true)
    expect(isAgentConfigurationLocked('active')).toBe(false)
    expect(isAgentConfigurationLocked('active', 'published-version-id')).toBe(true)
    expect(isAgentConfigurationLocked('archived')).toBe(true)
    expect(agentConfigurationLockMessage('published')).toContain('新的 Agent Version')
    expect(agentConfigurationLockMessage('archived')).toContain('只读状态')
  })

  it('uses the backend API Client rate-limit bounds', () => {
    expect(isValidClientRateLimit(1)).toBe(true)
    expect(isValidClientRateLimit(60)).toBe(true)
    expect(isValidClientRateLimit(100_000)).toBe(true)
    expect(isValidClientRateLimit(0)).toBe(false)
    expect(isValidClientRateLimit(1.5)).toBe(false)
    expect(isValidClientRateLimit(100_001)).toBe(false)
  })

  it('does not perform rollback until the confirmation is accepted', async () => {
    const performRollback = vi.fn()
    let options: Record<string, unknown> | undefined
    const dialog = {
      warning: vi.fn((value: Record<string, unknown>) => {
        options = value
        return {} as never
      }),
    }

    confirmAgentRollback(dialog, 'v1 stable', performRollback)

    expect(performRollback).not.toHaveBeenCalled()
    expect(dialog.warning).toHaveBeenCalledOnce()
    expect(options?.content).toContain('v1 stable')
    await (options?.onPositiveClick as () => Promise<void>)()
    expect(performRollback).toHaveBeenCalledOnce()
  })
})
