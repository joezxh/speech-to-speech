# 设计：console 设置页对齐原型（console-refactor-demo.html#/settings）

日期：2026-11-28 · 范围：console 前端 + console 后端 · 状态：**已批准**（用户拍板 A/A/A）

## 意图与动机

`/settings`（前台「设置」，路由 `src/router/index.ts:40-45`）当前实现与原型
`console/design/console-refactor-demo.html#/settings` 的差距不是"少几块卡片"，而是**这一页根本没接通**：

- **结构缺 4 块**：模板说明横幅、热更参数只读表、热更字段编辑卡、底部操作条（重置/保存为模板/应用热更）全无。
- **样式基本失效**：`src/views/SettingsView.vue:81-91` 用的是 `var(--surface)/--border/--muted/--accent)`，
  而 `src/styles/tokens.ts` 里根本没有这些变量（真名是 `--s2s-*`）→ 卡片没有底色、没有边框。
- **开关是隐形的**：`PSwitch.vue` 的根 class 是 `.switch`，但任何样式表里都没定义 `.switch`。
- **后端没有「设置」的存储**：原型把值写 localStorage（`console-refactor-demo.html:2566`）。现有后端
  只有 `session.update`（热更下发）、机器草稿、模板 CRUD、智能设置 —— **「保存后刷新还在」这条链路是断的**。
- **字段元数据只存在于 HTML**：原型的 `PARAM_TEMPLATES`（`console-refactor-demo.html:1504-1533`）带
  type/min/max/step/opts/group/hint/src/platform，而前端 `src/utils/hotParams.ts` 只有 name/patch/catalogKey/label
  → 表单只能全渲染成文本框，select/textarea/switch 全做不出来。

本设计把该页前端逐像素对齐原型，并把设置落库 + 打通前后端读写闭环。

## 目标 / 非目标 / 反目标

**目标**

1. `/settings` 的结构、组件、间距、配色、交互态与原型一致，并保持响应式（≤1100px 两列塌一列）。
2. 后端提供设置的存储与读写（**全局一套**），保存后刷新/换浏览器仍在。
3. 页面所有数据都来自真实后端：字段目录、已存设置、机器实时值、智能设置、模板保存、热更下发。
4. 无占位内容：原型上每一个可交互元素都有真实后端行为。

**非目标**

- 不改 pipeline 与 WS 协议；设置页不做成发布台（发布仍走运维台）。
- **不实现原型的 `SETTINGS_GROUPS`**（llm/voice/call/ui 共 22 项，含 temperature/chat_size/tts_speed/
  denoise/reconnect/lang）。它在原型里是**死代码**（定义于 `console-refactor-demo.html:2530`，
  全文件无任何渲染引用），不在 `/settings` 页面上出现。本设计不把它"补"回来。
- 不动 `console:config` 配置面（那是控制台自己的配置），不动机器草稿语义。
- 不新增前端依赖。

**反目标**

- 不用 localStorage 兜底"看起来能存"——那正是原型的问题。
- 不把字段目录硬编码两份（前端一份、后端一份），必然漂移。后端是唯一真源，前端按返回渲染。
- 不让「应用热更」绕过白名单：`audio.output.voice` / `model` 必须被后端拒掉并在前端灰显。

## 已定决策（用户拍板）

1. **设置存储：全局一套**（方案 A）。新增 `param_front_setting` 表按参数名存一份；机器条只决定
   "实时值从哪台机器读、智能卡的机器上下文、保存为模板时的平台"。
   **注意**：`POST /api/v1/sessions/update` 的 `scope=all` 是"推给所有活跃会话"，链路里没有机器维度
   （`hot_update_service.update` 对 `scope=all` 要求 `target is None`）——所以"选中哪台机器"**不影响**
   热更下发的对象。要把机器纳入下发语义就得改 pipeline，超出本次非目标。
2. **冷参数分组卡照搬原型**：前台面（surface=front）原型渲染为空（冷字段全在 ops 面），本页不出现该区块。
3. **主按钮 = 落库 + 下发串联**（方案 A）：`PUT /api/v1/settings/front` → `POST /api/v1/sessions/update`。
   原型的 `saveSettings()` 就是"写存储 + 下发"两件事一起做；只下发不落库会让
   `param_front_setting` 表永远是空的，"保存后刷新还在"落空。
4. **重复 patch 路径按别名优先消歧**（方案 A）：`init_chat_prompt` 赢 `instructions`、
   `qwen3_tts_speaker` 赢 `voice`。照搬原型（后写覆盖先写）会把用户填的人设冲成空串。
