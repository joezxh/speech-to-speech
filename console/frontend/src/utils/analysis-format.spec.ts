import { describe, expect, it } from 'vitest'

import { confidenceText, riskLevel, sentSummary } from './analysis-format'

describe('sentSummary', () => {
  it('omits the truncation clause when nothing was dropped', () => {
    expect(sentSummary({ lines: 120, estimatedTokens: 800, truncated: false, droppedLines: 0, turnRows: 0 })).toBe(
      '已送入 120 行 / 约 0.8k tokens（估算）'
    )
  })

  it('keeps both the line count and the token estimate when the window was cut', () => {
    const text = sentSummary({
      lines: 412,
      estimatedTokens: 5800,
      truncated: true,
      droppedLines: 1200,
      turnRows: 0
    })
    expect(text).toBe('已送入 412 行 / 约 5.8k tokens（估算） · 已截断 1 200 行')
  })

  it('mentions the attached turn rows only when there are some', () => {
    expect(
      sentSummary({ lines: 412, estimatedTokens: 5800, truncated: false, droppedLines: 0, turnRows: 38 })
    ).toBe('已送入 412 行 / 约 5.8k tokens（估算） · 附带 38 条轮次')
    expect(
      sentSummary({ lines: 412, estimatedTokens: 5800, truncated: false, droppedLines: 0, turnRows: 0 })
    ).not.toContain('轮次')
  })
})

describe('confidenceText', () => {
  it('collapses a 0–1 number into high / medium / low', () => {
    expect(confidenceText(0.82)).toBe('高')
    expect(confidenceText(0.4)).toBe('中')
    expect(confidenceText(0.39)).toBe('低')
  })
})

describe('riskLevel', () => {
  it('grades a free-text risk by keyword', () => {
    expect(riskLevel('高：需要重启 pipeline')).toBe('bad')
    expect(riskLevel('medium')).toBe('warn')
    expect(riskLevel('低')).toBe('ok')
  })
})
