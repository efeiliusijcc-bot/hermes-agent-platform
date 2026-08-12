import { describe, expect, it, vi } from 'vitest'

vi.mock('./App.vue', () => ({ default: { template: '<div />' } }))
vi.mock('./router', () => ({ default: { install: vi.fn() } }))

describe('application bootstrap', () => {
  it('registers Naive UI components under their N-prefixed template names', async () => {
    document.body.innerHTML = '<div id="app"></div>'
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    await import('./main')

    expect(
      warn.mock.calls.some(([message]) =>
        String(message).includes('Failed to resolve component'),
      ),
    ).toBe(false)
    expect(document.querySelector('#app > div')).not.toBeNull()
  })
})
