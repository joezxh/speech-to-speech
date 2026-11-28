# Pipeline 编辑控制台设计（speech-to-speech）

> 状态：设计已确认（2026-11-28 与需求方逐段评审通过），待审阅定稿。
> 范围：在现有 console（`console/backend` + `console/frontend`）中扩展 pipeline 可视化编辑、
> 校验、发布与观测能力；定义 PipelineSpec v2 数据模型与节点能力目录；规划 P0–P3 落地路径。
> 决策记录：控制台定位=扩展现有 console；拓扑能力=固定主干+可插选节点（非任意 DAG）；
> 视频能力=协议预留+占位节点（P3 实装）；观测深度=含回放/模拟/单步调试（分期交付）；
> 契约形态=schema_version 2 单一事实源（方案 B）。

---

## 1. 现状梳理

### 1.1 架构分层与运行流程

系统为四层结构：

```
浏览器/客户端（OpenAI Realtime 协议）
  │ WS /v1/realtime 或 WebRTC /v1/realtime/calls
  ▼
console 后端（可选反代层，:8000）—— 票据鉴权、LB 选台、逐帧双向转发
  ▼
pipeline 服务（:8765）
  ├─ api/openai_realtime/websocket_router.py  WS 入口、unit 认领、客户端事件分派
  ├─ api/openai_realtime/service.py  RealtimeService —— 会话状态机 + 管线事件→协议事件翻译
  └─ PipelineUnit（s2s_pipeline.py:_build_pipeline_unit），每 unit 一条 handler 链：
       VAD → [STT → TranscriptionNotifier | AudioInputNotifier] → LM → LMOutputProcessor → TTS → 发送循环
```

- handler 基类 `src/speech_to_speech/baseHandler.py`：每阶段一个线程，
  `queue_in → process() → queue_out`，泛型 `BaseHandler[InT, OutT]` 约束各阶段输入输出
  （`pipeline/handler_types.py`：`STTIn=VADAudio`、`LLMIn=GenerateResponseRequest`、
  `TTSIn=TTSInput|EndOfResponse` 等）。
- 双通道：音频/响应依赖事件走主队列链
  （`recv_audio_chunks → spoken_prompt → stt_output → text_prompt → lm_response → lm_processed → send_audio_chunks`）；
  不等 TTS 的旁路事件（speech_started/stopped、partial transcription、tool call ready）走
  `text_output_queue`（NotifyingQueue），由 `RealtimeService.dispatch_pipeline_event()` 统一消费。

### 1.2 各阶段职责与机制

| 阶段 | 关键实现 | 职责与机制 |
|---|---|---|
| VAD | `VAD/vad_handler.py`（silero/firered） | 句末静音判停（`min_silence_ms`）、Smart Turn 语义判停（可选 ONNX）、投机重开（`speculative_reopen_ms`/`unanswered_reopen_ms`）、live transcription 触发；产出 `VADAudio(mode=progressive/final)` 与 `SpeechStarted/StoppedEvent`（含 `turn_id`/`turn_revision`） |
| STT | `STT/` 12+ 后端（qwen3-asr、sense-voice、parakeet、whisper、nemotron-streaming 等） | `STT/transcription_notifier.py` 把 `PartialTranscription/Transcription/TranscriptionFailure` 翻译为协议中立事件；`BackendCapabilities.streams_audio_chunks` 决定 VAD 是否直通流式 STT |
| LLM | `LLM/`（transformers、chat-completions、responses-api、mlx、zerogpu 等） | `chat_size` 历史窗口、`stream_batch_sentences` 攒句下传、工具调用、`TokenUsage`；`LLM/lm_output_processor.py` 维护 text/tool/audio 严格输出顺序（`output_sequence`） |
| TTS | `TTS/` 10+ 后端（voxcpm、qwen3、kokoro、cosyvoice 等） | 句内流式、prefetch transaction（投机预取）、`AudioOutput` 携带 `cancel_generation`/`response_key` 供发送端丢弃过期音频 |
| 旁路能力 | diarization（Nemotron worker）、STV 口型（wav2vec2）、voiceprint/emotion/ASR/TTS 独立 HTTP 端点、embedded agent、LiveKit worker | 以 side handler / worker / 独立服务挂载，不进主链 |

生命周期与并发：

- 停止：`stop_event` + `PIPELINE_END` 哨兵级联；会话重置用软控制消息 `SESSION_END`（不清线程）；
  模型重载用 `retire()`（退线程但不发哨兵，避免级联停止）。
- 打断/barge-in：`pipeline/cancel_scope.py`（代数式 cancel_generation，各阶段
  `should_process_input` 自行丢弃过期输入）+ `pipeline/speculative_turns.py`
  （turn_id/revision 乐观重开、`wait_for_gate` 门控、HOLD/PROCEED 决策）。
