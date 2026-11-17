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
