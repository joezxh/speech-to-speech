/** release/audit 页纯视图模型（Task 26，四阶段圆点流水线/灰度条）。 */

export interface Release {
  release_id: string
  version: string
  profile: string
  status: string
  stage: string
  created_by: string
  artifact_ref: string
  changes: Array<Record<string, unknown>>
}

export interface StageDot {
  key: string
  state: 'done' | 'active' | 'todo'
}

const STAGES: Array<{ key: string; name: string }> = [
  { key: 'build', name: 'building' },
  { key: 'staging', name: 'staging' },
  { key: 'canary', name: 'canary' },
  { key: 'rolling', name: 'rolling' },
]

export function stageDots(r: Release): StageDot[] {
  // rolled_back：走过的阶段全部 done（圆点流水线不显示失败态/active 态）。
  const reachedIndex = r.status === 'rolled_back'
    ? Math.max(0, ...r.changes
        .map((c) => STAGES.findIndex((s) => s.name === c.stage))
        .filter((i) => i >= 0))
    : STAGES.findIndex((s) => s.name === r.status)
  return STAGES.map((stage, index) => {
    if (r.status === 'rolled_back') {
      return { key: stage.key, state: index <= reachedIndex ? ('done' as const) : ('todo' as const) }
    }
    return {
      key: stage.key,
      state: index < reachedIndex ? ('done' as const) : index === reachedIndex ? ('active' as const) : ('todo' as const),
    }
  })
}

export function rollPct(r: Release): number {
  if (r.status === 'current') return 100
  if (r.status === 'rolling') return 50
  if (r.status === 'rolled_back') return 0
  return 0
}

export function auditCategory(a: { action: string }): string {
  const prefixes = ['machine.', 'lb.', 'deploy.', 'release.', 'voice.', 'cluster.']
  for (const prefix of prefixes) {
    if (a.action.startsWith(prefix)) return prefix.slice(0, -1)
  }
  return 'other'
}
