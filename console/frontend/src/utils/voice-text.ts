import i18n from '@/i18n'
import type { VoiceSource, VoiceStatus } from '@/types/voice-library'

/** §3.11.2 步骤 5：`errorCode` 原样展示，四个固定文案，不新增第五个。 */
const PRECOMPUTE_KEYS: Record<string, string> = {
  model_not_found: 'voices.precompute.modelNotFound',
  audio_too_short: 'voices.precompute.audioTooShort',
  oom_cpu: 'voices.precompute.oomCpu',
  timeout: 'voices.precompute.timeout'
}

export function precomputeText(code: string | null | undefined): string {
  if (!code) return ''
  return i18n.global.t(PRECOMPUTE_KEYS[code] ?? 'voices.precompute.failed')
}

const STATUS_KEYS: Record<VoiceStatus, string> = {
  draft: 'voices.status.draft',
  precomputing: 'voices.status.precomputing',
  ready: 'voices.status.ready',
  failed: 'voices.status.failed'
}

export function statusLabel(status: VoiceStatus): string {
  const key = STATUS_KEYS[status]
  return key ? i18n.global.t(key) : status
}

/** 表格 `bodyCell` 里的 `record` 是 `Record<string, any>`，用这两个收口，避免在模板里做类型断言。 */
export function statusText(status: unknown): string {
  return statusLabel(String(status) as VoiceStatus)
}

const SOURCE_KEYS: Record<VoiceSource, string> = {
  builtin: 'voices.source.builtin',
  clone: 'voices.source.clone',
  design: 'voices.source.design'
}

export function sourceLabel(source: VoiceSource): string {
  const key = SOURCE_KEYS[source]
  return key ? i18n.global.t(key) : source
}

export function sourceText(source: unknown): string {
  return sourceLabel(String(source) as VoiceSource)
}

/** 时长列：一位小数就够；内置音色没有参考音频（`0`）就不该显成“0.0 s”。 */
export function formatSeconds(seconds: unknown): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds <= 0) return '—'
  return `${seconds.toFixed(1)} s`
}

/**
 * `409 voice_in_use` 的那一句（设计 §14.7 / 计划 Step 10：三处文案一致）。
 * `detail` 是 `[{field:"profiles",value:[…]},{field:"versions",value:N}]`，只有
 * 这两个字段可信；版本是**计数**，所以这里说「N 个已发布版本」而不编造版本号。
 */
export function describeInUse(name: string, detail: unknown[]): string {
  let profiles: string[] = []
  let versions = 0
  for (const item of detail) {
    if (typeof item !== 'object' || item === null) continue
    const entry = item as { field?: unknown; value?: unknown }
    if (entry.field === 'profiles' && Array.isArray(entry.value)) {
      profiles = entry.value.map(String)
    } else if (entry.field === 'versions' && typeof entry.value === 'number') {
      versions = entry.value
    }
  }

  const total = profiles.length + versions
  if (total === 0) {
    return i18n.global.t('voices.inUse.none', { name })
  }

  let lead = ''
  if (profiles.length > 0) {
    lead = i18n.global.t('voices.inUse.draftSuffix', {
      profiles: profiles.join(i18n.global.t('voices.inUse.list'))
    })
  }
  if (versions > 0) {
    const published = i18n.global.t('voices.inUse.publishedCount', { count: versions })
    lead = lead ? i18n.global.t('voices.inUse.join', { a: lead, b: published }) : published
  }
  return i18n.global.t('voices.inUse.total', { name, lead, total })
}
