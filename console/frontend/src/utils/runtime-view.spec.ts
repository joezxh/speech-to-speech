import { describe, expect, it } from 'vitest'

import type { RuntimeStage } from '@/types/runtime'
import { busyText, firstByteText, gpuHeadline, latencyText, loadLabel, modelText, vramText } from './runtime-view'

function stageFixture(patch: Partial<RuntimeStage> = {}): RuntimeStage {
  return {
    stage: 'tts',
    modelName: 'qwen3-tts-model',
    backend: 'torch',
    loaded: true,
    vram: { usedMb: 2048, percent: 25 },
    busy: { inUse: 1, size: 1, occupied: true, queueDepth: null },
    latency: { firstByteMs: 110, processMs: 420, p50Ms: 420, p95Ms: 980 },
    reasons: { queueDepth: 'queue_depth_not_exposed' },
    ...patch
  }
}

describe('runtime card text', () => {
  it('renders the reason code instead of a zero when vram is missing', () => {
    const stage = stageFixture({
      loaded: false,
      vram: { usedMb: null, percent: null },
      reasons: {
        loaded: 'pipeline_stopped',
        vram: 'nvidia_smi_missing',
        queueDepth: 'queue_depth_not_exposed'
      }
    })
    expect(vramText(stage)).toBe('不可用 · nvidia_smi_missing')
    expect(vramText(stage)).not.toContain('0 MB')
  })

  it('says not loaded and names the reason instead of leaving the model blank', () => {
    const stage = stageFixture({
      loaded: false,
      modelName: null,
      reasons: { loaded: 'pipeline_stopped', queueDepth: 'queue_depth_not_exposed' }
    })
    expect(loadLabel(stage.loaded)).toBe('not loaded')
    expect(modelText(stage)).toBe('不可用 · pipeline_stopped')
  })

  it('keeps a loaded stage honest when no call was traced to name it', () => {
    // Deployed STT/LLM are not instrumented, so a running stage has no name yet
    // is still loaded — say so plainly rather than an 'unavailable' code.
    const stage = stageFixture({
      loaded: true,
      modelName: null,
      reasons: { queueDepth: 'queue_depth_not_exposed' }
    })
    expect(loadLabel(stage.loaded)).toBe('loaded')
    expect(modelText(stage)).toBe('已加载 · 窗口内无调用样本')
  })

  it('renders p50 / p95 when they exist and a reason when they do not', () => {
    expect(latencyText(stageFixture())).toBe('420 / 980 ms')
    expect(firstByteText(stageFixture())).toBe('110 ms')

    const unmeasured = stageFixture({
      latency: { firstByteMs: null, processMs: null, p50Ms: null, p95Ms: null },
      reasons: { firstByte: 'first_byte_not_instrumented', latency: 'no_metrics_window' }
    })
    expect(latencyText(unmeasured)).toBe('不可用 · no_metrics_window')
    expect(firstByteText(unmeasured)).toBe('不可用 · first_byte_not_instrumented')
  })

  it('keeps queue depth unavailable rather than reporting an empty queue', () => {
    expect(busyText(stageFixture())).toBe('1 / 1 占用中')
    expect(stageFixture().busy.queueDepth).toBeNull()
  })
})

describe('gpu headline', () => {
  it('prints the card totals when the driver answers', () => {
    expect(gpuHeadline({ available: true, name: 'RTX 4090', totalMb: 24576, usedMb: 18420, percent: 75 })).toBe(
      'RTX 4090 · 18420 / 24576 MB · 75%'
    )
  })

  it('names the reason when the driver is absent', () => {
    expect(gpuHeadline({ available: false, reason: 'nvidia_smi_missing' })).toBe(
      'GPU 不可用 · nvidia_smi_missing'
    )
  })
})
