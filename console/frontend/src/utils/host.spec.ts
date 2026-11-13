import { describe, expect, it } from 'vitest'

import { hostOf } from './host'

describe('hostOf', () => {
  it('extracts the hostname with or without a scheme, dropping the port', () => {
    expect(hostOf('http://host1:8765')).toBe('host1')
    expect(hostOf('https://10.12.0.9:8765')).toBe('10.12.0.9')
    expect(hostOf('host2:8765')).toBe('host2')
  })

  it('falls back to the raw string for garbage instead of throwing', () => {
    expect(hostOf(':::')).toBe(':::')
    expect(hostOf('')).toBe('')
  })
})