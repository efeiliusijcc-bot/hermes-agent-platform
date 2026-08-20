import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('naive-ui', () => ({
  NCheckbox: { template: '<label><input type="checkbox" /><slot /></label>' },
  NIcon: { template: '<span><slot /></span>' },
  NInputNumber: {
    props: ['value'],
    emits: ['update:value'],
    template: '<input type="number" :aria-label="$attrs[\'aria-label\']" :value="value" @input="$emit(\'update:value\', Number($event.target.value))" />',
  },
  NTabPane: { template: '<section><slot /></section>' },
  NTabs: { template: '<div><slot /></div>' },
  useDialog: () => ({ warning: vi.fn() }),
  useMessage: () => ({ success: vi.fn(), warning: vi.fn(), error: vi.fn() }),
}))

import { platformApi } from '@/api/platform'
import DatabaseConnectionsView from './DatabaseConnectionsView.vue'

describe('DatabaseConnectionsView connection form', () => {
  afterEach(() => vi.restoreAllMocks())

  it('renders an editable PostgreSQL port control with the default value', async () => {
    vi.spyOn(platformApi, 'listDatabaseConnections').mockResolvedValue([])
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    const wrapper = mount(DatabaseConnectionsView, {
      global: {
        stubs: {
          PageHeader: { template: '<header><slot name="actions" /></header>' },
          StatusTag: true,
          NAlert: { template: '<div><slot /></div>' },
          NButton: { template: '<button @click="$emit(\'click\')"><slot name="icon" /><slot /></button>' },
          NForm: { template: '<form><slot /></form>' },
          NFormItem: { template: '<label><slot /></label>' },
          NInput: { template: '<input />' },
          NModal: { props: ['show'], template: '<div v-if="show"><slot /><slot name="footer" /></div>' },
          NSelect: { template: '<select />' },
        },
      },
    })
    await flushPromises()

    const create = wrapper.findAll('button').find((item) => item.text().includes('创建数据库连接'))
    expect(create).toBeDefined()
    await create!.trigger('click')

    const port = wrapper.get('input[aria-label="端口"]')
    expect((port.element as HTMLInputElement).value).toBe('5432')
    await port.setValue('15432')
    expect((port.element as HTMLInputElement).value).toBe('15432')
    expect(warn.mock.calls.some(([message]) => String(message).includes('Failed to resolve component: NInputNumber'))).toBe(false)

    wrapper.unmount()
  })
})
