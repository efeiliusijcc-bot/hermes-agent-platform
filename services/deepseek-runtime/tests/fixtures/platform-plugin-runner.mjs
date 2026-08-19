import { apply } from '../../platform-capabilities.mjs'


let registered
const disposers = []
const ctx = {
  tools: { register(value) { registered = value } },
  on(event, callback) { if (event === 'dispose') disposers.push(callback) },
}

await apply(ctx)
if (!registered) throw new Error('platform Capability tool was not registered')
const output = await registered.execute(
  { sql: 'SELECT 1' },
  { signal: new AbortController().signal },
)
process.stdout.write(JSON.stringify({
  name: registered.name,
  required: registered.parameters.required,
  output,
}))
for (const dispose of disposers) dispose()
