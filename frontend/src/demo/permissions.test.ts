import { describe, expect, it } from 'vitest'
import { canOpen, pageCapability, rolesUpTo } from './permissions'

describe('page access by role', () => {
  it('lets every role open the shared pages', () => {
    for (const role of ['Viewer', 'Analyst', 'Quant', 'Admin'] as const) {
      for (const page of ['/dashboard', '/market/data', '/market/instruments', '/alerts', '/reports']) {
        expect(canOpen(role, page)).toBe(true)
      }
    }
  })

  it('keeps administration pages for admins only', () => {
    for (const page of ['/admin/users', '/admin/roles', '/admin/system', '/audit-log']) {
      expect(canOpen('Admin', page)).toBe(true)
      expect(canOpen('Quant', page)).toBe(false)
      expect(canOpen('Viewer', page)).toBe(false)
    }
  })

  it('opens analysis to analysts and authoring to quants, following the spec matrix', () => {
    expect(canOpen('Viewer', '/risk/stress-testing')).toBe(false)
    expect(canOpen('Analyst', '/risk/stress-testing')).toBe(true)
    expect(canOpen('Analyst', '/simulation/configure')).toBe(false)
    expect(canOpen('Quant', '/simulation/configure')).toBe(true)
    expect(canOpen('Analyst', '/trading/strategies/new')).toBe(false)
    expect(canOpen('Quant', '/trading/strategies/s1')).toBe(true)
    expect(canOpen('Analyst', '/trading/strategies')).toBe(true)
  })

  it('leaves unknown pages open so the not-found page can show', () => {
    expect(pageCapability('/does-not-exist')).toBeNull()
    expect(canOpen('Viewer', '/does-not-exist')).toBe(true)
  })

  it('previews only equal or lower roles', () => {
    expect(rolesUpTo('Viewer')).toEqual(['Viewer'])
    expect(rolesUpTo('Quant')).toEqual(['Viewer', 'Analyst', 'Quant'])
    expect(rolesUpTo('Admin')).toHaveLength(4)
  })
})
