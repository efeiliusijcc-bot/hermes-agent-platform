import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('naive-ui', () => ({
  NButton: { template: '<button @click="$emit(\'click\')"><slot /></button>' },
  NCheckbox: {
    props: ['checked', 'disabled'],
    emits: ['update:checked'],
    template: '<label><input type="checkbox" :checked="checked" :disabled="disabled" @change="$emit(\'update:checked\', $event.target.checked)" /><slot /></label>',
  },
  NInput: {
    props: ['value'],
    emits: ['update:value'],
    template: '<input aria-label="搜索数据库对象" :value="value" @input="$emit(\'update:value\', $event.target.value)" />',
  },
  NVirtualList: {
    props: ['items'],
    template: '<div class="virtual-list-stub" :data-total="items.length"><template v-for="(item,index) in items.slice(0,20)" :key="item.key"><slot :item="item" :index="index" /></template></div>',
  },
}))

import type { DatabaseDiscovery } from '@/types/api'
import DatabaseObjectBrowser from './DatabaseObjectBrowser.vue'

function database(tableCount = 1000, viewCount = 25): DatabaseDiscovery['databases'][number] {
  return {
    name: 'analytics',
    status: 'READY',
    schemas: [{
      name: 'public',
      tables: Array.from({ length: tableCount }, (_, index) => ({
        name: `table_${index}`,
        columns: [{ name: `field_${index}`, type: 'text', udt: 'text', nullable: true }],
      })),
      views: Array.from({ length: viewCount }, (_, index) => ({
        name: `view_${index}`,
        columns: [{ name: `view_field_${index}`, type: 'text', udt: 'text', nullable: true }],
      })),
    }],
  }
}

describe('DatabaseObjectBrowser performance behavior', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('passes the full result set to a virtual list while rendering only its visible window', () => {
    const wrapper = mount(DatabaseObjectBrowser, { props: { database: database() } })

    expect(wrapper.get('.virtual-list-stub').attributes('data-total')).toBe('1025')
    expect(wrapper.findAll('.db-object-row')).toHaveLength(20)
  })

  it('debounces field search and supports bulk selection of the filtered result', async () => {
    vi.useFakeTimers()
    const wrapper = mount(DatabaseObjectBrowser, {
      props: { database: database(100, 5), selectable: true, selectedKeys: [] },
    })

    await wrapper.get('input[aria-label="搜索数据库对象"]').setValue('field_42')
    expect(wrapper.get('.virtual-list-stub').attributes('data-total')).toBe('105')
    await vi.advanceTimersByTimeAsync(150)
    expect(wrapper.get('.virtual-list-stub').attributes('data-total')).toBe('1')

    const selectVisible = wrapper.findAll('button').find((item) => item.text().includes('选择当前结果'))
    await selectVisible!.trigger('click')
    expect(wrapper.emitted('update:selectedKeys')?.at(-1)?.[0]).toHaveLength(1)
  })
})
