import { describe, expect, it } from 'vitest'

import { PERMISSION_ROLES, roleHasPermission } from './permissions'

describe('permission mirror', () => {
  it('mirrors the backend matrix: operator may query+switch but not write', () => {
    expect(roleHasPermission('operator', 'console:cluster:query')).toBe(true)
    expect(roleHasPermission('operator', 'console:cluster:switch')).toBe(true)
    expect(roleHasPermission('operator', 'console:cluster:create')).toBe(false)
    expect(roleHasPermission('admin', 'console:cluster:delete')).toBe(true)
    expect(roleHasPermission('viewer', 'console:cluster:query')).toBe(false)
  })

  it('unknown codes and roles fail closed', () => {
    expect(roleHasPermission('admin', 'console:nonexistent')).toBe(false)
    expect(roleHasPermission('', 'console:cluster:query')).toBe(false)
  })

  it('mirrors the machine codes the backend registers (2026-11-17 §7.3)', () => {
    expect(roleHasPermission('operator', 'console:machine:query')).toBe(true)
    expect(roleHasPermission('operator', 'console:machine:create')).toBe(false)
    expect(roleHasPermission('admin', 'console:machine:update')).toBe(true)
    expect(roleHasPermission('admin', 'console:agent:enroll')).toBe(true)
  })

  it('covers exactly the codes the backend registers', () => {
    expect(Object.keys(PERMISSION_ROLES).sort()).toEqual([
      'console:agent:enroll',
      'console:audit:export',
      'console:audit:query',
      'console:callback:manage',
      'console:callback:query',
      'console:cluster:create',
      'console:cluster:delete',
      'console:cluster:query',
      'console:cluster:switch',
      'console:cluster:update',
      'console:lb:query',
      'console:lb:rule:write',
      'console:machine:create',
      'console:machine:delete',
      'console:machine:operate',
      'console:machine:query',
      'console:machine:update',
      'console:release:query',
      'console:release:write',
      'console:smart:analyze',
      'console:template:create',
      'console:template:delete',
      'console:template:query',
      'console:template:update',
      'console:token:query',
      'console:tool:create',
      'console:tool:delete',
      'console:tool:query',
      'console:tool:update'
    ])
  })
})