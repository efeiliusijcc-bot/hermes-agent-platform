import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import { NInput, NInputNumber, NSelect, NSwitch } from 'naive-ui'

import SchemaForm from './SchemaForm.vue'


describe('SchemaForm', () => {
  it('uses safe UI schema ordering and textarea metadata', () => {
    const wrapper = mount(SchemaForm, {
      global: { components: { NInput, NInputNumber, NSelect, NSwitch } },
      props: {
        schema: {
          type: 'object',
          properties: {
            top_k: { type: 'integer', title: '数量' },
            query: { type: 'string', title: '查询' },
          },
          required: ['query'],
        },
        uiSchema: {
          order: ['query', 'top_k'],
          fields: {
            query: { widget: 'textarea', label: '查询内容', help: '输入检索主题', rows: 5 },
          },
        },
        values: {},
        errors: {},
      },
    })
    const labels = wrapper.findAll('label').map((item) => item.text())
    expect(labels[0]).toContain('查询内容')
    expect(labels[1]).toContain('数量')
    expect(wrapper.find('textarea').exists()).toBe(true)
    expect(wrapper.text()).toContain('输入检索主题')
  })
})
