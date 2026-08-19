import { Agent } from '@earendil-works/pi-agent-core'
import { createModels, createProvider, envApiKeyAuth } from '@earendil-works/pi-ai'
import { openAICompletionsApi } from '@earendil-works/pi-ai/api/openai-completions.lazy'

import { loadCapabilityTools, loadMcpTools } from './mcp-tools.mjs'

export class PiRunCancelledError extends Error {
  constructor(message = 'Pi execution was cancelled') {
    super(message)
    this.name = 'PiRunCancelledError'
  }
}

function modelRuntime(config, modelId) {
  const model = {
    id: modelId,
    name: modelId,
    api: 'openai-completions',
    provider: 'hermes-model-gateway',
    baseUrl: config.modelGatewayEndpoint,
    reasoning: false,
    input: ['text'],
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    contextWindow: config.contextWindow,
    maxTokens: config.maxOutputTokens,
    compat: {
      supportsStore: false,
      supportsDeveloperRole: false,
      supportsReasoningEffort: false,
      supportsStrictMode: false,
      maxTokensField: 'max_tokens',
    },
  }
  const provider = createProvider({
    id: 'hermes-model-gateway',
    name: 'Hermes Model Gateway',
    baseUrl: config.modelGatewayEndpoint,
    auth: {
      apiKey: envApiKeyAuth('Hermes Model Gateway key', ['MODEL_GATEWAY_API_KEY']),
    },
    models: [model],
    api: openAICompletionsApi(),
  })
  const models = createModels()
  models.setProvider(provider)
  return { models, model }
}

function splitMessages(messages) {
  const systemPrompt = messages
    .filter((message) => message.role === 'system')
    .map((message) => message.content)
    .join('\n\n') || 'You are a helpful enterprise agent.'
  const conversation = messages
    .filter((message) => message.role !== 'system')
    .map((message) => `${String(message.role).toUpperCase()}:\n${message.content}`)
    .join('\n\n')
  return { systemPrompt, prompt: conversation || 'Complete the requested task.' }
}

function textOutput(message) {
  if (!message || message.role !== 'assistant' || !Array.isArray(message.content)) return ''
  return message.content
    .filter((item) => item && item.type === 'text' && typeof item.text === 'string')
    .map((item) => item.text)
    .join('')
}

function usage(message) {
  const raw = message?.usage || {}
  const input = Number(raw.input || 0)
  const output = Number(raw.output || 0)
  const cacheRead = Number(raw.cacheRead || 0)
  const cacheWrite = Number(raw.cacheWrite || 0)
  return {
    input_tokens: input,
    output_tokens: output,
    cache_read_tokens: cacheRead,
    cache_write_tokens: cacheWrite,
    total_tokens: input + output + cacheRead + cacheWrite,
  }
}

function traceEvent(event, runId) {
  const base = { run_id: runId, runtime: 'pi' }
  if (event.type === 'agent_start') return { ...base, type: 'start', status: 'running' }
  if (event.type === 'turn_start') return { ...base, type: 'model_call', status: 'running' }
  if (event.type === 'turn_end') return { ...base, type: 'model_call', status: 'succeeded' }
  if (event.type === 'tool_execution_start') {
    return { ...base, type: 'tool_call', status: 'running', name: event.toolName }
  }
  if (event.type === 'tool_execution_end') {
    return {
      ...base,
      type: 'tool_result',
      status: event.isError ? 'failed' : 'succeeded',
      name: event.toolName,
      error: Boolean(event.isError),
    }
  }
  if (event.type === 'agent_end') return { ...base, type: 'end', status: 'succeeded' }
  return null
}

export class PiAgentEngine {
  constructor(config) {
    this.config = config
  }

  async run(request, { runId, signal, onEvent = async () => {} }) {
    const context = request.context || {}
    const metadata = context.metadata || {}
    const capabilities = Array.isArray(context.tools) ? context.tools : []
    const mcp = await loadMcpTools({
      endpoint: this.config.mcpGatewayEndpoint,
      accessToken: typeof metadata.mcp_access_token === 'string' ? metadata.mcp_access_token : '',
      capabilities,
      executionId: request.execution_id,
    })
    const capability = loadCapabilityTools({
      endpoint: typeof metadata.capability_gateway === 'string' ? metadata.capability_gateway : '',
      token: typeof metadata.capability_token === 'string' ? metadata.capability_token : '',
      tools: Array.isArray(metadata.capability_tools) ? metadata.capability_tools : [],
      executionId: request.execution_id,
    })
    const { models, model } = modelRuntime(this.config, request.model)
    const { systemPrompt, prompt } = splitMessages(request.messages)
    const trace = []
    const temperature = Number(request.options?.temperature)
    const streamOptions = {
      sessionId: request.session_id,
      ...(Number.isFinite(temperature) ? { temperature } : {}),
    }
    const agent = new Agent({
      initialState: {
        systemPrompt,
        model,
        thinkingLevel: 'off',
        tools: [...mcp.tools, ...capability.tools],
        messages: [],
      },
      sessionId: request.session_id,
      toolExecution: 'sequential',
      streamFn: (selectedModel, selectedContext, options) =>
        models.streamSimple(selectedModel, selectedContext, { ...options, ...streamOptions }),
    })
    const abort = () => agent.abort()
    signal.addEventListener('abort', abort, { once: true })
    const skills = Array.isArray(context.skills) ? context.skills : []
    if (skills.length) {
      const event = { run_id: runId, runtime: 'pi', type: 'skill_load', status: 'succeeded', skills }
      trace.push(event)
      await onEvent(event)
    }
    const unsubscribe = agent.subscribe(async (event) => {
      if (
        event.type === 'message_update' &&
        event.assistantMessageEvent?.type === 'text_delta' &&
        typeof event.assistantMessageEvent.delta === 'string'
      ) {
        await onEvent({ run_id: runId, type: 'token', text: event.assistantMessageEvent.delta })
      }
      const mapped = traceEvent(event, runId)
      if (mapped) {
        trace.push(mapped)
        await onEvent(mapped)
      }
    })

    try {
      if (signal.aborted) throw new PiRunCancelledError()
      await agent.prompt(prompt)
      if (signal.aborted) throw new PiRunCancelledError()
      if (agent.state.errorMessage) throw new Error(agent.state.errorMessage)
      const finalMessage = [...agent.state.messages]
        .reverse()
        .find((message) => message.role === 'assistant')
      const output = textOutput(finalMessage)
      if (!output) throw new Error('Pi Agent completed without text output')
      return { output, usage: usage(finalMessage), trace: trace.slice(0, 500) }
    } catch (error) {
      if (signal.aborted || error?.name === 'AbortError') throw new PiRunCancelledError()
      throw error
    } finally {
      unsubscribe()
      signal.removeEventListener('abort', abort)
      await Promise.allSettled([mcp.close(), capability.close()])
    }
  }
}
