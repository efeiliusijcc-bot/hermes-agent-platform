import { defineComponent, nextTick, ref } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { useChatThreadViewport } from './useChatThreadViewport'

function mountViewport() {
  const Component = defineComponent({
    setup() {
      const sessionId = ref('session-a')
      return { sessionId, ...useChatThreadViewport(sessionId) }
    },
    template: '<div><div ref="threadElement" class="thread" @scroll="handleThreadScroll" /><button v-if="latestAvailable" @click="jumpToLatest">回到最新消息</button></div>',
  })
  return mount(Component)
}

function dimensions(element: HTMLElement, values: { clientHeight: number; scrollHeight: number; scrollTop: number }) {
  Object.defineProperty(element, 'clientHeight', { configurable: true, value: values.clientHeight })
  Object.defineProperty(element, 'scrollHeight', { configurable: true, value: values.scrollHeight })
  element.scrollTop = values.scrollTop
}

describe('useChatThreadViewport', () => {
  it('follows new content while near the bottom', async () => {
    const wrapper = mountViewport()
    const element = wrapper.get('.thread').element as HTMLElement
    dimensions(element, { clientHeight: 400, scrollHeight: 1000, scrollTop: 590 })

    await (wrapper.vm as unknown as { contentChanged: () => Promise<void> }).contentChanged()
    expect(element.scrollTop).toBe(1000)
    expect(wrapper.text()).not.toContain('回到最新消息')
    wrapper.unmount()
  })

  it('does not steal scroll position after the user reads older messages', async () => {
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
    const wrapper = mountViewport()
    const element = wrapper.get('.thread').element as HTMLElement
    dimensions(element, { clientHeight: 400, scrollHeight: 1400, scrollTop: 200 })
    await wrapper.get('.thread').trigger('scroll')
    await nextTick()

    await (wrapper.vm as unknown as { contentChanged: () => Promise<void> }).contentChanged()
    expect(element.scrollTop).toBe(200)
    expect(wrapper.text()).toContain('回到最新消息')

    await wrapper.get('button').trigger('click')
    expect(element.scrollTop).toBe(1400)
    expect(wrapper.text()).not.toContain('回到最新消息')
    vi.unstubAllGlobals()
    wrapper.unmount()
  })

  it('restores the stored position for each session', async () => {
    vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => { callback(0); return 1 })
    const wrapper = mountViewport()
    const vm = wrapper.vm as unknown as {
      sessionId: string
      rememberThreadPosition: (key?: string) => void
      restoreSessionPosition: () => Promise<void>
    }
    const element = wrapper.get('.thread').element as HTMLElement
    dimensions(element, { clientHeight: 400, scrollHeight: 1600, scrollTop: 320 })
    vm.rememberThreadPosition('session-a')

    vm.sessionId = 'session-b'
    element.scrollTop = 900
    vm.rememberThreadPosition('session-b')
    vm.sessionId = 'session-a'
    await vm.restoreSessionPosition()
    expect(element.scrollTop).toBe(320)
    vi.unstubAllGlobals()
    wrapper.unmount()
  })
})