5. **operator 可写设置**（方案 A）：`console:settings:query` / `write` 都是 admin+operator；
   「保存为模板」因需 `console:template:create`（admin-only），对 operator **直接隐藏**。

## 方案取舍（Approaches）

### 1. 设置存哪

- **A 新表 `param_front_setting`（选定）**：键=参数名，值=字符串+类型；读写两个端点；reset=清行回落默认。
  代价：一次迁移 + 一个 router/service/repository。收益：语义清晰，与模板/草稿解耦，可审计。
- B 复用 `param_config`（控制台配置登记表）：键白名单来自 `docs/parameter-catalog.yaml` 的
  `console_parameters` 段（allocator/lb/… 全是**控制台自己**的配置），不含对话参数；扩白名单等于把对话参数
  混进控制台配置面，且 `PUT /api/v1/config` 仅 admin。弃。
- C 复用 `param_machine_draft`（机器草稿）：草稿按键走目录校验（`machine_config_service._validate_patch`），
  `init_chat_prompt`/`voice` 这类热更别名不是目录键会被 400；且草稿语义是"待发布"。弃。

### 2. 字段目录真源放哪

- **A 后端持有、前端只渲染（选定）**：`GET /api/v1/settings/front` 同时返回字段目录（label/hint 是
  i18n key，前端 `t()` 解析）与已存值。后端同时是校验者（类型/范围/枚举）与白名单判定者。
  代价：把原型 `PARAM_TEMPLATES` 的 front 子集搬进 Python。
- B 前端持有（照搬原型）：后端不校验，坏值能存进去；且前后端两份目录必然漂移。弃。
- C 从 `docs/parameter-catalog.yaml` 派生：目录有 type/default/exposure，但**没有** surface/label/hint/src/
  platform 这些"前台面"语义，凑不出原型那张表。弃。

### 3. 热更下发

- **A 复用 `POST /api/v1/sessions/update`（scope=all）**（选定）：前端按目录里的 patch 路径组装，
  后端白名单拒绝的字段在前端灰显（与既有 `HotUpdateSettings.vue:51-54` 的 `whitelisted()` 判定同构）。
- B 后端新端点 `POST /api/v1/settings/front/apply`：能一个事务"存 + 下发"，但下游 pipeline 只认
  session.update，等于造第二条下发链路。弃。

### 4. 智能设置面板

- **A 就地重写 `components/proto/SmartSettingsPanel.vue` 成原型 markup**（选定）：原型 `smartPanel(m, mode)`
  是 front/ops 共用的一段（`console-refactor-demo.html:3326-3355`），DeployView 用的就是同一段；
  重写一处两个页面同时对齐。代价：DeployView 的智能卡外观会一并变化（变的是"更贴原型"）。
- B 在设置页另写一个智能卡组件：DeployView 保持现状。代价：两份近似代码，后续必然漂移。弃。

## 约束

- 前端样式走 `src/styles/prototype.less` + `--s2s-*` token；`src/styles/hex-ban.spec.ts` 禁止裸 hex
  （`src/styles/**` 与 `src/components/proto/**` 在强制清单内）。
- i18n：`src/i18n/i18n.spec.ts` 断言 zh/en 扁平 key 集合完全相同且非空 → 新增 key 两语言必须同步。
- 权限码在 `app/core/permissions.py` 注册，前端 `src/utils/permissions.ts` 是同表镜像
  （`permissions.spec.ts` 拦漂移）。
- 迁移落地后必须跑 `console/backend/scripts/dump_schema_sql.py` 重出 `alembic/sql/*.sql`
  （drift guard：`tests/unit/test_schema_sql.py`），不得手改 SQL 文件。
- 后端成功信封 `{code,message,data}`（`app/schemas/common.py:18`）；审计只记字段名不记值。

## 后端设计（console/backend）

### 1. 迁移 0022：`param_front_setting`

| 列 | 类型 | 说明 |
|---|---|---|
| `id` | Integer PK | |
| `config_key` | String(128) NOT NULL UNIQUE | 参数名（`thresh` / `min_silence_ms` / …） |
| `value` | Text NOT NULL default `''` | 值统一存字符串（与 `param_config` 同口径） |
| `value_type` | String(16) NOT NULL default `'str'` | `str`/`int`/`float`/`bool` |
| `updated_by` | String(64) NOT NULL default `''` | |
| `updated_at` | DateTime(tz) NOT NULL | |

