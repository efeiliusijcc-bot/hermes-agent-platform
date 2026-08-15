export type SchemaFieldType = 'string' | 'number' | 'integer' | 'boolean' | 'array' | 'object'

export interface SchemaField {
  key: string
  label: string
  description: string
  type: SchemaFieldType
  required: boolean
  enumValues: unknown[]
  defaultValue: unknown
}

type JsonSchema = Record<string, unknown>

function asRecord(value: unknown): JsonSchema {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as JsonSchema
    : {}
}

export function normalizeSchemaFields(schema: JsonSchema): SchemaField[] {
  const properties = asRecord(schema.properties)
  const required = new Set(Array.isArray(schema.required) ? schema.required.map(String) : [])
  return Object.entries(properties).map(([key, raw]) => {
    const definition = asRecord(raw)
    const enumValues = Array.isArray(definition.enum) ? definition.enum : []
    const declared = String(definition.type || (enumValues.length ? typeof enumValues[0] : 'string'))
    const type: SchemaFieldType = ['number', 'integer', 'boolean', 'array', 'object'].includes(declared)
      ? declared as SchemaFieldType
      : 'string'
    return {
      key,
      label: String(definition.title || key),
      description: String(definition.description || ''),
      type,
      required: required.has(key),
      enumValues,
      defaultValue: definition.default,
    }
  })
}

export function createInitialSchemaValues(schema: JsonSchema): Record<string, unknown> {
  return Object.fromEntries(normalizeSchemaFields(schema).map((field) => {
    if (field.defaultValue !== undefined) return [field.key, field.defaultValue]
    if (field.type === 'boolean') return [field.key, false]
    if (field.type === 'array') return [field.key, '[]']
    if (field.type === 'object') return [field.key, '{}']
    return [field.key, null]
  }))
}

function isEmpty(value: unknown): boolean {
  return value === undefined || value === null || (typeof value === 'string' && !value.trim())
}

export function coerceSchemaValue(field: SchemaField, value: unknown): unknown {
  if (isEmpty(value)) return undefined
  if (field.type === 'integer') {
    const parsed = Number(value)
    if (!Number.isInteger(parsed)) throw new Error('必须是整数')
    return parsed
  }
  if (field.type === 'number') {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) throw new Error('必须是数字')
    return parsed
  }
  if (field.type === 'boolean') return Boolean(value)
  if (field.type === 'array' || field.type === 'object') {
    if (typeof value !== 'string') return value
    let parsed: unknown
    try {
      parsed = JSON.parse(value)
    } catch {
      throw new Error('必须是有效 JSON')
    }
    if (field.type === 'array' && !Array.isArray(parsed)) throw new Error('必须是 JSON 数组')
    if (field.type === 'object' && (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))) {
      throw new Error('必须是 JSON 对象')
    }
    return parsed
  }
  return String(value)
}

export function buildSchemaParameters(
  schema: JsonSchema,
  values: Record<string, unknown>,
): { parameters: Record<string, unknown>; errors: Record<string, string> } {
  const parameters: Record<string, unknown> = {}
  const errors: Record<string, string> = {}
  for (const field of normalizeSchemaFields(schema)) {
    const raw = values[field.key]
    if (field.required && isEmpty(raw)) {
      errors[field.key] = '此字段为必填项'
      continue
    }
    try {
      const coerced = coerceSchemaValue(field, raw)
      if (coerced !== undefined) parameters[field.key] = coerced
    } catch (error) {
      errors[field.key] = error instanceof Error ? error.message : '字段格式错误'
    }
  }
  return { parameters, errors }
}

export function formatDurationMs(value: number | null | undefined): string {
  if (value === null || value === undefined || value < 0) return '--'
  if (value < 1000) return `${value} ms`
  if (value < 60_000) return `${(value / 1000).toFixed(1)} s`
  return `${Math.floor(value / 60_000)}m ${Math.round((value % 60_000) / 1000)}s`
}

export function formatCount(value: number | null | undefined): string {
  return value === null || value === undefined ? '--' : String(value)
}

export function formatJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? null, null, 2)
  } catch {
    return String(value)
  }
}

export interface MarkdownBlock {
  kind: 'heading' | 'paragraph' | 'list' | 'code'
  text: string
}

export function parseSafeMarkdown(value: string): MarkdownBlock[] {
  const blocks: MarkdownBlock[] = []
  let inCode = false
  let code = ''
  for (const sourceLine of value.split(/\r?\n/)) {
    const line = sourceLine.trimEnd()
    if (line.trim().startsWith('```')) {
      if (inCode) {
        blocks.push({ kind: 'code', text: code.replace(/\n$/, '') })
        code = ''
      }
      inCode = !inCode
      continue
    }
    if (inCode) {
      code += `${sourceLine}\n`
      continue
    }
    if (!line.trim()) continue
    if (/^#{1,6}\s+/.test(line)) blocks.push({ kind: 'heading', text: line.replace(/^#{1,6}\s+/, '') })
    else if (/^[-*]\s+/.test(line)) blocks.push({ kind: 'list', text: line.replace(/^[-*]\s+/, '') })
    else blocks.push({ kind: 'paragraph', text: line })
  }
  if (code) blocks.push({ kind: 'code', text: code.replace(/\n$/, '') })
  return blocks
}
