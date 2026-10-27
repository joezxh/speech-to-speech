# 控制台信息架构重构 S1（三段式导航外壳 + i18n 基座 + token 收敛）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `console/` 前端外壳对齐静态原型的信息架构，补上 en/zh 成对 i18n 与单一事实来源的设计 token，并真实只读实现集群总览、流量与路由两个新页。

**Architecture:** 设计 token 收敛到 `styles/tokens.ts` 单源、运行时注入 `:root` 后同时驱动 ant 主题 / less / 原生 CSS；导航从路由表 `meta` 派生而非手工常量；i18n 用嵌套结构、按域（域 = route name）拆文件、locale 存 localStorage；两个新页复用既有 `GET /status` + `GET /instances`，流量页新增唯一后端只读端点 `GET /api/v1/traffic/settings`。

**Tech Stack:** Vue 3 + `<script setup>` + TypeScript、vue-router、pinia、vue-i18n(legacy:false)、ant-design-vue、less、Vite、vitest（`environment:'node'`，DOM 用例文件首行 `// @vitest-environment jsdom`）；后端 FastAPI + SQLAlchemy + pydantic-settings + pytest。

**Spec:** `docs/superpowers/specs/2026-10-28-console-ia-i18n-shell-design.md` — 本计划逐节实现该 spec，执行者同时读两份。

## Global Constraints

每个任务的验收都隐含本节。以下值逐字来自 spec。

- **门槛（每步都跑，四道全绿才算完）**：`cd console/frontend && npx vue-tsc --noEmit` 错误**恰好等于**附录 A 的 5 条（不新增也不减少，S8 才清）；`npm run lint`（= `eslint . --max-warnings 0`）全绿；`npx vitest run` 全绿；后端 `pytest`（`console/backend`）全绿。
- **`npm run build` = `copy-vendors.mjs && vue-tsc --noEmit && vite build`** — 类型检查是构建门禁。
- **术语与实现解耦**：UI 一律用 demo 术语；后端契约（API 路径 / DB 表 / service 名）一律不改。
- **代码态保留清单不键化、原样渲染**：引擎与后端名（`qwen3_asr` `qwen3_tts` `cosyvoice` `omnivoice` `ggml` `openapi`）；参数键名（`qwen3_tts_speaker` 等）；端口 / 路径 / URL（`8765` `/v1/realtime` `/api/v1/instances`）；错误码原文（`at_capacity` `recording_disabled` `not_found` `invalid_request` `session_limit_reached`）；标识符（`instance_id`、profile 名、版本号、commit hash）；数字与时间格式（保持 `format.ts` 确定性输出）。
- **展示译、比较不译**：状态枚举 `online / degraded / offline / draining / idle / active / stuck` 界面显示译文，但在 `data-testid`、排序键、与后端返回值的一切比较中一律用原值。
- **i18n 键结构禁止点分扁平键**：vue-i18n 默认 `messageResolver` 按 `.` 切段遍历对象，扁平键取不到值。顶层 = 域名，叶子小驼峰，嵌套 ≤ 三层。插值用命名式 `{count}`；仅英文确需区分单复数才用 `one|other`。
- **hex 禁令作用域 = 样式面**：`.less`/`.css`/`.ts` 全文 + `.vue` 的 `<style>` 块；模板内联 SVG `fill="#…"` 不在禁令内。仅对 `TOKEN_ENFORCED_GLOBS` 命中的文件断言。白名单**只增不减**。
- **不引入新依赖**：glob 解析由测试自己完成（`import.meta.glob` 或等价路径匹配）。
- **不新建 Playwright 套件**；不修 `test:e2e` 悬空；不统一 `instances`/`status` 的 casing；不合并语音页与外壳两套调色板。
- **git 安全**：本计划不 merge、不 force-push、不改写历史；每个任务结束按说明提交，提交信息中不含 `codex`。

## File Structure（本段创建/改动的全景）

**新建 — 前端**
- `src/styles/tokens.ts` — `shellTokens` / `voiceTokens` / `TOKEN_ENFORCED_GLOBS` 单源。
- `src/styles/applyTokens.ts` — 把 tokens 注入 `:root`（camelCase→kebab、`--s2s-*`/`--voice-*`）。
- `src/i18n/locale.ts` — 支持的 locale 常量、`navigator.language` 检测、localStorage 读写。
- `src/i18n/locales/zh-CN/{index,nav,shell,common,errors,auth,machines,deploy,sessionUpdate,voices,release,audit,voice,logs,latency,overview,traffic}.ts`
- `src/i18n/locales/en-US/{…同名同构…}.ts`
- `src/stores/locale.ts` — pinia locale store。
- `src/views/OverviewView.vue` — 集群总览（只读）。
- `src/views/TrafficView.vue` — 流量与路由（只读，内嵌趋势）。
- `src/components/NotImplemented.vue` — 未实现区块（props：`targetSubproject` + i18n 键）。
- `src/api/traffic.ts` — `getTrafficSettings()`。
- 测试：`src/styles/tokens.spec.ts`、`src/i18n/i18n.spec.ts`、`src/stores/locale.spec.ts`、`src/views/OverviewView.spec.ts`、`src/views/TrafficView.spec.ts`（后两者首行 `// @vitest-environment jsdom`）。

**新建 — 后端**
- `app/routers/traffic.py` — `GET /api/v1/traffic/settings`（唯一后端改动，additive）。
- `tests/integration/test_traffic_api.py`。

**修改 — 前端**
- `src/main.ts` — `mount()` 前同步 `applyTokens()`。
- `src/App.vue` — 补 `:locale="antLocale"`。
- `src/styles/theme.ts` — 从 `tokens.ts` 派生 16 个 ant token。
- `src/styles/variables.less` — 6 个值改为转发 `var(--s2s-*)`。
- `src/styles/voice.less` — 删 `:root` 块（值搬入 `tokens.ts`）。
- `src/layouts/ConsoleLayout.vue` — 导航改派生 + i18n + 语言切换器 + 19 处 hex 换 token。
- `src/views/LoginView.vue` — 3 处 hex 换 token。
- `src/router/index.ts` — 重命名、加 5 条 redirect、加 NavMeta、默认页改 overview。
- `src/router/nav.ts` — 删 `NAV_GROUPS`，保留类型 + `frontOverlays`，`NavIcon` 增删。
- `src/router/router.spec.ts` — 更新断言。
- `src/utils/storage.ts` — 新增 locale 键、改注释。
- 其余 views/components（步骤 4 的按域键化）。

**删除 — 前端**
- `src/i18n/zh-CN.ts`（18 行死代码，整体删除不迁移）。

---

## Task 0: 提交脏树成基线

把未纳入版本控制的「录音归档」前端线与当前所有工作树改动固化成基线提交，并把 `vue-tsc` 的 5 条错误作为 S8 输入记录在案。这一步不动任何代码，只建立干净起点。

**Files:**
- 无代码改动；仅 `git add -A` + commit。

**Interfaces:**
- Consumes: 无。
- Produces: 一个 `git status` 干净的基线；附录 A 的 5 条错误成为后续任务的「恰好等于」参照。

- [ ] **Step 1: 确认当前工作树状态**

Run: `cd console && git status --short`
Expected: 看到 untracked 的 `frontend/src/views/RecordingsView.vue`、`frontend/src/api/voiceSessions.spec.ts`、`frontend/src/features/voice/archive/` 等，以及其它已改文件。记下输出。

- [ ] **Step 2: 复现并留存基线类型错误**

Run: `cd console/frontend && npx vue-tsc --noEmit`
Expected: `EXIT=2`，且错误**恰好**是 spec 附录 A 列出的 5 条（`demo.ts(3,27)` / `voiceSessions.spec.ts(3,38)` / `RecordingsView.vue(13,8)` / `RecordingsView.vue(17,15)` / `RecordingsView.vue(77,55)`）。若条数或位置不符，停下报告——不要继续，门槛定义已变。

- [ ] **Step 3: 暂存全部改动（含 untracked）**

Run: `cd console && git add -A`
Then: `git status --short` 确认无 `??` 残留。

- [ ] **Step 4: 提交基线**

Run: `git commit -m "chore(console): baseline snapshot before S1 shell refactor"`
Expected: 一个 commit 建立。工作树干净。

- [ ] **Step 5: 验证门槛起点**

Run: `cd console/frontend && npx vue-tsc --noEmit`（仍恰好 5 条）；`git status`（clean）。
若 `git status` 不干净或错误数不符，报告后再进入 Task 1。

---

## Task 1: 设计 token 单源 + 运行时注入

**Files:**
- Create: `console/frontend/src/styles/tokens.ts`
- Create: `console/frontend/src/styles/applyTokens.ts`
- Create: `console/frontend/src/styles/tokens.spec.ts`
- Modify: `console/frontend/src/main.ts`

**Interfaces:**
- Consumes: 无。
- Produces:
  - `shellTokens`（`as const` 对象，字段见 Step 2）、`voiceTokens`（`as const` 对象）、`TOKEN_ENFORCED_GLOBS: readonly string[]`。
  - `applyTokens(): void` — 在 `document.documentElement` 上写入每个 `--s2s-*` 与 `--voice-*` CSS 变量。
  - 键名映射规则：`shellTokens` 的 camelCase 字段 → `--s2s-<kebab>`（如 `colorSurface2` → `--s2s-color-surface-2`）；`voiceTokens` 字段 → `--<kebab>`（如 `voiceBg` → `--voice-bg`、`voiceSurface2` → `--voice-surface-2`、`voiceRadius` → `--voice-radius`），沿用现名。

- [ ] **Step 1: 写注入的失败测试**

Create `console/frontend/src/styles/tokens.spec.ts`：

```ts
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
```

- [ ] **Step 2: 运行验证失败**

Run: `cd console/frontend && npx vitest run src/styles/tokens.spec.ts`
Expected: FAIL —找不到 `./applyTokens` / `./tokens`。

- [ ] **Step 3: 写 tokens.ts**

逐字采用 spec §9.1 的两个命名空间与白名单：

