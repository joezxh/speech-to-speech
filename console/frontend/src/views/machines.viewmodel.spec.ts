// Task 12（2026-11-17 原型对齐计划）——机器页视图模型纯函数。
import { describe, expect, it } from 'vitest'

import {
  clusterOptions,
  filterMachines,
  testStepsToView,
  vramSummary,
  workloadTags,
  type MachineRow,
  type WorkloadRow
} from './machines.viewmodel'

const machine = (over: Partial<MachineRow>): MachineRow => ({
  machineId: 'node-a01',
  addr: '10.12.0.31',
  role: 'agent',
  gpu: 'L40S',
  state: 'ok',
  clusterId: 'default',
  profile: null,
  gpuTotalGb: null,
  version: '',
  registryMode: 'manual',
  agentVersion: '',
  protocolVersion: 1,
  lastSeen: null,
  workloads: [],
  ...over
})

const workload = (over: Partial<WorkloadRow>): WorkloadRow => ({
  kind: 'pipeline',
  engine: 'speech-to-speech-pipeline',
  model: '',
  port: 8765,
  listen: '127.0.0.1:8765',
  publicAddr: '10.12.0.31:8765',
  vramGb: null,
  healthPath: '/v1/pool',
  healthIntervalS: 5,
  note: '',
  ...over
})

describe('filterMachines', () => {
  const rows = [
    machine({ machineId: 'node-a01', addr: '10.12.0.31' }),
    machine({ machineId: 'node-b02', addr: '10.12.0.32', gpu: 'L20' })
  ]

  it('matches on machine id', () => {
    expect(filterMachines(rows, 'a01').map((m) => m.machineId)).toEqual(['node-a01'])
  })

  it('matches on addr', () => {
    expect(filterMachines(rows, '10.12.0.32').map((m) => m.machineId)).toEqual(['node-b02'])
  })

  it('empty query returns all; no hit returns empty', () => {
    expect(filterMachines(rows, '')).toHaveLength(2)
    expect(filterMachines(rows, 'ghost')).toHaveLength(0)
  })
})

describe('vramSummary', () => {
  it('sums declared vram and computes usage against the machine total', () => {
    const rows = [
      workload({ vramGb: 9.5 }),
      workload({ kind: 'llm', vramGb: 6.5 }),
      workload({ kind: 'embed', vramGb: null })
    ]
    expect(vramSummary(rows, 48)).toEqual({ usedGb: 16, totalGb: 48, pct: 33.3 })
  })

  it('without a machine total pct stays 0', () => {
    expect(vramSummary([workload({ vramGb: 8 })], null)).toEqual({ usedGb: 8, totalGb: 0, pct: 0 })
  })
})

describe('workloadTags', () => {
  it('groups by kind with counts, preserving first-seen order', () => {
    const rows = [
      workload({ kind: 'pipeline' }),
      workload({ kind: 'llm' }),
      workload({ kind: 'pipeline' })
    ]
    expect(workloadTags(rows)).toEqual([
      { kind: 'pipeline', count: 2 },
      { kind: 'llm', count: 1 }
    ])
  })
})

describe('testStepsToView', () => {
  it('projects backend steps onto key/label/state and marks simulate failures', () => {
    const view = testStepsToView([
      { key: 'step1', label: '向注册中心登记', state: 'pass', detail: {} },
      { key: 'step2', label: '已下发注册指令 —— 等待机器端 Agent 上报', state: 'fail', detail: {} },
      { key: 'step3', label: 'Agent 握手 · 心跳 · 版本上报', state: 'pending', detail: {} }
    ])
    expect(view).toEqual([
      { key: 'step1', label: '向注册中心登记', state: 'ok' },
      { key: 'step2', label: '已下发注册指令 —— 等待机器端 Agent 上报', state: 'fail' },
      { key: 'step3', label: 'Agent 握手 · 心跳 · 版本上报', state: 'running' }
    ])
  })
})

describe('clusterOptions', () => {
  it('lists cluster names and keeps the current value even when absent from the table', () => {
    const options = clusterOptions(
      [{ name: 'default' }, { name: 'edge' }],
      'staging'
    )
    expect(options.map((o) => o.value)).toEqual(['default', 'edge', 'staging'])
  })

  it('does not duplicate the current value when it exists in the table', () => {
    const options = clusterOptions(
      [{ id: 1, name: 'default', note: '', createdAt: '' }],
      'default'
    )
    expect(options).toHaveLength(1)
    expect(options[0].value).toBe('default')
  })
})
