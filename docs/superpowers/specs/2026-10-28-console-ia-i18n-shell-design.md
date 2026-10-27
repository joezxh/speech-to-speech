# 控制台信息架构重构 S1：三段式导航外壳 + i18n 基座 + 设计 token 收敛

## 1. 目标

把 `console/` 控制台的前端外壳对齐静态原型 `console/design/console-refactor-demo.html`（3,651 行）所呈现的信息架构，并补上它依赖的两块基座：**成对的 en/zh 文案**与**单一事实来源的设计 token**。

本段只做外壳与基座。demo 里的集群/机器/负载模型、Token 计量、按机器参数下发、音色向导、发布四阶段、审计导出全部划给后续子项目（§2），本段仅为它们预留扩展点。

三项交付：

1. 三段式导航（负载均衡管理 · 总架构 / 语音对话前台 / 运维台 · 集群维度），由路由表派生而非手工维护。
2. 界面文案全量 i18n：en/zh 成对、可切换、跨会话记忆；引擎名/参数名/端口/路径/错误码保留代码态原文。
3. 设计 token 收敛到 `styles/tokens.ts` 单一源，同时驱动 ant 主题、less 与原生 CSS。

外加两个新页的**真实只读**实现：集群总览、流量与路由。

## 2. 范围裁定与八段拆分

对齐 demo 全部功能涉及至少 5 个互相独立的子系统、3 处需要新迁移与新契约的改动，单一实施计划无法承载。按用户确认拆成八段，每段独立走 spec → plan → 实现：

| 段 | 内容 | 依赖 | 本段是否涉及 |
|---|---|---|---|
| **S1** | 三段式导航外壳 + i18n 基座 + token 收敛 + 两个新页只读 | — | ✅ |
| S2 | 集群与机器模型（机器实体、多负载声明、Agent 注册与手动准入） | S1 | ❌ |
| S3 | 流量与路由可写化 + Token 消耗分析（新计量存储与迁移；路径 A 的 LLM 网关扩展点在此） | S1, S2 | ❌ |
| S4 | 机器实际部署与参数（按机器下发、漂移、场景推荐→草稿→diff→回滚） | S1, S2 | ❌ |
| S5 | 发布与版本管理（构建/预发/金丝雀/全量四阶段、版本锁定） | S1, S4 | ❌ |
| S6 | 音色库（列表 Source 列 + 5 步制作向导 + 与四个 qwen3 参数行打通） | S1 | ❌ |
| S7 | 审计增强（分类过滤、CSV 导出） | S1 | ❌ |
| S8 | 录音归档收尾（补 `api/voiceSessions.ts`、恢复 `SessionRecordConfig`、`RecordingsView` 挂进前台会话历史） | S1 | ❌ |

S1 的验收口径由用户明确为**外壳级**：外壳结构 + 两个新页的只读真实实现，其余 8 个页面内部布局与交互不动。

架构前提「路径 A」（自研 LB 扩展为 LLM 网关）在 S1 中只体现为一处：`TrafficView` 的契约把「未实现能力」显式编码（§10.2），使 S3 接入时不需改前端结构。S1 不实现任何模型流量代理。

## 3. 现状事实（设计依据）

以下均为本段设计前实测，非推断。

**后端既有能力足以支撑只读两页。**

- `GET /api/v1/instances` 的 `data` 含 `profile / version / container / pool / usage / alerts[] / summary / instances[]`（`services/instances_service.py:145-167`）。`summary` 有 `instances_total / online / offline / degraded / draining / slots_total / slots_in_use / slots_free / pending_grants`（同上 `:132-143`）。每条实例含 `instance_id / base_url / status / weight / enabled / drain_requested / size / in_use / free / stuck / probe_ms / p95_probe_ms / units[] / last_error / observed_by / declared_mismatch`（同上 `:105-129`）。
- `GET /api/v1/status` 的 `data` 含 `profile / version / status / catalogCommit / validatorMode / db / pipeline / internalTokenConfigured / allocatorMode / instancesRegistered / seedConfigured / consoleId / secretsConsistent`（`services/status_service.py:51-65`）。
- `AllocatorSettings` 共 11 个字段 + `resolved_console_id` 属性（`config/_allocator.py:21-39`）：`mode(off|local) / console_id / seed_path / probe_interval_s=5 / probe_timeout_s=2 / fail_threshold=3 / recover_threshold=2 / grant_ttl_s=60 / usage_interval_s=30 / metric_retention_days=7 / queue_enabled=False / webrtc_hangup_enabled=False`。**这些值目前没有任何端点暴露。**
- 成功信封统一为 `{code, message, data}`（`schemas/common.py:18-20`）。`status` 用 camelCase、`instances` 行内用 snake_case，casing 既有不一致。
- `/instances` 的契约是「降级读仍返回 200」（`routers/instances.py:25` 的 A.10）。

**demo 目标 IA 与后端能力的三处硬缺口。**

- 调度策略不是配置项。`allocator._candidates()` 是硬编码的「`free/capacity` 降序 → 同分按 `weight` 加权随机 → 排除已试」，没有 policy 字段。
- 无会话亲和。`allocate()` 每次独立选台，demo 的「会话粘滞」在后端不存在。
- 无路由规则表、无金丝雀比例、无机器实体。`param_instance_metric` 无任何 token/error 列，Token 消耗分析必须新建存储（S3）。

**前端既有约定。**

