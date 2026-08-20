import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { platformAdminGuide, renderPlatformAdminGuideMarkdown } from './platformAdminGuide'

describe('platform administrator guide', () => {
  it('covers all seven platform management sections with complete administrator guidance', () => {
    expect(platformAdminGuide.sections.map((section) => section.id)).toEqual([
      'models', 'runtimes', 'connections', 'database', 'api', 'operations', 'settings',
    ])
    for (const section of platformAdminGuide.sections) {
      expect(section.prerequisites.length).toBeGreaterThan(0)
      expect(section.fields.length).toBeGreaterThan(0)
      expect(section.steps.length).toBeGreaterThan(0)
      expect(section.success.length).toBeGreaterThan(0)
      expect(section.errors.length).toBeGreaterThan(0)
      expect(section.security.length).toBeGreaterThan(0)
    }
  })

  it('keeps the repository Markdown identical to the browser download', () => {
    const path = resolve(process.cwd(), '../docs/Hermes_Agent_Platform_Administration_Guide_CN.md')
    expect(readFileSync(path, 'utf8')).toBe(renderPlatformAdminGuideMarkdown())
  })

  it('contains required boundaries without production secrets or addresses', () => {
    const content = renderPlatformAdminGuideMarkdown()
    expect(content).toContain('Agent 模型别名不等于上游真实模型名')
    expect(content).toContain('平台使用之前加密保存的托管凭据')
    expect(content).toContain('不要填写 127.0.0.1')
    expect(content).toContain('不可原地覆盖')
    expect(content).not.toMatch(/116\.204\.135\.83|api\.test-link\.xin|qwB_fObeOJsup/i)
  })
})