**无 `machine_id` 维度**（用户拍板 A：全局一套）。

模型 `app/models/front_setting.py::ParamFrontSetting`，并注册进 `app/models/__init__.py`
（否则 `create_all` 不建表、drift guard 报漂移）。

### 2. 字段目录 `app/services/front_setting_catalog.py::FIELD_CATALOG`

镜像原型 `PARAM_TEMPLATES` 的 front 子集（`console-refactor-demo.html:1504-1533`，surface=front|both），共 7 条：

| key | group | type | 约束 | 默认 | patch | 白名单可下发 | catalogKey |
|---|---|---|---|---|---|---|---|
| `thresh` | vad | number | 0–1，step 0.05 | 0.6 | `audio.input.turn_detection.threshold` | ✅ | `vad.thresh` |
| `min_silence_ms` | vad | number | 0–5000，step 50 | 450 | `audio.input.turn_detection.silence_duration_ms` | ✅ | `vad.min_silence_ms` |
| `qwen3_asr_language` | stt | select | `auto`/`zh`/`en` | `auto` | `audio.input.transcription.language` | ✅ | `stt.qwen3_asr_language` |
| `init_chat_prompt` | llm | textarea | ≤2000 字 | `''` | `instructions` | ✅ | `llm.init_chat_prompt` |
| `instructions` | llm | textarea | ≤2000 字 | `''` | `instructions` | ✅ | `llm.instructions` |
| `qwen3_tts_speaker` | tts | select | 音色库 | `''` | `audio.output.voice` | ❌ | `tts.qwen3_tts_speaker` |
| `voice` | tts | select | 音色库 | `''` | `audio.output.voice` | ❌ | `tts.voice` |

每条目录项形如：

```
{key, group, type, hot, patch, catalogKey, src, def, min, max, step, opts,
 labelKey, hintKey, platform}
```

- `labelKey`/`hintKey` 是 **i18n key**（前端 `t()` 解析），文案取自原型字典
  （`tpl.field.*` / `settings.f.*`）。**key 字面量必须是根级形态**——前端 i18n 按模块文件在根级合并
  （`src/i18n/locales/zh-CN/index.ts:25` 是 `{ nav, shell, …, settings }` 的平铺），
  所以后端发 `tpl.field.thresh` 就得有一个根级 `tpl` 模块，不能塞进 `settings` 模块变成
  `settings.tpl.field.thresh`（那会与后端契约不一致，页面渲染出 key 原文）。
- `opts` 为固定列表或 `"voices"`（前端用 `GET /api/v1/voices` 中 `status==='ready'` 的 id 填充）。
- `hot` 恒为 true（front 面全是热更字段）。**能否即时下发**由后端按 `hot_update_service.WHITELIST` 判定，
  不在目录里重复编码 —— 新增 `hot_update_service.hot_whitelisted(path) -> bool`，与 `prune()` 同源，
  避免再抄一份白名单树。
- `src` 取原型的目录溯源串（如 `§2.2 · vad_arguments.py:22`）。

### 2.5 目录内部的重复 patch 路径（原型照搬带来的坑）

原型 7 条里有**两组共用同一条 patch path**（`console-refactor-demo.html:1518-1533`）：

| patch | 命中字段 |
|---|---|
| `instructions` | `init_chat_prompt`、`instructions` |
| `audio.output.voice` | `qwen3_tts_speaker`、`voice` |

`buildSessionPatch` 往嵌套对象里写，**后写覆盖先写**（原型的 `saveSettings` 同样如此）。
照搬的结果：用户改 `init_chat_prompt` 点了「应用热更」，实际下发的是 `instructions` 的值；
若 `instructions` 为空，用户刚填的人设会被空串覆盖 —— 这是真 bug，不能照搬。

**处理（用户已拍板 A）**：下发时按**别名优先**规则消歧——同一条 patch 内，
`init_chat_prompt` 赢 `instructions`、`qwen3_tts_speaker` 赢 `voice`
（前者是"专用的系统人设/部署音色"，后者是"客户端首帧可覆盖的通用槽位"，专用值优先更符合语义）。
两个字段在表单里都保留可编辑（与原型一致），但下发前若同组两值不同则提示"该项被覆盖"。
「保存为模板」仍按 7 条全量快照（模板存的是字段值，不是 patch）。

### 3. 端点 `app/routers/settings.py`（prefix `/api/v1/settings`）

