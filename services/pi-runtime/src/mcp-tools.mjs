import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'

const CAPABILITY_TOOLS = {
  filesystem: new Set(['filesystem_read']),
  database: new Set(['database_query']),
}

const TOOL_DESCRIPTIONS = {
  filesystem_read: 'Read one authorized UTF-8 text file from the platform-managed workspace.',
  database_query: 'Run one authorized read-only PostgreSQL SELECT or WITH query.',
}

export function sanitizeInputSchema(inputSchema) {
  const source = inputSchema && typeof inputSchema === 'object' ? inputSchema : {}
  const properties = { ...(source.properties || {}) }
  delete properties.access_token
  return {
    ...source,
    type: 'object',
    properties,
    required: Array.isArray(source.required)
      ? source.required.filter((name) => name !== 'access_token')
      : [],
    additionalProperties: false,
  }
}

function allowedToolNames(capabilities) {
  const names = new Set()
  for (const capability of capabilities) {
    for (const name of CAPABILITY_TOOLS[capability] || []) names.add(name)
  }
  return names
}

function textContent(content) {
  if (!Array.isArray(content)) return [{ type: 'text', text: JSON.stringify(content ?? null) }]
  const values = content
    .filter((item) => item && item.type === 'text' && typeof item.text === 'string')
    .map((item) => ({ type: 'text', text: item.text }))
  return values.length ? values : [{ type: 'text', text: 'MCP tool completed without text output.' }]
}

export async function loadMcpTools({ endpoint, accessToken, capabilities, executionId }) {
  if (!capabilities.length) return { tools: [], close: async () => {} }
  if (!accessToken) throw new Error('MCP access token is missing from the platform context')

  const client = new Client({ name: 'hermes-pi-runtime', version: '1.0.0' })
  const transport = new StreamableHTTPClientTransport(new URL(endpoint))
  await client.connect(transport)
  const listed = await client.listTools()
  const allowed = allowedToolNames(capabilities)
  const tools = listed.tools
    .filter((tool) => allowed.has(tool.name))
    .map((tool) => ({
      name: tool.name,
      label: tool.title || tool.name,
      description: TOOL_DESCRIPTIONS[tool.name] || `Authorized MCP tool ${tool.name}`,
      parameters: sanitizeInputSchema(tool.inputSchema),
      executionMode: 'sequential',
      execute: async (_toolCallId, parameters, signal) => {
        if (signal?.aborted) throw new Error('MCP tool call was cancelled')
        const result = await client.callTool(
          {
            name: tool.name,
            // The legacy MCP contract still accepts the short-lived mcp2 token
            // as a server-side argument. The schema exposed to the model is
            // sanitized above, so the model can neither see nor supply it.
            arguments: { ...parameters, access_token: accessToken },
          },
          undefined,
          { signal },
        )
        if (result.isError) throw new Error(`MCP tool ${tool.name} failed`)
        return {
          content: textContent(result.content),
          details: { tool: tool.name, execution_id: executionId },
        }
      },
    }))

  if (tools.length !== allowed.size) {
    const loaded = new Set(tools.map((tool) => tool.name))
    const missing = [...allowed].filter((name) => !loaded.has(name))
    await client.close()
    throw new Error(`Authorized MCP tools are unavailable: ${missing.join(', ')}`)
  }
  return { tools, close: () => client.close() }
}

function tokenExpiry(token) {
  try {
    const payload = JSON.parse(Buffer.from(String(token).split('.')[1] || '', 'base64url').toString('utf8'))
    return Number.isInteger(payload?.exp) ? payload.exp : 0
  } catch {
    return 0
  }
}

function resolveEndpoint(endpoint) {
  return endpoint.endsWith('/invoke') ? `${endpoint.slice(0, -'/invoke'.length)}/resolve` : endpoint
}

export function loadCapabilityTools({ endpoint, token, tools, executionId, fetchImpl = fetch }) {
  if (!Array.isArray(tools) || tools.length === 0) {
    return { tools: [], close: async () => {} }
  }
  if (!endpoint || !token) throw new Error('Capability Gateway context is incomplete')
  let accessToken = token
  let renewal
  let closed = false

  async function renewIfNeeded(force = false) {
    if (closed) throw new Error('Capability dispatcher is closed')
    const expiresAt = tokenExpiry(accessToken)
    const now = Math.floor(Date.now() / 1000)
    if (!force && expiresAt > now + 120) return
    if (!renewal) {
      renewal = (async () => {
        const response = await fetchImpl(resolveEndpoint(endpoint), {
          method: 'POST',
          headers: {
            Accept: 'application/json',
            Authorization: `Bearer ${accessToken}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ execution_id: executionId }),
        })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok || payload.status !== 'SUCCEEDED') {
          throw new Error(payload?.error?.message || 'Capability Token renewal failed')
        }
        if (typeof payload?.metadata?.token_renewal === 'string') {
          accessToken = payload.metadata.token_renewal
        }
      })().finally(() => { renewal = undefined })
    }
    await renewal
  }

  const timer = setInterval(() => {
    renewIfNeeded().catch(() => {})
  }, 30_000)
  timer.unref?.()

  const runtimeTools = tools.map((tool) => ({
    name: String(tool.tool_name),
    label: String(tool.tool_name),
    description: String(tool.description || `Platform capability ${tool.capability_key}`),
    parameters: sanitizeInputSchema(tool.input_schema),
    executionMode: 'sequential',
    execute: async (_toolCallId, parameters, signal) => {
      try {
        await renewIfNeeded()
      } catch (error) {
        if (tokenExpiry(accessToken) <= Math.floor(Date.now() / 1000)) throw error
      }
      const response = await fetchImpl(endpoint, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          Authorization: `Bearer ${accessToken}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          execution_id: executionId,
          tool_name: tool.tool_name,
          arguments: parameters || {},
        }),
        signal,
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok || payload.status !== 'SUCCEEDED') {
        throw new Error(payload?.error?.message || `Capability ${tool.tool_name} failed`)
      }
      if (typeof payload?.metadata?.token_renewal === 'string') {
        accessToken = payload.metadata.token_renewal
      }
      return {
        content: [{ type: 'text', text: JSON.stringify(payload.data ?? null) }],
        details: {
          tool: tool.tool_name,
          execution_id: executionId,
          invocation_id: payload.invocation_id,
        },
      }
    },
  }))
  return {
    tools: runtimeTools,
    close: async () => {
      closed = true
      clearInterval(timer)
      accessToken = ''
      if (renewal) await renewal.catch(() => {})
    },
  }
}
