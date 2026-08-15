import { describe, expect, it, vi } from 'vitest'
import { getCurrentInstance } from 'vue'

let registeredComponents: string[] = []
vi.mock('./App.vue', () => ({
  default: {
    setup() {
      registeredComponents = Object.keys(getCurrentInstance()?.appContext.components || {})
    },
    template: '<div />',
  },
}))
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
    expect(registeredComponents).toEqual(expect.arrayContaining(['NAlert', 'NButton', 'NInput']))
    expect(registeredComponents).not.toContain('NInputNumber')
    expect(registeredComponents).not.toContain('NDatePicker')
    expect(document.querySelector('#app > div')).not.toBeNull()
  })
})
