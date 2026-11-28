# 语音对话页对齐原型 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** VoiceView 对齐原型对话页（右栏常驻会话记录/访问路由 + 双侧气泡），并把通话双端音频片段落库使其可回放。

**Architecture:** 后端加 0020 片段表 + multipart 上传/字节回放端点；前端把 SessionLogPanel 从抽屉改为 `voice-grid` 右栏常驻卡，live 卡由 VoiceView 的 transcript 累加器喂数据，保存成功后逐条上传片段并在详情里回放。

**Tech Stack:** FastAPI + SQLAlchemy 2 + alembic；Vue 3 + TS + Pinia + vitest（零新依赖）。

**Spec:** `docs/superpowers/specs/2026-11-28-voice-ui-align-design.md`（含 6 条评审裁定，随计划一起读）。

## Global Constraints

- 零新前端依赖；WAV 编解码用现有 `pcm16ToWavBlob`（`features/voice/audio/sent-audio.ts`）。
- 片段单文件 ≤ 8MB；上行采样率 24000（`USER_AUDIO_SAMPLE_RATE`）；mime 默认 `audio/wav`。
- 助手侧 capture 为 best-effort：blob 为 null 不上传、不渲染片段条（对齐 `audio_state='none'` 语义）。
- 后端新表/列必须补 `comments.py` 注释并重跑 `python scripts/dump_schema_sql.py`（棘轮测试强制）。
- 权限码复用 `console:session:query` / `console:session:write`，审计动作前缀 `session-clip.`。
- 不动 HistoryView（并行会话管辖）；SessionRecordDetail 的改动须兼容其行内详情用法。
- `?panel=log|route`、`?session=<id>` 深链行为不回退。
- proto 外观层禁裸 hex（`src/styles/hex-ban.spec.ts`）。

## Review Focus

- clip 与消息行错位：片段上传的 `messageOrdinal` 必须与 `toSavePayload` 的 messages 下标一致 → Task 3 测试 `usableEntriesOf 对齐`。
- 助手 capture 失败（blob null）：不上传、live 卡显示「无音频」、详情无片段条 → Task 3 / Task 5 测试。
- 片段超 8MB：上传被拒不影响记录保存 → Task 2 测试。
- pipelineSessionId 为空：保存成功直接移除 live 卡，不做合并 → Task 5 测试。
- 已保存记录回放 404（片段缺失）：片段条显示「不可回放」而非播放失败抛错 → Task 5 测试。

---

### Task 1: 迁移 0020 + 片段模型

**Files:**
- Create: `console/backend/alembic/versions/0020_session_clips.py`
- Modify: `console/backend/app/models/session_record.py`、`console/backend/app/models/__init__.py`、`console/backend/app/models/comments.py`
- Modify: `console/backend/tests/unit/test_lb_backbone_models.py`（head 棘轮 0019→0020）

**Interfaces:**
- Produces: `ParamSessionClip`（SQLAlchemy 模型），字段：`id`、`session_id`（FK `param_session_record.id`，ON DELETE CASCADE）、`message_ordinal:int`、`role:str(16)`、`item_ref:str(128)`、`mime:str(64)` 默认 `'audio/wav'`、`sample_rate:int` 默认 24000、`duration_ms:int`、`size_bytes:int`、`data:LargeBinary`、`created_at`；`record` relationship（back_populates=`clips`）。迁移 revision=`0020_session_clips`，down_revision=`0019_session_records`。

- [ ] **Step 1: 写迁移文件**（仿 0019 的命名与 upgrade/downgrade 结构；索引 `ix_param_session_clip_session_id`）
- [ ] **Step 2: 模型 + __init__ 导出 + comments.py 注释**（表注释「会话音频片段：按全局行序挂在消息行上，随会话级联删除」；列注释逐列）
- [ ] **Step 3: head 棘轮改 0020**（`test_head_is_0019` → `test_head_is_0020`）
- [ ] **Step 4: 重新生成 SQL 并跑棘轮**

Run: `cd console/backend; $env:PYTHONPATH='.'; python scripts/dump_schema_sql.py; python -m pytest tests/unit/test_comments.py tests/unit/test_schema_sql.py tests/unit/test_lb_backbone_models.py -q`
Expected: 全部 PASS
- [ ] **Step 5: Commit** `feat(console): session audio clips table (0020)`

### Task 2: 片段上传/回放端点

**Files:**
- Modify: `console/backend/app/repositories/session_record_repository.py`、`console/backend/app/services/session_record_service.py`、`console/backend/app/routers/sessions_records.py`、`console/backend/app/schemas/session_record.py`
- Test: `console/backend/tests/integration/test_session_clips_api.py`（新建）