- 背压：无显式背压——Queue 无界，靠 stale 丢弃与 prefetch transaction 的 claim/discard 做逻辑削峰。
- 并发模型：每 handler 单线程 + `num_pipelines` 个隔离 unit 池（连接数超出拒绝），
  `ThreadManager` 统一托管。

### 1.3 与 OpenAI Realtime API 的映射

`pipeline/events.py` 定义协议中立内部事件；`RealtimeService.dispatch_pipeline_event()`
按类型路由（`_pipeline_dispatch` 表 + `response.on_assistant_output` 等特判），翻译为标准协议事件：

| 内部事件 | 协议事件 |
|---|---|
| `SpeechStarted/StoppedEvent` | `input_audio_buffer.speech_started/stopped`（触发 barge-in 中断当前 response） |
| `PartialTranscriptionEvent` / `TranscriptionCompletedEvent` | `conversation.item.input_audio_transcription.delta/completed` |
| `AssistantOutputEvent` / `AssistantToolCallReadyEvent` | `response.output_text.delta` / `response.function_call_arguments.*` |
| `AssistantResponseDoneEvent` | `response.done`（metadata 携带 `TURN_LATENCY` 分阶段延迟 JSON） |
| `TokenUsageEvent` | 计费口径 usage 累计（`GET /v1/usage`） |
| `ResponseFailedEvent` | `response.done(status=failed)` |

stale 事件（turn revision 被超越、响应已失败、turn 被删除）在 dispatch 入口统一丢弃。
WebRTC 走 `api/openai_realtime/webrtc_session.py`（SDP 协商 + RTP），共享同一 RealtimeService。

### 1.4 配置、加载与发布体系

- `config/prod.yaml`（schema_version 1）是初版 PipelineSpec：`blocks:`（每块
  `kind: vad|stt|llm|tts` + `backend` + `settings`）+ `pipelines:`（`stages` 固定四阶段引用 +
  `num_pipelines` + `options`）+ `runtime:`（server / livekit_worker）。
  `config.py:validate_config` 做结构校验（阶段必须恰好四个、kind 匹配、settings 按各后端参数类
  dataclass 字段校验、`{env:NAME}` 延迟到 load 时解析）。
- 后端注册表 `backend_registry.py`：`BackendSpec`（name/kind/config_type/create_handler/
  capabilities/required_extra/models）——"节点类型 + 参数 schema + 能力标签 + 工厂"的雏形；
  VAD 尚未入表（走 `vad_handler_kwargs` 独立参数类）。
- 参数目录 `docs/parameter-catalog.yaml`：全量参数元数据（默认值/范围/暴露级别/热更属性/风险），
  既是 console 后端校验源，也是前端表单渲染源与 console 自身配置注册源（`console_parameters` 段）。
- console 已有完整运营面：draft→validate→publish→restart 配置版本链
  （`param_draft`/`param_version`/`param_audit` + alembic）、热更新（`hot_update_service` →
  pipeline `/internal/sessions/update`）、模型重载（`model_reload.py`，agent 命令触发）、
  实例注册/LB/探活、会话记录与 clip（`ParamSessionClip`）、turn-latency 索引、流量与日志面板、
  agent 配置同步（etag 防回写覆盖）。
- 运行态衔接：文件模式启动的 pipeline 不热载 YAML，靠 console publish 流 + supervisor 重启生效；
  部分参数经 `RuntimeConfig` 会话级热更。

### 1.5 差距清单

已具备：后端注册表、blocks/pipelines YAML、结构化校验器、参数元数据目录、发布/版本/审计/观测链路。

距离可编辑、可插拔 pipeline 平台缺少：

1. 拓扑硬编码：`_build_handlers` 固定串行链，`stages` 必须恰好四个；无声明式旁路/分支
   （`stt: none` 走 AudioInputNotifier 是隐式分支）。
2. 无节点实例身份：队列在 unit 构造时写死互联，handler 不知自己在图中的位置，无法按节点路由/观测。
3. 控制消息分散：`should_listen`/`response_playing`/`CancelScope`/`SpeculativeTurnTracker`
   是共享可变对象注入，不是节点端口协议的一部分。
4. 视频方向空白：仅有 STV（音频→viseme 旁路，默认关闭）；无视频输入/帧抽取/VLM 节点；
   `BackendKind` 只有 `stt|llm|tts`。
5. 无统一 pipeline 观测抽象：观测逐点打桩（turn_latency、model_monitor 日志、`/v1/pool`、
   `/v1/usage`），无节点级队列深度/耗时/错误率面，无 dry-run/模拟执行。
6. 前端无图编辑器：ParamsView 为表单式，非拓扑视图。

---

## 2. 总体架构与数据流（设计 · 第 1 段）

新增能力全部挂在现有 console 骨架上，不新建进程：

