// @vitest-environment jsdom
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import { routes } from '@/router/index'
import { buildNavGroups } from '@/router/nav'

describe('buildNavGroups', () => {
  function frontRows() {
    const router = createRouter({ history: createMemoryHistory(), routes })
    const groups = buildNavGroups(router.getRoutes(), (name) => router.hasRoute(name))
    return groups.find((g) => g.key === 'front')?.rows ?? []
  }

  it('front 组的菜单项不允许重复（会话历史 / 工具 / 设置 各只出现一次）', () => {
    const labelKeys = frontRows().map((r) => r.labelKey)
    expect(labelKeys).toHaveLength(new Set(labelKeys).size)
    for (const key of ['nav.history', 'nav.tools', 'nav.settings']) {
      expect(labelKeys.filter((k) => k === key)).toHaveLength(1)
    }
  })

  it('所有组的 labelKey 全局唯一', () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    const keys = buildNavGroups(router.getRoutes(), (name) => router.hasRoute(name))
      .flatMap((g) => g.rows.map((r) => r.labelKey))
    expect(keys).toHaveLength(new Set(keys).size)
  })
})
