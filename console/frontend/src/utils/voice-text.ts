import type { VoiceSource, VoiceStatus } from '@/types/voice-library'

/** §3.11.2 步骤 5：`errorCode` 原样展示，四个固定文案，不新增第五个。 */
const PRECOMPUTE_TEXT: Record<string, string> = {
  model_not_found: '未找到 VoiceDesign / 说话人模型',
  audio_too_short: '参考音频太短（< 3 s）',
  oom_cpu: 'CPU 内存不足',
  timeout: '预计算超时'
}

export function precomputeText(code: string | null | undefined): string {
  if (!code) return ''
  return PRECOMPUTE_TEXT[code] ?? '预计算失败'
}

const STATUS_TEXT: Record<VoiceStatus, string> = {
  draft: '草稿',
  precomputing: '制作中',
  ready: '可用',
  failed: '失败'
}

export function statusLabel(status: VoiceStatus): string {
  return STATUS_TEXT[status] ?? status
}

/** 表格 `bodyCell` 里的 `record` 是 `Record<string, any>`，用这两个收口，避免在模板里做类型断言。 */
export function statusText(status: unknown): string {
  return statusLabel(String(status) as VoiceStatus)
}

const SOURCE_TEXT: Record<VoiceSource, string> = {
  builtin: '内置',
  clone: '克隆',
  design: '指令设计'
}

export function sourceLabel(source: VoiceSource): string {
  return SOURCE_TEXT[source] ?? source
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
    return `无法删除「${name}」：仍被配置引用。先从这些配置里换成别的音色并发布，再回来删除。`
  }

  // 中文里「与」两侧不对称：前面不留空格、后面留一个（与后面的数字分开）。
  let lead = ''
  if (profiles.length > 0) lead = `${profiles.join('、')}（草稿）`
  if (versions > 0) lead = lead ? `${lead}与 ${versions} 个已发布版本` : `${versions} 个已发布版本`
  return `无法删除「${name}」：正被 ${lead}引用，共 ${total} 处。先从这些配置里换成别的音色并发布，再回来删除。`
}