```
console 前端 /console/pipeline（新路由页，沿用 viewmodel.ts + vitest 模式）
  画布编辑器 ←→ NodeCatalog（只读投影） ←→ PipelineSpec v2 草稿
       │ REST（draft/validate/publish，复用 param_draft/param_version/param_audit 链）
       ▼
console 后端 app/routers/pipeline.py + app/services/pipeline_service.py（新模块）
  草稿管理 · 转发校验 · 发布渲染 prod.yaml(v2) · etag 防回写 · 观测聚合与回放编排
       │ PIPELINE_BASE_URL（HTTP + 新增 SSE）
       ▼
pipeline :8765
  ├─ config.py        v1/v2 归一化 + 图校验（validate 与 load 同源）
  ├─ s2s_pipeline.py  按归约图装配 handler 链（替代硬编码串行）
  └─ 新增内部端点      /internal/validate、/internal/graph、/internal/catalog、
                      /internal/metrics/stream（SSE）
```

五条数据流：

1. **编辑流**：画布改动 → spec v2 JSON → `param_draft`（新 `kind='pipeline'`，与现参数草稿共表
   不同 kind，避免两套草稿机制）。
2. **校验流**：draft → console 转发 → pipeline `/internal/validate` → 带路径的结构化错误回显到
   画布节点。校验逻辑只在引擎侧一处，console 不复制规则。
3. **发布流**：validate 通过 → 走现有 publish/版本/审计/重启链，渲染产物仍是 `config/prod.yaml`，
   仅 `schema_version: 2`——文件格式不换名，不动 supervisor/挂载/agent 同步的既有约定。
4. **观测流**：pipeline 节点埋点 → SSE → console 广播给画布（节点染色）+ 入库存档。
5. **回放/模拟流**：回放复用 `ParamSessionClip` + 事件存档；模拟执行在 pipeline 进程内跑隔离
   mock unit，不占真实会话槽。

关键取舍：

- 校验放引擎侧而非 console 侧：代价是多一个内部端点，收益是"控制台说合法就真能启动"，
  杜绝校验与加载两套规则漂移。
- 画布采用 Vue Flow（MIT，Vue3 原生），图状态即 spec v2 的投影，不维护第三份模型。

---

## 3. PipelineSpec v2 数据模型（设计 · 第 2 段）

### 3.1 结构定义（`schema_version: 2`，仍是 `config/prod.yaml`）

```yaml
schema_version: 2

nodes:
  # ── 主干（4 个 required 锚点，恰好各一个）──
  vad:  {type: vad,  backend: silero,          settings: {min_silence_ms: 300, smart_turn: false}}
  stt:  {type: stt,  backend: qwen3-asr,       settings: {qwen3_asr_model_name: {env: S2S_ASR_MODEL_DIR}}}
  llm:  {type: llm,  backend: chat-completions, settings: {model_name: {env: GPUSTACK_MODEL}}}
  tts:  {type: tts,  backend: voxcpm,          settings: {voxcpm_tts_streaming: true}}

  # ── 旁路/挂接节点（可增删、可 enabled 开关）──
  diarization: {type: speaker,  attach: vad, enabled: true,  settings: {model: cache/nemotron3-diarization, dtype: bfloat16}}
  visemes:     {type: lipsync,  attach: tts, enabled: true,  settings: {model: {env: S2S_STV_MODEL_DIR}, device: cpu}}
  emotion:     {type: emotion,  attach: stt, enabled: false, settings: {mode: proxy, endpoint: {env: SER_URL}}}
  voiceprint:  {type: speaker,  attach: vad, enabled: false, settings: {mode: side-api}}

  # ── 视频占位（P3 实装，契约现在固定）──
  frame_extractor: {type: video, role: frames,     attach: llm, enabled: false, settings: {strategy: on_speech_start, max_fps: 1}}
  vlm:             {type: vlm,   role: vision_llm, attach: llm, enabled: false, settings: {}}

edges:  # 可省略；省略时由 type/attach 按目录默认端口自动推导。
        # 画布手动连线序列化后必须与默认推导一致，否则校验报"冗余/冲突边"
  - {from: vad.audio_out, to: stt.audio_in, carries: audio}

runtime: {}   # 沿用 v1 语义（server / livekit_worker 等）

pipelines:
  prod:
    spec: {num_pipelines: 1, options: {enable_live_transcription: false}}
```

要点：

- **多定义保留**：顶层 `nodes/edges/runtime` 是默认定义，`pipelines.<id>.overrides` 可覆盖
  （现有 `--name prod` 选择语义不变）。同步/发布仍以单文件为单位，agent config sync 的 etag 链不动。
- **节点身份**：`node_id` 同时是画布节点 id、观测流 node 字段、事件存档 node 字段。
  主干四个 id 固定；旁路 id 需匹配目录声明的合法锚点。

### 3.2 端口与边的类型系统

流的种类直接映射现有队列拓扑，不是新发明：

