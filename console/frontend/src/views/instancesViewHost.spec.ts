import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const source = readFileSync(join(__dirname, 'InstancesView.vue'), 'utf8')

describe('InstancesView host drilldown (spec §6 决议③)', () => {
  it('reads route.query.host and feeds it to the table datasource', () => {
    expect(source).toContain('route.query.host')
    expect(source).toContain('visibleInstances')
    expect(source).toContain(':data-source="visibleInstances"')
  })

  it('keeps the unfiltered rows computed intact', () => {
    expect(source).toContain('const instances = computed(() => snapshot.value?.instances ?? [])')
  })
})