```ts
// styles/tokens.ts — 设计 token 唯一事实来源（spec §9）。
// 值允许是 `var(--…)` 字符串，因为 voice 的别名本来就这么写。
export const shellTokens = {
  colorBg: '#0b1020',
  colorSurface: '#141a2e',
  colorSurface2: '#1a2138',
  colorSurface3: '#212a45',
  colorBorder: '#232b45',
  colorBorderStrong: '#2e3856',
  colorText: '#e6e8f0',
  colorMuted: '#8b93a7',
  colorFaint: '#5b6478',
  colorAccent: '#5b8cff',
  colorAccentSoft: 'rgba(91, 140, 255, 0.16)',
  colorSuccess: '#35c48a',
  colorWarning: '#e8b339',
  colorDanger: '#f0655c',
  colorPurple: '#a78bfa',
  colorOrange: '#f0a05c',
  colorCyan: '#22d3ee',
  radiusSm: '6px',
  radiusMd: '10px',
  radiusLg: '14px',
  font: "-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
  fontMono: "'Geist Mono', ui-monospace, Consolas, 'Courier New', monospace"
} as const

export const voiceTokens = {
  voiceBg: '#0a0b10',
  voiceSurface: '#13151c',
  voiceSurface2: '#1b1e29',
  voiceSurfaceMix: '#2a2e3c',
  voiceBorder: 'rgba(255, 255, 255, 0.08)',
  voiceBorderStrong: 'rgba(255, 255, 255, 0.16)',
  voiceText: '#f5f6fa',
  voiceDim: 'rgba(245, 246, 250, 0.65)',
  voiceFaint: 'rgba(245, 246, 250, 0.42)',
  voiceAccent: '#8b7dff',
  voiceListening: '#22d3ee',
  voiceProcessing: '#f59e0b',
  voiceError: '#ff6a75',
  voiceReady: '#34d399',
  voiceQueued: '#94a3b8',
  voiceConnecting: '#facd15',
  voiceUser: 'var(--voice-listening)',
  voiceAssistant: 'var(--voice-accent)',
  voiceTool: 'var(--voice-processing)',
  voiceRadius: '14px'
} as const

/** hex 禁令的作用域。每完成一个子项目就把该页文件加进来，只增不减。 */
export const TOKEN_ENFORCED_GLOBS: readonly string[] = [
  'src/styles/**',
  'src/layouts/ConsoleLayout.vue',
  'src/views/LoginView.vue',
  'src/views/OverviewView.vue',
  'src/views/TrafficView.vue',
  'src/components/NotImplemented.vue'
]
```

- [ ] **Step 4: 写 applyTokens.ts**

```ts
// styles/applyTokens.ts — 把 tokens.ts 注入 :root，让 less / 原生 CSS / ant 三方共源。
import { shellTokens, voiceTokens } from './tokens'

/** shell：camelCase 字段 → --s2s-kebab（加前缀避开 ant 的 --ant-*）。 */
function shellVarName(key: string): string {
  return `--s2s-${key.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`)}`
}

/** voice：沿用现名 --voice-kebab。 */
function voiceVarName(key: string): string {
  return `--${key.replace(/[A-Z]/g, (m) => `-${m.toLowerCase()}`)}`
}

export function applyTokens(): void {
  const root = document.documentElement
  for (const [key, value] of Object.entries(shellTokens)) root.style.setProperty(shellVarName(key), value)
  for (const [key, value] of Object.entries(voiceTokens)) root.style.setProperty(voiceVarName(key), value)
}
```

> 注：`voiceVarName('voiceBg')` → `--voice-bg`；`voiceVarName('voiceSurface2')` → `--voice-surface-2`；`voiceVarName('voiceRadius')` → `--voice-radius`。数字前无需额外分隔，`2` 不是大写字母，天然得到 `-surface-2`（因 `Surface2` 里 `S` 转 `-s`，`2` 保留）。

- [ ] **Step 5: main.ts 在 mount 前同步调用 applyTokens**

Modify `console/frontend/src/main.ts`：在 `import './styles/voice.less'` 之后、`createApp(...)` 之前加 import 与调用。

```ts
import './styles/voice.less'
import { applyTokens } from './styles/applyTokens'

// 首帧即带 CSS 变量，无无样式闪烁（spec §9.2）。
applyTokens()
```

- [ ] **Step 6: 运行注入测试转绿**

Run: `cd console/frontend && npx vitest run src/styles/tokens.spec.ts`
Expected: PASS（2 条）。

- [ ] **Step 7: 四道门槛**

Run: `cd console/frontend && npx vue-tsc --noEmit`（恰好 5 条）→ `npm run lint`（绿）→ `npx vitest run`（绿）。
Expected: 均符合。`tokens.ts`/`applyTokens.ts` 不含裸 hex 之外的违规（tokens.ts 在白名单豁免内，见 Task 2）。

- [ ] **Step 8: 提交**

```bash
cd console
git add frontend/src/styles/tokens.ts frontend/src/styles/applyTokens.ts frontend/src/styles/tokens.spec.ts frontend/src/main.ts
git commit -m "feat(console): single-source design tokens injected at runtime"
```

---

## Task 2: 三方消费改接 token 单源 + hex 禁令

把 `theme.ts`、`variables.less`、`voice.less`、`ConsoleLayout.vue`、`LoginView.vue` 全部改为消费 `tokens.ts`，并落地 hex 禁令测试。S1 实际处理 **5 个文件、60 处**（spec §9.4）。

**Files:**
- Modify: `console/frontend/src/styles/theme.ts:1-28`
- Modify: `console/frontend/src/styles/variables.less:1-7`
- Modify: `console/frontend/src/styles/voice.less:1-24`
- Modify: `console/frontend/src/layouts/ConsoleLayout.vue`（`<style>` 内 19 处 hex；导航派生与 i18n 在 Task 3/4 处理，本任务只动 `<style>`）
- Modify: `console/frontend/src/views/LoginView.vue`（样式面 3 处 hex）
- Create: `console/frontend/src/styles/hex-ban.spec.ts`

**Interfaces:**
- Consumes: Task 1 的 `shellTokens`、`voiceTokens`、`TOKEN_ENFORCED_GLOBS`。
- Produces: `themeConfig`（shape 不变，值改为从 `shellTokens` 取）；CSS 变量成为 less/原生 CSS 的实际来源。

- [ ] **Step 1: 写 hex 禁令失败测试**

Create `console/frontend/src/styles/hex-ban.spec.ts`（作用域严格等于 spec §9.5：样式面，白名单文件，模板内联 SVG 不扫）：

```ts
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
      if (!TOKEN_ENFORCED_GLOBS.some((g) => matches(g, rel))) continue
      if (EXEMPT.has(rel)) continue
      const hits = styleSurface(rel, readFileSync(abs, 'utf8')).match(HEX)
      // 允许 color-mix 端点 #fff/#000
      const bad = (hits ?? []).filter((h) => !/^#(?:fff|000)$/i.test(h))
      if (bad.length) offenders.push(`${rel}: ${bad.join(' ')}`)
    }
    expect(offenders).toEqual([])
  })
})
```

- [ ] **Step 2: 运行验证失败**

Run: `cd console/frontend && npx vitest run src/styles/hex-ban.spec.ts`
Expected: FAIL — 报出 `ConsoleLayout.vue`、`LoginView.vue`、`theme.ts`、`variables.less`、`voice.less` 的裸 hex（此时它们尚未改接）。

- [ ] **Step 3: theme.ts 派生自 shellTokens**

Overwrite `console/frontend/src/styles/theme.ts`（保留既有 `token` 键；值全部从 `shellTokens` 取；注释「唯一主题事实来源」改指 `tokens.ts`）：

```ts
// 主题值来自 styles/tokens.ts（唯一事实来源，spec §9.2）。
import { theme } from 'ant-design-vue'

import { shellTokens } from './tokens'

export const themeConfig = {
  algorithm: theme.darkAlgorithm,
  token: {
    colorPrimary: shellTokens.colorAccent,
    colorBgBase: shellTokens.colorBg,
    colorBgLayout: shellTokens.colorBg,
    colorBgContainer: shellTokens.colorSurface,
    colorBgElevated: shellTokens.colorSurface2,
    colorBorder: shellTokens.colorBorder,
    colorBorderSecondary: shellTokens.colorBorder,
    colorTextBase: shellTokens.colorText,
    colorText: shellTokens.colorText,
    colorTextSecondary: shellTokens.colorMuted,
    colorTextTertiary: shellTokens.colorFaint,
    colorSuccess: shellTokens.colorSuccess,
    colorWarning: shellTokens.colorWarning,
    colorError: shellTokens.colorDanger,
    colorInfo: shellTokens.colorAccent,
    borderRadius: 8,
    fontSize: 13,
    fontFamily: shellTokens.font
  }
}
```

> 说明：`colorBorderSecondary` 原为 `#1e2740`（近似 `colorBorder`），按 spec「S1 不提前裁决近似值、未与 demo 重合部分各自页面重做时归并」就近归到 `colorBorder`；`fontFamily` 用 `shellTokens.font`（含 Segoe UI，值比原 `Inter` 串更完整，符合 spec §9.1）。此两处为 token 收敛预期内的值对齐。

- [ ] **Step 4: variables.less 转发 CSS 变量**

Overwrite `console/frontend/src/styles/variables.less`（less 侧无颜色函数调用，转发安全，spec §3 已核实）：

```less
@color-bg: var(--s2s-color-bg);
@color-surface: var(--s2s-color-surface);
@color-text: var(--s2s-color-text);
@color-muted: var(--s2s-color-muted);
@color-accent: var(--s2s-color-accent);
@radius-md: var(--s2s-radius-md);
```

- [ ] **Step 5: 删除 voice.less 的 :root 块**

Modify `console/frontend/src/styles/voice.less`：删除 `1-24` 行的 `:root { … }`（值已在 `tokens.ts` 的 `voiceTokens`，运行时由 `applyTokens()` 注入）。保留 `25` 行往后的全部 `.v-*` 规则与注释。删除后 `voice.less` 样式面无裸 hex（`color-mix(in srgb, #fff …)` 端点由测试豁免）。

Run（确认 :root 已移除）: `cd console/frontend && npx rg -n ":root" src/styles/voice.less`
Expected: 无输出（或仅剩非 token :root，若存在其它 :root 保留非色内容需人工确认——本仓 voice.less 的 :root 只有 token）。

- [ ] **Step 6: ConsoleLayout.vue 的 <style> 换 token**

Modify `console/frontend/src/layouts/ConsoleLayout.vue` 的 `<style scoped>`：按 spec §9.3 的映射表，把 19 处、8 个不同 hex 全部替换为 `var(--s2s-*)`。逐处：