| carries | 对应现有通道 | 允许方向 |
|---|---|---|
| `audio` | `recv_audio_chunks → spoken_prompt → stt_output → lm_processed → send_audio_chunks` 主干 | 主干相邻节点 |
| `text` | `text_prompt_queue`（TranscriptionNotifier→LM 桥） | stt→llm |
| `event` | `text_output_queue` 旁路（NotifyingQueue） | 任何节点→sink |
| `control` | `should_listen`/`response_playing`/`CancelScope`/`SpeculativeTurnTracker` | 隐式广播，画布统一虚线表达，不逐条画 |

**归约规则**：校验器要求图可归约为唯一主干路径 `vad→(stt|audio_input)→llm→tts`；旁路节点只允许
目录白名单内的 `attach` 锚点；不允许跨主干连线、不允许环路。画布表达力 ⊆ 引擎可执行能力；
将来放开任意 DAG 只是放宽这条校验规则，不改数据模型。

### 3.3 v1→v2 归一化与兼容

`config.py` 加载时把 v1 `stages:{vad,stt,llm,tts}` + options 中的
`diarization/enable_visemes/...` 布尔开关机械翻译为 v2 等价节点图（纯映射，约 100 行）。
引擎内部只见 v2；v1 文件继续可加载（存量部署、历史文件），console 编辑器只产 v2。
校验错误路径由 `("blocks","stt",...)` 变为 `("nodes","stt",...)`，前端按路径定位节点。

### 3.4 校验清单（`/internal/validate`）

1. 结构：主干四锚点齐且唯一、type 合法、attach 锚点合法、边端口类型匹配。
2. 参数：节点 settings 按 `BackendSpec.config_type` dataclass 字段校验（复用 `_settings`）；
   `{env:NAME}` 只查语法不查值（解析仍在 load 时）。
3. 组合：复用现有 `config.py:_check_composition` 的后端互斥规则
   （如 `stt:none` 与 audio-input LLM），新增显存/依赖 warnings（catalog 资源预估 +
   `required_extra` 已装探测），只警告不阻断，避免离线环境误报。

### 3.5 存储、版本与 diff

- 存储：spec 全文 JSON 存 `param_draft.content`（`kind='pipeline'`），单值参数草稿不受影响。
- 发布渲染：canonical YAML 序列化（key 排序 + 主干四节点固定在前 + 旁路按 id 排序），
  保证无实质改动的两次发布 diff 为空、git 友好。
- diff/回滚：`param_version` 存整份 spec；结构级 diff（节点增删 / backend 变更 / settings 变更 /
  enabled 翻转四类）在 console 后端计算，前端按节点高亮；回滚 = 旧版本内容重新入库为新版本
  （不改写历史，与现有版本链语义一致）。

---

## 4. NodeCatalog：节点类型与能力抽象（设计 · 第 3 段）

### 4.1 目录来源与投影

NodeCatalog 不是第四份配置，而是把既有元数据合并投影为只读 JSON，由 pipeline 侧
`GET /internal/catalog` 提供（console 缓存，随版本 etag 失效）：

| 来源（现状） | 提供什么 |
|---|---|
| `backend_registry.BackendSpec`（stt/llm/tts） | 后端清单、`config_type` 参数 schema、`capabilities`、`required_extra`、`models` |
| `arguments_classes/vad_arguments.py` | P0 改造：给 VAD 建注册表；kind 扩为 `vad|stt|llm|tts|speaker|lipsync|emotion|video|vlm|sink` |
| `docs/parameter-catalog.yaml` | 参数元数据 + 新增 `nodes:` 段（端口、锚点、impl、失败策略、资源） |

前端表单渲染继续用 catalog items（现状不变）；画布节点的端口/锚点/资源徽章用新增 `nodes:` 段。

### 4.2 节点类型描述符

```yaml
# docs/parameter-catalog.yaml nodes: 段（示意）
nodes:
  stt:
    impl: handler_thread
    ports_in:  {audio_in: audio}
    ports_out: {text_out: text, event_out: event}
    anchors:   [main]
    contexts:  [turn, cancel, text_output_queue, latency]
    failure:   {default: abort_pipeline, options: [abort_pipeline, drop_turn]}
    resources: {gpu_vram_mb: {qwen3-asr: 4096, sense-voice: 800}}
  lipsync:
    impl: sidecar_sink
    ports_in:  {audio_in: audio}
    ports_out: {event_out: event}
    anchors:   [tts.post]
    failure:   {default: disable_node, options: [disable_node]}
    resources: {cpu_only: true}
  video.frame_extractor:
    impl: placeholder
    anchors:   [llm.pre]
    ports_in:  {video_in: video}
    ports_out: {frames_out: image_batch}
    failure:   {default: disable_node, options: [disable_node]}
```

backend 维度差异（同 type 下 qwen3-asr vs sense-voice）留在既有 `BackendSpec`/catalog 参数层；
节点类型层只管拓扑语义，两层不混。

