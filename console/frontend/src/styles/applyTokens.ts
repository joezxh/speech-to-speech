// styles/applyTokens.ts — 把 tokens.ts 注入 :root，让 less / 原生 CSS / ant 三方共源。
import { shellTokens, voiceTokens } from './tokens'

/** camelCase → kebab，数字段前也补分隔符（`colorSurface2` → `color-surface-2`）。 */
function kebab(key: string): string {
  return key
    .replace(/([A-Z])/g, '-$1')
    .replace(/([0-9])/g, '-$1')
    .toLowerCase()
}

/** shell：camelCase 字段 → --s2s-kebab（加前缀避开 ant 的 --ant-*）。 */
function shellVarName(key: string): string {
  return `--s2s-${kebab(key)}`
}

/** voice：沿用现名 --voice-kebab。 */
function voiceVarName(key: string): string {
  return `--${kebab(key)}`
}

export function applyTokens(): void {
  const root = document.documentElement
  for (const [key, value] of Object.entries(shellTokens)) root.style.setProperty(shellVarName(key), value)
  for (const [key, value] of Object.entries(voiceTokens)) root.style.setProperty(voiceVarName(key), value)
}
