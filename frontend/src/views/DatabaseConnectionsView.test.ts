import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('naive-ui', () => ({
  NButton: { template: '<button><slot /></button>' },
  NCheckbox: { template: '<label><input type="checkbox" /><slot /></label>' },
  NForm: { template: '<form><slot /></form>' },
  NFormItem: { template: '<label><slot /></label>' },
  NIcon: { template: '<span><slot /></span>' },
  NInput: { template: '<input />' },
  NInputNumber: {
    props: ['value'],
    emits: ['update:value'],
    template: '<input type="number" :aria-label="$attrs[\'aria-label\']" :value="value" @input="$emit(\'update:value\', Number($event.target.value))" />',
  },
  NTabPane: { template: '<section><slot /></section>' },
  NTabs: { template: '<div><slot /></div>' },
  NModal: { template: '<div><slot /></div>' },
  NVirtualList: { props: ['items'], template: '<div><slot v-for="item in items" :item="item" /></div>' },
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

  it('exposes DM, Elasticsearch and mainstream database defaults', async () => {
    vi.spyOn(platformApi, 'listDatabaseConnections').mockResolvedValue([])
    const wrapper = mount(DatabaseConnectionsView, {
      global: {
        stubs: {
          PageHeader: { template: '<header><slot name="actions" /></header>' },
          StatusTag: true,
          NAlert: { template: '<div><slot /></div>' },
          NButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
          NIcon: { template: '<span><slot /></span>' },
          NInput: { template: '<input />' },
          NModal: { props: ['show'], template: '<div v-if="show"><slot /><slot name="footer" /></div>' },
          NSelect: { props: ['options'], template: '<div />' },
        },
      },
    })
    await flushPromises()
    const view = wrapper.vm as unknown as {
      databaseTypeOptions: Array<{ value: string; port: number | null }>
      form: { database_type: string; port: number | null; maintenance_database: string }
      applyDatabaseTypeDefaults: (value: string) => void
    }
    expect(view.databaseTypeOptions.map((item) => item.value)).toEqual(expect.arrayContaining([
      'postgresql', 'mysql', 'mariadb', 'doris', 'starrocks', 'sqlserver',
      'oracle', 'dm', 'clickhouse', 'elasticsearch', 'sqlite',
    ]))
    view.applyDatabaseTypeDefaults('dm')
    expect(view.form.port).toBe(5236)
    expect(view.form.maintenance_database).toBe('DM')
    view.applyDatabaseTypeDefaults('elasticsearch')
    expect(view.form.port).toBe(9200)
    wrapper.unmount()
  })
})
