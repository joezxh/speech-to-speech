import { describe, expect, it } from 'vitest'

import { readTurnLatency } from './turn-latency'

const good = {
  version: 2,
  turn_id: 't1',
  source: 'speech',
  turn_revision: 0,
  response_key: 'k1',
  status: 'completed',
  stt_s: 0.12,
  llm_s: 0.34,
  tts_ttfa_s: 0.05,
  e2e_s: 0.51,
  vad_decision_s: 0.16,
  smart_wait_s: null,
  smart_status: 'disabled',
  hold_s: 0
}

function wrap(data: unknown, status = 'completed') {
  return { status, metadata: { 'speech_to_speech.turn_latency': JSON.stringify(data) } }
}

describe('readTurnLatency', () => {
  it('accepts a well-formed v2 record', () => {
    expect(readTurnLatency(wrap(good))).toMatchObject({ e2e_s: 0.51, status: 'completed' })
  })

  it('accepts a v2 record with no turn id when the source is client or tool', () => {
    expect(readTurnLatency(wrap({ ...good, turn_id: null, source: 'tool' }))).not.toBeNull()
    // Same shape but a speech turn with no id is not attributable, so it is dropped.
    expect(readTurnLatency(wrap({ ...good, turn_id: null, source: 'speech' }))).toBeNull()
  })

  it('drops a record whose status disagrees with the response', () => {
    expect(readTurnLatency(wrap(good, 'cancelled'))).toBeNull()
  })

  it('drops negative or non-finite measurements instead of rendering them', () => {
    expect(readTurnLatency(wrap({ ...good, e2e_s: -1 }))).toBeNull()
    expect(readTurnLatency(wrap({ ...good, llm_s: null }))).not.toBeNull()
  })

  it('returns null for a missing, malformed or unknown-version payload', () => {
    expect(readTurnLatency({ status: 'completed' })).toBeNull()
    expect(readTurnLatency(wrap({ ...good, version: 3 }))).toBeNull()
    expect(
      readTurnLatency({ status: 'completed', metadata: { 'speech_to_speech.turn_latency': '{' } })
    ).toBeNull()
  })
})
