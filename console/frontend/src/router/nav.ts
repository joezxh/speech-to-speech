import type { RouteRecordNormalized } from 'vue-router'

export type ShellFace = 'console' | 'voice'

/** 语音对话组里的「打开浮层」项——它们不是路由。 */
export type VoiceOverlay = 'history' | 'tools' | 'settings'

/** 侧栏图标：对应 index.html 里 `<symbol>` 去 `i-` 前缀。 */
export type NavIcon =
  | 'sliders' | 'wave' | 'history' | 'server' | 'check' | 'target' | 'wrench' | 'gear'
  | 'layers' | 'signal' | 'cpu'

export interface NavMeta {
  navGroup: 'lb' | 'front' | 'ops'
  navKey: string
  navIcon: NavIcon
  navOrder: number
}

/** 侧栏行：`to` 是路由名；历史 / 工具 / 设置已演进为独立路由页，不再有浮层行。 */
export interface NavRow { key: string; icon: NavIcon; labelKey: string; to?: string }
export interface NavGroup { key: 'lb' | 'front' | 'ops'; rows: NavRow[] }

const GROUP_ORDER: Array<NavGroup['key']> = ['lb', 'front', 'ops']

/**
 * 侧栏导航从路由表 `meta` 派生（spec §6.1）：`navGroup` 分桶、`navOrder` 排序，
 * 路由项受 `hasRoute` 约束。front 段的历史 / 工具 / 设置已是独立路由，
 * 不得再从别处拼一遍，否则侧栏菜单重复出现。
 */
export function buildNavGroups(
  records: RouteRecordNormalized[],
  hasRoute: (name: string) => boolean
): NavGroup[] {
  const buckets: Record<NavGroup['key'], Array<{ row: NavRow; order: number }>> = { lb: [], front: [], ops: [] }
  for (const rec of records) {
    const m = rec.meta as unknown as NavMeta
    if (!m.navKey || !m.navGroup) continue
    if (rec.name && !hasRoute(String(rec.name))) continue
    buckets[m.navGroup].push({
      row: { key: String(rec.name), icon: m.navIcon, labelKey: m.navKey, to: String(rec.name) },
      order: m.navOrder
    })
  }
  return GROUP_ORDER.map((key) => ({
    key,
    rows: buckets[key].sort((a, b) => a.order - b.order).map((entry) => entry.row)
  })).filter((group) => group.rows.length > 0)
}
