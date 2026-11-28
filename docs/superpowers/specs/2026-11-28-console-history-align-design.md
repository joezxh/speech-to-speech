# 设计：console 会话历史页对齐原型（console-refactor-demo.html#/history）

日期：2026-11-28 · 范围：console 前端 + console 后端 · 状态：待批准

## 意图与动机

`/history` 会话历史页当前实现相对原型 `console/design/console-refactor-demo.html#/history`
被裁剪过多（KPI 口径、筛选维度、表列、消息面板、行内操作均缺）。本设计把该页
**完全对齐原型**，前端与后端一起改。

## 目标 / 非目标 / 反目标

- **目标**
  - 历史页结构、列、筛选、KPI、操作与原型一一对应。
  - 消息粒度具备原型的 STT/TTS 状态与时长字段（真实落库）。
  - 详情改为表格下方页内展开消息面板（对齐原型），删除 `/history/:id` 深链。
- **非目标**
  - 不做 live（进行中会话）状态：没有现成的活跃会话数据源，DB 只有 done/failed。
  - 不改对话页右侧「会话记录」面板（`SessionLogPanel`）的交互，只保证 store 兼容。
  - 不引入前端全量分页；保留后端分页（单会话消息可能数百行，SQL 层分页是既有约束）。
- **反目标**
  - 不产生死链：删除 `/history/:id` 时同步清理路由与视图文件。
  - 不破坏现有会话保存链路（POST /session-records 仍由 stop() 调用）。

## 已定决策（用户拍板）

1. **消息级 STT/TTS 状态 + 时长：加列**（方案 A）——迁移 0020，不做近似推导列。
2. **详情交互：删 `/history/:id` 深链，改页内展开**（方案 A），行选中高亮。
3. **live 口径：砍掉**（agent 拍板）——KPI 用 总数/正常/失败/平均TTFT 四卡，保持原型 g4 网格。

## 方案取舍（Approaches）

- **消息字段**：A 加列（真实数据、可过滤可展示，需迁移 + 保存链路补数） vs
  B 近似推导（零迁移，但状态列与原型有出入、历史数据无时长）。**选 A**。
- **详情**：A 页内展开（对齐原型） vs B 深链+页内展开并存（保底但多一条路由）。
  **选 A**；用户明确选了删深链。

## 后端设计（console/backend）

### 1. 迁移 0020 + 实体

`param_session_message` 加两列（SQLite/Postgres 通用 `ALTER TABLE ADD COLUMN`，
带 server_default 保证存量行可用）：

- `status` String(16) NOT NULL default `'ok'` —— 用户行=STT 结果，助手行=TTS 结果，枚举 `ok|fail`
- `duration_ms` Integer NOT NULL default `0` —— 该条语音时长（毫秒）

同步更新 `alembic/sql/init-sqlite.sql` / `init-postgresql.sql` —— 这两个文件是
`scripts/dump_schema_sql.py` 的**生成物**，有 drift-guard 测试
（`tests/unit/test_schema_sql.py`）把关；0020 落地后必须**跑生成脚本重出**，
不得手改 SQL 文件。模型 `ParamSessionMessage` 补两列。

### 2. 保存链路补数据（`session_record_service.save_record`）

`SessionMessageIn` 加 `status: str = "ok"`（校验 `ok|fail`）、`durationMs: int = 0`（ge=0）。
前端保存时计算（见前端设计 §3）；后端只校验枚举与长度，不二次统计（沿用既有约束）。

**builder check 修正**：现链路 `toSavePayload` 先丢弃空文本行（`entries.filter(text !== '')`），
STT/TTS 失败行根本进不了保存载荷，status='fail' 会成死代码。改为对齐原型保留失败行：
保留「text 非空」**或**「user 行带 audio」（STT 失败=有原音无转写）**或**
「assistant 行带 latency」（TTS 失败=无文本有延迟记录）的行；纯空占位行仍丢弃。
`VoiceView.vue` 的 `messages.length === 0` 兜底守卫不变（失败行也在 messages 里）。
store 测试 "drops empty lines" 断言同步改。

### 3. 列表行补 消息数 + 转写摘录

`list_records` 在取到当页 rows 后，对当页 record ids 批量查
`param_session_message(session_id IN …)`，组装：

- `messageCount`：行数
- `excerpt`：各行 content 以 ` · ` 连接后截 90 字符（对齐原型 `histRowsHtml`）

`_out(row)` 增加 `messageCount`、`excerpt` 两键，**始终返回**（列表与详情一致，
详情的 `n 条消息` 也用同源数据）；with_messages 只额外带 `messages` 数组。

### 3.5 关键词 q 扩面（对齐原型占位符）

现有 `q` 只匹配 title/note/pipeline_session_id；原型关键词覆盖 ID/实例/节点/转写。
`q` 扩为：`pipeline_session_id`（会话 ID）、`instance_id`、`node` 加
`param_session_message.content` 的 EXISTS 子查询（搜转写原文，非 90 字摘录）。
消息表规模受控（每会话数十行），EXISTS 走 `session_id` 外键索引可接受。

### 4. 筛选参数

- `inst`：`instance_id == inst OR node == inst`（原型实例下拉是 `inst` 维度）。
- `range`：`all|today|24h|7d`，后端按 UTC now 折算 `since`；`today` = 当日 00:00 起。
  与既有 `from/to`（YYYY-MM-DD）并存，`from/to` 优先级不变。
- 新端点 `GET /api/v1/session-records/instances`：distinct instance_id+node 去重清单
  （给实例下拉；只查非空值）。权限 `console:session:query`。

### 5. stats 补平均 TTFT

