// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'

import { applyTokens } from './applyTokens'
import { TOKEN_ENFORCED_GLOBS, shellTokens, voiceTokens } from './tokens'

describe('design tokens', () => {
  it('injects every shell and voice token as a CSS variable', () => {
    applyTokens()
    const style = document.documentElement.style
    // shell：camelCase → --s2s-kebab
    expect(style.getPropertyValue('--s2s-color-bg')).toBe(shellTokens.colorBg)
    expect(style.getPropertyValue('--s2s-color-surface-2')).toBe(shellTokens.colorSurface2)
    // voice：沿用现名 --voice-*
    expect(style.getPropertyValue('--voice-bg')).toBe(voiceTokens.voiceBg)
    expect(style.getPropertyValue('--voice-surface-2')).toBe(voiceTokens.voiceSurface2)
  })

  it('keeps the enforced-glob whitelist from shrinking', () => {
    expect(TOKEN_ENFORCED_GLOBS).toContain('src/styles/**')
    expect(TOKEN_ENFORCED_GLOBS).toContain('src/layouts/ConsoleLayout.vue')
    expect(TOKEN_ENFORCED_GLOBS).toContain('src/views/LoginView.vue')
  })
})
