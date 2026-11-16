import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const source = readFileSync(join(__dirname, 'InstancesView.vue'), 'utf8')

// Task 12 重写后 host 下钻的语义保留：?host= 进搜索词，命中机器表（filterMachines）。
describe('InstancesView host drilldown (spec §6 决议③)', () => {
  it('reads route.query.host and feeds it into the search', () => {
    expect(source).toContain('route.query.host')
    expect(source).toContain('filterMachines')
  })

  it('keeps watching the query so topology clicks always land', () => {
    expect(source).toContain('() => route.query.host')
  })
})
