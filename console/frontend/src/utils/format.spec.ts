import { describe, expect, it } from 'vitest'

import { formatBytes, formatDuration, formatTime } from './format'

describe('formatTime', () => {
  it('renders a UTC instant without the T', () => {
    expect(formatTime('2026-10-24T08:09:10Z')).toBe('2026-10-24 08:09:10')
  })

  it('renders an empty value as a dash, not as the epoch', () => {
    expect(formatTime(null)).toBe('—')
    expect(formatTime('')).toBe('—')
  })
})

describe('formatDuration', () => {
  it('keeps one decimal under ten seconds and drops it above', () => {
    expect(formatDuration(0.4)).toBe('0.4s')
    expect(formatDuration(41.27)).toBe('41s')
    expect(formatDuration(null)).toBe('—')
  })
})

describe('formatBytes', () => {
  it('keeps bytes whole and carries one decimal upwards', () => {
    expect(formatBytes(96_044)).toBe('93.8 KB')
    expect(formatBytes(8 * 1024 * 1024)).toBe('8.0 MB')
    expect(formatBytes(512)).toBe('512 B')
    expect(formatBytes(0)).toBe('0 B')
  })

  it('renders a missing size as a dash instead of 0 B', () => {
    expect(formatBytes(null)).toBe('—')
    expect(formatBytes(undefined)).toBe('—')
    expect(formatBytes(Number.NaN)).toBe('—')
  })
})