- `background: #0b1020` → `var(--s2s-color-bg)`
- `color: #e6e8f0`（多处以实际为准）→ `var(--s2s-color-text)`
- 顶栏 `background: #141a2e` → `var(--s2s-color-surface)`
- `color: #8b93a7`（次级）→ `var(--s2s-color-muted)`
- 三处 `border … #1f2740` → `var(--s2s-color-border)`（值变 `#232b45`）
- 分组标题 `color: #6b7285` → `var(--s2s-color-faint)`（值变 `#5b6478`）
- hover `background: #1d2742` → `var(--s2s-color-surface-2)`（值变 `#1a2138`）
- 侧栏 `background: #0f1424` → `var(--s2s-color-surface)`（值变 `#141a2e`）
- 当前项 `background: #1d2a4a` 与 hover `background: #1b2338`（`<style>` 内出现的其它裸 hex）→ 分别 `var(--s2s-color-surface-2)` 与 `var(--s2s-color-surface-2)`（收敛到 surface-2；观感走查在步骤 1/8 以 demo 为准比对）

替换后，`ConsoleLayout.vue` 的 `<style>` 块内**不得再有任何 `#…` 十六进制**。

- [ ] **Step 7: LoginView.vue 样式面 3 处换 token**

Modify `console/frontend/src/views/LoginView.vue`：把 `<style>`（或 `<script>` 内联样式常量，若 3 处在此）中的 3 处裸 hex 替换为对应 `var(--s2s-*)`（按用途取 `colorBg`/`colorSurface`/`colorBorder`/`colorText`/`colorAccent` 中最贴切者）。替换后 LoginView 样式面无裸 hex。

Run: `cd console/frontend && npx rg -n "#[0-9a-fA-F]{3,8}" src/views/LoginView.vue`
Expected: 仅可能命中模板内联 SVG（本任务豁免）；样式面无。

- [ ] **Step 8: hex 禁令测试转绿**

Run: `cd console/frontend && npx vitest run src/styles/hex-ban.spec.ts`
Expected: PASS（offenders 为空）。

- [ ] **Step 9: 四道门槛 + 视觉走查**

Run: `npx vue-tsc --noEmit`（恰好 5）→ `npm run lint`（绿）→ `npx vitest run`（绿）。
Then: `npm run build` 起本地或 `npm run dev`，人工确认 spec §9.3 的 4 处变化（边框/悬停/侧栏底色）符合 demo，不涉布局。

- [ ] **Step 10: 提交**

```bash
cd console
git add frontend/src/styles/theme.ts frontend/src/styles/variables.less frontend/src/styles/voice.less frontend/src/layouts/ConsoleLayout.vue frontend/src/views/LoginView.vue frontend/src/styles/hex-ban.spec.ts
git commit -m "feat(console): route theme, less and shell styles off tokens.ts"
```

---

## Task 3: 路由重命名 + 5 条 redirect + 导航派生

删除手工 `NAV_GROUPS`，导航改从路由表 `meta` 派生；重命名页面并保留旧路径 `redirect`；`ConsoleLayout` 接派生逻辑。i18n 标签在 Task 4 接入，本任务的 `navKey` 先以键名字面量写入 meta，navKey 可解析测试在 Task 4 兜底。

**Files:**
- Modify: `console/frontend/src/router/index.ts:8-50`
- Modify: `console/frontend/src/router/nav.ts`（删 `NAV_GROUPS`/`NavItem`/`NavGroup`/`navGroups()`，保留类型 + `frontOverlays`，改 `NavIcon`）
- Modify: `console/frontend/src/layouts/ConsoleLayout.vue:5,32-37,185-204`（脚本消费派生导航 + 模板渲染；本任务不动 `<style>`）
- Modify: `console/frontend/src/router/router.spec.ts`

**Interfaces:**
- Consumes: `NavIcon` 联合类型（Task 3 内改）。
- Produces:
  - route `meta` 上新增 `NavMeta`：`{ navGroup: 'lb'|'front'|'ops'; navKey: string; navIcon: NavIcon; navOrder: number }`。
  - `frontOverlays: Array<{ overlay: VoiceOverlay; navKey: string; navIcon: NavIcon; navOrder: number }>`（`nav.ts`）。
  - 新 route names：`overview` `traffic` `machines` `deploy` `session-update`（+ 既有 `voices` `release`[原 versions] `audit` `voice` `login` `console`）。`instance-trends` 不再是路由。
  - `deriveNav(router): NavGroup[]`（ConsoleLayout 内局部函数或 `nav.ts` 导出；本计划放 ConsoleLayout 脚本，用 `router.getRoutes()`）。

- [ ] **Step 1: 先更新失败的路由测试**

Modify `console/frontend/src/router/router.spec.ts`，把断言 `/console/params` → `name 'params'` 的用例改为新契约，并新增 redirect / 默认页断言：

```ts
// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'

import { routes } from './index'

function makeRouter() {
  return createRouter({ history: createMemoryHistory(), routes })
}

describe('shell routing', () => {
  it('mounts the voice face at / as a child of ConsoleLayout', () => {
    const matched = makeRouter().resolve('/').matched
    expect(matched).toHaveLength(2)
    expect(matched[1].name).toBe('voice')
    expect(matched[1].meta.face).toBe('voice')
  })

  it('keeps the console namespace record componentless', () => {
    const record = makeRouter().getRoutes().find((r) => r.name === 'console')
    expect(record?.path).toBe('/console')
    expect(record?.components?.default).toBeUndefined()
    expect(record?.meta.requiresAuth).toBe(true)
  })

  it('inherits face and requiresAuth on console children', () => {
    const resolved = makeRouter().resolve('/console/deploy')
    expect(resolved.matched.map((r) => r.name).filter(Boolean)).toEqual(['console', 'deploy'])
    expect(resolved.meta.face).toBe('console')
    expect(resolved.meta.requiresAuth).toBe(true)
  })

  it('gates the voice face behind auth', () => {
    const resolved = makeRouter().resolve('/')
    expect(resolved.meta.face).toBe('voice')
    expect(resolved.meta.requiresAuth).toBe(true)
  })

  it('defaults /console to overview', () => {
    expect(makeRouter().resolve('/console').name).toBe('overview')
  })

  it('redirects every legacy path to its new name', () => {
    const r = makeRouter()
    expect(r.resolve('/console/params').name).toBe('deploy')
    expect(r.resolve('/console/instances').name).toBe('machines')
    expect(r.resolve('/console/instances/trends').name).toBe('traffic')
    expect(r.resolve('/console/versions').name).toBe('release')
    expect(r.resolve('/console/sessions').name).toBe('session-update')
  })
})
```

- [ ] **Step 2: 运行验证失败**

Run: `cd console/frontend && npx vitest run src/router/router.spec.ts`
Expected: FAIL — `deploy`/`overview`/redirect 尚不存在（仍解析到 `params` 等旧名）。

- [ ] **Step 3: 重写 routes 表**

Modify `console/frontend/src/router/index.ts` 的 `routes`（`8-50` 行区间）。给每条参与导航的子路由加 `NavMeta`；`front` 段的 `voice` 也加 meta：

```ts
{
  path: '/',
  component: () => import('@/layouts/ConsoleLayout.vue'),
  children: [
    {
      path: '', name: 'voice', component: () => import('@/views/VoiceView.vue'),
      meta: { face: 'voice', requiresAuth: true, navGroup: 'front', navKey: 'nav.voice', navIcon: 'target', navOrder: 10 }
    },
    {
      path: 'console', name: 'console',
      meta: { face: 'console', requiresAuth: true },
      children: [
        { path: '', redirect: { name: 'overview' } },
        // lb 段
        { path: 'overview', name: 'overview', component: () => import('@/views/OverviewView.vue'),
          meta: { navGroup: 'lb', navKey: 'nav.overview', navIcon: 'layers', navOrder: 10 } },
        { path: 'traffic', name: 'traffic', component: () => import('@/views/TrafficView.vue'),
          meta: { navGroup: 'lb', navKey: 'nav.traffic', navIcon: 'signal', navOrder: 20 } },
        // ops 段（navGroup 一致，navOrder 排在其内）
        { path: 'machines', name: 'machines', component: () => import('@/views/InstancesView.vue'),
          meta: { navGroup: 'ops', navKey: 'nav.machines', navIcon: 'server', navOrder: 10 } },
        { path: 'deploy', name: 'deploy', component: () => import('@/views/ParamsView.vue'),
          meta: { navGroup: 'ops', navKey: 'nav.deploy', navIcon: 'cpu', navOrder: 20 } },
        { path: 'session-update', name: 'session-update', component: () => import('@/views/SessionsView.vue'),
          meta: { navGroup: 'ops', navKey: 'nav.sessionUpdate', navIcon: 'sliders', navOrder: 30 } },
        { path: 'voices', name: 'voices', component: () => import('@/views/VoicesView.vue'),
          meta: { navGroup: 'ops', navKey: 'nav.voices', navIcon: 'wave', navOrder: 40 } },
        { path: 'release', name: 'release', component: () => import('@/views/VersionsView.vue'),
          meta: { navGroup: 'ops', navKey: 'nav.release', navIcon: 'check', navOrder: 50 } },
        { path: 'audit', name: 'audit', component: () => import('@/views/AuditView.vue'),
          meta: { navGroup: 'ops', navKey: 'nav.audit', navIcon: 'history', navOrder: 60 } },
        // 旧路径 redirect（永久保留；name 只有新名）
        { path: 'params', redirect: { name: 'deploy' } },
        { path: 'instances', redirect: { name: 'machines' } },
        { path: 'instances/trends', redirect: { name: 'traffic' } },
        { path: 'versions', redirect: { name: 'release' } },
        { path: 'sessions', redirect: { name: 'session-update' } }
      ]
    }
  ]
}
```

保留 `login` 记录与 `/:pathMatch(.*)*` 通配；保留 `beforeEach` 守卫不动。`OverviewView`/`TrafficView` 此时尚未创建——vue-router 用懒加载 `() => import(...)`，类型检查会因模块缺失报错。**为维持门槛「恰好 5 条」**，本步骤先建占位组件（Step 4）。

- [ ] **Step 4: 建两个占位 view 让 vue-tsc 不新增错误**

Create `console/frontend/src/views/OverviewView.vue` 与 `TrafficView.vue`（最小占位，Task 7/8 会整体替换）：

```vue
<script setup lang="ts"></script>
<template><div /></template>
```