`stats()` 增加 `avgTtfaMs`（非空 `ttfa_ms` 的均值，无则 0）。既有键全部保留
（对话页共用）。

### 6. 消息删除/清空联动轮数

- `delete_message`：删后重算 `record.turns = count(role=='assistant')`（对齐原型删消息联动 turns）。
  `duration_ms` 是墙钟差，不改。
- `clear_messages`：`record.turns = 0`。
- `update_message`：`status` 不在编辑时重算——`SessionMessageUpdate.content` 有
  `min_length=1`，编辑永远产出非空内容，fail 分支不可达（builder check 证实）；
  编辑保持原 status 不动。tool 行同理不参与状态重算（默认 'ok'）。

### 7. 消息行出参

`_out` 的 messages 行、`update_message` 返回体补 `status`、`durationMs`。

## 前端设计（console/frontend）

### 1. `HistoryView.vue` 按 `renderHistory` 重写

- **KPI g4**：`总数 / 正常(done) / 失败 / 平均TTFT(ms)`（`stats.avgTtfaMs`）。
- **筛选卡**：关键词（占位符=ID/实例/节点/转写）、状态下拉(all/done/failed)、
  实例下拉(all + `/instances`)、范围下拉(all/today/24h/7d)、Query+Reset、
  右侧计数 `n 条` 与选中条（`已选 n` + 删除所选）。回车=Query，Reset 清空全部筛选。
- **表列（11 列）**：复选、Session ID(=记录 id，mono)、开始时间(createdAt)、
  实例 · 节点(`instanceId · node`)、转写摘录(excerpt, clip)、轮数、消息数、
  语音时长(s)、TTFT(ms)、状态徽章(done/failed)、操作（查看消息 + 删除）。
- **行交互**：点行/查看消息 → 页内展开消息面板并高亮该行；再点同一行收起。
- **消息面板（表格下方 card）**：标题=会话 ID + `n 条消息` + 清空全部消息(danger)；
  面板内消息关键词过滤（前端本地过滤，匹配 id/role/type/content）；
  列：消息ID(ordinal 序号 mono)、角色(调用者/助手)、类型(ASR/回复)、内容、时间、
  状态旗标(ok/fail)、操作（删除）。删除/清空走既有 store 方法，成功后刷新当前页
  （行摘要与消息数联动）。
- **分页**：保留后端分页，样式改原型 `‹ 上一页 · Page n of m · 下一页 ›`。

### 2. 路由清理

- 删 `router/index.ts` 的 `history/:id` 记录与 `views/HistoryDetailView.vue`；
  `router.spec.ts` 同步。
- 深链不做兼容重定向（用户拍板 A）。

### 3. store 与 API（`sessionRecords.ts` / `stores/sessionRecords.ts`）

- `SessionRecordRow` 加 `messageCount: number`、`excerpt: string`；
  `SessionMessageRow` 加 `status: 'ok'|'fail'`、`durationMs: number`；
  `SessionRecordStats` 加 `avgTtfaMs`；`SessionRecordQuery` 加 `inst?: string`、`range?: string`。
- `SessionSavePayload.messages` 行加 `status?`、`durationMs?`。
- filters 加 `inst`、`range`；新增 `instances` 拉取方法。
- 消息删除/清空后同步更新 rows 里对应行的 `messageCount`/`excerpt`（本地重算）。
- 对话页 `SessionLogPanel` 不改交互；保存侧见下。

### 4. 保存链路（`toSavePayload`）

- 用户行：`status = content 非空 ? 'ok' : 'fail'`（STT 失败=有 audio 无转写，
  该行现在**会被保留**，见后端 §2）；
  `durationMs = audio.durationMs ?? 0`（WS 传输下的用户行带 `TranscriptAudio.durationMs`，已核实存在）。
- 助手行：`status = content 非空且非 interrupted ? 'ok' : 'fail'`；
  `durationMs = round(latency.e2e_s * 1000)`（latency 缺失则 0）。
- tool 行：`status='ok'`、`durationMs=0`。
- 存量数据（迁移前保存的会话）：`status='ok'`、`durationMs=0`，前端展示时
  durationMs<=0 显示 `—`。

### 5. i18n

`en-US` 与 `zh-CN`（23 个模块文件中含 sessions.* 的那个，两语言同改）补 `hist.*`
键组，文案取自 demo 的 en/zh 字典（demo 内已有现成翻译，含删除确认、toast、
分页、筛选占位符等）。`i18n.spec.ts` 的键一致性校验必须保持绿。

## 测试

- 后端：`tests/integration/test_session_records_api.py` 补
  inst/range 筛选、q 搜转写原文、excerpt/messageCount、stats.avgTtfaMs、
  保存带 status/durationMs、删消息联动 turns、clear 清零 turns；
  迁移测试模仿 `test_migration_0006_clusters.py`（programmatic alembic 升级）；
  `test_schema_sql.py`（drift guard）在重跑生成脚本后必须绿。
- 前端：HistoryView 组件测试（KPI 渲染、筛选提交参数、展开面板、删消息调用，
  无先例需新建）；`stores/sessionRecords.spec.ts` 的 toSavePayload 失败行保留
  断言改写；`router.spec.ts` 删深链断言；`i18n/i18n.spec.ts` 键一致性保持绿；
  既有会话相关测试回归。

## 留给实现者的裁量

- excerpt 截断按字符还是按显示宽度（原型 slice(0,90)）——按字符即可。
- 消息面板内本地过滤的具体匹配字段组合。
- `GET /instances` 返回结构（`[{instanceId, node}]` 或去重字符串清单）二选一，
  倾向前者，下拉项显示 `instanceId · node`。