- 外壳是单个 `layouts/ConsoleLayout.vue`（469 行），导航来自 `router/nav.ts`（72 行）的手工常量 `NAV_GROUPS`，标签是硬编码中文；`ConsoleLayout` 用 `router.hasRoute()` 过滤未注册项。
- `i18n/index.ts`（12 行，`legacy:false`，`locale:'zh-CN'`）+ `i18n/zh-CN.ts`（18 行）：只有 `app.*` 与 6 个 `nav.*`，且 `nav.params='参数'` 这类键已与 `nav.ts` 的实际标签脱节。
- `App.vue`（10 行）的 `<a-config-provider :theme>` **未传 `:locale`**，ant 内置文案（空态、分页、`a-popconfirm`）目前只有英文。
- `utils/storage.ts`（44 行）只用 `sessionStorage`，注释写着「Nothing else is persisted」。
- `utils/format.ts`（43 行）只用显式 token（`YYYY-MM-DD HH:mm:ss`），无 relativeTime 插件，注释明确**故意不走 `toLocaleString`**（分隔符随环境变）。`dayjs` 在 `LogPanel.vue` 仅用于范围选择器的值。
- `npm run build` = `copy-vendors.mjs && vue-tsc --noEmit && vite build`——类型检查是构建门禁。`npm run lint` = `eslint . --max-warnings 0`。
- `src/router/router.spec.ts` 已有 4 条用例，其中一条断言 `/console/params` 与 `name === 'params'`。
- `package.json` 有 `test:e2e: playwright test`，但**仓库内没有 `playwright.config.ts`，也没有任何 e2e 用例**（`src` 下 24 个 `*.spec.ts` 全是 vitest）。

**类型检查基线是红的。** `npx vue-tsc --noEmit` → `EXIT=2`，5 个错误（附录 A），全部来自一条未完成且未纳入版本控制的「录音归档」前端线：`RecordingsView.vue`、`api/voiceSessions.spec.ts`、`features/voice/archive/` 等为 untracked，`api/voiceSessions.ts` 从未存在。该线的**后端半边真实完整**（`config/_console.py:43-51` 的 `session_record_enabled`、`services/demo_config_service.py:48-52` 的 `sessionRecord` 下发、`backend/data/sessions/` 下 3 个 ULID 目录含真实 `.wav`），因此拆为 S8 单独收尾而非删除。

**文案与颜色的实测规模。**

- 用户可见中文串约 **539 处**（views 161 / components 174 / utils 140 / features 31 / router 14 / stores 11 / layouts 8），已排除注释。
- 裸 hex 字面量全文件扫描 **163 处 / 58 个不同值 / 25 个文件**。按本段采用的「只管样式面」边界（§9.5）复扫：**152 处 / 52 个不同值 / 24 个文件**。被排除的 11 处全部位于模板内联 SVG 插画内（`LimitDialog.vue` 5 处、`InstanceTrendChart.vue` 6 处），它们不是主题色而是嵌死的画素。
- 24 个文件里 `styles/**` 占 3 个（`theme.ts` 15、`voice.less` 18、`variables.less` 5），其余 21 个是页面与组件。
- 52 个 distinct 值中 **20 个与 demo 的 shell/voice 两套 token 逐字相同**；demo 有、本仓尚无对应值的 4 个：`#212a45`(surface-3)、`#2e3856`(border-strong)、`#a78bfa`(purple)、`#f0a05c`(orange)。剩下的存在大量互相打架的近似值：`#5b6478/#5b647c`、`#6b7280/#6b7285/#6d7688/#6f7891`、`#94a3b8/#9aa3b8/#9ca3af`、`#1e2740/#1e2742/#1d2742/#1d2a4a`、`#4d7cff/#5b8cff`、`#0d1326/#0f1424/#101728/#12151f/#171b26/#1c2130`。
- token 现状是**四处**不同步：`variables.less` 6 个、`theme.ts` 16 个 ant token（注释自称「唯一主题事实来源」）、`voice.less:1-24` 的 `:root` 18 个 `--voice-*`（另一套暗色调色板，bg `#0a0b10`、accent `#8b7dff`）、`ConsoleLayout.vue` 19 处裸 hex。
- 全部 less 文件中**没有任何 less 颜色函数调用**（`darken/lighten/fade/mix/saturate` 均无）；`voice.less` 用的是 `color-mix(in srgb, …)`。因此「less 变量转发到 CSS 变量」不会遇到编译期求值失败。
- `ant-design-vue/es/locale/{zh_CN,en_US}.js` 与 `dayjs/locale/zh-cn.js` 均存在（已核实）。

**demo 自身的结构。**

- `NAV`（`console-refactor-demo.html:1837-1855`）三组共 12 项；`PAGES`（`:1857`）8 个页面，**无 sessions 页**。
- `I18N`（`:397-581`）是**扁平点分键**，en/zh 各约 92 行成对。
- `:root` token 块约 22 项，含 `--surface-2 #1a2138`、`--surface-3 #212a45`、`--border-strong #2e3856`、`--faint #5b6478`、`--accent-soft`、`--purple/--orange/--cyan`、`--radius-sm/md/lg`、`--mono`。

**一条工具链事实决定了 i18n 键结构。** vue-i18n 的默认 `messageResolver` 是 `@intlify/core-base` 的 `resolveValue(obj, path)`，它把 `path` 交给路径解析器按 `.` 切段后逐层遍历对象，**没有扁平键回落分支**。所以 demo 的 `'nav.overview': '…'` 照搬进 messages 取不到值，必须转成嵌套结构。

## 4. 本期不做

