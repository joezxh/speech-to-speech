---
kind: frontend_style
name: Demo 前端样式：纯 CSS + CSS 变量主题（无框架）
category: frontend_style
scope:
    - '**'
source_files:
    - demo/style.css
    - demo/console.css
    - demo/index.html
    - demo/console.html
    - demo/package.json
---

## 1. 系统/方法

本项目的前端 UI 位于 `demo/` 目录，采用 **原生 HTML + 原生 JavaScript + 纯 CSS** 的零依赖方案。没有引入任何 CSS 框架（Tailwind、Bootstrap、AntD 等）、没有 SCSS/Less 预处理器、也没有构建步骤——CSS 直接由浏览器加载。

- 字体通过 Google Fonts 在 `index.html` 中引入 `Inter` 与 `Geist Mono`，并在 CSS 中以 `font-family` 引用。
- 图标使用内联 SVG（`console.html` / `style.css` 中的 `<svg>`），不依赖图标库。
- 动画全部用 CSS `@keyframes` 和 `transition` 实现（旋转 spinner、thinking dots、voice wave、transport blink 等）。
- 响应式仅使用 CSS `@media (max-width: ...)` 断点（600px、800px），无 JS 媒体查询监听。

## 2. 关键文件

- `demo/style.css` (~2755 行) — 主对话页面（orb、topbar、account chip、queue、tool toast、mic gate、conversation panel）。
- `demo/console.css` (~750 行) — 部署参数控制台页面的样式，注释明确说明“Same palette as style.css so the two pages look like one tool, but nothing is shared”。
- `demo/index.html` / `demo/console.html` — 两个入口页，分别引用对应的 CSS。
- `demo/package.json` — 仅有测试脚本与运行时依赖（`@openai/agents`、`zod`），无构建工具链。

## 3. 架构与约定

### 设计令牌（Design Tokens）
所有视觉变量集中在 `:root` 伪类下，分为两类：

- 基础色板：`--bg`、`--bg-elev`、`--bg-elev-2`、`--border`、`--border-strong`、`--text`、`--text-dim`、`--text-faint`。
- 语义色：`--accent`（#8b7dff 紫）、`--accent-2`（#22d3ee 青）、`--listening`、`--speaking`、`--processing`、`--error`、`--success`。
- 角色色：`--voice-user`、`--voice-assistant`、`--voice-tool` —— 注释写明 “Thesis: color belongs to the voice”，颜色归属语音角色而非 UI chrome。
- 间距/圆角：`--radius-sm` (8px)、`--radius-md` (14px)、`--radius-lg` (22px)。
- 动态音频变量：`--audio-level`、`--bar0..--bar4`，由 JS 每帧更新以驱动频谱条高度。

两套 CSS 文件各自声明自己的 `:root` 变量，但值完全一致，保证两个页面视觉统一的同时保持文件独立。

### BEM-like 命名
类名采用扁平的 `.block` / `.block__element` 风格（如 `.topbar`、`.brand`、`.icon-btn`、`.circle`、`.circle-core`、`.circle-ring`、`.circle-indicator`、`.ind-spinner`、`.ind-thinking`、`.ind-bars`、`.ind-voice`），没有严格 BEM 但语义清晰。

### 状态驱动样式
UI 状态通过给根元素添加 class（如 `.state-signed-out`、`.state-listening`、`.state-ai-speaking`、`.state-error`）来切换显示，CSS 用后代选择器控制子元素的 `opacity` 与 `transform`，例如：
```css
.state-listening .ind-bars,
.state-ai-speaking .ind-voice { opacity: 1; transform: scale(1); }
```

### 暗色主题
`color-scheme: dark` 在两个 CSS 文件的 `:root` 中显式声明，背景为深灰黑（`#0a0b10`），强调色为紫色（`#8b7dff`）+ 青色（`#22d3ee`）。

### 响应式策略
- 桌面优先，使用 `@media (max-width: 600px)` 与 `@media (max-width: 800px)` 两个断点。
- 移动端隐藏品牌文案、将 `(i)` 按钮移入右侧控制区、缩小 icon-btn 尺寸、隐藏 account handle。
- 布局大量使用 Flexbox 与 CSS Grid（`.stage`、`.panel.params` 的双栏 grid、`.row` 的三列 grid）。

### 组件化约定
- 可复用控件：`.icon-btn`、`.btn`（含 `.primary` / `.ghost` / `.danger` 变体）、`.pill`、`.badge`（含 `.basic` / `.advanced` / `.expert` / `.ops` / `.live` / `.rolled_back` / `.failed` 变体）、`.card`、`.dialog`、`.toast`。
- 表单控件统一样式：`input` / `select` / `textarea` 共享边框、圆角、focus ring（`outline: none` + `box-shadow: 0 0 0 3px var(--accent-soft)`）。

## 4. 约定与约束

- **不使用任何 CSS 框架或预处理器**：`package.json` 无相关依赖，无 `tailwind.config.*`、无 `*.scss` 文件。
- **双页面共享同一套调色板但不共享 CSS 文件**：`console.css` 首行注释明确说明这一点，两套 `:root` 变量值保持一致。
- **颜色语义绑定到“语音角色”**：用户 = 青色、助手 = 紫色、工具调用 = 琥珀色，这一约定写在 `style.css` 的设计注释中。
- **所有交互状态通过 DOM class 切换**：JS 负责切换 class，CSS 只负责根据 class 显示/隐藏对应 indicator。
- **动画纯 CSS**：spinner、thinking dots、voice wave、transport blink 等均为 `@keyframes`，JS 仅控制 `animation-play-state`。
- **响应式断点固定为 600px 与 800px**，未见其他断点。
- **全局 `[hidden] { display: none !important }`**：`console.css` 覆盖 UA 默认规则以保证 JS 设置的 `hidden` 属性生效。
- **字体栈固定**：正文 `Inter`，代码/系统文本 `Geist Mono`，通过 Google Fonts 引入，不在仓库内托管字体文件。
- **无障碍**：使用 `:focus-visible` 定义焦点环，`aria-selected` 用于 tab 状态，`role` 与 `tabindex` 在 HTML 中配合使用。