| 方法 | 路径 | 权限 | 请求 | 响应 `data` |
|---|---|---|---|---|
| GET | `/api/v1/settings/front` | `console:settings:query` | – | `{fields:[…], values:{k:v}, defaults:{k:v}, updatedAt, updatedBy}` |
| PUT | `/api/v1/settings/front` | `console:settings:write` | `{values:{k:v}}` | `{values, updatedAt, updatedBy, applied:[k]}` |
| POST | `/api/v1/settings/front/reset` | `console:settings:write` | – | `{values:defaults, updatedAt, updatedBy}` |

- `values` = 已存值 ∪ 默认值（未存过的回落默认 → 前端永远拿到完整一份）。
- PUT 语义：**部分 upsert**。只写传入的键；值为 `null` 视为"回落默认"→ 删该行。
- **请求体的值类型是 `Any`**（`values: dict[str, Any]`），由服务端按目录类型强转——沿用既有约定
  （`app/schemas/config.py:14-17` + `app/services/config_service.py:49-67` 的 `coerce()`）。
  所以"类型不符 400"= **强转失败**（给 number 字段传 `"abc"`、给字符串字段传 list）。
  `value_type` 列由**服务端按目录推导**写入，不由客户端声明。
  前端 number 字段发 JSON number、string 字段发字符串。
- 校验清单：未知键 400；强转失败 400；超 min/max 400；枚举外 400；textarea 超 2000 字 400
  （对应原型 `set.err.prompt`）。**任一项非法整批不落库**（与 `config_service.update` 同口径）。
- 审计：action `settings.front.update` / `settings.front.reset`，`fields` 只记字段名不记值。
- `applied` = 本次落库且白名单可下发的**键名清单**（按 key 计，不按 patch 计）。
- **reset 的返回**：`values` 回落默认；`updatedAt` / `updatedBy` 返回 `null`
  ——重置即"删光所有行"，没有存值可读时间戳；重置这个动作本身记在审计里。
  （读取时若表为空，同样返回 `updatedAt: null`。）

新增权限码（`app/core/permissions.py` + 前端镜像 `src/utils/permissions.ts`）：

- `console:settings:query` = admin + operator
- `console:settings:write` = admin + operator

> 我的判断：设置页是前台日常调参面，与 `console:session:write`（operator 可写）同级；模板写
> （`console:template:create`）与机器写才是 admin。若要更严，把 write 改 admin 只是一行。

### 4. 前端所需的其他既有端点（本次不改）

| 用途 | 端点 |
|---|---|
| 机器条 | `GET /api/v1/machines` |
| 实时值（actual/expected） | `GET /api/v1/machines/{id}/config` |
| 智能设置 | `POST /api/v1/smart-settings/fetch` · `/analyze` |
| 音色下拉 | `GET /api/v1/voices`（取 `status==='ready'`） |
| 热更下发 | `POST /api/v1/sessions/update` |
| 保存为模板 | `POST /api/v1/templates`（`effect='runtime'`） |

### 5. 防漂移

`template_service.HOT_FIELDS`（模板侧的别名表）与新的 `FIELD_CATALOG` 有重叠键。加一条单测：
两表共享键的 patch 路径必须相等；`FIELD_CATALOG` 里标为可下发的 path 必须能通过
`hot_update_service.prune()`，标为不可下发的必须被 `prune()` 具名拒绝。

## 前端设计（console/frontend）

### 1. 页面骨架（重写 `src/views/SettingsView.vue`）

按原型 `renderSettings()`（`console-refactor-demo.html:4383-4426`）顺序，根容器
`.sv-page{display:grid;gap:16px}`：

```
1. .page-head            h1 = nav.settings ；p = set.page.desc
2. .card (padding 10px 14px) > .chips > button.chip
                          = PDot + machineId + 平台小字(tpl.plat.*)，选中 .chip.active
3. .card.tpl-banner      左：tpl.title(strong) + tpl.desc(.muted)；右：.tag.ok = tpl.source
4. 智能设置卡            <SmartSettingsPanel>（见 §4）
5. .card 热更只读表       h3 = tpl.live.title + .hint(tpl.live.hint {n}) + .tag.ok(tpl.effect.runtime)
                          .tscroll > table.tbl 4 列(tpl.live.col.field/value/patch/src)
                          底部 .note = tpl.live.note
6. .card 热更字段编辑卡    h3 = tpl.live.edit + .hint(tpl.live.edit.hint)；.set-grid 内按 type 渲染
7. .card.set-actions     左 .muted = tpl.save.hint；右 .btn 重置 / .btn 保存为模板 / .btn.primary 应用热更
```