机器实体与多负载声明、Token 计量与配额水位、可写的调度参数、参数下发的按机器路由（`hot_update_service.py:149` 写死回环 `pipeline_base_url`，本段不改）、发布四阶段与版本锁定、音色制作向导、审计 CSV 导出、录音归档（S8）、Playwright 套件配置、`instances`/`status` 的 casing 统一、语音页与外壳两套调色板的合并。

## 5. 已确认的决策记录

| # | 决策 | 取舍 |
|---|---|---|
| 1 | 拆 8 段，先做 S1 | 单计划无法承载 5+ 独立子系统 |
| 2 | S1 = 外壳级 + 两新页只读真实实现 | 其余 8 页内部不动 |
| 3 | UI 用 demo 术语，后端契约（API 路径/DB 表/service 名）一律不改 | 术语与实现解耦，降低回归面 |
| 4 | 脏树先提交成基线；S1 门槛 = `vue-tsc` 错误恰好等于基线 5 条；录音归档另立 S8 | 不丢已有工作，S1 不被无关功能线打断 |
| 5 | `SessionsView` → 运维台第 6 页「会话热更新」；`RecordingsView` → S8 挂进前台「会话历史」服务端归档 tab | demo IA 无对应位置，职责边界优先于页数一致 |
| 6 | locale 存 localStorage（新增例外），首次跟随 `navigator.language` | 语言是跨会话偏好；session/profile 仍是会话态 |
| 7 | i18n 用嵌套结构 + 按域拆文件，域 = route name | 已核实扁平点分键在 vue-i18n 下不可解析 |
| 8 | token 单一源 = `styles/tokens.ts`，运行时注入 `:root` | less 与 TS 天然不能互读，必须选一侧为源 |
| 9 | 旧路径用 `redirect`（非 `alias`）永久保留 | alias 会让新旧两个 URL 同时有效，面包屑/断言/高亮都要处理两遍 |
| 10 | `/console` 默认落地页由 `params` 改为 `overview`；`/` 仍是语音前台 | 与 demo `state.page='overview'` 一致 |
| 11 | 新增只读端点 `GET /api/v1/traffic/settings`（S1 唯一后端改动，additive） | 否则流量与路由页无数据来源 |
| 12 | `scheduling.configurable` 与 `unimplemented[]` 由后端声明 | 「哪些没实现」属于契约，不写死在前端 |
| 13 | hex 禁令用单调收紧的白名单，S1 只强制 5 个既有文件 | 163 处全改会使 S1 膨胀数倍，且 20 个文件将在各自子项目重做 |
| 14 | `fallbackLocale` 从 `zh-CN` 改为 `en-US` | demo 英文表覆盖最全，漏译显示英文最可诊断 |
| 15 | dayjs locale **不**联动 | `format.ts` 的确定性格式化是既有约定，不应被本地化打破 |

## 6. 目标信息架构与路由契约

### 6.1 三段导航

分组标题沿用 demo 已定稿的双语词：`负载均衡管理 · 总架构` / `语音对话前台` / `运维台 · 集群维度`。

| 段 | 页面 | route name | 新 path | 组件 | 图标 |
|---|---|---|---|---|---|
| lb | 集群总览 | `overview` | `/console/overview` | `OverviewView`（新建） | layers |
| lb | 流量与路由 | `traffic` | `/console/traffic` | `TrafficView`（新建） | signal |
| front | 对话演示 | `voice` | `/`（不变） | `VoiceView` | target |
| front | 会话历史 | — overlay | — | `VoiceOverlay('history')` | history |
| front | 工具 | — overlay | — | `VoiceOverlay('tools')` | wrench |
| front | 设置 | — overlay | — | `VoiceOverlay('settings')` | gear |
| ops | 机器管理 | `machines` | `/console/machines` | `InstancesView` | server |
| ops | 机器实际部署与参数 | `deploy` | `/console/deploy` | `ParamsView` | cpu |
| ops | 会话热更新 | `session-update` | `/console/session-update` | `SessionsView` | sliders |
| ops | 音色库 | `voices` | `/console/voices` | `VoicesView` | wave |
| ops | 发布与版本管理 | `release` | `/console/release` | `VersionsView` | check |
| ops | 操作审计日志 | `audit` | `/console/audit` | `AuditView` | history |

`InstanceTrendsView` 不再是路由页，降级为 `TrafficView` 内嵌的趋势区块组件，S1 直接复用其现有实现。`NavIcon` 联合类型新增 `layers | signal | cpu`，移除已无引用的 `chat | trend`。

### 6.2 旧路径 redirect

永久保留、不清理。`name` 只有新名，旧路径只做跳转：

```ts
{ path: '/console/params',           redirect: { name: 'deploy' } },
{ path: '/console/instances',        redirect: { name: 'machines' } },
{ path: '/console/instances/trends', redirect: { name: 'traffic' } },
{ path: '/console/versions',         redirect: { name: 'release' } },
{ path: '/console/sessions',         redirect: { name: 'session-update' } },
```

后端 SPA catch-all 已存在（注册顺序在 `core/router_registry.py` 固定：API 前缀先、catch-all 最后，本段不动它），旧 URL 会落到 SPA 再由上表跳转，地址栏规范化为新 path。

`/console` 的默认 redirect 从 `{name:'params'}` 改为 `{name:'overview'}`。`/` 仍解析到 `voice`，不改。

### 6.3 术语对照表

右列在 S1 一律不改，作为 S2–S8 的共同词表。

