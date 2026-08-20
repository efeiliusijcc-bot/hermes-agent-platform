import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('naive-ui', () => ({
  NForm: { template: '<form><slot /></form>' },
  NFormItem: { template: '<label><slot /></label>' },
  NIcon: { template: '<span><slot /></span>' },
  NInputNumber: { template: '<input type="number" />' },
  NModal: { props: ['show'], template: '<section v-if="show"><slot /><slot name="footer" /></section>' },
  useMessage: () => ({ success: vi.fn(), warning: vi.fn(), error: vi.fn() }),
}))

import { apiClient } from '@/api/client'
import { platformApi } from '@/api/platform'
import PlatformConnectionsView from './PlatformConnectionsView.vue'

describe('PlatformConnectionsView management actions', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(platformApi, 'listPlatformConnections').mockResolvedValue([{
      id: 'connector-1', key: 'knowledge.search', name: '内部知识检索', type: 'internal_rest',
      status: 'READY', capability_count: 1, instances: 1, updated_at: '2026-08-20T00:00:00Z',
    }])
    vi.spyOn(platformApi, 'listCapabilities').mockResolvedValue([{
      id: 'capability-1', namespace: 'knowledge', key: 'search', display_name: '知识检索',
      description: '检索内部知识', risk_level: 'LOW', status: 'published',
      created_at: '2026-08-20T00:00:00Z', updated_at: '2026-08-20T00:00:00Z',
    }])
    vi.spyOn(platformApi, 'listCredentials').mockResolvedValue([{
      id: 'credential-1', name: '知识检索密钥', credential_type: 'api_key', masked_label: 'abc***',
      key_id: 'key-1', rotation_status: 'active', last_rotated_at: '2026-08-20T00:00:00Z',
      created_at: '2026-08-20T00:00:00Z', updated_at: '2026-08-20T00:00:00Z',
    }])
  })

  it('opens real connector, capability and credential management flows', async () => {
    const get = vi.spyOn(apiClient, 'get').mockImplementation(async (url: string) => {
      if (url === '/api/connectors/connector-1') return { data: { display_name: '内部知识检索', description: '说明', status: 'published' } }
      if (url === '/api/console/platform/connections/connector-1') return { data: { instances: [{ id: 'instance-1', name: 'production', environment: 'production', health: 'healthy', enabled: true, current_revision_id: null }] } }
      if (url === '/api/connectors/connector-1/operations') return { data: [] }
      if (url === '/api/capabilities/capability-1/versions') return { data: [] }
      return { data: [] }
    })
    const patch = vi.spyOn(apiClient, 'patch').mockResolvedValue({ data: {} })

    const wrapper = mount(PlatformConnectionsView, {
      global: {
        stubs: {
          PageHeader: { template: '<header><slot name="actions" /></header>' },
          AdminGuideLink: true,
          StatusTag: { template: '<span><slot /></span>' },
          NAlert: { template: '<div><slot /></div>' },
          NButton: { template: '<button @click="$emit(\'click\')"><slot name="icon" /><slot /></button>' },
          NInput: { template: '<input />' },
          NSelect: { template: '<div />' },
          NTabs: { template: '<div><slot /></div>' },
          NTabPane: { template: '<section><slot /></section>' },
        },
      },
    })
    await flushPromises()

    const manageButtons = wrapper.findAll('button').filter((button) => button.text().includes('管理'))
    expect(manageButtons).toHaveLength(2)
    await manageButtons[0]!.trigger('click')
    await flushPromises()
    expect(get).toHaveBeenCalledWith('/api/connectors/connector-1')
    expect(get).toHaveBeenCalledWith('/api/console/platform/connections/connector-1')
    expect(wrapper.text()).toContain('创建新 Revision 并测试')
    await wrapper.findAll('button').find((button) => button.text().includes('保存基础信息'))!.trigger('click')
    await flushPromises()
    expect(patch).toHaveBeenCalledWith('/api/connectors/connector-1', expect.objectContaining({ display_name: '内部知识检索' }))

    await manageButtons[1]!.trigger('click')
    await flushPromises()
    expect(get).toHaveBeenCalledWith('/api/capabilities/capability-1/versions')
    expect(wrapper.text()).toContain('创建新 Draft Version')

    const rotate = wrapper.findAll('button').find((button) => button.text().includes('轮换'))
    expect(rotate).toBeDefined()
    await rotate!.trigger('click')
    expect(wrapper.text()).toContain('新密钥只通过当前请求提交')
    wrapper.unmount()
  })
})