**Interfaces:**
- Consumes: `ParamSessionClip`（Task 1）。
- Produces:
  - repo: `add_session_clip(session_id: int, *, message_ordinal: int, role: str, item_ref: str, mime: str, sample_rate: int, duration_ms: int, data: bytes) -> ParamSessionClip`；`list_session_clips(record_id: int) -> list[ParamSessionClip]`；`get_session_clip(record_id: int, clip_id: int) -> ParamSessionClip | None`（join record 校验归属，operator 全量规则与 get_record 一致）。
  - service: `save_clip(record, *, message_ordinal: int, role: str, item_ref: str, sample_rate: int, duration_ms: int, data: bytes) -> ParamSessionClip`（校验 role ∈ {user, assistant}、`len(data) <= 8 * 1024 * 1024` 否则 `ApiError` 400、mime 固定 audio/wav；审计 `session-clip.upload`）；`clip_bytes(record, clip_id) -> tuple[str, bytes]`（审计 `session-clip.download`）。
  - router: `POST /api/v1/session-records/{record_id}/clips`（multipart：`file: UploadFile` + Form `message_ordinal:int, role:str, item_ref:str, sample_rate:int=24000, duration_ms:int=0`）→ `SessionClipOut`；`GET /api/v1/session-records/{record_id}/clips/{clip_id}` → `Response(content=data, media_type=mime)`。
  - schema: `SessionClipOut(id:int, role:str, itemRef:str, messageOrdinal:int, durationMs:int, sizeBytes:int)`；`SessionRecordDetail` 响应模型加 `clips: list[SessionClipOut]`（不含 data）。
- 审计调用沿用文件内既有 `session-record.*` 动作的写法（同一 helper/参数风格）。

- [ ] **Step 1: 写失败测试**：上传→下载字节一致；8MB 拒绝（断言 error.code 400 且记录仍在）；401 无 token；未知 clip 404；`GET /{id}` 返回 `clips` 数组（无 data 字段）
- [ ] **Step 2: 跑测试确认失败** `pytest tests/integration/test_session_clips_api.py -q` → FAIL（404/字段缺失）
- [ ] **Step 3: 实现 repo → service → router → schema**（multipart 用 FastAPI `File`/`Form`；Response 用 `fastapi.Response`）
- [ ] **Step 4: 跑测试通过** + `pytest tests/unit/test_permissions.py tests/integration/test_session_records_api.py -q` 不回归
- [ ] **Step 5: Commit** `feat(console): session clip upload/playback endpoints`

### Task 3: 前端片段 API + 行序对齐

**Files:**
- Modify: `console/frontend/src/api/sessionRecords.ts`、`console/frontend/src/stores/sessionRecords.ts`
- Test: `console/frontend/src/stores/sessionRecords.spec.ts`（追加用例）

**Interfaces:**
- Consumes: Task 2 的端点。
- Produces（后续任务依赖，签名固定）：
  - `export interface SessionClipRow { id: number; role: 'user' | 'assistant'; itemRef: string; messageOrdinal: number; durationMs: number; sizeBytes: number }`；`SessionRecordRow` 加可选 `clips?: SessionClipRow[]`。
  - `export const uploadSessionClip = (recordId: number, clip: { role: 'user'|'assistant'; itemRef: string; messageOrdinal: number; sampleRate: number; durationMs: number; blob: Blob }): Promise<SessionClipRow>`（FormData 字段名：`file`、`message_ordinal`、`role`、`item_ref`、`sample_rate`、`duration_ms`）。
  - `export const fetchSessionClipUrl = (recordId: number, clipId: number): Promise<string>`（`client.get(..., { responseType: 'blob' })` → `URL.createObjectURL`；调用方负责 revoke）。
  - `export function usableEntriesOf(entries: readonly TranscriptEntry[]): TranscriptEntry[]`（把 `toSavePayload` 里的 usable 过滤逻辑提出来；`toSavePayload` 改为调用它）。
  - VoiceView 收集片段：`usableEntriesOf(entries).map((e, i) => ({ messageOrdinal: i, role: e.role, itemRef: e.itemId ?? e.responseId ?? '', blob: e.audio ?? null }))`，`blob == null` 的条目跳过。
- [ ] **Step 1: 写失败测试**：① `usableEntriesOf` 与 `toSavePayload(...).messages` 等长且顺序一致；② `uploadSessionClip` 发出的 FormData 字段名齐全（mock client.post）；③ `fetchSessionClipUrl` 返回 objectURL（mock blob 响应）
- [ ] **Step 2: 跑测试确认失败** `npx vitest run src/stores/sessionRecords.spec.ts` → FAIL
- [ ] **Step 3: 实现**（`client` 上传用 `Content-Type: undefined` 由浏览器设 boundary——axios 传 FormData 即可）
- [ ] **Step 4: 跑测试通过** + `npx vue-tsc --noEmit` 0 错误
- [ ] **Step 5: Commit** `feat(console-web): clip upload/playback api + ordinal alignment`