### 4.3 四种执行形态（impl）

| impl | 语义 | 现有实例 | 参与主干流 |
|---|---|---|---|
| `handler_thread` | BaseHandler 线程，占主干槽 | VAD/STT/LM/TTS/Notifier | 是（audio/text） |
| `worker` | 独立线程消费旁路队列，产出富化结果 | DiarizationWorker | 否，只出 event |
| `sidecar_sink` | 订阅主干旁路输出，产出扩展事件或调外部服务，失败可静默降级 | STV、emotion proxy、voiceprint | 否 |
| `placeholder` | 仅目录声明，装配时跳过并标灰，画布可见不可配置 | 视频帧抽取、VLM（P3 实装） | 契约占位 |

`contexts` 字段解决可插拔的真实痛点：现有 `HandlerContext` 是固定字段注入
（`should_listen`/`cancel_scope`/`speculative_turns`/`text_output_queue`…），新节点声明所需上下文，
装配器只注入声明项——打断/轮次语义从私有约定变成可校验接口。不在声明清单里的上下文类型
（如 `backpressure`）目录校验直接拒绝，防止画出引擎表达不了的节点。

### 4.4 失败策略与资源预估

- 失败三级：`abort_pipeline`（主干默认，维持现状——依赖缺失即启动失败）、
  `drop_turn`（旁路推理失败丢当轮不拖垮会话，如 smart_turn 现状）、
  `disable_node`（能力整体降级 not_ready，如 STV 模型缺失 soft-fail）。
  目录声明允许集合，节点可在集合内选择，校验器拒非法组合。
- 资源预估：发布校验对 `resource_ledger`（现有）选中 backend 求显存/依赖和，
  超机器水位（catalog 机器档位已有）出 warning 不阻断。

### 4.5 自定义节点注册契约（仅定契约，不实现加载器）

新后端接入 = 一个 `BackendSpec` 条目 + catalog `nodes:` 段一个类型声明（若属新类型），
入口仍是 `create_backend_handler` 工厂。占位节点转实装遵循同一路径：
`impl: placeholder → handler_thread/sidecar_sink` 换值 + 补 handler 实现，
spec 文件与画布布局零迁移——这是"协议预留"的实际含义。

> 过渡期提醒：catalog 的 `nodes:` 段与平台渲染版 YAML 必须同源。历史上发生过
> agent config sync 用平台渲染版覆盖本地 `config/prod.yaml`、冲掉手工项
> （voxcpm/diarization/livekit_worker）的事故。v2 编辑器上线后手工项本身就是平台内
> 节点/参数，渲染版不再缺项；但过渡期发布流必须保留 etag + diff 预览 + 明确确认，禁止静默覆盖。

---

## 5. 编辑器画布（设计 · 第 4 段）

### 5.1 页面结构与布局

新路由页 `PipelineView.vue`（`meta.navGroup='console'`，侧栏经 `buildNavGroups()` 路由派生）。
页面结构：顶栏（定义选择器/脏标记/校验/发布/版本 diff 入口）+ 左侧画布（拓扑/时序两 tab）+
右侧检视器（节点参数 / 边只读 / pipeline 全局三态）+ 底部诊断抽屉（校验错误列表可点击定位、
发布检查清单）。

拓扑 tab（编辑态）**只允许拖到锚点，不允许自由摆放**：主干四节点按 catalog 锚点顺序固定水平
排列（position 由布局函数派生，不可拖动）；旁路节点从锚点 ➕ 抽屉（catalog 按锚点过滤）添加，
落在主干节点上下的吸附槽位。`position` 只是渲染细节，回写 spec 时丢弃——spec 是单一事实源，
不存画布坐标，避免坐标漂移产生假 diff 污染版本链。

样式约定：边按 `carries` 着色（audio 实线粗 / text 实线细 / event 点线 / control 灰虚线一组）；
节点徽标显示 backend 名 + impl 形态图标 + enabled 开关；占位节点灰色不可配置，tooltip 注明
"P3 实装"。

### 5.2 全双工时序可视化（时序 tab）

原则：不重绘引擎内部状态机，把已有事件词汇表投影成图。词汇表完全来自现状：
`SpeculativeTurnTracker` 的 TurnPhase（LISTENING/CLOSED/HELD…）、`SpeechStarted/Stopped`、
revision 重开、cancel generation、partial transcription、`response.done`。

**① Turn 泳道时序图（回放/实时通用）**——数据源为现有 Realtime 事件流 + `TURN_LATENCY`
metadata，无需新埋点：

```
turn_7  rev0 ──●speech_started ──●speech_stopped ──(held 0.3s)──✕ superseded
turn_7  rev1 ──────────────────────●speech_reopen ──●stopped ──▶ stt ──▶ llm(sp1) ──▶ tts(sp3) ──▶ done
        ▲ 用户插话触发 barge-in：cancel_gen#12 → tts 残留音频按 AudioOutput.cancel_generation 丢弃
```

