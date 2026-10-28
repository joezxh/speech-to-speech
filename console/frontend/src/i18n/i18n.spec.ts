// @vitest-environment jsdom
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import { routes } from '@/router/index'
import { frontOverlays } from '@/router/nav'
import en from './locales/en-US'
import zh from './locales/zh-CN'

function flatten(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === 'object' ? flatten(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]
  )
}

function resolveKey(tree: Record<string, unknown>, dotted: string): unknown {
  return dotted.split('.').reduce<unknown>((acc, seg) => (acc && typeof acc === 'object' ? (acc as Record<string, unknown>)[seg] : undefined), tree)
}

describe('i18n parity', () => {
  it('zh and en flatten to identical key sets, all non-empty strings', () => {
    const zk = flatten(zh as never).sort()
    const ek = flatten(en as never).sort()
    expect(zk).toEqual(ek)
    for (const k of zk) {
      expect(typeof resolveKey(zh as never, k)).toBe('string')
      expect((resolveKey(zh as never, k) as string).length).toBeGreaterThan(0)
    }
  })

  it('every navKey from routes and frontOverlays resolves in both locales', () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    const keys = [
      ...router.getRoutes().map((r) => (r.meta as { navKey?: string }).navKey),
      ...frontOverlays.map((o) => o.navKey)
    ].filter((k): k is string => Boolean(k))
    expect(keys.length).toBeGreaterThanOrEqual(12)
    for (const key of keys) {
      expect(typeof resolveKey(zh as never, key), `zh missing ${key}`).toBe('string')
      expect(typeof resolveKey(en as never, key), `en missing ${key}`).toBe('string')
    }
  })
})