> 原型 front 面的冷参数分组卡渲染为空 → 本页不出现该区块（与原型一致）。

### 2. 字段渲染（新增 `src/components/proto/SettingField.vue`）

复刻原型 `renderSettingField()`（`console-refactor-demo.html:4352-4382`）：

| type | 控件 | 附加 |
|---|---|---|
| `switch` | `PSwitch`（补 `.switch` 样式） | `aria-checked` / `role="switch"` |
| `textarea` | `textarea.fin` | `.counter` 字数（右下 faint 11px）；`.sfield.ta-wrap` 跨两列 |
| `select` | `select.fin` | `opts==='voices'` 时用音色库 id 填充 |
| `number` | `input[type=number]` | 带 min/max/step |
| `text` | `input.fin` | |

- 标签 `.sfield > label`（12.5px muted）；提示 `.fhint`（faint）+ `.tpl-src`（mono 10.5px，目录溯源）。
- 值来源优先级：**已存值 → 默认值**；编辑落在页面本地副本 `draft`，不直接改 store。
- 非白名单字段（`audio.output.voice`）沿用既有 `settings.hotCold` 文案灰显，标「非白名单」。

### 3. 样式补齐（`src/styles/prototype.less`）

**先说不动什么**（避免外溢到别的页面）：`.fin` / `.field` / `.fhint` **已存在**
（`src/styles/prototype.less:988-1016`）且与原型基本一致，且被 `InstancesView.vue` / `HistoryView.vue` /
`MachineFormModal.vue` / `SessionRecordDetail.vue` 在用 —— **不重定义、不改它们的观感**。
机器条卡片原型是内联 `padding:10px 14px`，而全局 `.card` 是 `16px 18px` → 用修饰类 `.card--bar`，
不改 `.card` 本身。

只新增以下类（全部用 `var(--s2s-*)` / `var(--voice-*)`，禁裸 hex）：

```
.set-grid      display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px 18px;
              @media (max-width:1100px){ .set-grid{ grid-template-columns:1fr; } }
.sfield       min-width:0;
.sfield > label, .sfield .f-lbl  display:block; font-size:12.5px; color:var(--s2s-color-muted); margin-bottom:6px;
.sfield.sw .switch  align-self:flex-start;
.sfield.ta-wrap      grid-column:span 2;
textarea.fin  resize:vertical; min-height:96px; font-family:var(--s2s-font-mono); font-size:12px; line-height:1.6;
.counter      text-align:right; font-size:11px; color:var(--s2s-color-faint); margin-top:4px;
              font-variant-numeric:tabular-nums;
.set-actions  display:flex; align-items:center; gap:10px;
              @media (max-width:700px){ .set-actions{ flex-wrap:wrap; } }
.tpl-banner   display:flex; align-items:center; justify-content:space-between; gap:16px;
              border-left:3px solid var(--s2s-color-accent);
              @media (max-width:1100px){ .tpl-banner{ flex-direction:column; align-items:flex-start; } }
.tpl-banner p margin:4px 0 0; font-size:12px;
.tpl-src      display:block; font-size:10.5px; color:var(--s2s-color-faint); margin-top:3px;
              font-family:var(--s2s-font-mono);
.muted        color:var(--s2s-color-muted); font-size:12.5px;
.card--bar    padding:10px 14px;
.switch       width:36px; height:20px; border-radius:10px; background:var(--voice-surface-2);
              border:1px solid var(--voice-border); position:relative; cursor:pointer;
              transition:.2s; flex:0 0 36px; padding:0;
.switch::after        content:''; position:absolute; top:2px; left:2px; width:14px; height:14px;
              border-radius:50%; background:var(--voice-dim); transition:.2s;
.switch.on    background:color-mix(in srgb, var(--voice-accent) 35%, transparent);
              border-color:var(--voice-accent);
.switch.on::after  left:18px; background:var(--voice-accent);
.switch:focus-visible  outline:2px solid var(--s2s-color-accent); outline-offset:2px;
.page-head    margin:0 0 18px;
.page-head h1 margin:0 0 6px; font-size:20px;
.page-head p  margin:0; color:var(--s2s-color-muted); font-size:13px;
```

`--voice-*` 由 `src/styles/applyTokens.ts` 已注入的 voice token 提供，与原型 `.switch` 同源。

**`.switch` 是全局类**（`PSwitch.vue` 的根 class）——补上之后任何用 `PSwitch` 的页面同时从"隐形"变可见。
`PSwitch` 顺带改造为 `<button type="button" role="switch" :aria-checked="...">`（现在是个不可聚焦的
`<div>`，键盘不可达）。

