// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { routes } from './index'

function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

describe('shell routing', () => {
  it('mounts the voice face at / as a child of ConsoleLayout', () => {
    const matched = makeRouter().resolve('/').matched
    expect(matched).toHaveLength(2)
    expect(matched[1].name).toBe('voice')
    expect(matched[1].meta.face).toBe('voice')
  })

  it('keeps the console namespace record componentless', () => {
    const record = makeRouter().getRoutes().find((r) => r.name === 'console')
    expect(record?.path).toBe('/console')
    expect(record?.components?.default).toBeUndefined()
    expect(record?.meta.requiresAuth).toBe(true)
  })

  it('inherits face and requiresAuth on console children', () => {
    const resolved = makeRouter().resolve('/console/deploy')
    expect(resolved.matched.map((r) => r.name).filter(Boolean)).toEqual(['console', 'deploy'])
    expect(resolved.meta.face).toBe('console')
    expect(resolved.meta.requiresAuth).toBe(true)
  })

  it('gates the voice face behind auth', () => {
    const resolved = makeRouter().resolve('/')
    expect(resolved.meta.face).toBe('voice')
    expect(resolved.meta.requiresAuth).toBe(true)
  })

  it('defaults /console to overview', () => {
    // `resolve()` 不跟随 redirect 记录，直接断言叶子路由声明的重定向目标。
    const matched = makeRouter().resolve('/console').matched
    expect(matched[matched.length - 1]?.redirect).toEqual({ name: 'overview' })
  })

  it('redirects every legacy path to its new name', () => {
    const r = makeRouter()
    const redirectTo = (p: string) => {
      const matched = r.resolve(p).matched
      return matched[matched.length - 1]?.redirect
    }
    expect(redirectTo('/console/params')).toEqual({ name: 'deploy' })
    expect(redirectTo('/console/instances')).toEqual({ name: 'machines' })
    expect(redirectTo('/console/instances/trends')).toEqual({ name: 'traffic' })
    expect(redirectTo('/console/versions')).toEqual({ name: 'release' })
    expect(redirectTo('/console/sessions')).toEqual({ name: 'session-update' })
  })
})
