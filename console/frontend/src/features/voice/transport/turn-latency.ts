import type { TurnLatency } from '../types'

const TERMINAL_STATUSES = ['completed', 'cancelled', 'failed', 'incomplete']
const SOURCE_WITHOUT_TURN = ['client', 'tool']
const SMART_STATUSES = ['complete', 'incomplete', 'failed', 'disabled']

/** Seconds that are present must be real; `null` means “not measured”. */
function optionalSeconds(value: unknown): boolean {
  return value === undefined || value === null || (typeof value === 'number' && Number.isFinite(value) && value >= 0)
}

/**
 * Only terminal server measurements are trusted; older pipelines omit the
 * metadata entirely, which must read as “no numbers”, never as zero.
 */
export function readTurnLatency(response: any): TurnLatency | null {
  const raw = response?.metadata?.['speech_to_speech.turn_latency']
  if (typeof raw !== 'string') return null
  let data: any
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  if (!data || ![1, 2].includes(data.version)) return null

  const attributed =
    (typeof data.turn_id === 'string' && data.turn_id !== '') ||
    (data.version === 2 && SOURCE_WITHOUT_TURN.includes(data.source) && data.turn_id === null)
  if (!attributed) return null
  if (typeof data.response_key !== 'string' || data.response_key === '') return null
  if (!Number.isInteger(data.turn_revision) || data.turn_revision < 0) return null
  if (!TERMINAL_STATUSES.includes(data.status) || data.status !== response.status) return null
  if (!optionalSeconds(data.stt_s) || !optionalSeconds(data.llm_s)) return null
  if (!optionalSeconds(data.tts_ttfa_s) || !optionalSeconds(data.e2e_s)) return null
  if (!optionalSeconds(data.vad_decision_s) || !optionalSeconds(data.hold_s)) return null
  if (!optionalSeconds(data.smart_wait_s)) return null
  if (data.smart_status !== undefined && data.smart_status !== null && !SMART_STATUSES.includes(data.smart_status)) {
    return null
  }
  return data as TurnLatency
}