横轴时间、纵轴 turn/revision 泳道；打断点画剪刀符号（标注中断的 response_id 与已播放时长→
truncate 位置）；投机重开画成分叉汇合。回放（P2）与实时（P1）共用同一渲染组件，
只是事件来自存档还是 SSE。

**② 双工状态叠加层**——拓扑 tab 节点在实时染色之外，显示当前 turn 游标（该节点正在处理哪个
turn/rev、队列积压几项），并把"输入输出同时进行"表达为主干上两条方向相反的行进光带
（audio 下行 vs 事件/音频上行），不另画图。

### 5.3 参数面板

- 表单由 catalog items 驱动，沿用 ParamsView 既有渲染约定（范围/枚举/热更标记），检视器内不跳转旧页面。
- 字段标注四类徽标：`启动生效` / `会话热更` / `需重启` / `有风险`——来自 catalog 现有属性，
  把"改了文件没重启不生效"的配置漂移坑前置到界面上。
- 后端切换（如 voxcpm↔qwen3）整体切换 `config_type` 字段集，未识别字段标黄提示"将丢弃"。

### 5.4 校验回显

- 错误来自 `/internal/validate` 的结构化路径（如
  `("nodes","stt","settings","qwen3_asr_gen_max_new_tokens")`），前端做路径→节点/字段映射：
  节点红框、字段红行、底部抽屉按错误排序可点击定位；warning（显存/依赖）黄色不阻断。
- 编辑时防抖调用 catalog 本地子集校验（纯结构规则：锚点/类型/必填），远端全量校验只在手动
  "校验"与发布前触发。前端本地校验只负责即时反馈，合法性判定以引擎侧为唯一权威。
- 发布检查清单：结构 / 参数 / 组合 / 资源 warnings / 与运行版本的节点级 diff
  （新增节点、backend 变更、参数修改分类列出），确认弹窗内直接看差异再发布。

### 5.5 前端分层与测试

沿用 viewmodel 模式：`pipeline.viewmodel.ts` 为纯函数层（spec↔画布图投影、锚点合法性、
路径映射、diff 计算），Vue Flow 只做渲染；vitest 覆盖纯函数层（与既有
`*.viewmodel.spec.ts` 同风格），画布交互不做单测，靠 P1 浏览器验收清单。

---

## 6. 运行时与观测（设计 · 第 5 段）

### 6.1 节点级埋点清单

原则：能不改热路径就不改。

| 数据 | 现有基础 | 新增工作 |
|---|---|---|
| handler 耗时 | `BaseHandler._times` 已记录每次 `process()` 耗时 | 只读访问器 |
| 队列深度 | 标准库 `Queue.qsize()`（O(1) 线程安全） | 采样器周期读取 |
| 模型调用延迟/资源 | `utils/model_monitor` 已记录 per-call 指标 | 增加内存环形缓冲供 `/internal` 查询 |
| turn 级事件 | `dispatch_pipeline_event` 已是全量漏斗 | 入口挂观察者镜像（非阻塞 put，满丢弃并计数） |
| 节点身份 | 现状缺口：事件只有 turn_id/rev | P0 随 v2 装配补齐：装配器注入 `node_id`，所有 `PipelineEvent` 与采样指标统一带 `{node_id, pipeline_index}` |

采样器：每 unit 一个轻量循环（1s 周期），产出每节点
`{q_in_depth, q_out_depth, last_s, p50/p95(滑窗), error_count, idle|busy|stalled}`——
零 per-item 开销。`stalled` 判定 = 上游持续产出但本节点队列积压且 last_s 超阈值。

### 6.2 SSE 事件协议（`GET /internal/metrics/stream`）

与语音数据面完全隔离：独立内网端点、不进 `/v1/*` 反代路径、控制台专用 token。四类帧：

```
graph    {spec_version, nodes:[{id,type,backend,enabled,status}], edges}   # 连接首帧，运行图快照
stats    {ts, unit, node_id, q_in, q_out, last_s, p95_s, errors, state}    # 周期批量帧（ready/drain/uneven/empty）
turn     {ts, unit, node_id, conn_id, turn_id, rev, kind, detail}          # 逐事件：speech_started/
                                                                          # reopen/cancel/barge_in/stt_final/
                                                                          # llm_first_token/tts_first_audio/
                                                                          # response_done/error/vad_decision
session  {conn_id, state, usage:{tokens_in,tokens_out,audio_s}}           # 连接生命周期与累计量
```

console 后端订阅后做扇出（转发给画布/时序视图的浏览器 WS）与归档（turn 帧入库）。
断线语义：stats 是状态量（最新值覆盖即恢复一致），turn 是事件量（带 seq，断线用存档回补）。

### 6.3 回放索引与录像联动

