const integer = (name, fallback, minimum, maximum) => {
  const raw = process.env[name]
  const value = raw === undefined || raw === '' ? fallback : Number.parseInt(raw, 10)
  if (!Number.isInteger(value) || value < minimum || value > maximum) {
    throw new Error(`${name} must be an integer between ${minimum} and ${maximum}`)
  }
  return value
}

const requiredSecret = (name) => {
  const value = String(process.env[name] || '')
  if (value.length < 32) throw new Error(`${name} must contain at least 32 characters`)
  return value
}

const httpUrl = (name, fallback) => {
  const raw = String(process.env[name] || fallback || '').replace(/\/$/, '')
  const value = new URL(raw)
  if (!['http:', 'https:'].includes(value.protocol) || value.username || value.password) {
    throw new Error(`${name} must be an HTTP(S) URL without embedded credentials`)
  }
  return raw
}

export function loadConfig() {
  return {
    host: process.env.HOST || '0.0.0.0',
    port: integer('PORT', 8765, 1, 65535),
    runtimeApiKey: requiredSecret('PI_RUNTIME_API_KEY'),
    runtimeVersion: process.env.PI_CORE_VERSION || '0.84.2',
    serviceVersion: process.env.PI_RUNTIME_SERVICE_VERSION || '1.0.0',
    modelGatewayEndpoint: httpUrl('MODEL_GATEWAY_ENDPOINT', 'http://model-gateway:8080/v1'),
    modelGatewayApiKey: requiredSecret('MODEL_GATEWAY_API_KEY'),
    mcpGatewayEndpoint: httpUrl('MCP_GATEWAY_ENDPOINT', 'http://mcp-gateway:8090/mcp'),
    maxConcurrency: integer('PI_RUNTIME_MAX_CONCURRENCY', 4, 1, 64),
    queueTimeoutMs: integer('PI_RUNTIME_QUEUE_TIMEOUT_SECONDS', 60, 1, 600) * 1000,
    requestMaxBytes: integer('PI_RUNTIME_REQUEST_MAX_BYTES', 2_097_152, 1024, 20_971_520),
    sessionTtlMs: integer('PI_RUNTIME_SESSION_TTL_SECONDS', 1800, 60, 86400) * 1000,
    maxSessions: integer('PI_RUNTIME_MAX_SESSIONS', 1000, 1, 10000),
    contextWindow: integer('PI_RUNTIME_CONTEXT_WINDOW', 131072, 4096, 2_000_000),
    maxOutputTokens: integer('PI_RUNTIME_MAX_OUTPUT_TOKENS', 8192, 128, 131072),
  }
}
