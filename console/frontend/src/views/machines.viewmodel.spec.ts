// Task 12（2026-11-17 原型对齐计划）——机器页视图模型纯函数。
import { describe, expect, it } from 'vitest'

import {
  buildReloadPayload,
  clusterOptions,
  commandActions,
  commandStatusView,
  filterMachines,
  healthState,
  latestHealth,
  normalizeReloadModules,
  nodeMetricSummary,
  serviceIdOf,
  testStepsToView,
  vramSummary,
  workloadTags,
  workloadParamEntries,
  type MachineCommandView,
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
  platform: 'gpu',
  driver: '',
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
      [{ name: 'default' }],
      'default'
    )
    expect(options).toHaveLength(1)
    expect(options[0].value).toBe('default')
  })
})

const command = (over: Partial<MachineCommandView>): MachineCommandView => ({
  commandId: 'c1',
  machineId: 'node-a01',
  kind: 'health_check',
  status: 'succeeded',
  payload: {},
  result: null,
  error: '',
  expiresAt: null,
  dispatchedAt: null,
  finishedAt: null,
  createdAt: null,
  ...over
})

describe('commandActions (prototype machine row actions)', () => {
  it('offers drain, reboot and config-then-restart on a healthy machine', () => {
    expect(commandActions('ok', []).map((a) => a.kind)).toEqual(['drain', 'reboot', 'config_restart'])
  })

  it('offers resume while draining and recover when unreachable', () => {
    expect(commandActions('draining', []).map((a) => a.kind)).toEqual(['resume'])
    expect(commandActions('unreachable', []).map((a) => a.kind)).toEqual(['recover'])
    expect(commandActions('bad', []).map((a) => a.kind)).toEqual(['recover'])
  })

  it('disables only the kinds with an in-flight command', () => {
    expect(commandActions('ok', ['drain'])).toEqual([
      { kind: 'drain', labelKey: 'machines.action.drain', disabled: true },
      { kind: 'reboot', labelKey: 'machines.action.reboot', disabled: false },
      { kind: 'config_restart', labelKey: 'machines.action.config_restart', disabled: false }
    ])
    expect(commandActions('draining', ['resume'])[0].disabled).toBe(true)
  })
})

describe('model_reload command (phase 1)', () => {
  it('normalizes modules in canonical order and drops unknown values', () => {
    expect(normalizeReloadModules(['tts', 'asr', 'tts', 'gpu'])).toEqual(['asr', 'tts'])
  })

  it('builds a camelCase payload with defaults', () => {
    expect(buildReloadPayload(['llm', 'asr'])).toEqual({
      modules: ['asr', 'llm'],
      scope: 'all',
      unitIndex: null,
      drain: true,
      drainTimeoutMs: 5000
    })
  })

  it('maps progress and expired command states', () => {
    expect(commandStatusView('dispatched')).toBe('running')
    expect(commandStatusView('progress')).toBe('running')
    expect(commandStatusView('expired')).toBe('expired')
    expect(commandStatusView('failed')).toBe('failed')
  })

  it('offers the reload action only when the agent declares the capability', () => {
    expect(commandActions('ok', [], false).map((a) => a.kind)).not.toContain('model_reload')
    expect(commandActions('ok', [], true).map((a) => a.kind)).toContain('model_reload')
    expect(commandActions('ok', ['model_reload'], true).find((a) => a.kind === 'model_reload')?.disabled).toBe(true)
  })
})

describe('nodeMetricSummary', () => {
  it('formats real node metrics and keeps missing values as dash', () => {
    expect(nodeMetricSummary({
      cpuPct: 12.5, memUsedGb: 20, memTotalGb: 64, memPct: 31.2,
      gpuUtilPct: 64, gpuMemUsedGb: 20.5, collectedAt: '2026-11-17T12:00:00Z'
    })).toEqual([
      { key: 'cpu', value: '12.5%' },
      { key: 'mem', value: '20 / 64 GB (31.2%)' },
      { key: 'gpu', value: '64%' },
      { key: 'gpuMem', value: '20.5 GB' },
      { key: 'collectedAt', value: '2026-11-17T12:00:00Z' }
    ])
    expect(nodeMetricSummary({})).toEqual([
      { key: 'cpu', value: '—' }, { key: 'mem', value: '—' }, { key: 'gpu', value: '—' },
      { key: 'gpuMem', value: '—' }, { key: 'collectedAt', value: '—' }
    ])
  })
})

describe('workloadParamEntries', () => {
  it('renders collected pipeline params in stable order without inventing values', () => {
    expect(
      workloadParamEntries({
        'tts.qwen3_tts_streaming_chunk_size': 4,
        'llm.model_name': 'qwen3.8-27b',
        'llm.responses_api_api_key': '***'
      })
    ).toEqual([
      { key: 'llm.model_name', value: 'qwen3.8-27b' },
      { key: 'llm.responses_api_api_key', value: '***' },
      { key: 'tts.qwen3_tts_streaming_chunk_size', value: '4' }
    ])
    expect(workloadParamEntries(undefined)).toEqual([])
  })
})

describe('service checks', () => {
  it('builds a stable service id from kind and port', () => {
    expect(serviceIdOf(workload({ kind: 'asr', port: 8011 }))).toBe('asr:8011')
    expect(serviceIdOf(workload({ kind: 'asr', port: null }))).toBe('asr')
  })

  it('picks the latest check command for a service', () => {
    const rows = [
      command({ commandId: 'c1', payload: { service_id: 'asr:8011' }, createdAt: '2026-01-01T00:00:00Z' }),
      command({ commandId: 'c2', kind: 'drain' }),
      command({ commandId: 'c3', payload: { service_id: 'asr:8011' }, createdAt: '2026-01-02T00:00:00Z' })
    ]
    expect(latestHealth(rows, 'asr:8011')?.commandId).toBe('c3')
    expect(latestHealth(rows, 'llm:8000')).toBeUndefined()
  })

  it('maps real check results to ok/bad/checking/unknown without fabrication', () => {
    expect(healthState(undefined)).toBe('unknown')
    expect(healthState(command({ status: 'pending' }))).toBe('checking')
    expect(healthState(command({ result: { reachable: true } }))).toBe('ok')
    expect(healthState(command({ status: 'failed', result: { reachable: false } }))).toBe('bad')
    expect(healthState(command({ result: { reachable: null } }))).toBe('unknown')
  })
})
