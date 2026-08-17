import crypto from 'node:crypto'
import http from 'node:http'

import { loadConfig } from './config.mjs'
import { PiAgentEngine, PiRunCancelledError } from './pi-engine.mjs'

class HttpError extends Error {
  constructor(statusCode, message) {
    super(message)
    this.statusCode = statusCode
  }
}

class ConcurrencyGate {
  constructor(limit, timeoutMs) {
    this.limit = limit
    this.timeoutMs = timeoutMs
    this.active = 0
    this.queue = []
  }

  acquire(signal) {
    if (signal?.aborted) return Promise.reject(new PiRunCancelledError())
    if (this.active < this.limit) {
      this.active += 1
      return Promise.resolve(() => this.release())
    }
    return new Promise((resolve, reject) => {
      const entry = { resolve, timer: null, abort: null, signal }
      const remove = () => {
        this.queue = this.queue.filter((item) => item !== entry)
        if (entry.abort) signal?.removeEventListener('abort', entry.abort)
      }
      entry.timer = setTimeout(() => {
        remove()
        reject(new HttpError(503, 'Pi Runtime concurrency queue timed out'))
      }, this.timeoutMs)
      entry.abort = () => {
        clearTimeout(entry.timer)
        remove()
        reject(new PiRunCancelledError())
      }
      signal?.addEventListener('abort', entry.abort, { once: true })
      this.queue.push(entry)
    })
  }

  release() {
    const next = this.queue.shift()
    if (next) {
      clearTimeout(next.timer)
      if (next.abort) next.signal?.removeEventListener('abort', next.abort)
      next.abort = null
      next.resolve(() => this.release())
      return
    }
    this.active = Math.max(0, this.active - 1)
  }
}

function secureEqual(actual, expected) {
  const left = Buffer.from(actual || '')
  const right = Buffer.from(expected)
  return left.length === right.length && crypto.timingSafeEqual(left, right)
}

function authorize(request, config) {
  const header = String(request.headers.authorization || '')
  if (!secureEqual(header, `Bearer ${config.runtimeApiKey}`)) {
    throw new HttpError(401, 'invalid Pi Runtime key')
  }
}

async function readJson(request, maximumBytes) {
  const chunks = []
  let size = 0
  for await (const chunk of request) {
    size += chunk.length
    if (size > maximumBytes) throw new HttpError(413, 'request body is too large')
    chunks.push(chunk)
  }
  try {
    const value = JSON.parse(Buffer.concat(chunks).toString('utf8') || '{}')
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error()
    return value
  } catch {
    throw new HttpError(400, 'request body must be a JSON object')
  }
}

function sendJson(response, statusCode, body) {
  const value = JSON.stringify(body)
  response.writeHead(statusCode, {
    'content-type': 'application/json; charset=utf-8',
    'content-length': Buffer.byteLength(value),
    'cache-control': 'no-store',
  })
  response.end(value)
}

function sendSse(response, event) {
  if (!response.destroyed && !response.writableEnded) {
    response.write(`data: ${JSON.stringify(event)}\n\n`)
  }
}

function cleanSessions(sessions, config) {
  const threshold = Date.now() - config.sessionTtlMs
  for (const [id, session] of sessions) {
    if (session.lastUsedAt < threshold) sessions.delete(id)
  }
  while (sessions.size >= config.maxSessions) {
    const oldest = [...sessions.values()].sort((a, b) => a.lastUsedAt - b.lastUsedAt)[0]
    if (!oldest) break
    sessions.delete(oldest.id)
  }
}

