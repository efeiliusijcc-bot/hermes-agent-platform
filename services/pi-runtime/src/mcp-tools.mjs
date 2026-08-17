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
