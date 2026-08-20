import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import router from '@/router'
import PlatformAdminGuideView from './PlatformAdminGuideView.vue'

describe('PlatformAdminGuideView', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback: FrameRequestCallback) => {
      callback(0)
      return 1
    })
    vi.spyOn(window, 'scrollTo').mockImplementation(() => undefined)
    vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      const tops: Record<string, number> = { 'guide-database': 900, 'guide-settings': 1400 }
      return { top: tops[(this as HTMLElement).id] || 0 } as DOMRect
    })
  })

  it('restores the requested section and filters by administrator terminology', async () => {
    await router.push('/help/platform-management?section=database')
    await router.isReady()
    const wrapper = mount(PlatformAdminGuideView, {
      attachTo: document.body,
      global: {
        plugins: [router],
        stubs: {
          NButton: { template: '<button><slot /></button>' },
          NDrawer: { template: '<div><slot /></div>' },
          NDrawerContent: { template: '<div><slot /></div>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('数据库连接')
    expect(wrapper.text()).toContain('模型管理')
    const databaseButton = wrapper.findAll('.admin-guide-toc button').find((button) => button.text() === '数据库连接')
    expect(databaseButton?.classes()).toContain('active')
    await vi.waitFor(() => {
      expect(window.scrollTo).toHaveBeenCalledWith({ top: 822, behavior: 'auto' })
    })

    const settingsButton = wrapper.findAll('.admin-guide-toc button').find((button) => button.text() === 'Settings')
    await settingsButton?.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.section).toBe('settings')
    await vi.waitFor(() => {
      expect(window.scrollTo).toHaveBeenLastCalledWith({ top: 1322, behavior: 'auto' })
    })

    await wrapper.get('.n-input__input-el').setValue('写 CTE')
    await flushPromises()
    expect(wrapper.text()).toContain('查询被安全策略拒绝')
    expect(wrapper.text()).not.toContain('上游模型名或 Base URL 路径不正确')

    await wrapper.get('.n-input__input-el').setValue('完全不存在的关键词')
    await flushPromises()
    expect(wrapper.text()).toContain('没有找到相关内容')
    wrapper.unmount()
  })
})
