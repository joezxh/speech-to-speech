import type { VoiceRow, VoiceSource } from '@/types/voice-library'

export type Values = Record<string, unknown>

export interface Conflict {
  field: string
  with?: string
  reason?: string
}

export type VoiceSlot = 'builtin' | 'clone' | 'design'

/** §3.11.1 的表：与后端 `voice_service.BINDINGS` 逐字相同，两边各自算一遍（不互相信任）。 */
export const BINDINGS: Record<string, Record<string, string> | null> = {
  'builtin/qwen3': { speaker: 'qwen3_tts_speaker' },
  'builtin/openai_compatible': { speaker: 'openai_tts_voice' },
  'builtin/kokoro': { speaker: 'kokoro_voice', language: 'kokoro_lang_code' },
  'clone/qwen3': {
    refAudio: 'qwen3_tts_ref_audio',
    refText: 'qwen3_tts_ref_text',
    refSpk: 'qwen3_tts_ref_spk',
    refRvq: 'qwen3_tts_ref_rvq'
  },
  'design/qwen3': { instruct: 'qwen3_tts_instruct' },
  'design/openai_compatible': {
    instruct: 'openai_tts_instructions',
    taskType: 'openai_tts_task_type'
  }
}

export function bindings(source: VoiceSource, backend: string): Record<string, string> | null {
  return BINDINGS[`${source}/${backend}`] ?? null
}

/**
 * 切到 clone 时要顺手清掉的内置音色字段。`BINDINGS` 只回答「这个来源写哪些
 * 字段」，清空是反方向，所以单独一张表——设计 §3.11.4 的 patch 是 4 个键，
 * 第一个就是 `qwen3_tts_speaker: null`。
 */
const SPEAKER_ON_CLONE: Record<string, string> = {
  qwen3: 'qwen3_tts_speaker'
}

/**
 * 选中音色 → 草稿 patch。`cacheDir` 由调用方从 catalog 的 `qwen3_tts_ref_cache_dir`
 * 取（缺省 `/app/data/voices`），前端不内置绝对路径之外的任何东西。
 */
export function bindPatch(voice: VoiceRow, fields: Record<string, string>, cacheDir: string): Values {
  const base = `${cacheDir.replace(/\/+$/, '')}/${voice.id}`
  switch (voice.source) {
    case 'builtin':
      return { [fields.speaker]: voice.name }
    case 'clone': {
      // 预计算完成才有 spk / rvq；否则退回 refAudio。克隆与内置互斥：speaker
      // 必须显式置空，不然旧 speaker 会留着一起下发（§3.11.4 的 4 键形状）。
      const speaker = SPEAKER_ON_CLONE[voice.backend]
      const cleared = speaker ? { [speaker]: null } : {}
      return voice.status === 'ready'
        ? {
            ...cleared,
            [fields.refSpk]: `${base}/spk.npy`,
            [fields.refRvq]: `${base}/rvq.npy`,
            [fields.refText]: voice.refText ?? ''
          }
        : {
            ...cleared,
            [fields.refAudio]: `${base}/ref.wav`,
            [fields.refText]: voice.refText ?? ''
          }
    }
    case 'design':
      return { [fields.instruct]: voice.instruct ?? '' }
    default:
      return {}
  }
}

/** 与后端 `voice_service.conflicts` 同口径：先在草稿层拦住（§3.11.4）。 */
export function conflicts(patch: Values): Conflict[] {
  const errors: Conflict[] = []
  const has = (name: string) => Object.prototype.hasOwnProperty.call(patch, name)
  if (has('qwen3_tts_ref_audio') && has('qwen3_tts_ref_spk')) {
    errors.push({ field: 'qwen3_tts_ref_spk', with: 'qwen3_tts_ref_audio' })
  }
  if (has('qwen3_tts_ref_rvq') && !(has('qwen3_tts_ref_spk') && has('qwen3_tts_ref_text'))) {
    errors.push({ field: 'qwen3_tts_ref_rvq', reason: 'requires_spk_and_text' })
  }
  return errors
}

/** 参数字段下挂的音色池：只列该后端、且已 `ready` 的（A.18 固定文案）。 */
export function selectable(voices: VoiceRow[], backend: string): VoiceRow[] {
  return voices.filter((voice) => voice.backend === backend && voice.status === 'ready')
}

const SLOTS: Record<string, VoiceSlot> = {
  qwen3_tts_speaker: 'builtin',
  openai_tts_voice: 'builtin',
  kokoro_voice: 'builtin',
  kokoro_lang_code: 'builtin',
  qwen3_tts_ref_audio: 'clone',
  qwen3_tts_ref_text: 'clone',
  qwen3_tts_ref_spk: 'clone',
  qwen3_tts_ref_rvq: 'clone',
  qwen3_tts_instruct: 'design',
  openai_tts_instructions: 'design',
  openai_tts_task_type: 'design'
}

/**
 * 一条音色字段属于哪个控件位。同一个 `backend` 只有三个位置（builtin / clone /
 * design），所以 11 条字段不会渲染成 11 个选择器；`qwen3_tts_ref_cache_dir` 不是
 * 绑定字段，返回 null，仍由普通输入框渲染。
 */
export function voiceSlot(name: string): VoiceSlot | null {
  return SLOTS[name] ?? null
}

/** 槽位去重：`direct` 与 `folded` 各自只渲染每个槽位的第一个字段。 */
export function slotKey(backend: string | null, name: string): string | null {
  const slot = voiceSlot(name)
  return slot === null || backend === null ? null : `${backend}::${slot}`
}

/**
 * 从字段值里反查音色 id：值形如 `<ref_cache_dir>/<id>/spk.npy`。绑定字段可以由
 * 用户手改路径，所以找不到就返回 `null`，不能猜。
 */
export function voiceIdIn(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const parts = value.split(/[\\/]+/)
  const index = parts.indexOf('voices')
  return index >= 0 && index + 1 < parts.length ? parts[index + 1] : null
}