新表 `pipeline_turn_event`（console alembic 迁移）：
`(id, instance_id, session_record_id, conn_id, turn_id, rev, node_id, kind, ts, payload_json)`，
索引 `(session_record_id, ts)`。迁移后须重新生成 `alembic/sql/init-*.sql`
（`tests/unit/test_schema_sql.py` 会校验覆盖）。

- 事件轴从该表重建，回放/实时共用 §5.2 渲染组件。
- 音频联动现有 `ParamSessionClip`（前端采集已有上传链）：点击泳道事件跳 clip 时间点，
  `speech_stopped_at_s`/`TURN_LATENCY` 单调时钟对齐到 clip 毫秒轴。
- 归档范围默认只存 turn 帧（KB 级/轮），stats 帧不落库。

### 6.4 模拟执行（mock run）

在 pipeline 进程内跑隔离 unit：按当前 draft spec 装配同一张图，模型 handler 全部换成 mock
（impl 形态、端口连线、control 广播走与生产完全相同的装配器代码路径——验证的是拓扑而非模型）。
mock 延迟参数来自 catalog 区间（如 `stt: 0.3–0.8s`、`tts 首音: 0.15–0.4s`）。两种驱动：

1. **干跑**：喂内置测试音频，输出每节点收发计数 + 事件序列 + 预估轮延迟区间，秒级完成，发布前一键验证。
2. **供数回放**：把 §6.3 存档事件流/音频 clip 重放到 mock 图，验证拓扑改动对时序的影响。

隔离：mock unit 走独立 `pipeline_index`（如 -1），不占 `/v1/pool` 真实槽位；并发限 1，超时自动销毁。

### 6.5 单步调试（分级）

- **A 档 · 回放单步（P2 实装）**：事件序列帧进/退/跳 turn，检视器展示选中事件完整 payload
  （Pydantic 已序列化），双栏对照事件轴与音频波形。纯前端+存档，零引擎风险。
- **B 档 · 活体干预（仅协议预留）**：对 mock unit（非生产 unit）暂停节点出队、手动注入
  `response.create`/barge-in/`SESSION_END`。协议：`POST /internal/mock/step
  {node_id, action: pause|resume|inject}`。真正的进程内断点不做——全双工时序 bug 多在挂起
  等待中变形，成本极高且结果不可信。

### 6.6 错误统计与延迟分布

- 错误：`turn kind=error` 帧 + 现有 `response_failed`/`transcription_failed` 计数入库，
  按节点/类型聚合计入发布检查清单"运行健康"栏。
- 延迟：复用 `TURN_LATENCY` 与 console 现有 `turn_latency` 表/indexer，新增按节点拆分的
  可视化（现有为轮级），直方图/分位图画在时序 tab 标尺上，不另建指标管道。

---

## 7. 落地路径（设计 · 第 6 段）

### P0 · 定义模型 + 编辑器 + 发布闭环（引擎 ~2 周，console ~3 周，可并行）

引擎侧：

- `src/speech_to_speech/config.py`：v2 schema、`normalize_v1_to_v2`、图校验。
- `src/speech_to_speech/backend_registry.py` + `arguments_classes/vad_arguments.py`：VAD 入表，kind 扩展。
- `src/speech_to_speech/s2s_pipeline.py`：`_build_handlers` 重构为按图装配（`assemble_graph`），
  保留 v1 归约特例路径。
- `src/speech_to_speech/baseHandler.py`、`pipeline/events.py`：`node_id` 注入并贯穿事件。
- 新内部端点 `/internal/validate`、`/internal/graph`、`/internal/catalog`
  （新文件 `api/openai_realtime/internal_routes.py`，仿 `emotion_routes.py` 挂载模式）。
- `config/prod.yaml` 迁移为 v2（现存手工项全部节点化）。

console 侧：

- 后端：`app/routers/pipeline.py` + `app/services/pipeline_service.py`
  （draft `kind='pipeline'`、转发校验、canonical 渲染、节点级 diff）；测试仿
  `tests/integration/test_drafts.py`/`test_publish.py`。
- 前端：`views/PipelineView.vue` + `pipeline.viewmodel.ts` + Vue Flow 依赖 + 拓扑 tab +
  检视器 + 校验回显 + 发布检查清单；`router/index.ts` 加路由。

集成方式：发布走现有 publish→渲染文件→supervisor 重启链；agent config sync etag 链不动。
验收：v1 文件兼容回归通过；画布切换 TTS backend + 关 diarization 节点 → 校验 → 发布重启 →
`/v1/realtime` 全链路对话正常。

### P1 · 实时观测 + 全双工可视化（~3 周）

- 引擎：采样器 + 观察者镜像 + `/internal/metrics/stream` SSE。
- console：订阅器 + `pipeline_turn_event` 表（alembic + 重新生成 sql 文件）+ 扇出 WS。
- 前端：拓扑实时染色、时序 tab（turn 泳道图）、双工光带、延迟分布接现有 turn_latency 索引。
- 验收：真实会话中画布可见 speech_started→reopen→cancel→tts_first_audio 泳道，节点队列深度实时变化。

