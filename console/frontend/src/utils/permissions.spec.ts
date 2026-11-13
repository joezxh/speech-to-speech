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

  it('covers exactly the five cluster codes the backend registers', () => {
    expect(Object.keys(PERMISSION_ROLES).sort()).toEqual([
      'console:cluster:create',
      'console:cluster:delete',
      'console:cluster:query',
      'console:cluster:switch',
      'console:cluster:update'
    ])
  })
})