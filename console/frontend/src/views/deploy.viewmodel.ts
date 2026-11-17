/** deploy 页纯视图模型（Task 23，11 列宽表/场景顾问/行级下发）。 */

export interface ParamRow {
  key: string
  expected: string | null
  actual: string | null
  drift: boolean
  source: string
  effect: string
  exposure: string
  risk: string
  anchor: string
  draft?: string
}

export interface Scene {
  name: string
  patches: Record<string, string>
  note: string
  why: string
  gain: string
  cost: string
  risk: string
}

export type RowTone = 'drift' | 'ro' | 'ops' | 'draft' | null

export function rowTone(r: ParamRow): RowTone {
  if (r.drift) return 'drift'
  if (r.exposure === 'ops') return 'ops'
  if (r.effect === 'startup' || r.effect === 'restart') return 'ro'
  if (r.draft !== undefined && r.draft !== r.expected) return 'draft'
  return null
}

export function applyScenario(scene: Scene, patch: Record<string, string>): Record<string, string> {
  const next = { ...patch }
  for (const [key, value] of Object.entries(scene.patches)) {
    // 只写与当前值不同的键（相同值不制造伪草稿行）。
    if (next[key] !== value) next[key] = value
  }
  return next
}

export const stageOf = (row: ParamRow): string => row.key.split('.')[0] || 'other'

/** 原型 g4 KPI 全部由真实参数目录字段推导，没有来源的场景名显式沿用当前选择。 */
export function deployKpis(
  rows: ParamRow[],
  driftCount: number,
  sceneName: string
): { params: number; drift: number; ops: number; hot: number; scene: string } {
  return {
    params: rows.length,
    drift: driftCount,
    ops: rows.filter((r) => r.exposure === 'ops').length,
    hot: rows.filter((r) => r.effect === 'hot' || r.effect === 'both').length,
    scene: sceneName
  }
}

export function groupChips(rows: ParamRow[]): Array<{ group: string; count: number }> {
  const counts = new Map<string, number>()
  for (const row of rows) {
    const stage = stageOf(row)
    counts.set(stage, (counts.get(stage) ?? 0) + 1)
  }
  return [
    { group: 'ALL', count: rows.length },
    ...[...counts.entries()].map(([group, count]) => ({ group, count }))
  ]
}

export function groupRows(rows: ParamRow[], group: string): ParamRow[] {
  return group === 'ALL' ? rows : rows.filter((row) => stageOf(row) === group)
}

/** 原型的“当前版本”无真源（backend 不下发 group 版本），显式 null 由页面显示 —。 */
export function deployStack(rows: ParamRow[]): Array<{ group: string; count: number; version: null }> {
  return groupChips(rows)
    .filter((chip) => chip.group !== 'ALL')
    .map((chip) => ({ group: chip.group, count: chip.count, version: null }))
}

export interface DiffRow {
  key: string
  current: string
  suggested: string
  state: 'same' | 'diff'
}

export function diffRows(scene: Scene, actual: Record<string, string>): DiffRow[] {
  return Object.entries(scene.patches).map(([key, suggested]) => ({
    key, suggested, current: actual[key] ?? '',
    state: (actual[key] ?? '') === suggested ? 'same' : 'diff',
  }))
}