| UI 术语 zh / en | route name | 后端契约（不动） |
|---|---|---|
| 集群 / Cluster | — | 无 cluster 实体；S1 中集群 = `profile` |
| 机器 / Machine | `machines` | `param_instance` 表、`InstanceRegistry`、`GET /instances` |
| Pipeline 实例 / Pipeline instance | — | `instance.units[]`、`pool.size` |
| 负载 / Workload | — | 不存在，S2 引入 |
| 流量与路由 / Traffic & Routing | `traffic` | `AllocatorSettings`（env 只读） |
| 机器实际部署与参数 / Deployments & Params | `deploy` | `catalog / draft / publish_flow / hot_update` |
| 发布与版本管理 / Releases & Versions | `release` | `publish_flow_service`、`versions` |
| 操作审计日志 / Audit Log | `audit` | `audit` |
| 会话热更新 / Session Hot Update | `session-update` | `POST /sessions/update` |

「集群 = profile」是 S1 的权宜映射：后端没有 cluster 实体，`profile` 承担的是配置环境维度。**S2 必须重新裁决 cluster 与 profile 是否 1—1**，本表把这条列为 S2 的必答题，不允许悄悄固化。

## 7. 导航派生机制

`NAV_GROUPS` 手工常量删除，改为从路由表派生。

### 7.1 NavMeta 契约

```ts
interface NavMeta {
  navGroup: 'lb' | 'front' | 'ops'
  navKey: string      // i18n 键，如 'nav.deploy'
  navIcon: NavIcon
  navOrder: number    // 段内排序，步进 10，便于插入
}
```

`ConsoleLayout` 用 `router.getRoutes()` 取 `meta.navKey` 存在的记录，按 `navGroup` 分桶、`navOrder` 排序，标签走 `t(meta.navKey)`。既有的 `router.hasRoute()` 过滤保留——它承担「未注册的可选页不显示」，与派生逻辑正交。

### 7.2 frontOverlays 补充表

demo 前台的「会话历史 / 工具 / 设置」不是路由而是 overlay，无法从路由表派生，单独保留一张约 12 行的常量表：

```ts
export const frontOverlays: Array<{ overlay: VoiceOverlay; navKey: string; navIcon: NavIcon; navOrder: number }> = [
  { overlay: 'history',  navKey: 'nav.history',  navIcon: 'history', navOrder: 20 },
  { overlay: 'tools',    navKey: 'nav.tools',    navIcon: 'wrench',  navOrder: 30 },
  { overlay: 'settings', navKey: 'nav.settings', navIcon: 'gear',    navOrder: 40 }
]
```

`ConsoleLayout` 渲染 `front` 段时把它拼接在 `voice`（`navOrder: 10`）之后。

`router/nav.ts` 文件保留，但 `NAV_GROUPS` 手工常量删除；文件只剩 `VoiceOverlay` / `NavIcon` 类型与上述 `frontOverlays` 常量。

### 7.3 收益与代价

收益：S2–S8 每加一页只改一处（route meta）；i18n 的域命名空间有客观依据（域 = route name），不需要先猜。

代价与兜底：`navKey` 是字符串字面量，TS 无法校验对应键存在。用 §12 的 `navKey 可解析` 测试兜住。

## 8. 国际化

### 8.1 目录与域划分

域直接取自 §6.1 的 route name：

```
src/i18n/
  index.ts            createI18n(legacy:false)，locale 由 store 驱动，missing 处理器
  locale.ts           支持的 locale 常量、navigator.language 检测、localStorage 读写
  locales/zh-CN/{index,nav,shell,auth,common,errors,overview,traffic,machines,
                 deploy,sessionUpdate,voices,release,audit,voice,logs,latency}.ts
  locales/en-US/{index,nav,shell,auth,common,errors,overview,traffic,machines,
                deploy,sessionUpdate,voices,release,audit,voice,logs,latency}.ts
                  ↑ 与 zh-CN 同名同构，文件名与键树一一对应
```

16 个域 × 2 语言。每个域的 `index.ts` 只做聚合，不含文案。现有 18 行 `zh-CN.ts` 整体删除，不迁移（已与 `nav.ts` 脱节，实际是死代码）。

16 个域分两类落地：`nav` / `shell` / `common` / `errors` / `auth` / `machines` / `deploy` / `sessionUpdate` / `voices` / `release` / `audit` / `voice` / `logs` / `latency` 这 14 个是**既有串的键化**（步骤 4）；`overview` / `traffic` 两个无既有串，其文案随新建页在步骤 6/7 一并写下。步骤 3 先建 `nav` / `shell` / `common` 三个骨架域。

### 8.2 键命名规则

顶层 = 域名，叶子小驼峰，嵌套不超过三层：`deploy.draft.diffTitle`、`machines.table.colStatus`、`errors.recordingDisabled`。**禁止点分扁平键**（§3 已核实其在本项目 vue-i18n 下不可解析）。demo 文案逐字照搬但结构转嵌套：`'kpi.machines': 'Machines'` → `overview.kpi.machines`。插值用命名式 `{count}`；仅英文确需区分单复数时才用 vue-i18n 的 `one|other`。

### 8.3 代码态保留清单

不键化、原样渲染：

- 引擎与后端名：`qwen3_asr`、`qwen3_tts`、`cosyvoice`、`omnivoice`、`ggml`、`openai`
- 参数键名：`qwen3_tts_speaker`、`qwen3_tts_ref_spk`、`qwen3_tts_ref_rvq`、`qwen3_tts_instruct`、`min_silence_ms`、`smart_turn`
- 端口、路径、URL：`8765`、`/v1/realtime`、`/api/v1/instances`
- 错误码原文：`at_capacity`、`recording_disabled`、`not_found`、`invalid_request`、`session_limit_reached`（键化的只是其旁的人读描述）
- 标识符：`instance_id`、profile 名、版本号、commit hash
- 数字与时间格式：保持 `format.ts` 的确定性输出