- [ ] **Step 5: 重写 nav.ts**

Overwrite `console/frontend/src/router/nav.ts`（删 `NAV_GROUPS`/`NavItem`/`NavGroup`/`navGroups()`；`NavIcon` 加 `layers|signal|cpu`、去 `chat|trend`；留 `frontOverlays`）：

```ts
export type ShellFace = 'console' | 'voice'

/** 语音对话组里的「打开浮层」项——它们不是路由。 */
export type VoiceOverlay = 'history' | 'tools' | 'settings'

/** 侧栏图标：对应 index.html 里 `<symbol>` 去 `i-` 前缀。 */
export type NavIcon =
  | 'sliders' | 'wave' | 'history' | 'server' | 'check' | 'target' | 'wrench' | 'gear'
  | 'layers' | 'signal' | 'cpu'

export interface NavMeta {
  navGroup: 'lb' | 'front' | 'ops'
  navKey: string
  navIcon: NavIcon
  navOrder: number
}

/** demo 前台三个 overlay 不是路由，无法从路由表派生，单独保留常量表。 */
export const frontOverlays: Array<{ overlay: VoiceOverlay; navKey: string; navIcon: NavIcon; navOrder: number }> = [
  { overlay: 'history', navKey: 'nav.history', navIcon: 'history', navOrder: 20 },
  { overlay: 'tools', navKey: 'nav.tools', navIcon: 'wrench', navOrder: 30 },
  { overlay: 'settings', navKey: 'nav.settings', navIcon: 'gear', navOrder: 40 }
]
```

- [ ] **Step 6: ConsoleLayout 改为派生导航**

Modify `console/frontend/src/layouts/ConsoleLayout.vue`：

1. 脚本：删 `import { navGroups, type NavGroup, type NavItem }`，改为 `import { frontOverlays, type NavIcon, type NavMeta, type VoiceOverlay } from '@/router/nav'`。`groups` computed 改为派生：

```ts
interface Row { key: string; icon: NavIcon; labelKey: string; to?: string; overlay?: VoiceOverlay }
interface Group { key: 'lb' | 'front' | 'ops'; rows: Row[] }

const GROUP_ORDER: Array<Group['key']> = ['lb', 'front', 'ops']

const groups = computed<Group[]>(() => {
  const buckets: Record<Group['key'], Row[]> = { lb: [], front: [], ops: [] }
  for (const rec of router.getRoutes()) {
    const m = rec.meta as NavMeta
    if (!m.navKey || !m.navGroup) continue
    if (rec.name && !router.hasRoute(rec.name)) continue // 既有过滤，未注册可选页不显示
    buckets[m.navGroup].push({ key: String(rec.name), icon: m.navIcon, labelKey: m.navKey, to: String(rec.name) })
  }
  // front 段拼上 overlay（voice 已在路由派生里，navOrder 10）
  for (const ov of frontOverlays) {
    buckets.front.push({ key: `overlay:${ov.overlay}`, icon: ov.navIcon, labelKey: ov.navKey, overlay: ov.overlay })
  }
  const withSort = (rows: Row[], orderOf: (r: Row) => number): Row[] =>
    rows.map((r) => ({ ...r, __o: orderOf(r) } as Row & { __o: number }))
      .sort((a, b) => (a as never as { __o: number }).__o - (b as never as { __o: number }).__o) as Row[]
  const orderMap = new Map<string, number>()
  for (const rec of router.getRoutes()) {
    const m = rec.meta as NavMeta
    if (m.navKey && rec.name) orderMap.set(String(rec.name), m.navOrder)
  }
  const overlayOrder = new Map(frontOverlays.map((o) => [`overlay:${o.overlay}`, o.navOrder]))
  return GROUP_ORDER.map((k) => ({
    key: k,
    rows: withSort(buckets[k], (r) => orderMap.get(r.key) ?? overlayOrder.get(r.key) ?? 999)
  })).filter((g) => g.rows.length > 0)
})
```

> 更简单可靠的等价写法（若上面 `__o` hack 触发 lint 不满，用它）：先各桶收集 `{row, order}` 再排序剥掉 order。实现者二选一，保持 `eslint --max-warnings 0`。

2. `onNavClick`/`isCurrent`/`keyOf` 适配 `Row`：`isCurrent(row) = route.name === row.to`；`onNavClick(row)`：`row.to` 走 `router.push({name: row.to})`，`row.overlay` 走 `shell.openOverlay(row.overlay)` 且非 voice 时 `router.push({name:'voice'})`。
3. 分组标题 `{{ group.label }}` → `{{ t(`nav.group.${group.key}`) }}`（`useI18n`），模板项 `{{ item.label }}` → `{{ t(row.labelKey) }}`，`:title` 同步。脚本首部 `import { useI18n } from 'vue-i18n'` + `const { t } = useI18n()`。

> i18n 键 `nav.group.*`/`nav.*` 在 Task 4 落库；Task 3 结束时若 `t()` 因缺键回落，属预期——本任务门槛只保证 vue-tsc 恰好 5 条、lint 绿、router.spec 绿。

- [ ] **Step 7: 跑测试转绿**

Run: `cd console/frontend && npx vitest run src/router/router.spec.ts`
Expected: PASS（6 条，含默认页与 redirect）。

- [ ] **Step 8: 四道门槛**

Run: `npx vue-tsc --noEmit`（恰好 5）→ `npm run lint`（绿）→ `npx vitest run`（绿）。
Then: `npm run dev`，人工确认 12 个导航项可见可点、分组与顺序对齐 spec §6.1（lb: overview/traffic；front: voice + 3 overlay；ops: machines/deploy/session-update/voices/release/audit）。

- [ ] **Step 9: 提交**

```bash
cd console
git add frontend/src/router/index.ts frontend/src/router/nav.ts frontend/src/router/router.spec.ts frontend/src/layouts/ConsoleLayout.vue frontend/src/views/OverviewView.vue frontend/src/views/TrafficView.vue
git commit -m "feat(console): derive nav from route meta, rename pages, keep legacy redirects"
```

---

## Task 4: i18n 基座（locale store + 目录骨架 + ant locale + 切换器）

建 locale store、i18n 实例、目录骨架（本任务先只放 `nav`/`shell`/`common` 三个域），接 ant `:locale`，顶栏加 en/zh toggle，落地 i18n 对等测试与 navKey 可解析测试。

**Files:**
- Create: `console/frontend/src/i18n/locale.ts`
- Create: `console/frontend/src/i18n/locales/zh-CN/{index,nav,shell,common}.ts`
- Create: `console/frontend/src/i18n/locales/en-US/{index,nav,shell,common}.ts`
- Create: `console/frontend/src/stores/locale.ts`
- Create: `console/frontend/src/stores/locale.spec.ts`
- Create: `console/frontend/src/i18n/i18n.spec.ts`
- Modify: `console/frontend/src/i18n/index.ts`（重写）
- Modify: `console/frontend/src/App.vue:1-9`
- Modify: `console/frontend/src/layouts/ConsoleLayout.vue`（顶栏切换器）
- Modify: `console/frontend/src/utils/storage.ts`（locale 键 + 注释）
- Delete: `console/frontend/src/i18n/zh-CN.ts`

**Interfaces:**
- Consumes: Task 3 的 `frontOverlays`（navKey）与路由 `meta.navKey`。
- Produces:
  - `type Locale = 'zh-CN' | 'en-US'`；`SUPPORTED_LOCALES: readonly Locale[]`；`detectLocale(): Locale`（localStorage → `navigator.language` → `zh-CN`）。
  - `useLocaleStore`：`{ locale: Ref<Locale>; setLocale(next: Locale): void }`，`setLocale` 写 localStorage 并同步 i18n 实例 locale。
  - `antLocale`（computed，`App.vue` 用）：`zh_CN` 或 `en_US`。
  - storage：`readLocale(): Locale | null` / `saveLocale(l: Locale): void`，键 `s2s.console.locale`。

- [ ] **Step 1: 写 locale store 失败测试**

Create `console/frontend/src/stores/locale.spec.ts`：

```ts
// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createLocaleStore } from './locale.test-harness'

// 通过 harness 注入受控 navigator/localStorage，见 Step 5。
describe('locale store', () => {
  beforeEach(() => localStorage.clear())

  it('prefers a stored locale', () => {
    localStorage.setItem('s2s.console.locale', 'en-US')
    expect(createLocaleStore().locale).toBe('en-US')
  })

  it('falls back to navigator.language (zh prefix)', () => {
    vi.stubGlobal('navigator', { language: 'zh-TW' })
    expect(createLocaleStore().locale).toBe('zh-CN')
    vi.unstubAllGlobals()
  })

  it('defaults non-zh navigator to en-US', () => {
    vi.stubGlobal('navigator', { language: 'fr-FR' })
    expect(createLocaleStore().locale).toBe('en-US')
    vi.unstubAllGlobals()
  })

  it('persists on setLocale', () => {
    const store = createLocaleStore()
    store.setLocale('zh-CN')
    expect(localStorage.getItem('s2s.console.locale')).toBe('zh-CN')
  })
})
```

- [ ] **Step 2: 运行验证失败**

Run: `cd console/frontend && npx vitest run src/stores/locale.spec.ts`
Expected: FAIL — 找不到 `./locale.test-harness` / store。

- [ ] **Step 3: 写 locale.ts（检测 + 常量）**

Create `console/frontend/src/i18n/locale.ts`：

```ts
import { readLocale, saveLocale } from '@/utils/storage'

export type Locale = 'zh-CN' | 'en-US'
export const SUPPORTED_LOCALES: readonly Locale[] = ['zh-CN', 'en-US']

export function detectLocale(): Locale {
  const stored = readLocale()
  if (stored) return stored
  const lang = (typeof navigator !== 'undefined' ? navigator.language : 'zh-CN') ?? 'zh-CN'
  return lang.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US'
}

export { saveLocale }
```

- [ ] **Step 4: storage.ts 加 locale 键并改注释**

Modify `console/frontend/src/utils/storage.ts`：加

```ts
import type { Locale } from '@/i18n/locale'
const LOCALE_KEY = 's2s.console.locale'
export function readLocale(): Locale | null {
  const v = localStorage.getItem(LOCALE_KEY)
  return v === 'zh-CN' || v === 'en-US' ? v : null
}
export function saveLocale(locale: Locale): void {
  localStorage.setItem(LOCALE_KEY, locale)
}
```

