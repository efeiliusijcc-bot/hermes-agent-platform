import net from 'node:net'

import { defineTool } from '@deepseek-ai/dsh-tools'


class DispatcherClient {
  constructor(fd) {
    this.socket = new net.Socket({ fd, readable: true, writable: true })
    this.pending = new Map()
    this.buffer = ''
    this.sequence = 0
    this.socket.setEncoding('utf8')
    this.socket.on('data', chunk => this.consume(chunk))
    this.socket.on('error', error => this.fail(error))
    this.socket.on('close', () => this.fail(new Error('Platform Capability dispatcher closed')))
  }

  consume(chunk) {
    this.buffer += chunk
    while (true) {
      const offset = this.buffer.indexOf('\n')
      if (offset < 0) return
      const raw = this.buffer.slice(0, offset)
      this.buffer = this.buffer.slice(offset + 1)
      if (!raw) continue
      let frame
      try { frame = JSON.parse(raw) } catch { continue }
      const waiter = this.pending.get(String(frame.id))
      if (!waiter) continue
      this.pending.delete(String(frame.id))
      if (frame.ok) waiter.resolve(frame)
      else waiter.reject(new Error(String(frame?.error?.message || 'Platform Capability call failed')))
    }
  }

  fail(error) {
    for (const waiter of this.pending.values()) waiter.reject(error)
    this.pending.clear()
  }

  request(payload, signal) {
    if (signal?.aborted) return Promise.reject(new Error('Platform Capability call cancelled'))
    const id = String(++this.sequence)
    return new Promise((resolve, reject) => {
      const abort = () => {
        this.pending.delete(id)
        reject(new Error('Platform Capability call cancelled'))
      }
      signal?.addEventListener('abort', abort, { once: true })
      this.pending.set(id, {
        resolve: value => { signal?.removeEventListener('abort', abort); resolve(value) },
        reject: error => { signal?.removeEventListener('abort', abort); reject(error) },
      })
      this.socket.write(`${JSON.stringify({ id, ...payload })}\n`, error => {
        if (error) {
          this.pending.delete(id)
          signal?.removeEventListener('abort', abort)
          reject(error)
        }
      })
    })
  }

  close() {
    this.socket.destroy()
    this.fail(new Error('Platform Capability dispatcher closed'))
  }
}


function propertySpec(schema, required = false) {
  if (!schema || typeof schema !== 'object' || Array.isArray(schema)) throw new Error('Invalid Capability input schema')
  const type = schema.type
  if (!['string', 'integer', 'number', 'boolean', 'array', 'object'].includes(type)) {
    throw new Error(`Unsupported Capability input type: ${String(type)}`)
  }
  const value = { type, ...(required ? { required: true } : {}) }
  for (const key of ['description', 'minimum', 'maximum', 'minLength', 'maxLength', 'minItems', 'maxItems']) {
    if (schema[key] !== undefined) value[key] = schema[key]
  }
  if (Array.isArray(schema.enum)) value.enum = [...schema.enum]
  if (type === 'array') value.items = propertySpec(schema.items || { type: 'string' })
  if (type === 'object') {
    const requiredNames = new Set(Array.isArray(schema.required) ? schema.required : [])
    value.properties = Object.fromEntries(
      Object.entries(schema.properties || {}).map(([name, child]) => [name, propertySpec(child, requiredNames.has(name))]),
    )
  }
  return value
}


function parameters(schema) {
  if (!schema || schema.type !== 'object' || typeof schema.properties !== 'object') {
    throw new Error('Capability input schema must be an object')
  }
  const required = new Set(Array.isArray(schema.required) ? schema.required : [])
  return Object.fromEntries(
    Object.entries(schema.properties).map(([name, value]) => [name, propertySpec(value, required.has(name))]),
  )
}


export const name = 'hermes-platform-capabilities'
export const inject = ['tools']

export async function apply(ctx) {
  const rawFd = process.env.HERMES_CAPABILITY_FD
  if (!rawFd) return
  const fd = Number(rawFd)
  if (!Number.isInteger(fd) || fd < 3) throw new Error('HERMES_CAPABILITY_FD is invalid')
  delete process.env.HERMES_CAPABILITY_FD
  const client = new DispatcherClient(fd)
  const listed = await client.request({ type: 'list' })
  for (const tool of listed.tools || []) {
    ctx.tools.register(defineTool({
      name: String(tool.tool_name),
      description: String(tool.description || tool.tool_name),
      parameters: parameters(tool.input_schema),
      output: {
        schema: { type: 'string' },
        render: (_args, value) => [{ type: 'text', text: value }],
      },
      async execute(args, exec) {
        const response = await client.request(
          { type: 'invoke', tool_name: String(tool.tool_name), arguments: args },
          exec.signal,
        )
        return JSON.stringify(response.data ?? null)
      },
    }))
  }
  ctx.on('dispose', () => client.close())
}
