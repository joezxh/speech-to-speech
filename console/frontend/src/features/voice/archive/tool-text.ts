/**
 * tool 轮次的归档文本（Spec D6）。
 *
 * 抽屉里一次调用是两栏（Input / Output，见 `TranscriptTool`），归档只有一列
 * `voice_turns.text`，所以按「调用 → 结果」拼成一行：后来者用同一个 natural key
 * 覆写前一版，读的人看到的就是完整的因果。
 *
 * 故意不做的：把截图的 base64 写进文本。`text` 是给人读的转写，一个 data URL
 * 会把它撑成一堵墙，而图片本来也没有第二个落点——归档里有文件的只有音频。
 */
import type { ToolCallRecord, ToolResultRecord } from '../transport/events'

/** `{}` 与空串都等于「这个工具不吃参数」，写进归档就是噪音。 */
function argumentText(raw: string): string {
  const value = (raw ?? '').trim()
  if (!value || value === '{}') return ''
  return value
}

/** 调用先到的那半行：只有名字与参数，结果还没存在。 */
export function toolCallText(call: ToolCallRecord): string {
  const args = argumentText(call.arguments)
  const name = (call.name ?? '').trim() || 'tool'
  return args ? `${name}(${args})` : name
}

/** 结果后到的那半行：把调用与输出合成一行，覆盖 `toolCallText` 写下的那一版。 */
export function toolResultText(result: ToolResultRecord): string {
  const call = toolCallText(result)
  const output = (result.output ?? '').trim()
  // 没有文字输出时也要留个记号：快照类工具（camera_snapshot）的成功就是「有图」。
  const outcome = output || (result.image ? '[image]' : '[no output]')
  return `${call} → ${outcome}${result.failed ? ' (failed)' : ''}`
}