`.muted` / `.page-head` 是新增全局类：已有页面若用了同名 class，其 scoped 样式特异性更高，不会被覆盖。

### 4. 智能设置卡（重写 `src/components/proto/SmartSettingsPanel.vue`）

按原型 `smartPanel(m, mode)`（`console-refactor-demo.html:3326-3355`）的 markup：

```
.card
├ h3  smart.title + .hint(smart.hint {machine}) + .tag.accent "AI"
├ .rowline  [.btn.sm smart.fetch] [.muted smart.fetch.hint] [.spacer] [.tag.ok smart.fetched]
├ 已拉取时：.tscroll > table.tbl 4 列(field/actual/effect/src) + pre.smart-log
├ .field    label smart.fault + textarea.fin(rows=2, placeholder smart.fault.ph)
├ .rowline  [.btn.primary.sm smart.analyze]（busy 时加 .muted smart.busy）
└ 有结果时：p.note(summary) + 每条推荐一个 .rec > .rec-top(rname.mono / from→to / .btn.sm smart.apply) + .p-risk(reason)
```

数据来源与现状一致（`useSmartSettingsStore` → `/smart-settings/fetch`、`/analyze`），
`apply` 事件改为向上抛 `(key, value)`，由设置页写入 `draft`（不自动下发，与原型 `smartApply` 一致）。

**行集规则**：
- `mode='front'`：行集 = **前台 7 条字段**（与原型 `templateFor('front')` 一致）。值取自
  `/smart-settings/fetch` 返回的 `params`（那是整份机器目录，可能几百行），按 `catalogKey` 精确匹配、
  失败再按后缀匹配（`vad.min_silence_ms` → `min_silence_ms`）。
- `mode='deploy'`：维持现状 —— 渲染全部 fetched params（原型 ops 面是 18 条模板字段，本页不涉及）。
- **推荐 key 的归一**：`analyze` 可能返回目录键形态（`vad.min_silence_ms`）或别名（`min_silence_ms`），
  也可能返回**不在前台目录里的键**（规则兜底会返回 `num_pipelines`，LLM 可能返回任意目录键）。
  归一顺序：先按别名精确匹配 → 再按目录键后缀匹配 → 都不中则视为**目录外**。
  **目录外的推荐只读展示，不给「应用」按钮**（否则点了会静默丢失，用户看不见）。
- `mode='front'` 的推荐若归一后命中目录，则「应用」写 `draft[key] = rec.to`。

### 5. i18n

新增**根级** locale 模块文件（前端 i18n 在根级合并，`src/i18n/locales/zh-CN/index.ts:25`）：

| 文件 | 内容 | 产出的 key |
|---|---|---|
| `src/i18n/locales/{zh-CN,en-US}/tpl.ts`（新建） | 模板/热更相关文案 | `tpl.*` |
| `src/i18n/locales/{zh-CN,en-US}/set.ts`（新建） | 设置页专用文案 | `set.*` |
| `src/i18n/locales/{zh-CN,en-US}/settings.ts`（改） | 补 `f` 子对象 | `settings.f.*` |

并在两个 `index.ts` 里注册 `tpl` / `set`（**不改已有模块的导出形状**，避免影响其它 key 的路径）。

要补的 key：

- `set.page.desc` · `set.reset` · `set.reset.body` · `set.err.prompt`
- `tpl.title` · `tpl.desc` · `tpl.source` · `tpl.source.front` · `tpl.effect.runtime` · `tpl.hot` · `tpl.restart`
- `tpl.plat.{gpu,npu,amd,cpu}` · `tpl.col.{field,actual,effect}`
- `tpl.live.{title,hint,note,edit,edit.hint}` + `tpl.live.col.{field,value,patch,src}`
- `tpl.field.*`（7 个前台字段的 label + hint）
- `settings.f.init_chat_prompt` · `settings.f.instructions` · `settings.f.voice`
  （**这三个 key 前端目前不存在**，原型里是根级 `settings.f.*`，需要新建）
- `tpl.save` · `tpl.save.hint` · `tpl.save.as` · `tpl.save.as.hint` · `tpl.save.as.desc`
- `toast.tpl.hot` · `toast.set.saved` · `toast.set.reset`

文案**逐字取自原型字典**（en 行 640–760 / zh 行 930–1130），保证与原型一致。
注：原型里 `tpl.effect.runtime` 未定义（真机上会显示 key 本身），本设计补上
「对话态热更 / Conversation hot」。