function validateContext(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function normalizeExecutionPayload(body, sessionId = null) {
  const context = validateContext(body.context || body.agent_context)
  const task = validateContext(body.task)
  const messages = Array.isArray(body.messages)
    ? body.messages
    : [
        ...(typeof task.system_prompt === 'string'
          ? [{ role: 'system', content: task.system_prompt }]
          : []),
        { role: 'user', content: String(task.input || task.prompt || body.input || '') },
      ]
  if (!messages.length || messages.some((item) => !item || typeof item.content !== 'string')) {
    throw new HttpError(422, 'messages must contain text content')
  }
  const model = String(body.model || task.model || '').trim()
  if (!model) throw new HttpError(422, 'model is required')
  const executionId = String(body.execution_id || task.execution_id || crypto.randomUUID())
  return {
    messages: messages.map((item) => ({ role: String(item.role || 'user'), content: item.content })),
    model,
    model_adapter: String(body.model_adapter || task.model_adapter || 'hermes'),
    agent_id: String(body.agent_id || context.agent_id || 'pi-agent'),
    execution_id: executionId,
    session_id: String(sessionId || body.session_id || context.session_id || crypto.randomUUID()),
    options: validateContext(body.options || task.options),
    context,
  }
}

export function createPiRuntimeServer({ config = loadConfig(), engine = new PiAgentEngine(config) } = {}) {
  const sessions = new Map()
  const runs = new Map()
  const pendingStops = new Map()
  const gate = new ConcurrencyGate(config.maxConcurrency, config.queueTimeoutMs)

  const findRun = (id) => runs.get(id) || [...runs.values()].find((run) => run.executionId === id)
  const stopRun = (id) => {
    const run = findRun(id)
    if (run) {
      run.controller.abort()
      run.status = 'cancelling'
      return { run_id: run.id, status: 'cancelling' }
    }
    const now = Date.now()
    for (const [key, expiresAt] of pendingStops) {
      if (expiresAt <= now) pendingStops.delete(key)
    }
    while (pendingStops.size >= config.maxSessions) {
      const oldest = pendingStops.keys().next().value
      if (oldest === undefined) break
      pendingStops.delete(oldest)
    }
    pendingStops.set(id, now + 30_000)
    return { run_id: id, status: 'cancelling' }
  }

  async function execute(payload, response, streaming) {
    const runId = payload.execution_id
    const existingRun = runs.get(runId)
    if (existingRun) {
      if (['cancelling', 'cancelled'].includes(existingRun.status)) {
        if (streaming) {
          response.writeHead(200, {
            'content-type': 'text/event-stream; charset=utf-8',
            'cache-control': 'no-cache, no-store',
            connection: 'keep-alive',
            'x-accel-buffering': 'no',
          })
          sendSse(response, { type: 'cancelled', run_id: runId, status: 'cancelled' })
          response.end()
        } else {
          sendJson(response, 409, { run_id: runId, status: 'cancelled' })
        }
        return
      }
      throw new HttpError(409, 'Pi Runtime execution id is already active')
    }
    const controller = new AbortController()
    const run = {
      id: runId,
      executionId: payload.execution_id,
      sessionId: payload.session_id,
      controller,
      status: 'queued',
      startedAt: Date.now(),
    }
    runs.set(run.id, run)
    if ((pendingStops.get(run.id) || 0) > Date.now()) controller.abort()
    pendingStops.delete(run.id)
    let release
    try {
      release = await gate.acquire(controller.signal)
    } catch (error) {
      runs.delete(run.id)
      if (error instanceof PiRunCancelledError || controller.signal.aborted) {
        if (streaming) {
          response.writeHead(200, {
            'content-type': 'text/event-stream; charset=utf-8',
            'cache-control': 'no-cache, no-store',
            connection: 'keep-alive',
            'x-accel-buffering': 'no',
          })
          sendSse(response, { type: 'cancelled', run_id: runId, status: 'cancelled' })
          response.end()
        } else {
          sendJson(response, 409, { run_id: runId, status: 'cancelled' })
        }
        return
      }
      throw error
    }
    run.status = controller.signal.aborted ? 'cancelling' : 'running'
    if (streaming) {
      response.writeHead(200, {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache, no-store',
        connection: 'keep-alive',
        'x-accel-buffering': 'no',
      })
      response.on('close', () => {
        if (!response.writableEnded) controller.abort()
      })
    }
    try {
      const result = await engine.run(payload, {
        runId,
        signal: controller.signal,
        onEvent: streaming ? (event) => sendSse(response, event) : async () => {},
      })
      run.status = 'completed'
      const body = {
        run_id: runId,
        status: 'completed',
        output: result.output,
        usage: result.usage,
        trace: result.trace,
      }
      if (streaming) {
        sendSse(response, { type: 'done', run_id: runId, result: result.output, usage: result.usage })
        response.end()
      } else {
        sendJson(response, 200, body)
      }
    } catch (error) {
      if (error instanceof PiRunCancelledError || controller.signal.aborted) {
        run.status = 'cancelled'
        if (streaming) {
          sendSse(response, { type: 'cancelled', run_id: runId, status: 'cancelled' })
          response.end()
        } else {
          sendJson(response, 409, { run_id: runId, status: 'cancelled' })
        }
      } else {
        run.status = 'failed'
        const message = error instanceof Error ? error.message : 'Pi Runtime execution failed'
        if (streaming) {
          sendSse(response, { type: 'error', run_id: runId, status: 'failed', error: message })
          response.end()
        } else {
          throw new HttpError(502, message)
        }
      }
    } finally {
      release?.()
      setTimeout(() => runs.delete(run.id), 60_000).unref()
    }
  }

  const server = http.createServer(async (request, response) => {
    try {
      const url = new URL(request.url || '/', 'http://pi-runtime')
      if (request.method === 'GET' && url.pathname === '/health') {
        sendJson(response, 200, {
          runtime: 'pi',
          status: 'healthy',
          version: config.runtimeVersion,
          service_version: config.serviceVersion,
          active: gate.active,
          max_concurrency: gate.limit,
        })
        return
      }
      authorize(request, config)

      if (request.method === 'POST' && url.pathname === '/sessions') {
        const body = await readJson(request, config.requestMaxBytes)
        cleanSessions(sessions, config)
        const id = crypto.randomUUID()
        sessions.set(id, {
          id,
          agentId: String(body.agent_id || ''),
          executionId: String(body.execution_id || ''),
          metadata: validateContext(body.metadata),
          context: validateContext(body.context),
          createdAt: Date.now(),
          lastUsedAt: Date.now(),
        })
        sendJson(response, 201, { id, session_id: id, runtime: 'pi' })
        return
      }

      const sessionMatch = url.pathname.match(/^\/sessions\/([^/]+)\/(execute|stream)$/)
      if (request.method === 'POST' && sessionMatch) {
        const session = sessions.get(decodeURIComponent(sessionMatch[1]))
        if (!session) throw new HttpError(404, 'Pi session not found')
        if (session.lastUsedAt < Date.now() - config.sessionTtlMs) {
          sessions.delete(session.id)
          throw new HttpError(410, 'Pi session expired')
        }
        session.lastUsedAt = Date.now()
        const body = await readJson(request, config.requestMaxBytes)
        const payload = normalizeExecutionPayload(
          { ...body, context: { ...session.context, ...validateContext(body.context) } },
          session.id,
        )
        await execute(payload, response, sessionMatch[2] === 'stream')
        return
      }

      if (request.method === 'POST' && ['/execute', '/stream'].includes(url.pathname)) {
        const body = await readJson(request, config.requestMaxBytes)
        await execute(normalizeExecutionPayload(body), response, url.pathname === '/stream')
        return
      }

      const stopMatch = url.pathname.match(/^\/(?:stop|runs)\/([^/]+)(?:\/stop)?$/)
      if (request.method === 'POST' && stopMatch) {
        sendJson(response, 202, stopRun(decodeURIComponent(stopMatch[1])))
        return
      }

      const runMatch = url.pathname.match(/^\/runs\/([^/]+)$/)
      if (request.method === 'GET' && runMatch) {
        const run = findRun(decodeURIComponent(runMatch[1]))
        if (!run) throw new HttpError(404, 'Pi run not found')
        sendJson(response, 200, {
          run_id: run.id,
          execution_id: run.executionId,
          session_id: run.sessionId,
          status: run.status,
          started_at: new Date(run.startedAt).toISOString(),
        })
        return
      }
      throw new HttpError(404, 'not found')
    } catch (error) {
      if (response.headersSent) {
        if (!response.writableEnded) response.end()
        return
      }
      const statusCode = error instanceof HttpError ? error.statusCode : 500
      const message = error instanceof Error ? error.message : 'internal Pi Runtime error'
      sendJson(response, statusCode, { error: { message } })
    }
  })
  return { server, sessions, runs }
}

if (process.argv[1] === new URL(import.meta.url).pathname) {
  const config = loadConfig()
  const { server } = createPiRuntimeServer({ config })
  server.listen(config.port, config.host, () => {
    process.stdout.write(`Pi Runtime ${config.runtimeVersion} listening on ${config.host}:${config.port}\n`)
  })
}
