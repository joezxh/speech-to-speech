# 设计：语音对话页对齐原型（右侧会话记录/访问路由 + 双侧气泡 + 片段可播放）

日期：2026-11-28 · 范围：console 前端 + console 后端 · 状态：待批准

## 意图与动机

对话演示页（VoiceView）与原型 `console/design/console-refactor-demo.html#/conversation` 有三处形态差异：
右侧「会话记录/访问路由」是点击滑出的抽屉而非常驻右栏；通话气泡堆在对话图标上方且样式未对齐原型；
会话片段（语音）不可回放。本次把页面形态与原型完全对齐，并把已采集但未持久化的双端音频落库，让
片段在历史记录里可回放。

## 目标 / 非目标 / 反目标

- 目标：
  1. 右栏常驻双卡布局（左舞台 1fr + 右面板 360px），会话记录/访问路由 tab 风格与交互完全对齐原型；
  2. 通话中，当前会话以「live 卡」实时出现在会话记录 tab 顶部，逐行转写 + 片段条；
  3. 通话气泡移到 orb 下方，用户右对齐紫色 / 助手左对齐灰色，样式对齐原型 `.bubble`；
  4. 片段可播放：通话中播内存 Blob；保存后的记录播后端落库音频；
  5. 挂断后 live 卡先入列表，成功保存后与后端记录合并去重；保存失败标注「未保存」。
- 非目标：不改 WS 协议与 pipeline；不重做转写/延迟统计链路；不引入新前端依赖。
- 反目标：把右栏做成覆盖舞台的浮层（回到旧抽屉形态）；片段条沦为纯装饰。

## 约束

- 沿用现有 voice 主题 token（`--voice-*`）与组件风格；零新依赖（WAV 编解码已有 `pcm16ToWavBlob`）。
- 音频持久化用 Postgres `bytea`（sqlite 用 BLOB），单片段上限沿用 demo 语义（单轮 ≤120s，超长截断已有）。
- 上行采样率 24k（`USER_AUDIO_SAMPLE_RATE`）；助手侧 capture 可能失败，语义为「抓不到不是故障」。
- 并行会话已把 HistoryView 改为行内详情并复用本设计的 `sessionRecords` store/API——HistoryView 不在本次范围。

## 方案对比

**A. 片段持久化：随保存请求 base64 内嵌**——一次请求搞定，但 JSON 体积膨胀 33%，长会话易撞请求上限。弃。

**B. 片段持久化：保存记录后逐条 multipart 上传（选定）**——记录先落库拿 id，片段逐条上传，单条失败不影响记录；
请求体小、可断点续传语义简单、bytea 存储与现有 alembic/repository 范式一致。

**C. 右栏实现：复用抽屉组件改常驻**——改动最小，但抽屉的关闭按钮/overlay 语义要拔掉，等于重写；不如直接按
原型重构为 `voice-grid` 双卡布局，`?panel=` 深链保留为初始 tab。

## 设计

### 后端

1. **迁移 0020**（接 0019）：`param_session_clip`：id、session_id（FK `param_session_record` ON DELETE CASCADE）、
   role（user/assistant）、item_ref（前端 turn 标识，如 itemId/responseId）、mime（默认 audio/wav）、sample_rate
   （默认 24000）、duration_ms、size_bytes、data（bytea/BLOB）、created_at；索引 `(session_id)`。
2. **模型/仓库/服务**：仿 0019 四件套；comments.py 补注释；`dump_schema_sql.py` 重生成；schema SQL 棘轮同步。
3. **端点**（挂 `console:session:query/write` + 审计 `session-clip.*`）：
   - `POST /api/v1/session-records/{id}/clips`：multipart（role、item_ref、ordinal、sample_rate、duration_ms、file），
     单片 ≤ 8MB；返回 clip 概要。
   - `GET /api/v1/session-records/{id}/clips/{clip_id}`：返回 WAV 字节（Content-Type audio/wav，浏览器可直接播放）。
   - `GET /api/v1/session-records/{id}` 响应新增 `clips: [{id, role, itemRef, ordinal, durationMs, sizeBytes}]`
     （不含字节），前端据此接线播放。