### 6. 数据流

新增 `src/api/settings.ts`：

```
settingsApi.getFront():  Promise<FrontSettingsSnapshot>
settingsApi.putFront(values): Promise<{values, applied, updatedAt, updatedBy}>
settingsApi.resetFront(): Promise<{values, updatedAt, updatedBy}>
```

新增 `src/stores/settings.ts`（`useFrontSettingsStore`）：
state `{fields, values, defaults, loading, saving, error}`；actions `load()` / `save(values)` / `reset()`。

页面本地状态：`selectedMachine`（支持 `?machine=` 深链，默认第一台）、`draft`（表单副本）。

| 交互 | 行为 |
|---|---|
| 智能推荐「应用」 | 写 `draft[key] = rec.to`，不自动下发 |
| 「应用热更」（主按钮） | 落库 + 下发串联（见 §6.1）：`PUT /api/v1/settings/front` → `POST /api/v1/sessions/update` |
| 「保存为模板」 | `templatesApi.create({name, effect:'runtime', platform:选中机器平台, status:'draft', fields:7 条 {key,value,patch}})` → toast；**需 `console:template:create`（admin）**，operator 面前按权限隐藏（见 §6.2） |
| 「重置」 | `ConfirmDialog` 确认（文案 `set.reset` / `set.reset.body`）→ `settingsApi.resetFront()` → 表单回落默认 → toast `toast.set.reset` |

音色下拉的数据源：`GET /api/v1/voices?status=ready&pageSize=200`
（`/voices` 是分页的，默认 pageSize=50，不显式传大页会只拿到前 50 条）。

`templatesApi.create` 的 `fields` 类型要从 `Array<{key,value}>` 扩成
`Array<{key, value, patch?, source?}>`（后端 `TemplateFieldIn` 接受 `patch`/`source`，
`console/backend/app/schemas/template.py:8-14`）。

### 6.1 主按钮的语义（用户已拍板 A）

原型的 `saveSettings()`（`console-refactor-demo.html:4442-4461`）**同时**做两件事：
写 `state.settings`（localStorage）+ 组 hot patch 并弹 `toast.tpl.hot {n}`。
真机上只有三个按钮（重置 / 保存为模板 / 应用热更），其中"应用热更"是唯一的保存入口。

若照搬"主按钮只下发不落库"，`param_front_setting` 表永远为空 → 本设计的第一目标
（保存后刷新/换浏览器仍在）直接落空。所以主按钮必须是**串联两步**：

```
PUT /api/v1/settings/front   （落库，失败即中止）
  → POST /api/v1/sessions/update （下发；非白名单字段被白名单拒绝 → 记 rejected 并提示）
  → toast：落库成功 toast.set.saved；下发成功 toast.tpl.hot {n}
```

部分失败语义：落库成功、下发失败（502 pipeline 不可达等）→ **表已更新**（这是"设置"的真相），
页面提示"已保存，下发失败：{reason}"，不回滚。

### 6.2 权限矩阵（用户已拍板 A）

两个新码的定位：

| 码 | 建议 | 理由 |
|---|---|---|
| `console:settings:query` | admin + operator | 读是所有登录用户的日常操作 |
| `console:settings:write` | admin + operator | 设置页是前台日常调参面，与 `console:session:write`（operator 可写）同级 |

**但 `POST /api/v1/templates` 需要 `console:template:create`（仅 admin）**
（`console/backend/app/core/permissions.py:50`）—— 所以 operator 点「保存为模板」必然 403。
前端已有成熟门禁范式（`v-if="auth.hasPermission('console:template:create')"`，
`console/frontend/src/components/proto/TemplatePanel.vue:142`）。

因此 operator 面前「保存为模板」必须**显式处理**，否则就是一个必然 403 的死按钮。三种处理：

- **隐藏**（推荐）：`v-if` 门禁，operator 看不到这个按钮；底栏只剩「重置 / 应用热更」。
- 置灰 + tooltip 说明"需要管理员权限"。
- 放宽 `console:template:create` 给 operator（会改动模板域的权限面，影响部署页，超出本次范围）。

### 7. 组件增删

| 动作 | 文件 |
|---|---|
| 新增 | `src/components/proto/SettingField.vue` · `src/api/settings.ts` · `src/stores/settings.ts` |
| 重写 | `src/views/SettingsView.vue` · `src/components/proto/SmartSettingsPanel.vue` |
| 删除 | `src/components/proto/HotUpdateSettings.vue`（重写后仅 `SettingsView` 引用它，已确认无其它引用） |
| 精简 | `src/utils/hotParams.ts`：`HOT_PARAMS` 静态表删除（真源移到后端），保留 `isHotPath`（白名单镜像）与 `buildSessionPatch`（改为接受后端目录形状），`actualForParam` 保留 |

