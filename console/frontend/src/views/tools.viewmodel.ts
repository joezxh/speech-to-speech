import type { ToolFilter, ToolRow } from '@/api/tools'

export interface ToolKpis {
  total: number
  on: number
  builtin: number
  custom: number
}

export function isToolEnabled(row: ToolRow, sessionEnabled: Record<string, boolean> = {}): boolean {
  return row.effectiveEnabled === null ? Boolean(sessionEnabled[row.id]) : Boolean(row.effectiveEnabled)
}

export function applyToolFilter(rows: ToolRow[], filter: ToolFilter, sessionEnabled: Record<string, boolean> = {}): ToolRow[] {
  const q = (filter.q ?? '').trim().toLowerCase()
  const enabled = (row: ToolRow) => isToolEnabled(row, sessionEnabled)
  return rows.filter(
    (row) =>
      (!filter.type || filter.type === 'all' || row.type === filter.type) &&
      (!filter.scope || filter.scope === 'all' || row.scope === filter.scope) &&
      (!filter.on || filter.on === 'all' || String(enabled(row)) === filter.on) &&
      (!q || `${row.name} ${row.id} ${row.description} ${row.type}`.toLowerCase().includes(q))
  )
}

export function toolKpis(rows: ToolRow[], sessionEnabled: Record<string, boolean> = {}): ToolKpis {
  return {
    total: rows.length,
    on: rows.filter((row) => isToolEnabled(row, sessionEnabled)).length,
    builtin: rows.filter((row) => row.builtin).length,
    custom: rows.filter((row) => !row.builtin).length
  }
}

export function toolParamText(row: ToolRow): string {
  if (!row.params.length) return '—'
  return row.params.map((p) => `${p.k}:${p.t}${p.req ? '!' : ''}`).join(' · ')
}