### 8.4 展示译、比较不译

状态枚举 `online / degraded / offline / draining / idle / active / stuck` 在界面显示译文（`common.statusOnline` = 在线 / Online），但在 `data-testid`、排序键、与后端返回值的一切比较中一律用原值。demo 已把这些词翻译（`'ok': '健康'`），不立此规则会出现拿译文比对 API 返回的 bug。

### 8.5 locale 状态与联动

新增 `stores/locale.ts`，状态 `'zh-CN' | 'en-US'`。初始化顺序：localStorage `s2s.console.locale` → `navigator.language` 前缀匹配（`zh*` → `zh-CN`，其余 → `en-US`）→ 兜底 `zh-CN`。

`utils/storage.ts` 新增这一个键，并把「Nothing else is persisted」改为写明例外与理由（语言是跨会话偏好；session/profile 是会话态，继续留在 sessionStorage）。

`App.vue` 补 `:locale="antLocale"`，由同一 store 计算为 `ant-design-vue/es/locale/zh_CN` 或 `en_US`。**dayjs 不动**：`format.ts` 只用显式 token，`LogPanel.vue` 只把 dayjs 用于日期值，无任何本地化格式需求。

切换器放顶栏，en/zh 两态 toggle（对齐 demo 的 `#lang-btn`，不用下拉）。`fallbackLocale` 从 `'zh-CN'` 改为 `'en-US'`。

### 8.6 缺失键处理

`missingWarn` / `fallbackWarn` 关闭（否则控制台被刷屏），改传 `missing` 处理器：开发期把缺键收进去重集合后 `console.warn` 一次，生产静默回落 `fallbackLocale`。真正的防线是 §12 的键集合对等测试。

## 9. 设计 token

### 9.1 `styles/tokens.ts`

两个命名空间，对应实测的两套调色板，各自保持既有变量名以免重写 720 余行 `var(--voice-*)` 消费方。

```ts
export const shellTokens = {
  colorBg:'#0b1020', colorSurface:'#141a2e', colorSurface2:'#1a2138', colorSurface3:'#212a45',
  colorBorder:'#232b45', colorBorderStrong:'#2e3856',
  colorText:'#e6e8f0', colorMuted:'#8b93a7', colorFaint:'#5b6478',
  colorAccent:'#5b8cff', colorAccentSoft:'rgba(91, 140, 255, 0.16)',
  colorSuccess:'#35c48a', colorWarning:'#e8b339', colorDanger:'#f0655c',
  colorPurple:'#a78bfa', colorOrange:'#f0a05c', colorCyan:'#22d3ee',
  radiusSm:'6px', radiusMd:'10px', radiusLg:'14px',
  font:"-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
  fontMono:"'Geist Mono', ui-monospace, Consolas, 'Courier New', monospace"
} as const

export const voiceTokens = {
  voiceBg:'#0a0b10', voiceSurface:'#13151c', voiceSurface2:'#1b1e29', voiceSurfaceMix:'#2a2e3c',
  voiceBorder:'rgba(255, 255, 255, 0.08)', voiceBorderStrong:'rgba(255, 255, 255, 0.16)',
  voiceText:'#f5f6fa', voiceDim:'rgba(245, 246, 250, 0.65)', voiceFaint:'rgba(245, 246, 250, 0.42)',
  voiceAccent:'#8b7dff', voiceListening:'#22d3ee', voiceProcessing:'#f59e0b', voiceError:'#ff6a75',
  voiceReady:'#34d399', voiceQueued:'#94a3b8', voiceConnecting:'#facd15',
  voiceUser:'var(--voice-listening)', voiceAssistant:'var(--voice-accent)', voiceTool:'var(--voice-processing)',
  voiceRadius:'14px'
} as const

/** hex 禁令的作用域。每完成一个子项目就把该页文件加进来，只增不减。 */
export const TOKEN_ENFORCED_GLOBS: readonly string[] = [
  'src/styles/**', 'src/layouts/ConsoleLayout.vue', 'src/views/LoginView.vue',
  'src/views/OverviewView.vue', 'src/views/TrafficView.vue', 'src/components/NotImplemented.vue'
]
```

`voiceSurfaceMix`（原 `voice.less:162` 的 `#2a2e3c`）与 `voiceConnecting`（原 `voice.less:243` 的 `#facd15`）是本次从 inline 收进来的两项。`voiceTokens` 共 20 项 = `voice.less:1-24` 原有 14 实值 + 3 别名 + 1 圆角 + 2 新增。值允许是 `var(--…)` 字符串，因为别名本来就这么写。

### 9.2 注入与三条消费路径

注入后 CSS 变量名：shell 用 `--s2s-*`（camelCase → kebab，加前缀避免与 ant 的 `--ant-*` 冲突），voice **沿用现名** `--voice-*`。

1. `theme.ts` 改为 import tokens 后映射 ant 的 16 个 token（`colorPrimary = shellTokens.colorAccent` 等），注释里的「唯一主题事实来源」改为指向 `tokens.ts`。
2. `variables.less` 的 6 个值定义改为转发（`@color-bg: var(--s2s-color-bg);`），`index.less` 的 `background: @color-bg` 一行不动。可行依据见 §3：less 侧无任何颜色函数调用。
3. `voice.less:1-24` 的 `:root` 块删除（值搬入 `tokens.ts`），其余 `var(--voice-*)` 消费不变。

