import { describe, expect, it } from 'vitest'

import { presentTeamRunResult } from './teamRunResult'

describe('presentTeamRunResult', () => {
  it('prefers structured report markdown and exposes business status', () => {
    const result = presentTeamRunResult('{"status":"completed"}', {
      status: 'completed',
      title: '欧洲热点编报',
      report_markdown: '# 欧洲热点\n正文',
    })

    expect(result.readable).toBe('# 欧洲热点\n正文')
    expect(result.businessStatus).toBe('completed')
    expect(result.title).toBe('欧洲热点编报')
    expect(result.structuredText).toContain('"report_markdown"')
  })

  it('turns blocked structured output into readable sections', () => {
    const result = presentTeamRunResult(JSON.stringify({
      status: 'blocked',
      summary: '授权材料不足',
      report_markdown: null,
      blocking_reasons: ['未找到材料'],
      information_gaps: ['缺少原始文件'],
    }))

    expect(result.businessStatus).toBe('blocked')
    expect(result.readable).toContain('结果摘要')
    expect(result.readable).toContain('阻塞原因')
    expect(result.readable).toContain('信息缺口')
  })

  it('extracts a JSON object after a non-compliant preface for display', () => {
    const result = presentTeamRunResult('以下为结果\n{"status":"completed","summary":"ok"}')

    expect(result.businessStatus).toBe('completed')
    expect(result.summary).toBe('ok')
  })

  it('keeps markdown and invalid JSON as raw readable output', () => {
    expect(presentTeamRunResult('# 普通输出\n正文').readable).toContain('普通输出')
    expect(presentTeamRunResult('{invalid json').readable).toBe('{invalid json')
  })

  it('returns an empty presentation when no output exists', () => {
    const result = presentTeamRunResult(null)

    expect(result.readable).toBe('')
    expect(result.structured).toBeNull()
    expect(result.businessStatus).toBeNull()
  })
})
