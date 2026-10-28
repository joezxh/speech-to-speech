// @vitest-environment jsdom
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { TOKEN_ENFORCED_GLOBS } from './tokens'

const SRC = join(__dirname, '..') // src/
const HEX = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/g

// tokens.ts 自身是色值定义处，与 color-mix 的 #fff/#000 端点一并豁免。
const EXEMPT = new Set(['styles/tokens.ts'])

function matches(glob: string, rel: string): boolean {
  if (glob.endsWith('/**')) return rel.startsWith(glob.slice(0, -3) + '/') || rel === glob.slice(0, -3)
  return rel === glob
}

/** 只取样式面：.less/.css/.ts 全文；.vue 的 <style> 块。 */
function styleSurface(file: string, text: string): string {
  if (file.endsWith('.vue')) {
    const blocks = [...text.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1])
    return blocks.join('\n')
  }
  return text
}

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name)
    return statSync(p).isDirectory() ? walk(p) : [p]
  })
}

describe('hex ban (ratchet)', () => {
  it('enforced files carry no bare hex on the style surface', () => {
    const offenders: string[] = []
    for (const abs of walk(SRC)) {
      const rel = abs.slice(SRC.length + 1).replace(/\\/g, '/')
      if (!/\.(ts|less|css|vue)$/.test(rel)) continue
      // TOKEN_ENFORCED_GLOBS 带 `src/` 前缀（见 tokens.ts），而 rel 相对于 src/ 目录不带，补回再匹配。
      if (!TOKEN_ENFORCED_GLOBS.some((g) => matches(g, `src/${rel}`))) continue
      if (EXEMPT.has(rel)) continue
      const hits = styleSurface(rel, readFileSync(abs, 'utf8')).match(HEX)
      // 允许 color-mix 端点 #fff/#000
      const bad = (hits ?? []).filter((h) => !/^#(?:fff|000)$/i.test(h))
      if (bad.length) offenders.push(`${rel}: ${bad.join(' ')}`)
    }
    expect(offenders).toEqual([])
  })
})
