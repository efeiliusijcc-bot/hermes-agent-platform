import assert from 'node:assert/strict'
import { once } from 'node:events'
import test from 'node:test'

import { validateToolArguments } from '@earendil-works/pi-ai'

import { sanitizeInputSchema } from '../src/mcp-tools.mjs'
import { PiRunCancelledError } from '../src/pi-engine.mjs'
import { createPiRuntimeServer } from '../src/server.mjs'

const config = {
  host: '127.0.0.1',
  port: 0,
  runtimeApiKey: 'p'.repeat(48),
  runtimeVersion: '0.84.2',
  serviceVersion: '1.0.0',
  maxConcurrency: 2,
  queueTimeoutMs: 1000,
  requestMaxBytes: 1024 * 1024,
  sessionTtlMs: 60000,
  maxSessions: 20,
}

async function fixture(engine) {
  const value = createPiRuntimeServer({ config, engine })
  value.server.listen(0, '127.0.0.1')
  await once(value.server, 'listening')
  const address = value.server.address()
  return {
    ...value,
    url: `http://127.0.0.1:${address.port}`,
    close: () => new Promise((resolve) => value.server.close(resolve)),
  }
}

const headers = {
  authorization: `Bearer ${config.runtimeApiKey}`,
  'content-type': 'application/json',
}

test('health identifies the official Pi core runtime and protected routes reject missing auth', async () => {
  const app = await fixture({ run: async () => ({ output: 'unused', usage: {}, trace: [] }) })
  try {
    const health = await fetch(`${app.url}/health`).then((response) => response.json())
    assert.deepEqual(
      { runtime: health.runtime, status: health.status, version: health.version },
      { runtime: 'pi', status: 'healthy', version: '0.84.2' },
    )
    assert.equal((await fetch(`${app.url}/sessions`, { method: 'POST' })).status, 401)
  } finally {
    await app.close()
  }
})

test('session execute and SSE stream preserve the Pi runtime contract', async () => {
  const engine = {
    run: async (_payload, { runId, onEvent }) => {
      await onEvent({ type: 'token', run_id: runId, text: 'hello ' })
      await onEvent({ type: 'token', run_id: runId, text: 'world' })
      return { output: 'hello world', usage: { total_tokens: 3 }, trace: [{ type: 'model_call' }] }
    },
  }
  const app = await fixture(engine)
  try {
    const sessionResponse = await fetch(`${app.url}/sessions`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ agent_id: 'agent-a', execution_id: 'execution-a', context: {} }),
    })
    assert.equal(sessionResponse.status, 201)
    const session = await sessionResponse.json()
    const payload = {
      messages: [{ role: 'user', content: 'hello' }],
      model: 'internal-model',
      execution_id: 'execution-a',
      agent_id: 'agent-a',
      context: {},
    }
    const executed = await fetch(`${app.url}/sessions/${session.id}/execute`, {
      method: 'POST', headers, body: JSON.stringify(payload),
    })
    assert.equal(executed.status, 200)
    assert.equal((await executed.json()).output, 'hello world')

    const streamed = await fetch(`${app.url}/sessions/${session.id}/stream`, {
      method: 'POST', headers, body: JSON.stringify({ ...payload, execution_id: 'execution-b' }),
    })
    assert.equal(streamed.status, 200)
    const body = await streamed.text()
    assert.match(body, /"type":"token"/)
    assert.match(body, /"type":"done"/)
    assert.match(body, /hello world/)
  } finally {
    await app.close()
  }
})

test('stop endpoint aborts an active Pi run', async () => {
  let calls = 0
  const engine = {
    run: (_payload, { signal }) => new Promise((resolve, reject) => {
      calls += 1
      signal.addEventListener('abort', () => reject(new PiRunCancelledError()), { once: true })
      setTimeout(() => resolve({ output: 'too late', usage: {}, trace: [] }), 10000).unref()
    }),
  }
  const app = await fixture(engine)
  try {
    const session = await fetch(`${app.url}/sessions`, {
      method: 'POST', headers, body: JSON.stringify({ agent_id: 'agent-a', context: {} }),
    }).then((response) => response.json())
    const execution = fetch(`${app.url}/sessions/${session.id}/execute`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'wait' }], model: 'internal-model',
        execution_id: 'execution-stop', context: {},
      }),
    })
    await new Promise((resolve) => setTimeout(resolve, 30))
    const stopped = await fetch(`${app.url}/stop/execution-stop`, { method: 'POST', headers })
    assert.equal(stopped.status, 202)
    const cancelled = await execution
    assert.equal(cancelled.status, 409)
    assert.equal((await cancelled.json()).status, 'cancelled')

    const repeated = await fetch(`${app.url}/sessions/${session.id}/execute`, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'retry after stop' }], model: 'internal-model',
        execution_id: 'execution-stop', context: {},
      }),
    })
    assert.equal(repeated.status, 409)
    assert.equal((await repeated.json()).status, 'cancelled')
    assert.equal(calls, 1)
  } finally {
    await app.close()
  }
})

