// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { routes } from './index'

/** 与 `index.ts` 同一张表，但用内存 history：不碰地址栏，也不跑守卫。 */
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

  it('keeps the console namespace record componentless so RouterView skips it', () => {
    const record = makeRouter()
      .getRoutes()
      .find((route) => route.name === 'console')
    expect(record?.path).toBe('/console')
    expect(record?.components?.default).toBeUndefined()
    expect(record?.meta.requiresAuth).toBe(true)
  })

  it('inherits face and requiresAuth on console children', () => {
    const resolved = makeRouter().resolve('/console/params')
    // 链首是挂在 `/` 上的外壳记录（匿名，与第 1 条同一个 `ConsoleLayout`），
    // 所以这里只比对有名字的那两条。
    expect(resolved.matched.map((record) => record.name).filter(Boolean)).toEqual(['console', 'params'])
    expect(resolved.meta.face).toBe('console')
    expect(resolved.meta.requiresAuth).toBe(true)
  })

  it('leaves the voice face anonymous', () => {
    expect(makeRouter().resolve('/').meta.requiresAuth).toBeFalsy()
  })
})
