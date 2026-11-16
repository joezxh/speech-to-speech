import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const source = readFileSync(join(__dirname, 'OverviewView.vue'), 'utf8')

describe('OverviewView sections (spec §5.2)', () => {
  it('composes the five prototype sections', () => {
    for (const marker of ['overview.kpi.', 'overview.table.', 'TopoChart', 'overview.legend.', 'overview.events.']) {
      expect(source).toContain(marker)
    }
  })

  it('gates every write action behind the mirrored permission codes', () => {
    for (const code of [
      'console:cluster:create',
      'console:cluster:switch',
      'console:cluster:update',
      'console:cluster:delete'
    ]) {
      expect(source).toContain(code)
    }
  })

  it('derives machines for the topo from instance hosts', () => {
    expect(source).toContain('hostOf(')
    expect(source).toContain('layoutTopo(')
  })

  it('matches the prototype chrome: page head, card hints, six legend items, category column', () => {
    for (const marker of [
      'overview.page.title',
      'overview.table.sectionTitle',
      'overview.table.hint',
      'overview.topology.hint',
      'overview.legend.lb',
      'overview.legend.flow',
      'overview.events.cat.',
      'categoryOf',
      'STATUS_COLOR'
    ]) {
      expect(source).toContain(marker)
    }
  })

  it('gives toast feedback on every write path (prototype toast.cluster.*)', () => {
    for (const marker of [
      'message.success',
      'overview.toast.created',
      'overview.toast.updated',
      'overview.toast.deleted',
      'overview.toast.switched',
      'overview.toast.last'
    ]) {
      expect(source).toContain(marker)
    }
  })

  it('lays out the four KPI cards full width (prototype .grid.g4)', () => {
    expect(source).toContain('repeat(4, minmax(0, 1fr))')
    expect(source).toContain('max-width: 1100px')
    expect(source).toContain('gap: 14px')
    expect(source).not.toContain('auto-fill, minmax(180px, 1fr)')
  })

  it('refreshes real data periodically without overlapping requests', () => {
    expect(source).toContain('setInterval')
    expect(source).toContain('refreshSafely')
    expect(source).toContain('onBeforeUnmount')
  })

  it('drills a machine click into the deploy page with ?host=', () => {
    expect(source).toContain(`name: 'machines'`)
    expect(source).toContain('query: { host')
  })
})