并把顶部注释 `Nothing else is persisted` 改为：语言是跨会话偏好，存 localStorage（唯一 localStorage 例外）；session/profile 仍留 sessionStorage。

> 循环依赖规避：`locale.ts` import `storage`，`storage` 仅 import `locale` 的**类型**（`import type`，编译期擦除），无运行时环。若 eslint `import/no-cycle` 报警，把 `Locale` 类型定义移入 `locale.ts` 且 storage 用 `import type` 即可。

- [ ] **Step 5: 写 store 与测试 harness**

Create `console/frontend/src/stores/locale.ts`：

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'

import i18n from '@/i18n'
import { detectLocale, saveLocale, type Locale } from '@/i18n/locale'

export const useLocaleStore = defineStore('locale', () => {
  const locale = ref<Locale>(detectLocale())
  i18n.global.locale.value = locale.value

  function setLocale(next: Locale): void {
    locale.value = next
    i18n.global.locale.value = next
    saveLocale(next)
  }

  return { locale, setLocale }
})
```

Create `console/frontend/src/stores/locale.test-harness.ts`（供 Step 1 测试用受控初始化，不依赖真 i18n 实例的全局副作用）：

```ts
import { createPinia, setActivePinia } from 'pinia'

import { detectLocale, type Locale } from '@/i18n/locale'

/** 测试专用：直接跑 detectLocale + 一个把 setLocale 落到 localStorage 的最小实现。 */
export function createLocaleStore(): { locale: Locale; setLocale: (n: Locale) => void } {
  setActivePinia(createPinia())
  const state: { locale: Locale } = { locale: detectLocale() }
  return {
    get locale() {
      return state.locale
    },
    setLocale(n: Locale) {
      state.locale = n
      localStorage.setItem('s2s.console.locale', n)
    }
  }
}
```

> 说明：harness 测的是 `detectLocale()` 的三条分支 + 持久化写入，这正是 locale store 的初始化/`setLocale` 逻辑的纯函数核心。真 store 在 Step 6 的 i18n 实例就绪后由 `App.vue`/`ConsoleLayout` 使用。

- [ ] **Step 6: 重写 i18n/index.ts + 建三个骨架域**

Create `console/frontend/src/i18n/locales/zh-CN/nav.ts`（示例值，Task 5 补全；键必须与 en-US 对等）：

```ts
export default {
  overview: '集群总览',
  traffic: '流量与路由',
  voice: '对话演示',
  history: '会话历史',
  tools: '工具',
  settings: '设置',
  machines: '机器管理',
  deploy: '机器实际部署与参数',
  sessionUpdate: '会话热更新',
  voices: '音色库',
  release: '发布与版本管理',
  audit: '操作审计日志',
  group: { lb: '负载均衡管理 · 总架构', front: '语音对话前台', ops: '运维台 · 集群维度' }
}
```

Create `en-US/nav.ts`（同键、英文值）：

```ts
export default {
  overview: 'Cluster Overview',
  traffic: 'Traffic & Routing',
  voice: 'Conversation Demo',
  history: 'Conversation History',
  tools: 'Tools',
  settings: 'Settings',
  machines: 'Machines',
  deploy: 'Deployments & Params',
  sessionUpdate: 'Session Hot Update',
  voices: 'Voice Library',
  release: 'Releases & Versions',
  audit: 'Audit Log',
  group: { lb: 'Load Balancing · Topology', front: 'Voice Frontend', ops: 'Ops · Cluster' }
}
```

Create `zh-CN/shell.ts` 与 `en-US/shell.ts`（外壳文案：`brand`、`signIn`、`signOut`、`language`、`toggleSider`、`pipelineOk`、`pipelineUnreachable`、`notConnected`、`selectMenuPrompt` 等）。Create `zh-CN/common.ts` 与 `en-US/common.ts`（至少含状态展示词 `statusOnline/degraded/offline/draining/idle/active/stuck`，供展示译）。Create 每语言 `index.ts` 聚合：

```ts
// locales/zh-CN/index.ts
import common from './common'
import nav from './nav'
import shell from './shell'

export default { nav, shell, common }
```

（`en-US/index.ts` 同构。）

Rewrite `console/frontend/src/i18n/index.ts`：

```ts
import { createI18n } from 'vue-i18n'

import enUS from './locales/en-US'
import zhCN from './locales/zh-CN'

const missingSeen = new Set<string>()

export default createI18n({
  legacy: false,
  locale: 'zh-CN',
  fallbackLocale: 'en-US',
  missingWarn: false,
  fallbackWarn: false,
  messages: { 'zh-CN': zhCN, 'en-US': enUS },
  missing: (locale, key) => {
    if (import.meta.env.DEV) {
      const id = `${locale}:${key}`
      if (!missingSeen.has(id)) {
        missingSeen.add(id)
        console.warn(`[i18n] missing key "${key}" for locale "${locale}"`)
      }
    }
  }
})
```

Delete `console/frontend/src/i18n/zh-CN.ts`。

- [ ] **Step 7: App.vue 接 ant locale**

Overwrite `console/frontend/src/App.vue`：

```vue
<script setup lang="ts">
import zhCN from 'ant-design-vue/es/locale/zh_CN'
import enUS from 'ant-design-vue/es/locale/en_US'
import { computed } from 'vue'

import { themeConfig } from './styles/theme'
import { useLocaleStore } from './stores/locale'

const localeStore = useLocaleStore()
const antLocale = computed(() => (localeStore.locale === 'zh-CN' ? zhCN : enUS))
</script>

<template>
  <a-config-provider :theme="themeConfig" :locale="antLocale">
    <router-view />
  </a-config-provider>
</template>
```

> `useLocaleStore()` 需在 pinia 安装后调用；`main.ts` 已 `.use(pinia)` 先于挂载，`App.vue` 的 `<script setup>` 在挂载期运行，store 可用。

- [ ] **Step 8: ConsoleLayout 顶栏加语言 toggle**

Modify `console/frontend/src/layouts/ConsoleLayout.vue`：脚本加 `import { useLocaleStore } from '@/stores/locale'` + `const localeStore = useLocaleStore()`，加

```ts
function toggleLocale(): void {
  localeStore.setLocale(localeStore.locale === 'zh-CN' ? 'en-US' : 'zh-CN')
}
```

模板在 `shell__user` 之前插入一枚两态按钮（对齐 demo `#lang-btn`，非下拉）：

```html
<button class="shell__lang" type="button" :aria-label="t('shell.language')" @click="toggleLocale">
  {{ localeStore.locale === 'zh-CN' ? '中 / EN' : 'EN / 中' }}
</button>
```

（`.shell__lang` 样式用 token 变量，勿写裸 hex。）

- [ ] **Step 9: 写 i18n 对等 + navKey 可解析测试**

Create `console/frontend/src/i18n/i18n.spec.ts`：

```ts
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'

import { routes } from '@/router/index'
import { frontOverlays } from '@/router/nav'
import en from './locales/en-US'
import zh from './locales/zh-CN'

function flatten(obj: Record<string, unknown>, prefix = ''): string[] {
  return Object.entries(obj).flatMap(([k, v]) =>
    v && typeof v === 'object' ? flatten(v as Record<string, unknown>, `${prefix}${k}.`) : [`${prefix}${k}`]
  )
}

function resolveKey(tree: Record<string, unknown>, dotted: string): unknown {
  return dotted.split('.').reduce<unknown>((acc, seg) => (acc && typeof acc === 'object' ? (acc as Record<string, unknown>)[seg] : undefined), tree)
}

describe('i18n parity', () => {
  it('zh and en flatten to identical key sets, all non-empty strings', () => {
    const zk = flatten(zh as never).sort()
    const ek = flatten(en as never).sort()
    expect(zk).toEqual(ek)
    for (const k of zk) {
      expect(typeof resolveKey(zh as never, k)).toBe('string')
      expect((resolveKey(zh as never, k) as string).length).toBeGreaterThan(0)
    }
  })

  it('every navKey from routes and frontOverlays resolves in both locales', () => {
    const router = createRouter({ history: createMemoryHistory(), routes })
    const keys = [
      ...router.getRoutes().map((r) => (r.meta as { navKey?: string }).navKey),
      ...frontOverlays.map((o) => o.navKey)
    ].filter((k): k is string => Boolean(k))
    expect(keys.length).toBeGreaterThanOrEqual(12)
    for (const key of keys) {
      expect(typeof resolveKey(zh as never, key), `zh missing ${key}`).toBe('string')
      expect(typeof resolveKey(en as never, key), `en missing ${key}`).toBe('string')
    }
  })
})
```

- [ ] **Step 10: 跑测试转绿**

Run: `cd console/frontend && npx vitest run src/i18n/i18n.spec.ts src/stores/locale.spec.ts`
Expected: PASS（对等 + navKey + locale 四分支）。

- [ ] **Step 11: 四道门槛 + 切换走查**

Run: `npx vue-tsc --noEmit`（恰好 5）→ `npm run lint`（绿）→ `npx vitest run`（绿）→ 后端 `pytest`（本任务未动后端，应仍绿）。
Then: `npm run dev`，切 en/zh，reload 后保持；确认 ant 空态/`a-popconfirm` 文案随语言变化。

- [ ] **Step 12: 提交**

```bash
cd console
git add frontend/src/i18n frontend/src/stores/locale.ts frontend/src/stores/locale.spec.ts frontend/src/stores/locale.test-harness.ts frontend/src/App.vue frontend/src/layouts/ConsoleLayout.vue frontend/src/utils/storage.ts
git add -u frontend/src/i18n/zh-CN.ts
rm -f frontend/src/i18n/zh-CN.ts
git commit -m "feat(console): i18n base with locale store, ant locale and toggle"
```

---

## Task 5: 按域键化既有中文字符串（分 6–8 个提交）

把约 539 处用户可见中文（views 161 / components 174 / utils 140 / features 31 / router 14 / stores 11 / layouts 8）按域键化。**域 = 文件所属的 route name / 功能域**（spec §8.1）。这一步不新增行为，只做“硬编码中文 → `t(key)` + 成对文案”的机械迁移，每个提交保持四道门槛绿。本任务给出统一规则、域→文件映射、首批（errors）的完整工样板，余批次按同一 grammar 逐域执行。

