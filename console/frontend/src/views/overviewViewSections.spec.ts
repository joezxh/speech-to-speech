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

  it('drills a machine click into the deploy page with ?host=', () => {
    expect(source).toContain(`name: 'machines'`)
    expect(source).toContain('query: { host')
  })
})