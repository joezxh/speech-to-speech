import { describe, expect, it } from 'vitest'

import { formatSeconds, statusLabel, timingNote, timingRows, timingSummary } from './useTurnLatency'
import type { TurnLatency } from './types'

const v2: TurnLatency = {
  version: 2,
  turn_id: 't1',
  source: 'speech',
  turn_revision: 0,
  response_key: 'k1',
  status: 'completed',
  stt_s: 2.04,
  llm_s: 0.34,
  tts_ttfa_s: 0.5,
  e2e_s: 6.26,
  vad_decision_s: 0.55,
  smart_wait_s: null,
  smart_status: 'disabled',
  hold_s: null
}

describe('Server timings', () => {
  it('puts the E2E number in the summary line', () => {
    expect(timingSummary(v2)).toBe('Server timings · E2E 6.26 s')
  })

  it('drops back to two words when e2e was not measured', () => {
    expect(timingSummary({ ...v2, e2e_s: null })).toBe('Server timings')
  })

  it('labels a v1 record by its first-audio number instead of E2E', () => {
    expect(timingSummary({ ...v2, version: 1 })).toBe('Server timings · First audio 6.26 s')
  })

  it('writes the seven rows in the old page order and never prints a zero for a missing stage', () => {
    expect(timingRows(v2).map((row) => row.label)).toEqual([
      'E2E time',
      'VAD end decision',
      'Smart Turn decision',
      'Transcription',
      'Response generation',
      'Voice synthesis to first audio',
      'Hold time before response'
    ])
    expect(timingRows(v2).map((row) => row.value)).toEqual([
      '6.26 s',
      '0.55 s',
      'disabled',
      '2.04 s',
      '0.34 s',
      '0.50 s',
      'Unavailable'
    ])
    // v1 的最后一行取的是 smart_wait_s 而不是 hold_s（`chat.js:659`）。
    expect(timingRows({ ...v2, version: 1, smart_wait_s: 0.3 }).map((row) => row.value).pop()).toBe('0.30 s')
  })

  it('maps the four server statuses to the strings the old page painted', () => {
    expect(['completed', 'cancelled', 'failed', 'incomplete'].map(statusLabel)).toEqual([
      'Completed',
      'Interrupted',
      'Failed',
      'Incomplete'
    ])
  })

  it('keeps both footnote sentences verbatim and treats non-finite numbers as Unavailable', () => {
    expect(timingNote(v2)).toBe(
      'E2E: estimated speech end to first generated audio, excluding browser playback. Stages overlap and do not add up.'
    )
    expect(timingNote({ ...v2, version: 1 })).toBe(
      'First audio: VAD handoff to generated audio, excluding browser playback. Stages overlap and do not add up.'
    )
    expect(formatSeconds(Number.POSITIVE_INFINITY)).toBe('Unavailable')
  })
})
