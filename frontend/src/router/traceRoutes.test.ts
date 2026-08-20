import { describe, expect, it } from 'vitest'

import router from './index'

describe('execution and trace routes', () => {
  it('keeps the centers and their detail pages as independent routes', () => {
    const routes = router.getRoutes()
    const executions = routes.find((route) => route.name === 'executions')
    const traces = routes.find((route) => route.name === 'execution-trace')
    const executionDetail = routes.find((route) => route.name === 'execution-detail')
    const traceDetail = routes.find((route) => route.name === 'trace-detail')

    expect(executions?.path).toBe('/executions')
    expect(traces?.path).toBe('/trace')
    expect(executionDetail?.path).toBe('/executions/:id')
    expect(traceDetail?.path).toBe('/trace/:id')
    expect(executions?.components?.default).not.toBe(traces?.components?.default)
  })

  it('registers the Multi-Agent orchestration workspace', () => {
    const orchestration = router.getRoutes().find((route) => route.name === 'multi-agent')
    expect(orchestration?.path).toBe('/orchestration')
  })

  it('registers the Runtime management page', () => {
    const runtimes = router.getRoutes().find((route) => route.name === 'runtimes')
    expect(runtimes?.path).toBe('/runtimes')
  })

  it('registers the direct Agent chat workspace', () => {
    const chat = router.getRoutes().find((route) => route.name === 'agent-chat')
    expect(chat?.path).toBe('/chat')
  })
})