`applyTokens()` 在 `main.ts` 里、`createApp().mount()` **之前同步**调用，首帧即带变量，无无样式闪烁；纯 SPA，不需要构建期生成 CSS。

### 9.3 外壳 8 个 hex 的去向

`ConsoleLayout.vue` 的 19 处、8 个不同值，逐一对应：

| 现值 | 用途 | 去向 | 值是否变 |
|---|---|---|---|
| `#0b1020` | 外壳底 | `--s2s-color-bg` | 同值 |
| `#e6e8f0` | 主文本 | `--s2s-color-text` | 同值 |
| `#141a2e` | 顶栏底 | `--s2s-color-surface` | 同值 |
| `#8b93a7` | 次级文本/图标 | `--s2s-color-muted` | 同值 |
| `#1f2740` | 三处边框 | `--s2s-color-border` | **改为 `#232b45`** |
| `#6b7285` | 分组标题 | `--s2s-color-faint` | **改为 `#5b6478`** |
| `#1d2742` | 导航项 hover | `--s2s-color-surface-2` | **改为 `#1a2138`** |
| `#0f1424` | 侧栏底 | `--s2s-color-surface`（与顶栏同色，靠 `--s2s-color-border` 分隔，取 demo 侧栏做法） | **改为 `#141a2e`** |

4 个值会变，这是「沿用 demo 暗色 token」的直接后果，属于本段预期内的视觉微调，走查时以 demo 为准比对。

### 9.4 强制范围的 ratchet

`TOKEN_ENFORCED_GLOBS` **只增不减**。S1 实际处理 **5 个文件、60 处**：`styles/**` 38 处（`theme.ts` 15 + `voice.less` 18 + `variables.less` 5）+ `ConsoleLayout.vue` 19 处 + `LoginView.vue` 3 处。其余 **19 个文件、92 处**按附录 B 归属各子项目，在其重做该页时收进 `tokens.ts` 并把文件加入白名单。52 个近似值中未与 demo 重合的部分在各自页面重做时自然归并，S1 不提前裁决。

### 9.5 禁令边界：只管样式面

hex 禁令的作用面是**样式面**：`.less` / `.css` / `.ts` 的全文，加上 `.vue` 的 `<style>` 块。**模板内的内联 SVG `fill="#…"` 不在禁令内**——那是插画像素而非主题色，强行收进 `tokens.ts` 会把一次性图案的填充色伪装成设计 token。实测受影响的两处：`LimitDialog.vue`（5 处全在表情插画内，因此从附录 B 中整项消失）与 `InstanceTrendChart.vue`（9 处中 6 处在模板 SVG内，仅 3 处计入样式面）。

## 10. 两个新页的数据契约

### 10.1 `OverviewView`（零后端改动）

数据源即既有的 `GET /api/v1/status` + `GET /api/v1/instances`（均 `require_user`）。

真实可得 KPI 与来源字段：

| 指标 | 来源 |
|---|---|
| 集群名 | `status.profile`（§6.3 权宜映射） |
| 当前版本 / 状态 | `status.version`、`status.status` |
| 目录 commit | `status.catalogCommit` |
| DB / Pipeline 健康 | `status.db`、`status.pipeline` |
| LB 模式 / console id / seed 配置 | `status.allocatorMode`、`status.consoleId`、`status.seedConfigured` |
| 已注册实例数 | `status.instancesRegistered` |
| Pipeline 实例总数、在线/降级/离线/排空 | `summary.instances_total / online / degraded / offline / draining` |
| 活跃会话、空闲槽位、槽位总量 | `summary.slots_in_use / slots_free / slots_total` |
| 已签发未领取 grant | `summary.pending_grants` |
| 集群告警 | `alerts[]`（`pool_unreachable:*`、`pool_stuck:*`、`instance_capacity_mismatch:*`、`pipeline_stopped`） |
| 容量声明不一致的实例 | `instances[].declared_mismatch` |

demo 上有、S1 拿不到的，渲染为带子项目标记的空态，**不伪造数据**：

| demo 指标 | S1 状态 | 依据 |
|---|---|---|
| 机器数 / 机器在线数 | S2 | `instances` 行无 host 字段，机器实体不存在 |
| 错误率（5m）/ 主要错误来源 | S3 | `param_instance_metric` 无 token/error 列 |
| 会话粘滞命中率 | S3 | `allocate()` 无亲和性 |
| P95 TTFT | S3 | `GET /turn-latency` 是单机回环口径，非集群聚合 |
| 训练任务 | 不在八段范围内 | — |

拓扑图 S1 只画两层（LB → pipeline instances），机器层留一个带 S2 标记的空层。

### 10.2 `TrafficView` 与新端点

数据源：新端点 + `GET /api/v1/instances` + 内嵌 `InstanceTrendsView`（走既有 `GET /instances/{id}/metrics`）。

```
GET /api/v1/traffic/settings        require_user；无写路径；不写 DB；不记审计
→ ok({
    allocatorMode, consoleId, seedConfigured,
    probeIntervalS, probeTimeoutS, failThreshold, recoverThreshold,
    grantTtlS, usageIntervalS, metricRetentionDays,
    queueEnabled, webrtcHangupEnabled,
    scheduling: { policy: 'least-in-use', configurable: false, tieBreaker: 'weight-random' },
    unimplemented: ['session-stickiness', 'canary-ratio', 'routing-rules']
  })
```

