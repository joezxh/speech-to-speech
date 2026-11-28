// utils/hotParams.ts — 对话态热更参数表（原型「对话态热更」模块的数据与白名单判定）。
// 白名单与后端 hot_update_service.WHITELIST 同源维护：instructions、extensions、
// audio.input.turn_detection、audio.input.transcription.language。模板/设置页可以
// 展示更多「运行时可变」参数，但下发前必须先过这里的判定，避免 400 unsupported_field。

export interface HotParamDef {
  name: string
  /** session.update 里的路径（后端 prune 的对象）。 */
  patch: string
  /** 目录参数键（机器配置视图里匹配 actual 值用；后缀匹配，容忍前缀差异）。 */
  catalogKey: string
  label: { zh: string; en: string }
}

export const HOT_PARAMS: HotParamDef[] = [
  {
    name: 'thresh',
    patch: 'audio.input.turn_detection.threshold',
    catalogKey: 'vad.thresh',
    label: { zh: 'VAD 语音阈值', en: 'VAD speech threshold' }
  },
  {
    name: 'min_silence_ms',
    patch: 'audio.input.turn_detection.silence_duration_ms',
    catalogKey: 'vad.min_silence_ms',
    label: { zh: '判停静音时长', en: 'Endpointing silence' }
  },
  {
    name: 'qwen3_asr_language',
    patch: 'audio.input.transcription.language',
    catalogKey: 'stt.qwen3_asr_language',
    label: { zh: '识别语言', en: 'Transcription language' }
  },
  {
    name: 'init_chat_prompt',
    patch: 'instructions',
    catalogKey: 'llm.init_chat_prompt',
    label: { zh: '对话人设提示词', en: 'Chat persona prompt' }
  },
  {
    name: 'instructions',
    patch: 'instructions',
    catalogKey: 'llm.instructions',
    label: { zh: '会话指令', en: 'Session instructions' }
  },
  {
    name: 'qwen3_tts_speaker',
    patch: 'audio.output.voice',
    catalogKey: 'tts.qwen3_tts_speaker',
    label: { zh: 'TTS 音色', en: 'TTS voice' }
  },
  {
    name: 'voice',
    patch: 'audio.output.voice',
    catalogKey: 'tts.voice',
    label: { zh: '输出音色', en: 'Output voice' }
  },
  {
    name: 'model',
    patch: 'model',
    catalogKey: 'llm.model_name',
    label: { zh: '对话模型', en: 'Conversation model' }
  }
]

/** 与后端 prune 同构的路径判定：先切路径，再逐级对白名单树放行。 */
const WHITELIST: Record<string, unknown> = {
  instructions: null,
  extensions: null,
  audio: { input: { turn_detection: null, transcription: { language: null } } }
}

export function isHotPath(patch: string): boolean {
  // 叶子为 null 的含义与后端 _walk 一致：该子树整体放行（任意下级路径都算热更）。
  let node: unknown = WHITELIST
  for (const part of patch.split('.')) {
    if (node === null) return true
    if (node && typeof node === 'object' && part in (node as Record<string, unknown>)) {
      node = (node as Record<string, unknown>)[part]
    } else {
      return false
    }
  }
  // 路径必须落在 null 叶子上（整子树放行）；落在中间分支（如 transcription）不算合法终点。
  return node === null
}

export const hotParamByName = (name: string): HotParamDef | undefined =>
  HOT_PARAMS.find((param) => param.name === name)

/** 机器配置行里按目录键后缀匹配实际值（键可能是 vad.min_silence_ms 或 min_silence_ms）。 */
export function actualForParam(rows: Array<{ key: string; actual: string | null }>, catalogKey: string): string | null {
  const suffix = catalogKey.split('.').pop() ?? catalogKey
  const row =
    rows.find((item) => item.key === catalogKey) ??
    rows.find((item) => item.key.endsWith(`.${suffix}`) || item.key === suffix)
  return row?.actual ?? null
}

/** 把若干 (参数名, 值) 组装成 session.update 形状的 patch（丢弃不在白名单里的项）。 */
export function buildSessionPatch(values: Record<string, string>): {
  patch: Record<string, unknown>
  rejected: string[]
} {
  const patch: Record<string, unknown> = {}
  const rejected: string[] = []
  for (const [name, value] of Object.entries(values)) {
    const def = hotParamByName(name)
    if (!def) {
      rejected.push(name)
      continue
    }
    if (!isHotPath(def.patch)) {
      rejected.push(name)
      continue
    }
    const parts = def.patch.split('.')
    let node = patch as Record<string, unknown>
    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index]
      if (index === parts.length - 1) node[part] = value
      else {
        if (typeof node[part] !== 'object' || node[part] === null) node[part] = {}
        node = node[part] as Record<string, unknown>
      }
    }
  }
  return { patch, rejected }
}
