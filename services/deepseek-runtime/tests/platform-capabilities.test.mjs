import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import { fileURLToPath } from 'node:url'
import test from 'node:test'


const root = fileURLToPath(new URL('..', import.meta.url))
const fixture = fileURLToPath(new URL('./fixtures/platform-plugin-runner.mjs', import.meta.url))

test('Cordis plugin registers an alias and sends only business arguments over inherited fd', async () => {
  const child = spawn(process.execPath, [fixture], {
    cwd: root,
    env: { ...process.env, HERMES_CAPABILITY_FD: '3' },
    stdio: ['ignore', 'pipe', 'inherit', 'pipe'],
  })
  const channel = child.stdio[3]
  let protocol = ''
  const requests = []
  channel.setEncoding('utf8')
  channel.on('data', chunk => {
    protocol += chunk
    while (true) {
      const offset = protocol.indexOf('\n')
      if (offset < 0) break
      const raw = protocol.slice(0, offset)
      protocol = protocol.slice(offset + 1)
      if (!raw) continue
      const request = JSON.parse(raw)
      requests.push(request)
      if (request.type === 'list') {
        channel.write(`${JSON.stringify({
          id: request.id,
          ok: true,
          tools: [{
            tool_name: 'business_db_select',
            description: 'query database',
            input_schema: {
              type: 'object',
              properties: { sql: { type: 'string' } },
              required: ['sql'],
              additionalProperties: false,
            },
          }],
        })}\n`)
      } else {
        channel.write(`${JSON.stringify({ id: request.id, ok: true, data: { rows: [{ id: 1 }] } })}\n`)
      }
    }
  })
  let stdout = ''
  child.stdout.setEncoding('utf8')
  child.stdout.on('data', chunk => { stdout += chunk })
  const [code] = await once(child, 'exit')
  assert.equal(code, 0)
  const result = JSON.parse(stdout)
  assert.equal(result.name, 'business_db_select')
  assert.deepEqual(result.required, ['sql'])
  assert.equal(result.output, '{"rows":[{"id":1}]}')
  assert.deepEqual(requests[1], {
    id: '2', type: 'invoke', tool_name: 'business_db_select', arguments: { sql: 'SELECT 1' },
  })
  assert.doesNotMatch(JSON.stringify(requests), /token|credential|endpoint/i)
})