**Files（按域，每域 zh + en 两文件）:**
- Modify: `console/frontend/src/i18n/locales/{zh-CN,en-US}/errors.ts`（新建）
- Modify: `console/frontend/src/i18n/locales/{zh-CN,en-US}/auth.ts`（新建）
- Modify: `console/frontend/src/i18n/locales/{zh-CN,en-US}/{shell,common}.ts`（补全）
- Modify: `console/frontend/src/i18n/locales/{zh-CN,en-US}/{machines,deploy,sessionUpdate,voices,release,audit,voice,logs,latency}.ts`（新建）
- Modify: 上述各域对应的 views/components/utils/stores/features 文件（把字面量换为 `t(...)`）
- Modify: `console/frontend/src/utils/error.ts`（`translate()` 改走 i18n）
- 各域 `locales/<locale>/index.ts` 需 import 新域并汇进默认导出。

**Interfaces:**
- Consumes: Task 4 的 `useI18n` 基座与对等测试。
- Produces: 每个域一个命名空间（`errors.*` `auth.*` `machines.*` …）；`utils/error.ts` 的 `translate(code)` 返回 `t(`errors.${code}`)`（错误码原文仍另处保留，见 Global Constraints）。

**迁移规则（逐字适用每一批）:**
1. 只键化用户可见串；Global Constraints 的代码态清单一律不动。
2. 状态枚举按 §8.4：显示处用 `common.statusXxx`，`data-testid`/排序/比较用原值。
3. 插值用命名式 `{count}`；仅英文单复数不同才 `one|other`。
4. 每键必须同时写进 zh 与 en（对等测试是硬门）。
5. `<script setup>` 组件首部加 `import { useI18n } from 'vue-i18n'` + `const { t } = useI18n()`；模板里用 `{{ t('domain.key')) }}`，属性用 `:label="t(...)"`，`a-modal` 的 `title`、`placeholder` 等同理。
6. 非组件模块（utils/stores）无法用 `useI18n`，改用 `i18n.global.t(...)`（import 默认实例）。

- [ ] **Step 1（批次 A：errors）: 建两语言 errors.ts 并接 translate()**

Create `locales/zh-CN/errors.ts`（错误码旁的人读描述，码名保留原样）：

```ts
export default {
  atCapacity: '实例已达容量上限，请稍后再试。',
  recordingDisabled: '录音归档未启用。',
  notFound: '资源不存在。',
  invalidRequest: '请求参数无效。',
  sessionLimitReached: '已达会话上限。',
  unknownProfile: '未知 profile。',
  network: '网络错误，请检查连接。',
  timeout: '请求超时。',
  serverError: '服务端错误。',
  unauthorized: '登录已失效，请重新登录。'
}
```

Create `locales/en-US/errors.ts`（同键、英文值）。

Modify `console/frontend/src/utils/error.ts`：`translate(code)` 改为 `i18n.global.t(`errors.${camel(code)}`)`（`code` 如 `at_capacity`→`atCapacity`），回退键与现有行为保持。`fallbackCode` 不动。

- [ ] **Step 2: 跑对等测试（批次 A）**

Run: `cd console/frontend && npx vitest run src/i18n/i18n.spec.ts`
Expected: PASS（errors 两语对等）。若失败，补键直到绿。

- [ ] **Step 3: 四道门槛后提交批次 A**

Run: `npx vue-tsc --noEmit`（恰好 5）→ `npm run lint`（绿）→ `npx vitest run`（绿）。

```bash
cd console
git add frontend/src/i18n/locales frontend/src/utils/error.ts
git commit -m "feat(console): i18n errors domain"
```

- [ ] **Step 4（批次 B：auth + shell 补全）:** 按同一 grammar 键化 `LoginView.vue` 与 `ConsoleLayout.vue` 模板/脚本内残余硬编码中文（登录表单、`退出`、`未连接`、`选择左侧菜单开始`、pipeline 文案、折叠按钮 title 等），写进 `auth.ts`/`shell.ts`。每完成一文件即时跑对等测试。

- [ ] **Step 5（批次 C：machines + deploy）:** 键化 `InstancesView.vue`/`InstanceCard.vue` 入 `machines.ts`；`ParamsView.vue`/`ParamTree.vue`/`ParamField.vue`/`FixedField.vue`/`EffectBadge.vue`/`RuntimeGrid.vue`/`ModelRuntimeCard.vue` 入 `deploy.ts`。状态枚举走 §8.4。

- [ ] **Step 6（批次 D：voices/release/audit/sessionUpdate）:** 对应 `VoicesView` 组、`VersionsView`/`PublishDialog`、`AuditView`/`AuditTable`、`SessionsView` 分别入四个域文件。

- [ ] **Step 7（批次 E：voice/logs/latency）:** `features/voice/**` 的用户可见串入 `voice.ts`；`LogPanel.vue`/`LogAnalysisCard.vue` 入 `logs.ts`；`TurnLatencyPanel.vue` 入 `latency.ts`。**不碰 `RecordingsView.vue` 与 `api/voiceSessions.spec.ts` 等待清线（S8），以免改变 `vue-tsc` 基线。**

- [ ] **Step 8: 每批后回归**

每个 Step 4–7 内部，每改完一个域文件都跑：`npx vitest run src/i18n/i18n.spec.ts`（对等）+ `npx vue-tsc --noEmit`（恰好 5）+ `npm run lint`。各域可并行，但提交粒度按域分开（保证单提交可回滚）。

- [ ] **Step 9: 批次收尾扫描**

Run: `cd console/frontend && npx rg -n "[\u4e00-\u9fa5]" src --glob '!*.spec.ts' -g '!src/features/voice/archive/**' -g '!src/views/RecordingsView.vue' -g '!src/i18n/**'`
Expected: 仅剩注释与代码态保留清单（日志/错误上下文里有意保留的中文注释）。用户可见模板/标签串应已空。若有残留，归入对应域补键。**注释不算，不键化。**

---

## Task 6: 后端只读端点 GET /api/v1/traffic/settings

S1 唯一后端改动，additive。只读 `AllocatorSettings`，无写路径、不写 DB、不记审计。

**Files:**
- Create: `console/backend/app/routers/traffic.py`
- Modify: `console/backend/app/core/router_registry.py:12-25`（import `traffic`）与 `:43-46`（`include_router`）
- Create: `console/backend/tests/integration/test_traffic_api.py`

**Interfaces:**
- Consumes: `app.config.allocator`（`AllocatorSettings` 单例）、`app.core.security.require_user`、`app.schemas.common.ok`。
- Produces: `GET /api/v1/traffic/settings` 返回 `ok({...})`，data 字段（camelCase）：`allocatorMode consoleId seedConfigured probeIntervalS probeTimeoutS failThreshold recoverThreshold grantTtlS usageIntervalS metricRetentionDays queueEnabled webrtcHangupEnabled` + `scheduling:{policy:'least-in-use', configurable:false, tieBreaker:'weight-random'}` + `unimplemented:['session-stickiness','canary-ratio','routing-rules']`。

- [ ] **Step 1: 写失败测试**

Create `console/backend/tests/integration/test_traffic_api.py`（沿用既有 `client`/`_auth` 模式）：

```python
"""S1 spec §10.2: read-only traffic settings snapshot; no writes, no audit."""
from __future__ import annotations

from app.config import allocator


def _auth(client):
    tokens = client.post(
        "/api/v1/auth/login", json={"username": "alice", "password": "correct-horse"}
    ).json()["data"]
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


def test_requires_auth(client):
    assert client.get("/api/v1/traffic/settings").status_code == 401


def test_envelope_and_fields(client):
    body = client.get("/api/v1/traffic/settings", headers=_auth(client)).json()
    assert set(body) == {"code", "message", "data"}
    data = body["data"]
    assert data["allocatorMode"] == allocator.mode
    assert data["consoleId"] == allocator.resolved_console_id
    assert data["seedConfigured"] == bool(allocator.seed_path.strip())
    assert data["probeIntervalS"] == allocator.probe_interval_s
    assert data["scheduling"] == {
        "policy": "least-in-use",
        "configurable": False,
        "tieBreaker": "weight-random",
    }
    assert "session-stickiness" in data["unimplemented"]


def test_off_mode_still_200(client, monkeypatch):
    monkeypatch.setattr(allocator, "mode", "off")
    assert client.get("/api/v1/traffic/settings", headers=_auth(client)).status_code == 200


def test_write_methods_not_registered(client):
    headers = _auth(client)
    assert client.post("/api/v1/traffic/settings", headers=headers).status_code == 405


def test_no_audit_row_written(client):
    headers = _auth(client)
    client.get("/api/v1/traffic/settings", headers=headers)
    # No side effects: re-read yields identical payload and DB/audit untouched.
    assert client.get("/api/v1/traffic/settings", headers=headers).json()["data"]["allocatorMode"] == allocator.mode
```

- [ ] **Step 2: 运行验证失败**

Run: `cd console/backend && python -m pytest tests/integration/test_traffic_api.py -q`
Expected: FAIL —404（路由未注册）。

- [ ] **Step 3: 写 router**

Create `console/backend/app/routers/traffic.py`：

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import allocator
from app.core.security import CurrentUser, require_user
from app.schemas.common import ok

router = APIRouter(prefix="/api/v1", tags=["traffic"])


@router.get("/traffic/settings")
def get_traffic_settings(user: CurrentUser = Depends(require_user)):
    """Read-only allocator snapshot (spec §10.2). No write path, no DB, no audit.

    ``scheduling.configurable`` is False because the policy is hard-coded in
    ``allocator._candidates``; S3 flips it to a real enum without touching
    the frontend structure. ``unimplemented`` is declared here, not guessed
    client-side.
    """
    return ok(
        {
            "allocatorMode": allocator.mode,
            "consoleId": allocator.resolved_console_id,
            "seedConfigured": bool(allocator.seed_path.strip()),
            "probeIntervalS": allocator.probe_interval_s,
            "probeTimeoutS": allocator.probe_timeout_s,
            "failThreshold": allocator.fail_threshold,
            "recoverThreshold": allocator.recover_threshold,
            "grantTtlS": allocator.grant_ttl_s,
            "usageIntervalS": allocator.usage_interval_s,
            "metricRetentionDays": allocator.metric_retention_days,
            "queueEnabled": allocator.queue_enabled,
            "webrtcHangupEnabled": allocator.webrtc_hangup_enabled,
            "scheduling": {
                "policy": "least-in-use",
                "configurable": False,
                "tieBreaker": "weight-random",
            },
            "unimplemented": ["session-stickiness", "canary-ratio", "routing-rules"],
        }
    )