test('MCP schema hides the per-execution access token from the model', () => {
  const schema = sanitizeInputSchema({
    type: 'object',
    properties: { access_token: { type: 'string' }, path: { type: 'string' } },
    required: ['access_token', 'path'],
  })
  assert.deepEqual(schema.required, ['path'])
  assert.equal(schema.properties.access_token, undefined)
  assert.equal(schema.additionalProperties, false)
  const tool = { name: 'filesystem_read', description: 'read', parameters: schema }
  assert.deepEqual(
    validateToolArguments(tool, {
      id: 'call-1', name: 'filesystem_read', arguments: { path: 'report.txt' },
    }),
    { path: 'report.txt' },
  )
  assert.throws(
    () => validateToolArguments(tool, {
      id: 'call-2', name: 'filesystem_read',
      arguments: { path: 'report.txt', access_token: 'model-visible-secret' },
    }),
    /Validation failed/,
  )
})

test('stop cancels a queued run without waiting for the active run', async () => {
  let finishActive
  const calls = []
  const engine = {
    run: (payload, { signal }) => {
      calls.push(payload.execution_id)
      return new Promise((resolve, reject) => {
        if (payload.execution_id === 'active-run') {
          finishActive = () => resolve({ output: 'active complete', usage: {}, trace: [] })
        } else {
          resolve({ output: 'queued should not execute', usage: {}, trace: [] })
        }
        signal.addEventListener('abort', () => reject(new PiRunCancelledError()), { once: true })
      })
    },
  }
  const value = createPiRuntimeServer({ config: { ...config, maxConcurrency: 1 }, engine })
  value.server.listen(0, '127.0.0.1')
  await once(value.server, 'listening')
  const address = value.server.address()
  const url = `http://127.0.0.1:${address.port}`
  try {
    const session = await fetch(`${url}/sessions`, {
      method: 'POST', headers, body: JSON.stringify({ agent_id: 'agent-a', context: {} }),
    }).then((response) => response.json())
    const payload = (executionId) => JSON.stringify({
      messages: [{ role: 'user', content: 'wait' }], model: 'internal-model',
      execution_id: executionId, context: {},
    })
    const active = fetch(`${url}/sessions/${session.id}/execute`, {
      method: 'POST', headers, body: payload('active-run'),
    })
    await new Promise((resolve) => setTimeout(resolve, 20))
    const queued = fetch(`${url}/sessions/${session.id}/execute`, {
      method: 'POST', headers, body: payload('queued-run'),
    })
    await new Promise((resolve) => setTimeout(resolve, 20))
    const stopped = await fetch(`${url}/stop/queued-run`, { method: 'POST', headers })
    assert.equal(stopped.status, 202)
    assert.equal((await queued).status, 409)
    assert.deepEqual(calls, ['active-run'])
    finishActive()
    assert.equal((await active).status, 200)
  } finally {
    await new Promise((resolve) => value.server.close(resolve))
  }
})

test('expired sessions are rejected even when no new session is created', async () => {
  const value = createPiRuntimeServer({
    config: { ...config, sessionTtlMs: 10 },
    engine: { run: async () => ({ output: 'unused', usage: {}, trace: [] }) },
  })
  value.server.listen(0, '127.0.0.1')
  await once(value.server, 'listening')
  const address = value.server.address()
  const url = `http://127.0.0.1:${address.port}`
  try {
    const session = await fetch(`${url}/sessions`, {
      method: 'POST', headers, body: JSON.stringify({ agent_id: 'agent-a', context: {} }),
    }).then((response) => response.json())
    await new Promise((resolve) => setTimeout(resolve, 20))
    const response = await fetch(`${url}/sessions/${session.id}/execute`, {
      method: 'POST', headers,
      body: JSON.stringify({
        messages: [{ role: 'user', content: 'hello' }], model: 'internal-model',
        execution_id: 'expired-run', context: {},
      }),
    })
    assert.equal(response.status, 410)
  } finally {
    await new Promise((resolve) => value.server.close(resolve))
  }
})
