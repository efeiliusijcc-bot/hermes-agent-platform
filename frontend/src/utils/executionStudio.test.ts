import { describe, expect, it } from 'vitest'

import {
  buildSchemaParameters,
  createInitialSchemaValues,
  formatDurationMs,
  normalizeSchemaFields,
  parseSafeMarkdown,
} from './executionStudio'

const schema = {
  type: 'object',
  required: ['topic', 'count'],
  properties: {
    topic: { type: 'string', title: '主题' },
    count: { type: 'integer', default: 2 },
    enabled: { type: 'boolean' },
    tags: { type: 'array' },
  },
}

describe('execution studio schema helpers', () => {
  it('normalizes fields and creates deterministic initial values', () => {
    expect(normalizeSchemaFields(schema).map((field) => [field.key, field.required])).toEqual([
      ['topic', true], ['count', true], ['enabled', false], ['tags', false],
    ])
    expect(createInitialSchemaValues(schema)).toEqual({ topic: null, count: 2, enabled: false, tags: '[]' })
  })

  it('coerces schema values without fabricating missing required values', () => {
    const missing = buildSchemaParameters(schema, { count: '3', enabled: true, tags: '["a"]' })
    expect(missing.errors).toEqual({ topic: '此字段为必填项' })

    const valid = buildSchemaParameters(schema, { topic: 'Hermes', count: '3', enabled: true, tags: '["a"]' })
    expect(valid.errors).toEqual({})
    expect(valid.parameters).toEqual({ topic: 'Hermes', count: 3, enabled: true, tags: ['a'] })
  })

  it('formats unavailable metrics explicitly', () => {
    expect(formatDurationMs(null)).toBe('--')
    expect(formatDurationMs(1250)).toBe('1.3 s')
  })

  it('parses a safe markdown subset as text blocks', () => {
    expect(parseSafeMarkdown('# 标题\n- 项目\n```\n<a>\n```')).toEqual([
      { kind: 'heading', text: '标题' },
      { kind: 'list', text: '项目' },
      { kind: 'code', text: '<a>' },
    ])
  })
})