```

- [ ] **Step 4: 注册路由（只 GET）**

Modify `console/backend/app/core/router_registry.py`：`from app.routers import (... status, traffic, ...)` 列表按字母序加入 `traffic`；在 `app.include_router(status.router)` 之后加 `app.include_router(traffic.router)`。

- [ ] **Step 5: 跑测试转绿**

Run: `cd console/backend && python -m pytest tests/integration/test_traffic_api.py -q`
Expected: PASS（5 条）。

- [ ] **Step 6: 后端全量回归 + 提交**

Run: `cd console/backend && python -m pytest -q`（全绿）。

```bash
cd console
git add backend/app/routers/traffic.py backend/app/core/router_registry.py backend/tests/integration/test_traffic_api.py
git commit -m "feat(console): read-only GET /api/v1/traffic/settings"
```

---

## Task 7: OverviewView（集群总览，只读）+ overview 域

真实只读页，数据源为既有 `GET /api/v1/status` + `GET /api/v1/instances`。拿不到的 demo 指标渲染带子项目标记的空态，不伪造。

**Files:**
- Modify(替换占位): `console/frontend/src/views/OverviewView.vue`
- Create: `console/frontend/src/views/overviewMetrics.ts`（纯映射函数，无 DOM 依赖，供 spec 单测）
- Create: `console/frontend/src/i18n/locales/{zh-CN,en-US}/overview.ts`（并在两 `index.ts` 里 import）
- Create: `console/frontend/src/components/NotImplemented.vue`
- Create: `console/frontend/src/views/overviewMetrics.spec.ts`
- Modify: `console/frontend/src/types/api.d.ts:42-51`（`StatusSnapshot` 补 `allocatorMode/instancesRegistered/seedConfigured/consoleId/secretsConsistent` 可选字段，与后端 `status_service.snapshot` 实际返回对齐）

**Interfaces:**
- Consumes: `api.get<StatusSnapshot>('/status')`、`api.get<InstanceSnapshot>('/instances')`（均有）；`NotImplemented.vue`。
- Produces: `NotImplemented` props `{ targetSubproject: string; reasonKey: string }`（`reasonKey` 走 `t()`）；`overviewMetrics(status: StatusSnapshot, snapshot: InstanceSnapshot): { value: string | null; key: string; unimpl?: 'S2' | 'S3' | 'none' }[]`（`OverviewView.vue` 消费）；`OverviewView` 默认导出。

> **测试方式（已核实）**：仓内未装 `@vue/test-utils`，且全局约束禁止引入新依赖。本段沿用仓库既有惯例（`src` 下 24 个 spec 全是纯函数单测）：把页面的数据映射抽为 `.ts` 纯函数单测，**不挂载组件**。视觉/交互正确性由 Task 9 的人工走查承担。

- [ ] **Step 1: 写 NotImplemented**

Create `console/frontend/src/components/NotImplemented.vue`：

```vue
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
defineProps<{ targetSubproject: string; reasonKey: string }>()
const { t } = useI18n()
</script>

<template>
  <div class="ni">
    <a-tag color="default">{{ targetSubproject }}</a-tag>
    <span class="ni__reason">{{ t(reasonKey) }}</span>
  </div>
</template>

<style scoped>
.ni {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--s2s-color-muted);
}
.ni__reason {
  font-size: 12px;
}
</style>
```

- [ ] **Step 2: 写纯函数映射的失败测试**

Create `console/frontend/src/views/overviewMetrics.ts`（空实现先占位，令测试先红）：

```ts
import type { InstanceSnapshot, StatusSnapshot } from '@/types/api'

export interface OverviewMetric {
  key: string
  value: string | null
  unimpl?: 'S2' | 'S3' | 'none'
}

export function overviewMetrics(_status: StatusSnapshot, _snapshot: InstanceSnapshot): OverviewMetric[] {
  return []
}
```

Create `console/frontend/src/views/overviewMetrics.spec.ts`：

```ts
import { describe, expect, it } from 'vitest'

import type { InstanceSnapshot, StatusSnapshot } from '@/types/api'
import { overviewMetrics } from './overviewMetrics'

const status = {
  profile: 'prod', version: 3, status: 'live', catalogCommit: 'abc123',
  validatorMode: 'runtime', db: 'ok', pipeline: 'ok', internalTokenConfigured: true
} as unknown as StatusSnapshot
const snapshot = {
  profile: 'prod', version: 3, container: { name: '', status: '', startedAt: null, image: '', pid: null, detail: '' },
  pool: null, usage: null, alerts: ['pool_stuck:x'],
  summary: { instances_total: 2, online: 1, offline: 0, degraded: 1, draining: 0, slots_total: 8, slots_in_use: 3, slots_free: 5, pending_grants: 0 },
  instances: []
} as unknown as InstanceSnapshot

describe('overviewMetrics', () => {
  it('maps real KPIs from status + summary', () => {
    const byKey = Object.fromEntries(overviewMetrics(status, snapshot).map((m) => [m.key, m]))
    expect(byKey['overview.kpi.catalogCommit'].value).toBe('abc123')
    expect(byKey['overview.kpi.pipelineInstances'].value).toBe('2')
    expect(byKey['overview.kpi.online'].value).toBe('1')
    expect(byKey['overview.kpi.activeSessions'].value).toBe('3')
  })

  it('marks demo-only metrics as unimplemented, never mocks them', () => {
    const list = overviewMetrics(status, snapshot)
    expect(list.find((m) => m.key === 'overview.unimpl.machines')?.unimpl).toBe('S2')
    expect(list.find((m) => m.key === 'overview.unimpl.errorRate')?.unimpl).toBe('S3')
  })
})
```

Run: `cd console/frontend && npx vitest run src/views/overviewMetrics.spec.ts`
Expected: FAIL（空实现，断言取不到值）。

- [ ] **Step 3: 建 overview 域文案**

Create `locales/zh-CN/overview.ts`：`kpi.{machines,pipelineInstances,online,degraded,offline,draining,activeSessions,freeSlots,totalSlots,pendingGrants,clusterAlerts,catalogCommit,version,status,allocatorMode,consoleId,dbHealth,pipelineHealth,seedConfigured}`、`topology.{lbLayer,pipelineLayer,machineLayer}`、`unimpl.{machines,errorRate,stickiness,p95ttft,training}`（后五个供 `NotImplemented` 的 `reasonKey`）。
Create `en-US/overview.ts`（同键、英文值）。
两 `index.ts` 各 `import overview from './overview'` 并汇进默认导出。

- [ ] **Step 4: 实现纯函数 + 写 OverviewView**

Modify `console/frontend/src/views/overviewMetrics.ts`：实现 `overviewMetrics`，逐个映射 spec §10.1 的真实字段（集群名=`status.profile`、版本/状态、catalog commit、DB/Pipeline 健康、`allocatorMode/consoleId/seedConfigured`、`instancesRegistered`、`summary.*`、`declared_mismatch`）；`null` 字段 `value` 置 `null`（视图层渲染 `DASH`）。机器数=`unimpl:'S2'`，错误率/粘滞命中率/P95 TTFT=`'S3'`，训练任务=`'none'` 且 `value:null`（不伪造）。

Modify(替换占位) `console/frontend/src/views/OverviewView.vue`：
- `onMounted` 并发 `api.get('/status',{params:{profile}})` + `api.get('/instances',{params:{profile}})`（profile 取 `useConsoleStore().profile`），存进两个 `ref`。
- KPI 卡区：`overviewMetrics(status, snapshot)` 逐项渲染；`value==null` 走 `DASH`；带 `unimpl` 的项渲染 `<NotImplemented :target-subproject="m.unimpl ?? 'none'" :reason-key="m.key" :data-unimplemented="m.unimpl" />`。
- `alerts[]` 逐条 `<a-alert>` banner；`declared_mismatch` 实例列一条提醒。
- 拓扑两层（LB → pipeline instances），机器层留带 S2 标记空层。
- **严禁 mock 数据填充任何区块**；降级读（`/instances` 200 但字段缺）必须部分渲染，不得因单条告警整页失败。

- [ ] **Step 5: 补 StatusSnapshot 类型**

Modify `console/frontend/src/types/api.d.ts:42-51`：`StatusSnapshot` 加可选 `allocatorMode?: string; instancesRegistered?: number; seedConfigured?: boolean; consoleId?: string; secretsConsistent?: boolean`（与 `status_service.snapshot` 实际返回一致）。

- [ ] **Step 6: 测试转绿 + 四道门槛**

Run: `npx vitest run src/views/overviewMetrics.spec.ts src/i18n/i18n.spec.ts`（绿）→ `npx vue-tsc --noEmit`（恰好 5）→ `npm run lint`（绿）→ `npx vitest run`（全绿）。

- [ ] **Step 7: 提交**

```bash
cd console
git add frontend/src/views/OverviewView.vue frontend/src/views/overviewMetrics.ts frontend/src/views/overviewMetrics.spec.ts frontend/src/components/NotImplemented.vue frontend/src/i18n/locales frontend/src/types/api.d.ts
git commit -m "feat(console): read-only cluster overview page"
```

---

## Task 8: TrafficView（流量与路由，只读）+ traffic 域

数据源：新端点 + `GET /api/v1/instances` + 内嵌 `InstanceTrendsView`（走既有 metrics）。全程只读，`allocatorMode='off'` 时有醒目状态条。

**Files:**
- Modify(替换占位): `console/frontend/src/views/TrafficView.vue`
- Create: `console/frontend/src/views/trafficViewModel.ts`（纯函数，无 DOM 依赖，供 spec 单测）
- Create: `console/frontend/src/api/traffic.ts`
- Create: `console/frontend/src/types/traffic.ts`
- Create: `console/frontend/src/i18n/locales/{zh-CN,en-US}/traffic.ts`（并在两 `index.ts` import）
- Create: `console/frontend/src/views/trafficViewModel.spec.ts`

**Interfaces:**
- Consumes: Task 6 的 `GET /api/v1/traffic/settings`；`NotImplemented.vue`；`InstanceTrendsView.vue`（降级为内嵌区块，复用其现有实现）。
- Produces: `getTrafficSettings(): Promise<TrafficSettings>`（`api/traffic.ts`）。

- [ ] **Step 1: 写类型 + api**

Create `console/frontend/src/types/traffic.ts`：

```ts
export interface TrafficSettings {
  allocatorMode: 'off' | 'local'
  consoleId: string
  seedConfigured: boolean
  probeIntervalS: number
  probeTimeoutS: number
  failThreshold: number
  recoverThreshold: number
  grantTtlS: number
  usageIntervalS: number
  metricRetentionDays: number
  queueEnabled: boolean
  webrtcHangupEnabled: boolean
  scheduling: { policy: string; configurable: boolean; tieBreaker: string }
  unimplemented: string[]
}
```

Create `console/frontend/src/api/traffic.ts`：

```ts
import { api } from './client'
import type { TrafficSettings } from '@/types/traffic'