### Task 4: 双卡布局 + 右栏常驻 + 气泡对齐

**Files:**
- Modify: `console/frontend/src/views/VoiceView.vue`（模板与样式）
- Modify: `console/frontend/src/components/voice/SessionLogPanel.vue`（去抽屉化）
- Modify: `console/frontend/src/features/voice/components/BubbleStack.vue`（样式对齐原型）
- Test: 相关既有 spec 更新 + `src/components/voice/SessionLogPanel.spec.ts`（若无则新建）

**Interfaces:**
- Produces: SessionLogPanel props 变为 `{ tab: 'log' | 'route'; live: LiveCard | null; saveState: 'pending'|'saved'|'partial'|'unsaved' }`，emit `update:tab`（`open`/`close` 移除）；`LiveCard = { entries: TranscriptEntry[]; pipelineSessionId: string; instanceId: string; node: string }`。
- VoiceView：`<div class="voice-grid"><section class="v-stage">…</section><SessionLogPanel class="v-panel" …/></div>`；头部 `v-panelbtn` 两个按钮删除；`openPanel/closePanel` 保留改名为只改 `panelTab` ref；`?panel=` 深链 = 初始 tab（不变）。
- 布局 CSS（对齐原型 271-287 行）：`.voice-grid{display:grid;grid-template-columns:1fr 360px;gap:16px}`、≤1100px 单列；BubbleStack 气泡：`max-width:78%;padding:9px 13px;border-radius:14px;font-size:13.5px`，user 右对齐 `rgba(139,125,255,.22)`/边框 `.35`，assistant 左对齐 `var(--voice-surface-2)`，meta 居中无边框；容器 `max-height:300px;overflow-y:auto`。模板顺序：OrbStage 在前、BubbleStack 在后。
- [ ] **Step 1: 更新/新建面板与气泡测试**：面板无 `open` prop、双 tab 常驻渲染；BubbleStack 渲染的 class 含对齐类（断言现有类名即可，避免快照脆测）；VoiceView.spec 若断言 `v-panelbtn` 则删除该断言
- [ ] **Step 2: 跑确认失败**
- [ ] **Step 3: 实现布局/样式改动**（VoiceView 现有 `v-stage` 语义并入新 grid；`?session=` 定位逻辑不动）
- [ ] **Step 4: 跑通过** + `npx vue-tsc --noEmit` + `npx vitest run src/styles/hex-ban.spec.ts`（禁 hex）
- [ ] **Step 5: Commit** `feat(console-web): persistent right panel + prototype bubble styling`

### Task 5: 会话卡片流 + 片段回放 + 保存合并

**Files:**
- Create: `console/frontend/src/components/voice/SessionCards.vue`（纯渲染组件）
- Modify: `console/frontend/src/components/voice/SessionLogPanel.vue`（log tab 用 SessionCards；路由 tab 数据在 Task 6）
- Modify: `console/frontend/src/components/voice/SessionRecordDetail.vue`（已保存记录的片段回放）
- Modify: `console/frontend/src/views/VoiceView.vue`（保存流程接入片段上传与合并）
- Test: `src/components/voice/SessionCards.spec.ts`（新建）+ 既有 detail/panel spec 追加

**Interfaces:**
- Consumes: Task 3 的 `uploadSessionClip`/`fetchSessionClipUrl`/`usableEntriesOf`；Task 4 的 props。
- Produces:
  - `SessionCards.vue` props：`{ cards: SessionCardVM[] }`，`SessionCardVM = { key: string; kind: 'live'|'saved'; state: 'live'|'done'|'failed'|'unsaved'|'partial'; when: string; inst: string; node: string; lines: { role: 'user'|'assistant'; asr: string; text: string; stt: 'ok'|'fail'|'none'; tts: 'ok'|'fail'|'none'; durMs: number; audio?: Blob | null }[]; id: string; turns: number; durMs: number; ttfaMs: number | null; recordId?: number; clips?: SessionClipRow[] }`。live 卡 `audio` 为内存 Blob 直接 `URL.createObjectURL` 播放；saved 卡按 `messageOrdinal` 匹配 `clips` 后 `fetchSessionClipUrl` 播放，404 → 片段条禁用态（title「不可回放」）。
  - 波形条：导出 `export function waveBars(seed: string, n = 12): number[]`（FNV-1a + LCG，与原型 waveBars 同算法语义，高度 3-11px）。
  - VoiceView 保存流程（stop 内，替换现有「保存→toast」段）：`payload = toSavePayload(...)` → `saveSessionRecord(payload)` → `const usable = usableEntriesOf(entries)` → 并发 2 逐条 `uploadSessionClip`（`blob==null` 跳过）→ 失败数>0 时 `saveState='partial'`，全成功 `'saved'`；`saveSessionRecord` 本身抛错 → `'unsaved'` 且不清 transcript（现状保留）。保存后处置用纯函数 `export function decidePostSave(pipelineSessionId: string, ok: boolean): 'merge' | 'drop' | 'keep-unsaved'`（放 `stores/sessionRecords.ts`：`ok=false → 'keep-unsaved'`；`ok && psid==='' → 'drop'`；否则 `'merge'`）。