- 字段值直接取自 `AllocatorSettings`（`config/_allocator.py:21-35`）。
- casing 用 camelCase，与 `status_service` 同风格（该端点是 console 级配置快照，与 `/status` 同类）。`instances` 行的 snake_case 不一致本段不修也不扩大。
- `scheduling.configurable: false` 把「策略当前是硬编码的」这一事实编码进契约。前端据此渲染只读说明；S3 真做策略时改 `true`、`policy` 变枚举，**前端结构不动**。
- `unimplemented[]` 由后端声明，前端据此渲染「未实现」空态。「哪些没实现」属于契约，不允许前后端各说一套。
- 路由只注册 `GET`，不允许出现任何写方法（§12 有断言）。

## 11. 错误处理

沿用既有机制，不新造：`api/client.ts` 的 `AppError` + `ErrorBanner.vue` + `utils/error.ts` 的 `translate()`。

- **降级读**：`/instances` 契约是降级仍 200（A.10），`OverviewView` 必须能渲染部分数据——`null` 字段走 `DASH`，`alerts[]` 逐条渲染成 banner，不得因单条告警整页失败。
- **`allocatorMode === 'off'`**（默认值）：`TrafficView` 顶部一条醒目状态条，说明 LB 未启用、下方读数是配置值而非生效行为。这是常态不是异常，不用 error 级样式。
- **空注册表**：`summary.instances_total === 0` 且 `status.seedConfigured === false` → `OverviewView` 空态指向机器管理页与 seed 配置。
- **401**：走既有拦截器跳登录，本段不改拦截器。
- **未实现区块**：统一由 `components/NotImplemented.vue` 渲染，props 只有 `targetSubproject` 与 i18n 键。禁止用 mock 数据填充任何区块。

## 12. 测试策略

**后端 pytest**（新端点，沿用仓库既有长描述式测试名）：未登录 401；信封是 `{code,message,data}`；每个字段与 `AllocatorSettings` 当前值一致；调用前后 DB 无写入、`audit` 表无新行；`allocatorMode='off'` 时仍 200；该 router 只注册 `GET`。

**前端 vitest**：

| 用例 | 断言 |
|---|---|
| i18n 对等 | 递归展平 `zh-CN` 与 `en-US`，键集合完全相等，每个值是非空字符串 |
| navKey 可解析 | 遍历 `router.getRoutes()` 与 `frontOverlays` 的全部 `navKey`，在两语言树中均可解析 |
| token 注入 | `applyTokens()` 后 `documentElement` 上每个 `--s2s-*` / `--voice-*` 均存在；`theme.ts` 引用的每个值都来自 `tokens.ts` |
| hex 禁令 | 扫描范围严格等于 §9.5 的样式面（`.less`/`.css`/`.ts` 全文 + `.vue` 的 `<style>` 块），且仅对 `TOKEN_ENFORCED_GLOBS` 命中的文件断言无裸 hex；白名单只有 `tokens.ts` 自身与 `color-mix()` 的 `#fff`/`#000` 端点。模板内联 SVG 不在扫描范围内。glob 解析由测试自己完成（`import.meta.glob` 或等价路径匹配），**不引入新依赖** |
| 白名单单调收紧 | `TOKEN_ENFORCED_GLOBS` 只增不减（新增条目须同时提供该文件已无 hex 的证据） |
| locale store | localStorage 命中 / `navigator.language` 回退 / 兜底 `zh-CN` 三条路径；写入后 localStorage 有值 |
| router | 新 name 与 path；5 条 redirect 命中并规范化；`/console` 落 `overview`；`/` 仍是 `voice`；meta 的 `face`/`requiresAuth` 继承（更新既有 `router.spec.ts`） |
| 两新页渲染 | mocked api 下 KPI 取自 `summary`；未实现区块出现 S2/S3 标记；`allocatorMode='off'` 出现状态条 |

**不新建 Playwright 套件**（§3：有 `test:e2e` 脚本但无 config、无用例）。界面验证沿用既有方式：一次人工浏览器走查 + 截图归档到 `qa-artifacts-archive/`。「`test:e2e` 悬空」记为独立技术债，不在 S1 修。

**每步都跑的门槛**：`npx vue-tsc --noEmit` 错误**恰好等于**附录 A 的 5 条（不新增也不减少，S8 才清）；`npm run lint` 全绿；`npx vitest run` 全绿；后端 pytest 全绿。

## 13. 实施顺序与验收

| 步 | 内容 | 依赖 | 验证 |
|---|---|---|---|
| 0 | 提交脏树成基线（含 untracked），把 `vue-tsc` 5 条错误固进附录 A | — | `git status` 干净；`vue-tsc` 恰好 5 条 |
| 1 | `tokens.ts` + `applyTokens` + `theme.ts` 派生 + `variables.less` 转发 + 删 `voice.less` 的 `:root` + `ConsoleLayout`(19) 与 `LoginView`(3) 替换 + hex 禁令测试 | 0 | 四道门槛全绿；视觉走查确认 §9.3 的 4 处变化 |
| 2 | 路由重命名 + 5 条 redirect + `NavMeta` + `frontOverlays` + 导航派生 + `router.spec.ts` 更新 + navKey 测试 | 0 | 四道门槛全绿；12 个导航项可见可点 |
| 3 | i18n 基座：`stores/locale.ts`、`i18n/index.ts`、目录骨架（先只放 nav/shell/common）、ant `:locale`、顶栏切换器、对等测试 | 2 | 切换 en/zh 后 reload 保持；对等测试绿 |
| 4 | 按域键化 539 处，分 6–8 个提交：errors → auth → shell 补全 → machines/deploy → voices/release/audit/session-update → voice/logs/latency | 3 | 每批后对等测试绿；`vue-tsc` 仍恰好 5 条 |
| 5 | 后端 `GET /api/v1/traffic/settings` + pytest | 0 | 后端 pytest 绿 |
| 6 | `OverviewView` + `overview` 域文案（新建，无既有串） | 2, 3, 4(`common`+`errors` 批次已完) | 渲染用例绿；每个 KPI 可指来源 |
| 7 | `TrafficView` + `traffic` 域文案（新建）（内嵌 `InstanceTrendsView`） | 2, 3, 5 | 渲染用例绿；`mode=off` 有状态条 |
| 8 | 人工走查（zh/en 各一遍：12 导航项 + 5 redirect + 落地页）+ 截图归档 + 全量验收 | 1–7 | 全部门槛绿 |

