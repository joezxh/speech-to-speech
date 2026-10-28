import i18n from '@/i18n'
import type { LogAnalysis } from '@/types/logs'
import { groupThousands } from '@/utils/format'

/**
 * A.16 的头部一行：说清「送了多少、估多少 token、有没有截断、附带多少轮次」。
 * 这一行不是修饰——截断与否决定了这份结论能看到多少证据。
 */
export function sentSummary(sent: LogAnalysis['sent']): string {
  const sep = ' · '
  const base = `${i18n.global.t('logs.sent.lines', { n: groupThousands(sent.lines) })} / ${i18n.global.t('logs.sent.approxTokens', { n: (sent.estimatedTokens / 1000).toFixed(1) })}`
  const dropped = sent.truncated ? `${sep}${i18n.global.t('logs.sent.dropped', { n: groupThousands(sent.droppedLines) })}` : ''
  // 0 条不写：附带 0 条轮次只会让人怀疑哪里出了错。
  const turns = sent.turnRows > 0 ? `${sep}${i18n.global.t('logs.sent.turns', { n: groupThousands(sent.turnRows) })}` : ''
  return `${base}${dropped}${turns}`
}

/** 置信度是一个 0–1 的数，界面只说高 / 中 / 低。 */
export function confidenceText(value: number): string {
  return value >= 0.7 ? i18n.global.t('logs.confidence.high') : value >= 0.4 ? i18n.global.t('logs.confidence.medium') : i18n.global.t('logs.confidence.low')
}

export type RiskLevel = 'ok' | 'warn' | 'bad'

/** `actions[].risk` 是模型写的自由文本，这里只按关键字分级上色。 */
export function riskLevel(risk: string): RiskLevel {
  const text = risk.toLowerCase()
  if (text.includes('高') || text.includes('high') || text.includes('restart')) return 'bad'
  if (text.includes('中') || text.includes('medium')) return 'warn'
  return 'ok'
}