- [ ] **Step 1: 写失败测试**：① SessionCards：live 态渲染 live 点与「进行中」、unsaved 态渲染「未保存」徽标、partial 渲染「部分片段缺失」；② `waveBars` 确定性（同 seed 两次相等、值域 3..11）；③ detail 回放：clips 匹配 messageOrdinal、404 时片段条禁用不抛错；④ `decidePostSave` 三分支（空串→drop、非空→merge、失败→keep-unsaved）
- [ ] **Step 2: 跑确认失败**
- [ ] **Step 3: 实现**（组件 + VoiceView 流程 + detail 回放；i18n `sessions.*` 补 zh/en：进行中/未保存/部分片段缺失/无音频/不可回放/返回列表已有则复用）
- [ ] **Step 4: 跑通过** + `npx vue-tsc --noEmit` + `npx eslint src/components/voice src/views/VoiceView.vue`
- [ ] **Step 5: Commit** `feat(console-web): session cards + clip playback + save merge`

### Task 6: 访问路由 tab 对齐原型

**Files:**
- Modify: `console/frontend/src/components/voice/SessionLogPanel.vue`（route pane 改 `v-row` 键值行 + Tools 开关区）
- Modify: `console/frontend/src/i18n/locales/{zh-CN,en-US}/sessions.ts`
- Test: SessionLogPanel.spec 追加

**Interfaces:**
- Consumes: 集群 policy——读现有 clusters API/store（在 `src/api` / `src/stores` 里 grep `clusters`，取当前所选集群的 `policy` 字段，找不到或未加载显示 `—`）；工具开关复用 voice store `store.settings.tools`（现有 toggle 逻辑，参照 SettingsDialog 的绑定方式）。
- Produces: route pane 行序（对齐原型 3766-3777 行）：实例、端点（`node:8765`）、节点、路由策略（真实 policy）、注册中心（集群 registry，取不到 `—`）、粘滞会话（固定 `300 s`）、当前音色（`store.settings.voice`）、末轮 TTFT（最近一条助手 `latency.tts_ttfa_s` 换算 ms，无则 `—`）、轮次引擎（固定 `smart-turn`）、会话 ID（pipelineSessionId）。下方 Tools 区：每个工具一行 名称+开关（绑定 `store.settings.tools` 同名字段）。
- [ ] **Step 1: 写失败测试**：route pane 渲染行数 ≥10；policy 来自注入的集群数据（mock）；工具开关切换会调 store（spy）
- [ ] **Step 2: 跑确认失败**
- [ ] **Step 3: 实现**
- [ ] **Step 4: 跑通过** + `npx vue-tsc --noEmit`
- [ ] **Step 5: Commit** `feat(console-web): prototype-aligned route tab`

### Task 7: 全量验证与部署留证

**Files:** 无新代码；验证与镜像。

- [ ] **Step 1: 后端全量** `cd console/backend; $env:PYTHONPATH='D:\work\qwen-audio-agent\speech-to-speech-src\src'; python -m pytest tests -q` 全绿
- [ ] **Step 2: 前端全量** `npx vue-tsc --noEmit`（0 行）+ `npx vitest run`（全绿）+ `npx eslint src/views/VoiceView.vue src/components/voice`（0 问题）
- [ ] **Step 3: 重建部署** `docker build -f Dockerfile.console --build-arg NODE_IMAGE=docker.m.daocloud.io/library/node:20-alpine --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.12-slim --build-arg NPM_REGISTRY=https://registry.npmmirror.com -t s2s-console:local .` + `docker compose -f docker-compose.local.yml up -d --force-recreate s2s-console`
- [ ] **Step 4: 浏览器留证（agent-browser）**：登录 8010 → `/conversation` 右栏常驻可见截图；`?panel=route` 截图；造一条带片段的记录（curl 上传小 WAV）→ 会话记录卡片段条可点播截图；`?panel=log` 深链不回退
- [ ] **Step 5: Commit**（如 docs/截图入库）+ 汇总报告
