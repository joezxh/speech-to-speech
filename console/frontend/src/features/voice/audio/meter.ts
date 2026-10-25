/** The gate slider and the level bar share one dB axis (demo/main.js:51-56). */
export const GATE_OFF_DB = -66
export const GATE_MAX_DB = -3
export const GATE_DEFAULT_DB = -50

/** Local speech detection: open above this, hold this long (demo client). */
export const SPEAKING_OPEN_DB = -50
export const SPEAKING_HANG_MS = 250

const SILENCE_DB = -100

export function rmsToDb(samples: Float32Array): number {
  if (!samples.length) return SILENCE_DB
  let sum = 0
  for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i]
  const rms = Math.sqrt(sum / samples.length)
  // log10(0) is -Infinity; the meter has to stay a number the UI can format.
  return rms > 0 ? 20 * Math.log10(rms) : SILENCE_DB
}

export function dbToPercent(db: number): number {
  const clamped = Math.min(GATE_MAX_DB, Math.max(GATE_OFF_DB, db))
  return ((clamped - GATE_OFF_DB) / (GATE_MAX_DB - GATE_OFF_DB)) * 100
}

/**
 * 弧上的反向映射：拖拽把手得到的 0-1 比例换回 dB。
 * `MicGate.vue` 的 `atan2` 在缺口里会算出 [0,1] 之外的值，必须夹住。
 */
export function fractionToDb(fraction: number): number {
  const clamped = Math.min(1, Math.max(0, fraction))
  return GATE_OFF_DB + clamped * (GATE_MAX_DB - GATE_OFF_DB)
}

/** `thresholdDb === GATE_OFF_DB` is the OFF detent: the gate never opens. */
export function gateOpen(levelDb: number, thresholdDb: number): boolean {
  return thresholdDb > GATE_OFF_DB && levelDb > thresholdDb
}

/** Hysteresis on release only: opening is immediate, closing waits out noise. */
export class SpeakingDetector {
  private lastVoiceAt = Number.NEGATIVE_INFINITY

  constructor(private readonly now: () => number = () => performance.now()) {}

  push(levelDb: number): boolean {
    const at = this.now()
    if (levelDb > SPEAKING_OPEN_DB) this.lastVoiceAt = at
    return at - this.lastVoiceAt <= SPEAKING_HANG_MS
  }

  reset(): void {
    this.lastVoiceAt = Number.NEGATIVE_INFINITY
  }
}
