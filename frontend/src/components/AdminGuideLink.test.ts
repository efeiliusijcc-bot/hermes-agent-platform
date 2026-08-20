import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AdminGuideLink from './AdminGuideLink.vue'

describe('AdminGuideLink', () => {
  it('opens a contextual guide section', () => {
    const wrapper = mount(AdminGuideLink, {
      props: { section: 'models' },
      global: {
        stubs: {
          NButton: { props: ['href'], template: '<a :href="href"><slot /></a>' },
          NIcon: { template: '<span><slot /></span>' },
        },
      },
    })
    expect(wrapper.get('a').attributes('href')).toBe('/help/platform-management?section=models')
  })

  it('is present on every platform management page', () => {
    const root = resolve(process.cwd(), 'src/views')
    const pages = {
      PlatformConnectionsView: 'connections', DatabaseConnectionsView: 'database', ModelManagementView: 'models',
      RuntimeListView: 'runtimes', APIManagementView: 'api', OperationsView: 'operations', SettingsView: 'settings',
    }
    for (const [page, section] of Object.entries(pages)) {
      const source = readFileSync(resolve(root, `${page}.vue`), 'utf8')
      expect(source).toContain(`<AdminGuideLink section="${section}"`)
    }
  })
})
