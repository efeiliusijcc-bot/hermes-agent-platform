import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const fetchHealth = vi.fn().mockResolvedValue(undefined)
vi.mock('naive-ui', () => ({
  NIcon: { template: '<span><slot /></span>' },
}))
vi.mock('@/stores/system', () => ({
  useSystemStore: () => ({ health: true, error: null, fetchHealth }),
}))

import router from '@/router'
import AppLayout from './AppLayout.vue'

describe('AppLayout sidebar', () => {
  afterEach(() => vi.clearAllMocks())

  it('uses the Agent management brand and exposes a scrollable navigation region', async () => {
    await router.push('/orchestration')
    await router.isReady()
    const wrapper = mount(AppLayout, {
      global: {
        plugins: [router],
        stubs: {
          NMenu: {
            props: ['collapsed'],
            template: '<div class="menu-stub" :data-collapsed="String(collapsed)" />',
          },
          RouterView: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Agent 管理平台')
    expect(wrapper.text()).not.toContain('Hermes Platform')
    expect(wrapper.get('nav[aria-label="平台主导航"]')).toBeTruthy()
    expect(wrapper.get('.menu-stub').attributes('data-collapsed')).toBe('false')

    await wrapper.get('button[aria-label="收起导航"]').trigger('click')
    expect(wrapper.get('.app-shell').classes()).toContain('sidebar-collapsed')
    expect(wrapper.get('.menu-stub').attributes('data-collapsed')).toBe('true')
    expect(wrapper.get('button[aria-label="展开导航"]')).toBeTruthy()
    wrapper.unmount()
  })
})