### P2 · 回放 / 模拟 / 单步调试（~4 周）

- 回放：事件轴重建 + `ParamSessionClip` 联动 + A 档单步。
- 模拟：mock backend 族（挂 `BackendSpec` 同接口）+ 隔离 unit + 干跑 + 供数回放；B 档仅协议文档。
- 验收：含占位视频节点的 draft 干跑通过；对历史慢会话回放可定位瓶颈段。

### P3 · 视频理解实装（契约不变）

- 前端上行视频帧（Realtime 协议扩展或 `input_image_buffer` 语义，届时定）；
  引擎实装 `frame_extractor`（VAD 锚点，on_speech_start 抽帧）与 `vlm`
  （替换/前置 llm 节点，走既有 chat-completions image content）。
- 占位节点 `impl` 换实装值，spec/画布零迁移；音画同步复用 viseme 扩展事件通道。
- 验收：视频+语音混合会话端到端。

### 风险与缓解

| 风险 | 等级 | 缓解 |
|---|---|---|
| P0 装配器重构碰全双工核心（`_build_handlers` 与 turn/cancel 语义耦合深） | 高 | 行为保持重构：先让 v1 归约路径跑通全部现有测试（`tests/` 含 turn 语义专项），再切 v2 装配；音频路径变更按 AGENTS.md 跑 Big Bench Audio eval |
| config sync 回写覆盖（平台渲染版缺手工项冲掉本地文件） | 高 | P0 迁移时把现存手工项全部节点化进 v2 再切编辑器接管；过渡期发布保留 etag+diff 确认，禁止静默覆盖 |
| 观测拖慢热路径 | 中 | 只读采样 + 非阻塞镜像 + 丢弃计数；SSE 断开不影响 pipeline |
| 双事实源复活（画布坐标 / 前端规则漂移） | 中 | spec 不存坐标；前端本地校验仅为即时反馈子集，判定权在引擎 |
| 模拟结果误导（mock 延迟 ≠ 真模型） | 中 | 报告标注"拓扑验证用途"；延迟区间取 catalog 真实分位数 |
| Vue Flow 依赖引入 | 低 | MIT、无传递重依赖；布局受锚点约束，不涉自由画布复杂度 |

取舍声明：放弃任意 DAG（换全双工时序可校验）、放弃进程内真断点（B 档仅协议）、
stats 帧不落库（只归档 turn 帧）。

---

## 8. 关键能力与接口缺口总结

| # | 缺口 | 补齐物 | 阶段 |
|---|---|---|---|
| 1 | 拓扑硬编码、stages 强制四元 | PipelineSpec v2 节点图 + 归约校验 + 按图装配器 | P0 |
| 2 | VAD 游离注册表、无节点类型抽象 | registry kind 扩展 + catalog `nodes:` 段（端口/锚点/impl/失败策略/资源） | P0 |
| 3 | 无节点身份 | `node_id` 贯穿 spec→handler→事件→观测帧 | P0 |
| 4 | 校验只在启动时 | `/internal/validate` + `/internal/graph` + `/internal/catalog` | P0 |
| 5 | 无图编辑界面 | Vue Flow 拓扑/时序双 tab + 检视器 + 发布检查清单 | P0/P1 |
| 6 | 观测逐点打桩、无节点级面 | 采样器 + SSE 事件协议 + turn 帧归档表 | P1 |
| 7 | 无全双工可视化 | turn/revision 泳道图（barge-in/投机重开/首音锚点） | P1 |
| 8 | 无回放/模拟基础设施 | 事件存档联动 clip 回放 + mock unit | P2 |
| 9 | 视频方向零契约 | `video/vlm` 占位类型 + `image_batch` 流类 | P2 契约 / P3 实装 |
| 10 | 发布链对图无感知 | draft `kind='pipeline'` + canonical 渲染 + 节点级 diff/回滚 | P0 |

## 9. 参考文件索引

- 引擎：`src/speech_to_speech/{baseHandler.py, s2s_pipeline.py, config.py, backend_registry.py}`、
  `src/speech_to_speech/pipeline/{events.py, handler_types.py, queue_types.py, messages.py,
  speculative_turns.py, cancel_scope.py, turn_latency.py}`、
  `src/speech_to_speech/api/openai_realtime/{service.py, websocket_router.py, webrtc_session.py,
  pipeline_unit.py, model_reload.py}`
- console：`console/backend/app/{routers,services,repositories}`、
  `console/frontend/src/{views,features/voice,router}`、`console/README.md`
- 配置与文档：`config/prod.yaml`、`docs/parameter-catalog.yaml`、`docs/model-pipeline.md`、
  `docs/full-duplex-voice-pipeline-CN.md`、`docs/console-service.md`、`docs/deployment.md`