4. 权限棘轮 `test_permissions.py` 不需新增码（复用 session 读写）。

### 前端

1. **布局**：VoiceView 主体改 `.voice-grid`（`grid-template-columns: 1fr 360px`，窄屏单列）；
   SessionLogPanel 从抽屉改为右栏常驻卡（去掉 overlay/关闭按钮，tab 常驻顶部下划线式）；
   头部 `v-panelbtn` 按钮移除；`?panel=log|route` 仍作初始 tab；`?session=` 深链保留。
2. **舞台**：orb 在上、`BubbleStack` 移到 orb 下方，样式对齐原型（user 紫右、assistant 灰左、meta 居中、
   `max-height:300px` 滚动）；现有 OrbStage 状态色与动画保留（原型一致语义）。
3. **会话记录 tab = 卡片流**：
   - live 卡：通话中置顶，逐行渲染（who 标签 + ASR/回复文本 + stt/tts 标记 + 片段条）；数据源 = 现有
     transcript 累加器（store.subscribeTranscript 已广播整句）；片段条播 `URL.createObjectURL(blob)`。
   - 挂断：live 卡转「待保存」入列表顶部；保存成功后用返回记录合并（按 pipelineSessionId 去重）并刷新后端
     列表；保存失败保留卡并打「未保存」标记。
   - 历史卡：`GET /session-records` 列表卡片化（状态点/时间/实例·节点/turns/时长/TTFT 徽标，原型样式）；
     点开复用 SessionRecordDetail（行内展开，与并行会话的 HistoryView 一致）。
   - 片段回放（已保存记录）：`GET .../clips/{id}` → objectURL → `<audio>`；波形条按 durationMs 伪随机高度
     （原型 waveBars 同款视觉），播放时高亮。
4. **路由 tab**：改原型键值行（实例/端点/节点/策略/粘滞/音色/末轮 TTFT/轮次引擎/session id）；实例·节点·
   session id·TTFT 取真实票据与 turn 延迟，策略/粘滞/音色取当前设置；下方保留工具开关区（对齐原型 Tools 区）。
5. **保存流程改造**：`toSavePayload` 增加 clips 元数据；保存成功后逐条 `POST /{id}/clips`（并发 ≤2，失败静默
   计数，记录卡标「部分片段缺失」）；live 卡合并逻辑进 sessionRecords store。

## 评审裁定（builder check 后定案）

1. **clip↔message 对齐键**：0020 clip 表用 `message_ordinal`（全局行序，与 `param_session_message.ordinal`
   同一语义）替代独立 ordinal；上传时由前端按行序带上。无音频的行（STT 失败/`audio_state='none'`）不上传、
   回放端匹配不到就不渲染片段条。
2. **路由 tab 数据源**：policy 取所选集群的真实值（`GET /clusters` 已有）；sticky（300 s）与轮次引擎
   （smart-turn）按原型文案展示默认值——原型即演示语义，不为其新开接口。
3. **「部分片段缺失」不持久化**：不加字段；重新打开记录时由 clips 数与 messages 数推断展示。
4. **片段字节端点**：鉴权沿用现有 bearer header（API client），前端 fetch→objectURL 播放；ownership 过滤
   沿用 `get_record` 的 user_id/operator 规则。
5. **SessionRecordDetail 共享边界**：片段回放做成组件内建能力，HistoryView 行内详情切到该组件时自动生效，
   不留开关。
6. **pipelineSessionId 为空**：空键不做合并，保存成功后直接移除 live 卡；非空才按 pipelineSessionId 合并。

## 交给实现者的裁量

- 片段上传顺序与重试次数；波形条高度算法细节；live 卡 DOM 复用 SessionRecordDetail 还是独立渲染。
- 助手侧 capture 失败时片段条显示「无音频」（对齐现有 audio_state='none' 语义）。

## 验收

- 布局：右栏常驻可见，窄屏折叠；气泡左右分布样式与原型一致（对照截图）。
- 通话：live 卡实时逐行 + 片段可点播；挂断保存后片段回放可用（重新打开记录仍可播）。
- `?panel=` / `?session=` 深链行为不回退；全部既有测试（vue-tsc/vitest/pytest/棘轮）绿。