### 8. 响应式

- `.set-grid` ≤1100px 塌一列（与原型同断点）。
- `.tpl-banner` ≤1100px 改纵向堆叠（新增一条 media query）。
- `.set-actions` ≤700px 允许换行。
- 机器条 `.chips` 已 `flex-wrap: wrap`；`.card h3` 已 `flex-wrap: wrap`。

### 9. 顺带修的既有缺陷

`src/components/proto/TemplatePanel.vue:163` 用 `t('templates.' + reason)`，而
`src/views/templatePanel.viewmodel.ts:29-30` 返回的是 `'panel.check.platformMismatch'` 形状
→ 拼出 `templates.panel.check.platformMismatch` 这个不存在的 key，界面直接显示 key 原文。
改为返回 `templates.panel.checkPlatformMismatch` 形状（与 `templates.ts` 里已有的
`checkPlatformMismatch` / `checkVramShort` / `checkVramUnknown` 对齐）。
该缺陷在「设置 → 保存为模板 → 硬件校验」链路上，顺手修。

## 测试

**后端**

- `tests/integration/test_settings_api.py`（新建）：GET 返回 7 条字段目录 + 默认值；
  PUT 合法值落库并审计（只记键名）；PUT 非法类型 / 超范围 / 未知键 → 400 且**整批不落库**；
  `null` 值删行回落默认；reset 清行回落默认；operator 可读可写。
- `tests/unit/test_front_setting_catalog.py`（新建）：目录 7 条与原型一致；共享键的 patch 路径与
  `template_service.HOT_FIELDS` 相等；标为可下发的 path 能通过 `hot_update_service.prune()`，
  标为不可下发的被 `prune()` 具名拒绝。
- 迁移测试仿 `console/backend/tests/unit/test_migration_0006_clusters.py`（**注意是 `tests/unit/`，
  不是 `tests/integration/`**）；跑完 `scripts/dump_schema_sql.py` 后 `tests/unit/test_schema_sql.py` 必须绿。
- `tests/unit/test_permissions.py` 补两个新码（后端那份是精确集合断言）。
- **两条会因本设计"因无关原因"变红的既有闸门，必须一并处理**（否则实现者会误以为自己写错了）：
  1. `console/backend/app/models/comments.py` 的 `TABLE_COMMENTS` / `COLUMN_COMMENTS`
     必须为新表与 6 个列补中文注释（`tests/unit/test_comments.py:23-34` 要求与
     `Base.metadata` 的表/列一一对应且含中文）。
  2. `console/frontend/src/utils/permissions.spec.ts:26-54` 断言 `PERMISSION_ROLES` 的 key 集合
     **完全等于**一份写死的列表 —— 往 `src/utils/permissions.ts` 加两个新码后必须同步该列表。

**前端**

- `src/views/settings.viewmodel.spec.ts`（新建）：字段目录 → 表单模型（类型分发、枚举、默认值回落、
  平台过滤）；收集表单 → patch；非白名单字段被拒；重复 patch 的消歧规则；2000 字上限。
- `src/stores/settings.spec.ts`（新建）：`load` / `save` / `reset` 三条动作。
- `src/i18n/i18n.spec.ts` 键一致性保持绿（新增 `tpl` / `set` 两个根级模块后，
  两个 locale 的扁平 key 集合仍必须完全相同）；`src/styles/hex-ban.spec.ts` 保持绿。
- `src/utils/hotParams.spec.ts` 随 `HOT_PARAMS` 删除而改写（`buildSessionPatch` 改吃后端目录形状）。

## 留给实现者的裁量

- 「实时值」的取值优先级：机器 `actual` → `expected` → 已存设置 → 默认值。
  我倾向 `actual → expected → 已存 → 默认`（机器上真跑的值优先于设置里的目标值）。
- 音色下拉的空态文案，以及是否允许"不选音色"。
- 「保存为模板」用现有 `TemplatePanel` 的保存表单，还是按原型做独立轻量弹窗（原型是独立 modal）。
- 机器为空（无机器 / 加载失败）时，各区块的空态展示文案。
- `param_front_setting.value` 是否要拆 `value_json`（本设计按字符串存，与 `param_config` 一致）。
