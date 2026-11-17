import { describe, expect, it } from 'vitest'

import { auditCategory, rollPct, stageDots, type Release } from './release.viewmodel'

const release = (over: Partial<Release> = {}): Release => ({
  release_id: 'v1', version: 'v1', profile: 'prod', status: 'building',
  stage: 'building', created_by: 'alice', artifact_ref: '', changes: [],
  ...over,
})

describe('release viewmodel', () => {
  it('stageDots maps building to active build and others todo', () => {
    const dots = stageDots(release())
    expect(dots.find((d) => d.key === 'build')?.state).toBe('active')
    expect(dots.find((d) => d.key === 'staging')?.state).toBe('todo')
    expect(dots.find((d) => d.key === 'canary')?.state).toBe('todo')
    expect(dots.find((d) => d.key === 'rolling')?.state).toBe('todo')
  })

  it('stageDots maps rolled_back with canary done and rolling todo', () => {
    const dots = stageDots(release({ status: 'rolled_back', stage: 'rolled_back', changes: [{ stage: 'canary', result: 'ok', at: '' }] }))
    expect(dots.find((d) => d.key === 'canary')?.state).toBe('done')
    expect(dots.find((d) => d.key === 'rolling')?.state).toBe('todo')
  })

  it('rollPct prefers explicit pct then falls back to stage', () => {
    expect(rollPct(release({ status: 'rolling' }))).toBe(50)
    expect(rollPct(release({ status: 'current' }))).toBe(100)
    expect(rollPct(release({ status: 'rolled_back' }))).toBe(0)
  })

  it('auditCategory maps action prefix', () => {
    expect(auditCategory({ action: 'machine.create' } as never)).toBe('machine')
    expect(auditCategory({ action: 'publish' } as never)).toBe('other')
  })
})