1–3 是结构层，必须串行。4 在 3 之后各域可并行。5 与 1–4 完全独立，可最先做掉。

**S1 验收标准**：

1. 三段导航按 §6.1 渲染，分组与顺序与 demo 一致；导航标签全部来自 i18n，无硬编码中文。
2. 12 个导航项 en/zh 键齐全且对等；`vue-tsc` 错误恰好是附录 A 的 5 条。
3. 5 条旧路径 redirect 生效，地址栏规范化为新 path。
4. `/console/login` 成功后落 `/console/overview`；`/` 仍是语音前台。
5. 语言切换后刷新保持；`navigator.language` 决定首访语言；ant 内置文案（空态、`a-popconfirm`）随语言变化。
6. `TOKEN_ENFORCED_GLOBS` 内无裸 hex；`tokens.ts` 是 `theme.ts`、less、原生 CSS 三方共同的源。
7. `OverviewView` 每个 KPI 都能指出来源字段；每个未实现项都带 S2/S3 标记且无 mock 数据。
8. `TrafficView` 全程只读；`allocatorMode='off'` 时有状态条；`scheduling.configurable=false` 渲染为只读说明。
9. `npm run build`、`npm run lint`、`npx vitest run`、后端 pytest 全绿。

## 14. 风险与缓解

| 风险 | 缓解 |
|---|---|
| §9.3 的 4 处颜色变化让外壳观感偏移预期 | 步骤 1 结束即走查截图，以 demo 为准比对；变化集中在边框/悬停/侧栏底色，不涉及布局 |
| i18n 分 6–8 个提交期间存在半英半中中间态 | 步骤 4 期间不做人工验收与发布；每批完成后统一走查；对等测试保证任意时刻两语言键集一致 |
| `navKey` 字符串写错导致运行时缺键 | §12 的 navKey 可解析测试 + `missing` 处理器开发期告警 |
| 新端点被后续需求顺手扩成写端点 | router 只注册 `GET` 有测试断言；契约里「无写路径、不记审计」写进 docstring |
| hex 白名单被遗忘收紧，token 源再度漂移 | 附录 B 把 20 个文件与归属子项目写死；白名单「只增不减」有测试；每个子项目的 spec 必须引用该表 |
| 「集群 = profile」被后续当作既定事实 | §6.3 明确标为权宜映射，并列为 S2 必答题 |
| 步骤 0 的基线提交把录音归档半成品固化 | 附录 A 记下 5 条错误作为 S8 的输入；S8 的 spec 必须包含「后端 session-archive 能力已真实存在」这一实测结论 |

## 附录 A：基线 `vue-tsc` 错误清单（固定为 5 条，S8 负责清零）

```
src/api/demo.ts(3,27)                TS2305  '@/features/voice/types' 无导出成员 SessionRecordConfig
src/api/voiceSessions.spec.ts(3,38)  TS2307  找不到模块 './voiceSessions'
src/views/RecordingsView.vue(13,8)   TS2307  找不到模块 '@/api/voiceSessions'
src/views/RecordingsView.vue(17,15)  TS2305  '@/features/voice/types' 无导出成员 SessionRecordConfig
src/views/RecordingsView.vue(77,55)  TS7006  参数 'turn' 隐式 'any'
```

复现命令：`cd console/frontend && npx vue-tsc --noEmit`（当前 `EXIT=2`）。

## 附录 B：裸 hex 技术债表（S1 范围外，随各页重做收紧）

| 文件 | 处数 | 归属子项目 |
|---|---|---|
| `InstancesView.vue` `InstanceCard.vue` `InstanceTrendChart.vue` `TurnLatencyPanel.vue` | 27 | S2 / S3 |
| `ParamsView.vue` `ParamTree.vue` `ParamField.vue` `RuntimeGrid.vue` `ModelRuntimeCard.vue` `FixedField.vue` `EffectBadge.vue` | 35 | S4 |
| `VoicesView.vue` `VoiceLibraryTable.vue` `VoicePicker.vue` `VoiceAudition.vue` `VoiceCreateDialog.vue` | 17 | S6 |
| `LogPanel.vue` `LogAnalysisCard.vue` | 20 | S7 |
| `RecordingsView.vue` `LimitDialog.vue` | 5 | S8 |
| 合计 | 103 | — |

处置规则：每个子项目在重做对应页面时，必须（a）把该页的 hex 收进 `tokens.ts` 并归并近似值，（b）把该文件加入 `TOKEN_ENFORCED_GLOBS`，（c）在提交说明里注明归并了哪些原值。白名单只增不减。