export const getTrafficSettings = (): Promise<TrafficSettings> =>
  api.get<TrafficSettings>('/traffic/settings')
```

- [ ] **Step 2: 写纯函数失败测试**

Create `console/frontend/src/views/trafficViewModel.ts`（空实现先占位）：

```ts
import type { TrafficSettings } from '@/types/traffic'

export interface TrafficFeature {
  feature: string
  reasonKey: string
}

export function trafficViewModel(_settings: TrafficSettings): {
  showOffBanner: boolean
  policyReadOnly: boolean
  features: TrafficFeature[]
} {
  return { showOffBanner: false, policyReadOnly: false, features: [] }
}
```

Create `console/frontend/src/views/trafficViewModel.spec.ts`（直接测纯函数，**不挂载组件**，与 Task 7 同一理由）：

```ts
import { describe, expect, it } from 'vitest'

import type { TrafficSettings } from '@/types/traffic'
import { trafficViewModel } from './trafficViewModel'

const off: TrafficSettings = {
  allocatorMode: 'off', consoleId: 'c1', seedConfigured: false, probeIntervalS: 5,
  probeTimeoutS: 2, failThreshold: 3, recoverThreshold: 2, grantTtlS: 60, usageIntervalS: 30,
  metricRetentionDays: 7, queueEnabled: false, webrtcHangupEnabled: false,
  scheduling: { policy: 'least-in-use', configurable: false, tieBreaker: 'weight-random' },
  unimplemented: ['session-stickiness', 'canary-ratio', 'routing-rules']
}

describe('trafficViewModel', () => {
  it('flags off-mode and read-only policy', () => {
    const vm = trafficViewModel(off)
    expect(vm.showOffBanner).toBe(true)
    expect(vm.policyReadOnly).toBe(true)
  })

  it('maps each unimplemented feature to a traffic.unimpl key', () => {
    const keys = trafficViewModel(off).features.map((f) => f.reasonKey)
    expect(keys).toContain('traffic.unimpl.stickiness')
    expect(trafficViewModel(off).features.every((f) => f.feature)).toBe(true)
  })
})
```

Run: `cd console/frontend && npx vitest run src/views/trafficViewModel.spec.ts`
Expected: FAIL（空实现）。

- [ ] **Step 3: 建 traffic 域文案**

Create `locales/{zh-CN,en-US}/traffic.ts`：`banner.off`（LB 未启用说明）、`title.{settings,policy,routing,trends}`、`field.{probeIntervalS,probeTimeoutS,failThreshold,recoverThreshold,grantTtlS,usageIntervalS,metricRetentionDays,queueEnabled,webrtcHangupEnabled,consoleId,seedConfigured,allocatorMode}`、`policy.{readOnlyNote,policy,tieBreaker}`、`unimpl.{stickiness,canary,routing}`。
两 `index.ts` 各 import 并汇入。

- [ ] **Step 4: 实现纯函数 + 写 TrafficView**

Modify `console/frontend/src/views/trafficViewModel.ts`：`showOffBanner = settings.allocatorMode === 'off'`；`policyReadOnly = settings.scheduling.configurable === false`；`features = settings.unimplemented.map(f => ({ feature: f, reasonKey: 'traffic.unimpl.' + mapFeature(f) }))`（`mapFeature`：`session-stickiness`→`stickiness`、`canary-ratio`→`canary`、`routing-rules`→`routing`）。

Modify(替换占位) `console/frontend/src/views/TrafficView.vue`：
- `onMounted` 跑 `getTrafficSettings()`，存 `ref`，模板用 `trafficViewModel(settings)` 驱动。
- 顶部：`vm.showOffBanner` 时渲染 `<a-alert data-testid="lb-off-banner" type="info">`（spec §11：常态非异常，不用 error 级），说明 LB 未启用、下方是配置值而非生效行为。
- 配置读数表：逐字段只读展示（camelCase 值），`vm.policyReadOnly` → 只读说明卡（policy `least-in-use`、tieBreaker `weight-random`）；true 时（S3）预留可编辑插槽，本段结构不动。
- `vm.features` 每项 → `<NotImplemented target-subproject="S3" :reason-key="f.reasonKey" data-unimplemented="S3" />`。
- 内嵌趋势：`import InstanceTrends from '@/views/InstanceTrendsView.vue'` 直接渲染（复用其现有实现，走 `GET /instances/{id}/metrics`）。若 `InstanceTrendsView` 强依赖 route params，用其内部默认窗口或传 prop 包裹；不重写其逻辑。

- [ ] **Step 5: 测试转绿 + 四道门槛**

Run: `npx vitest run src/views/trafficViewModel.spec.ts src/i18n/i18n.spec.ts src/styles/hex-ban.spec.ts`（绿；TrafficView 在 hex 白名单内，须无裸 hex）→ `npx vue-tsc --noEmit`（恰好 5）→ `npm run lint`（绿）→ `npx vitest run`（全绿）→ 后端 `pytest`（未动，绿）。

- [ ] **Step 6: 提交**

```bash
cd console
git add frontend/src/views/TrafficView.vue frontend/src/views/trafficViewModel.ts frontend/src/views/trafficViewModel.spec.ts frontend/src/api/traffic.ts frontend/src/types/traffic.ts frontend/src/i18n/locales
git commit -m "feat(console): read-only traffic and routing page"
```

---

## Task 9: 人工走查 + 截图归档 + 全量验收

S1 不做自动化 e2e（无 playwright config），沿用既有方式：一次人脑浏览器走查 zh/en 各一遍 + 截图归档。

**Files:**
- Create: `console/qa-artifacts-archive/2026-10-28-console-s1/*.png`（走查截图）

**Interfaces:**
- Consumes: Task 1–8 全部产出。
- Produces: S1 验收结论（对照 spec §13 的 9 条验收标准）。

- [ ] **Step 1: 起服务**

Run: `cd console/frontend && npm run build`（确认 `vue-tsc`+vite 绿）→ 后端按仓内现有方式起 console 服务。

- [ ] **Step 2: 走查 checklist（zh/en 各一遍）**

逐项对 spec §13 验收标准：① 三段导航分组/顺序与 demo 一致，标签全来自 i18n 无硬编码中文；② 12 项 en/zh 键齐全对等；③ 5 条旧路径 redirect 生效、地址栏规范化；④ `/console/login` 成功后落 `/console/overview`，`/` 仍是语音前台；⑤ 语言切换后 reload 保持，`navigator.language` 决定首访，ant 内置文案随语言变；⑥ 白名单内无裸 hex；⑦ OverviewView 每个 KPI 可指来源、每个未实现项带 S2/S3 且无 mock；⑧ TrafficView 全程只读、`off` 有状态条、`configurable=false` 渲染只读说明。

- [ ] **Step 3: 截图归档**

将走查截图存到 `console/qa-artifacts-archive/2026-10-28-console-s1/`（导航展开态、OverviewView、TrafficView off/on、语言切换前后）。

- [ ] **Step 4: 全量门槛**

Run: `cd console/frontend && npx vue-tsc --noEmit && npm run lint && npx vitest run && npm run build`；`cd console/backend && python -m pytest -q`。
Expected: 全部符合门槛（vue-tsc 恰好 5 条）。

- [ ] **Step 5: 提交走查产物**

```bash
cd console
git add qa-artifacts-archive/2026-10-28-console-s1
git commit -m "test(console): S1 manual walkthrough screenshots"
```

---

## Self-Review（计划 vs spec）

**1. Spec coverage：** §13 实施顺序 0–8 → Task 0–9 一一对应（步 1 拆为 Task 1+2，步 8 为 Task 9）。§6.1 导航表、§6.2 redirect、§7 派生机制 → Task 3；§8.1–§8.6 i18n → Task 4+5；§9.1–§9.5 token → Task 1+2；§10.1/§10.2 两个新页 → Task 7/8；§10.2 后端端点 → Task 6；§11 错误处理内嵌于 Task 7/8（降级读/`off` 状态条/NotImplemented）；§12 测试策略各用例均有对应 spec 文件（hex-ban/tokens/i18n 对等+navKey/locale/router/两新页渲染/后端 pytest）；§14 风险缓解已写入各步（如基线 5 条错误、白名单只增不减、集群=profile 权宜映射）。

**2. Placeholder scan：** Task 5 是觕 539 串的机械迁移，不逐字枚举（不可行也无用），但给出统一规则、域→文件映射、首批 errors 的完整工样板与每批回归命令，以 `i18n 对等测试`+`Step 9 残留扫描`为验收门，符合“无占位”原则（可执行、可验证）。无 TBD/TODO。

**3. Type consistency：** `shellTokens.colorSurface2`/`voiceTokens.voiceSurface2` 命名在 Task 1/2 一致；`TrafficSettings` 字段与 Task 6 后端返回逐一对齐；`NotImplemented` props (`targetSubproject`/`reasonKey`) 在 Task 1(白名单声明)/Task 7(定义)/Task 8(使用) 一致；route names (`overview/traffic/machines/deploy/session-update/release`) 在 Task 3 定义、Task 4 navKey、Task 7/8 组件均同。

**已核实的依赖事实：** `@vue/test-utils` 与 `happy-dom` 均未装（`jsdom ^29.1.1` 已装）。因此 Task 7/8 的两个新页**不挂载组件**，而是把数据映射抽为 `overviewMetrics.ts` / `trafficViewModel.ts` 纯函数单测（对齐仓库 `src` 下 24 个纯 vitest spec 的惯例），DOM 相关测试（tokens 注入/locale/router/i18n）用 `// @vitest-environment jsdom` + `vi.stubGlobal('navigator', …)`，零新依赖。视觉/交互正确性由 Task 9 人工走查承担。

---
