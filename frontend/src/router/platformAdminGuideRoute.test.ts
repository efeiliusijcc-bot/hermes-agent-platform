import { describe, expect, it } from 'vitest'

import router from './index'

describe('platform administrator guide route', () => {
  it('resolves the stable help URL and section query', () => {
    const route = router.resolve('/help/platform-management?section=models')
    expect(route.name).toBe('platform-admin-guide')
    expect(route.query.section).toBe('models')
    expect(route.meta.title).toBe('平台管理使用手册')
  })
})
