# Pipeline 编辑控制台设计方案：评审报告与优化方案

> 评审对象：`docs/superpowers/specs/2026-11-28-pipeline-editor-console-design.md`（qwen3.8-flash 生成）
> 评审方法：逐条对照引擎源码（`src/speech_to_speech/`）与 console 源码（`console/backend`、`console/frontend`）核实。
> 状态：**待确认**。原设计文件未被修改；本文经确认后再合并回原设计。
> 约定：文中"原方案 §x"指原设计文件的章节；代码证据写成 `文件:行号`。

---

## 第一部分　评审报告

### 1. 结论

原方案的**方向和骨架是对的**：固定主干 + 可插挂接节点（不做任意 DAG）、spec 单一事实源、节点身份贯穿、`impl`/`contexts` 抽象、发布复用现有版本链、观测与数据面隔离。这些都应保留。

问题集中在三类：

| 类别 | 数量 | 性质 |
|---|---|---|
| 现状梳理与代码不符 | 10 | 会导致拓扑投影错误、方案无法按描述实现 |
| 逻辑漏洞与内部矛盾 | 14 | 含冗余事实源、数据模型丢字段、观测数据源不存在 |
| 可扩展性 / 体验 / 工程风险 | 7 | 多实例、时钟对齐、热路径成本、i18n 等 |

其中 6 项必须在动工前修正，否则会造成返工或线上行为变化：

1. **STV 口型被误判为旁路节点**，实际是主干内联 handler（F1）。
2. **`blocks` 改名 `nodes` 会波及草稿/目录/审计/agent 同步的全部点路径寻址**，"约 100 行映射"严重低估（L3）。
3. **节点目录放在 console 才读的文档 YAML 里，引擎装配器却要依赖它**（F9）。
4. **草稿表结构不存在**，且与"每 profile 一个补丁草稿"的既有决策冲突（F5）。
5. **泳道图声称的若干事件没有数据源**，`_times` 也算不出滑窗分位数（F7、F8）。
6. **v2 示例丢失 `models`、`runtime.server/client` 等字段的落点**（L2）。

---

### 2. 核心优势与可复用设计点

| # | 设计点 | 为什么合理 | 优化方案中的处置 |
|---|---|---|---|
| S1 | 固定主干 `vad→(stt\|audio_input)→llm→tts` + 挂接节点，不做任意 DAG | 与引擎实际可执行能力对齐；全双工时序可校验；画布表达力 ⊆ 引擎能力 | **保留** |
| S2 | spec 是单一事实源，不存画布坐标 | 避免坐标漂移产生假 diff 污染版本链 | **保留**，补充确定性布局规则 |
| S3 | `node_id` 贯穿 spec → handler → 事件 → 观测帧 | 现状事件只有 turn_id/rev，无法按节点归因 | **保留** |
| S4 | `impl` 四形态 + `contexts` 声明式注入 | 把 `HandlerContext` 的固定字段注入变成可校验接口；打断/轮次语义不再是私有约定 | **保留**，目录改放引擎代码 |
| S5 | 校验权在引擎，console 不复制规则；结构化路径回显到节点/字段 | 防止校验与加载两套规则漂移 | **保留**，改为三模式并带版本标识 |
| S6 | 发布复用 draft→validate→publish→重启版本链，etag 防回写，diff 预览后确认 | 针对历史上平台渲染版覆盖手工项的事故 | **保留** |
| S7 | 观测与数据面隔离：独立内网端点、非阻塞镜像、满则丢弃并计数 | 观测不能拖慢实时音频 | **保留**，修正"零开销"表述 |
| S8 | 泳道图只投影既有事件词汇，不重绘状态机；回放与实时共用渲染组件 | 降低引擎风险 | **保留**，补齐缺失的数据源 |
| S9 | 单步调试分级：A 档纯前端回放，不做进程内真断点 | 进程内断点在全双工场景下结果不可信 | **保留** |
| S10 | mock run 验证拓扑而非模型；用独立 `pipeline_index` 隔离 | 定位准确 | **保留**，改走子进程 |
| S11 | 视频能力先定契约、占位后实装；占位转实装只换 `impl` 值 | spec 与画布零迁移 | **保留**，修正锚点与能力归属 |
| S12 | 前端 viewmodel 纯函数层 + vitest；画布交互靠浏览器验收 | 与现有 `*.viewmodel.spec.ts` 约定一致 | **保留** |
| S13 | 行为保持重构：先让 v1 归约路径跑通全部测试再切新装配 | P0 最大风险的正确缓解方式 | **保留**，并拆成独立里程碑 |
| S14 | 风险表与取舍声明明确 | 便于评审 | **保留** |

---

### 3. 问题清单

严重度：**P0** = 动工前必须修正；**P1** = 影响正确性或可维护性；**P2** = 改进项。

#### 3.1 现状梳理与代码不符

**F1（P0）STV 口型是主干内联 handler，不是旁路 sidecar**

- 证据：[s2s_pipeline.py:596](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/s2s_pipeline.py#L596) `tts_output_queue = Queue() if module_kwargs.enable_visemes else send_audio_chunks_queue`；[s2s_pipeline.py:606-621](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/s2s_pipeline.py#L606-L621) 把 `Wav2Vec2STVHandler` 以 `queue_in=tts_output_queue, queue_out=send_audio_chunks_queue` 串在 TTS 与发送循环之间；[w2v_stv_handler.py:31](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/STV/w2v_stv_handler.py#L31) 类型为 `BaseHandler[AudioOutItem, AudioOutItem]`。
- 原方案：§1.2 称 STV"不进主链"；§4.2/§4.3 定义 `lipsync: impl: sidecar_sink, anchors: [tts.post], failure: disable_node`。
- 影响：画布把它画成挂接节点，实际每个音频块都经过它（多一次线程切换，内部还有 0.5 s 缓冲）。按图装配若照 sidecar 装配，会改变音频路径的延迟与行为。`disable_node` 也与现状不符：现状模型缺失时 `skip=True`，但线程仍在链上透传。

**F2（P1）VLM / 图像输入不是空白**

- 证据：[backend_registry.py:343-351](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/backend_registry.py#L343-L351) `is_vlm` → `VisionLanguageModelHandler`；[language_model_arguments.py:52](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/arguments_classes/language_model_arguments.py#L52) `llm_is_vlm`；[LLM/chat.py:1288](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/LLM/chat.py#L1288) 与 [chat_completions_language_model.py:126](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/LLM/chat_completions_language_model.py#L126) 已处理 `input_image`；前端已有 [camera.ts](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/frontend/src/features/voice/tools/camera.ts) 与 [VoiceView.vue:234](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/frontend/src/views/VoiceView.vue#L234) 的快照链路。
- 原方案：§1.5 "无视频输入/帧抽取/VLM 节点"。
- 影响：P3 从零起步会重复建设；原方案另设 `vlm` 节点并称"替换/前置 llm 节点"，既与"固定主干"矛盾，也与现有 `llm_is_vlm`（backend 参数）冲突。

**F3（P1）视频占位节点锚点前后不一致**

- §3.1 `frame_extractor: attach: llm`；§4.2 目录 `anchors: [llm.pre]`；§7 P3 "VAD 锚点，on_speech_start 抽帧"。三处三个说法，契约无法固定。

**F4（P1）`resource_ledger` 被误读为显存估算表**

- 证据：[s2s_pipeline.py:452-623](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/s2s_pipeline.py#L452-L623) 中它是启动失败时用于回滚的已加载资源清单；catalog 里没有按 backend 的显存数据；console 现有显存预算是常数 `DEFAULT_PIPELINE_VRAM_GB = 4.6`（[validator_service.py:36](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/validator_service.py#L36)）。
- 原方案 §4.4："对 resource_ledger 选中 backend 求显存/依赖和"。该计算无法实现。

**F5（P0）草稿表结构不存在，且与既有决策冲突**

- 证据：[param_draft.py](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/models/param_draft.py) 只有 `profile(unique) / base_version / patch`，注释明确 "a patch, never a whole config"；[param_version.py](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/models/param_version.py) 存 `yaml_text` 整文件快照。没有 `content`、`kind` 列。
- 原方案 §3.5："spec 全文 JSON 存 `param_draft.content`（`kind='pipeline'`）"。
- 影响：`profile` 唯一约束下，画布草稿与 ParamsView 的补丁草稿会互相覆盖；"全文"与"补丁"两种语义混在一张表。

**F6（P1）校验现状误判，且会回退现有保证**

- 证据：[validator_service.py:58-69](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/validator_service.py#L58-L69) 与 [:340-372](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/validator_service.py#L340-L372) 显示 console 已在进程内导入 `speech_to_speech.config` 做运行时校验（runtime / structural 双模式），并且会解析 `{env: NAME}`（合并渲染后的 `.env`），在发布前暴露缺失变量。
- 原方案：(a) 把"引擎侧校验"当作新增收益，形成第三条校验路径；(b) §3.4 "`{env:NAME}` 只查语法不查值"是现有保证的回退。
- 附带发现：console 的结构校验与引擎已经漂移——引擎允许顶层 `models:`（[config.py:450](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/config.py#L450)），console `TOP_LEVEL_KEYS` 不允许（[validator_service.py:31](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/validator_service.py#L31)）。原方案未处理，v2 会放大。

**F7（P0）泳道图声称的若干事件没有数据源**

- 证据：[pipeline/events.py](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/pipeline/events.py) 的事件类型只有 `speech_started/stopped`、`partial_transcription`、`transcription_completed/failed`、`audio_input_completed`、`assistant_text`、`assistant_tool_call_ready`、`token_usage`、`assistant_response_done`、`response_generation_done`、`response_failed`。没有 `speech_reopen`（只有 `SpeechStartedEvent.reopened` 布尔位）、cancel、barge-in、stale 丢弃、`llm_first_token`、`tts_first_audio`。`llm_ttft_s` 也不进 metadata（[turn_latency.py:234-262](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/pipeline/turn_latency.py#L234-L262)）。
- stale 丢弃发生在 handler 内部的 `should_process_input`（[baseHandler.py:74-99](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/baseHandler.py#L74-L99)），到不了 `dispatch_pipeline_event` 入口。原方案"在 dispatch 入口挂观察者"看不到 `cancel_gen` 丢弃，§5.2 示意图里的"tts 残留音频丢弃"无法由所述数据源得到。
- 原方案 §5.2："数据源为现有事件流 + TURN_LATENCY metadata，无需新埋点"。不成立。

**F8（P0）观测成本自相矛盾，`_times` 不支持所述计算**

- 证据：[baseHandler.py:66](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/baseHandler.py#L66) 与 [:217](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/baseHandler.py#L217)：`_times` 是无界 `list`，只在 emit 输出时追加耗时，没有时间戳，长期运行会持续增长。[:229-230](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/baseHandler.py#L229-L230)：`process()` 异常被 `log_exception` 吞掉，既无计数也无事件。
- 原方案 §6.1 一边说"能不改热路径就不改""零 per-item 开销"，一边要 `p50/p95(滑窗)` 和 `error_count`。两者都不能由现有数据得到。

**F9（P0）节点目录放错了位置**

- 证据：`docs/parameter-catalog.yaml` 只被 console 读取（[catalog_service.py](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/catalog_service.py)，容器路径 `/app/catalog/`），引擎 `src/` 不读它。该文件是生成物（头部 `generated_from`），CI 有 schema 漂移测试（`test_catalog_schema_drift.py`、`test_catalog_extra_fields.py`）。
- 原方案 §4.1/§4.2：把 `impl / ports / contexts / failure` 写进该 YAML，装配器据此装配。
- 影响：引擎运行时依赖 console 镜像里的文档文件；`impl`、`contexts` 本质是代码事实，不该放文档。

**F10（P2）配置路径与 `.env` 耦合未覆盖**

- 证据：不存在 `config/prod.yaml`；实际是 `config/<profile>/prod.yaml` + `<profile>.env`（如 [config/split-2b/prod.yaml](file:///d:/work/qwen-audio-agent/speech-to-speech-src/config/split-2b/prod.yaml)；[publish_flow_service.py:48-59](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/publish_flow_service.py#L48-L59)）。`stage: env` 类参数渲染到 `.env`（[renderer_service.py:61-79](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/renderer_service.py#L61-L79)）。
- 原方案 v2 模型未提 `.env`，检视器里的 env 类参数没有落点。

#### 3.2 逻辑漏洞与内部矛盾

**L1（P1）`edges` 是冗余事实源**

§3.1："可省略；省略时自动推导；手动连线序列化后必须与默认推导一致，否则校验报冗余/冲突边"。一个只允许等于推导结果的人工可编辑字段，只可能产生假冲突，不会带来表达力。应从持久化中删除。

**L2（P0）v2 示例自身矛盾，且丢字段**

- 示例写 `pipelines.prod.spec.{num_pipelines, options}`，正文写"`pipelines.<id>.overrides` 可覆盖"，v1 实际是 `num_pipelines` / `options` 直接在 pipeline 下。三处不一致。
- 示例 `runtime: {}`，但 v1 的 `runtime.server / client / livekit_worker` 与进程级参数（`log_level` 等）在 v2 中没有落点。
- v1 允许的顶层 `models:`（模型卡 `repo_id` / `default_load_params` 覆盖）在 v2 中完全消失。按原方案迁移即丢配置。

**L3（P0）`blocks` 改名 `nodes` 的影响面被严重低估**

- v1 中 block 可被多个 pipeline 共享（[layout_service.py:95](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/layout_service.py#L95)），改成每 pipeline 一份 `nodes` 后共享语义丢失。
- 草稿补丁键、布局定位、目录、审计 diff、agent 配置同步全部以 `blocks.<id>.settings.<param>` 点路径寻址：[layout_service.py:52-89](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/layout_service.py#L52-L89)、[agent/config_sync.py:70-81](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/agent/config_sync.py#L70-L81)。
- 原方案称"纯映射，约 100 行"。实际要同步改动上述全部模块及其测试。

**L4（P1）失败策略混合了启动期与运行期**

`abort_pipeline`（依赖缺失即启动失败）是启动期语义，`drop_turn` 是运行期语义，不在一个维度。并且没有定义主干节点在运行期失败时谁来收尾 response——现状是 `process()` 异常后条目被吞，response 可能悬挂。

**L5（P1）占位节点被启用时会静默跳过**

§4.3 "装配时跳过并标灰"，但没有"启用未实装节点 → 校验失败"的规则。用户打开开关后以为视频已生效。

**L6（P1）校验权威与版本偏斜**

`/internal/validate` 在目标实例进程内执行是正确方向，但实例未启动、多实例版本不一致、console 镜像内包版本不同的情况没有降级策略，结果里也没有引擎版本标识。

**L7（P2）吸附槽位布局不确定**

多个旁路节点吸附同一锚点时的上下分布与排序没有规则，同一 spec 在不同浏览器可能布局不同。应提供确定性布局函数。

**L8（P1）发布 = 重启，但未处理在途会话与生效方式**

catalog 的 `effect` 取值是 `startup / hot / both`。原方案徽标写"启动生效 / 会话热更 / 需重启 / 有风险"："需重启"不是 catalog 值，且与"启动生效"重复。也没有把热更参数与现有的免重启应用流程（[hot_update_service.py](file:///d:/work/qwen-audio-agent/speech-to-speech-src/console/backend/app/services/hot_update_service.py) → `/internal/sessions/update`）接起来，发布清单里没有在途会话提示。

**L9（P1）运行态三方漂移缺失**

草稿、已发布版本、实际运行（手改文件、热更、模型重载之后）三者没有对账。`graph` 帧只有 `spec_version`，无法发现"文件被改了但没重启"。

**L10（P0）回放的时钟对齐缺少锚点**

`speech_stopped_at_s` 与 TURN_LATENCY 基于 `perf_counter()`（进程内单调钟），clip 是浏览器端采集的。原方案 §6.3 "单调时钟对齐到 clip 毫秒轴"没有锚点交换协议，无法实现。

**L11（P1）mock run 在 pipeline 进程内执行会干扰在线会话**

与实时音频会话争用 GIL 与线程，"不占真实会话槽"不能消除延迟干扰。mock unit 还共享全局 `get_model_monitor()`（[baseHandler.py:57](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/baseHandler.py#L57)），会污染模型监控指标。

**L12（P1）SSE 断线语义不完整**

"turn 帧带 seq，断线用存档回补"：存档写入 console DB 是异步的，重连窗口内的帧既不在 DB 也已丢失。缺 `Last-Event-ID` 重放、心跳、背压下的丢弃优先级。

**L13（P1）内部端点鉴权未统一**

现有模式是 `S2S_INTERNAL_TOKEN` fail-closed（[websocket_router.py:999-1011](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/api/openai_realtime/websocket_router.py#L999-L1011)）。原方案新增 4 个 `/internal/*` 端点加一个 B 档注入端点，只说"控制台专用 token"，没有复用现有模式，也没有对应现有的 operator / admin 权限划分。

**L14（P0）装配器重构范围低估**

`_build_handlers` 中存在大量隐式耦合，原方案 P0 未纳入：

- 属性回注：`vad.streaming_stt_sink`、`vad.diarization_worker`、`vad.transcription_window_samples`。
- 按列表位置取 handler：`tts_index = -2 if enable_visemes else -1`（[s2s_pipeline.py:736-745](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/s2s_pipeline.py#L736-L745)）。
- LiveKit local ASR 用 `isinstance` 扫描 handlers（[s2s_pipeline.py:875-879](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/s2s_pipeline.py#L875-L879)）。
- 模型重载用类名后缀定位 handler（[stage_rebuild.py:17-23](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/stage_rebuild.py#L17-L23)），并通过 `getattr(unit, "lm_processed_queue")` 取队列（[stage_rebuild.py:103-108](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/stage_rebuild.py#L103-L108)），而 `PipelineUnit` 并未声明这些字段（[pipeline_unit.py:116-147](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/api/openai_realtime/pipeline_unit.py#L116-L147)）。**需单测确认**：重载后的 handler 可能接到一个新建的空队列。

#### 3.3 可扩展性、体验与工程风险

**E1（P2）跨节点约束没有前置到画布**。如 diarization 要求 STT 存在、采样率与 VAD 一致（[s2s_pipeline.py:504-505](file:///d:/work/qwen-audio-agent/speech-to-speech-src/src/speech_to_speech/s2s_pipeline.py#L504-L505)）。目前只在引擎校验时报错，画布不禁用不兼容选项。

**E2（P2）后端切换时未识别字段一律"将丢弃"**。同名同类型字段可以自动保留。

**E3（P2）未提 i18n、键盘操作、窄屏降级**。console 有 zh-CN / en-US 双语约定；画布在窄屏不可用。

**E4（P1）多实例 / 多机场景缺失**。console 管理多实例，观测帧未带 `instance_id`，画布没有实例选择，发布目标是 profile 而不是实例。

**E5（P2）回放数据无保留策略与隐私开关**。`pipeline_turn_event` 没有量级估算、TTL；payload 含转写文本，应沿用 `log_transcripts` 的门控。

**E6（P2）P0 把引擎重构、配置迁移、编辑器、发布闭环捆在一个里程碑**。风险集中，任何一个环节出问题都会阻塞整条链。

**E7（P2）未覆盖其他接入端**。LiveKit worker（local ASR 直接复用 STT handler）、嵌入式 agent、本地音频客户端都绕过 RealtimeService，直接依赖 `unit.handlers` 的列表结构。

---

## 第二部分　优化后设计方案

### 4. 决策修订摘要

| # | 原决策 | 修订 | 解决的问题 |
|---|---|---|---|
| D1 | v2 把 `blocks` 重命名为 `nodes`，v1→v2 归一化 | v2 是 v1 的**增量扩展**：保留 `blocks` / `pipelines.<id>.stages` / `runtime` / `models`，新增顶层 `nodes:` 放挂接节点 | L2、L3、F10 |
| D2 | 节点目录写在 `parameter-catalog.yaml` 的 `nodes:` 段 | 节点目录放引擎代码（`node_registry.py`），经 `/internal/catalog` 导出；catalog YAML 只放展示元数据 | F9 |
| D3 | `edges` 可选持久化，须等于默认推导 | `edges` 不持久化，恒由目录推导 | L1 |
| D4 | spec 全文存 `param_draft.content` | 新表 `pipeline_draft` 存全文文档；发布仍落 `param_version` / `param_audit` | F5 |
| D5 | 校验只在 `/internal/validate`；`{env}` 只查语法 | 三模式：engine（实例在线，权威）/ runtime（进程内导入）/ structural；结果带 `mode` 与 `engine_version`；`{env}` 保持发布前解析 | F6、L6 |
| D6 | 失败三级 `abort_pipeline / drop_turn / disable_node` | 按生命周期分两段：启动期 `abort_startup / disable_node`；运行期 `fail_turn / skip / pass_through` | L4 |
| D7 | 占位节点启用时静默跳过 | 占位节点 `enabled: true` → 校验错误 | L5 |
| D8 | mock run 在 pipeline 进程内 | mock run 走子进程，带硬超时 | L11 |
| D9 | "零 per-item 开销"的有界指标 | 有界环形缓冲 + 计数器 + 显式丢弃原因钩子；明确列出热路径改动点 | F8、F7 |
| D10 | 控制台专用 token | 复用 `S2S_INTERNAL_TOKEN` fail-closed；只读端点与写端点分开；B 档注入默认关闭 | L13 |
| D11 | 视频为独立 `vlm` 节点 | 视觉是 llm backend 的能力位（`llm_is_vlm`）；节点只保留 `frame_extractor` 与可选 `vision_captioner` | F2、F3 |
| D12 | — | 内部端点、装配器、重载统一走 `PortRegistry` + 角色查找 | L14、E7 |

---

### 5. PipelineSpec v2（修订版）

#### 5.1 结构

```yaml
schema_version: 2

# ── 与 v1 完全相同的部分 ──────────────────────────────
models: {}                      # 同 v1：模型卡 repo_id / default_load_params 覆盖
blocks:                         # 同 v1：主干四阶段的参数块，可被多个 pipeline 共享
  vad:  {kind: vad,  backend: silero,          settings: {min_silence_ms: 450}}
  stt:  {kind: stt,  backend: qwen3-asr,       settings: {qwen3_asr_model_name: {env: S2S_ASR_MODEL_DIR}}}
  llm:  {kind: llm,  backend: chat-completions, settings: {model_name: {env: GPUSTACK_MODEL}}}
  tts:  {kind: tts,  backend: voxcpm,          settings: {voxcpm_tts_streaming: true}}

# ── v2 新增：挂接节点 ────────────────────────────────
nodes:
  diarization:
    type: speaker_diarization
    enabled: true
    attach: {node: vad, point: post}       # 单锚点类型可省略
    settings: {model: {env: DIAR_MODEL_DIR}, dtype: bfloat16}
    on_failure: skip
  visemes:
    type: lipsync
    enabled: true
    attach: {node: tts, point: inline_post}
    settings: {model: {env: S2S_STV_MODEL_DIR}, device: cpu}
    on_failure: pass_through
  frame_extractor:
    type: frame_extractor                  # impl: placeholder
    enabled: false
    attach: {node: vad, point: post}
    settings: {strategy: on_speech_start, max_fps: 1}

runtime:                        # 同 v1
  server: {host: 0.0.0.0, port: 8765}
  livekit_worker: {enabled: true}

pipelines:
  prod:
    stages: {vad: vad, stt: stt, llm: llm, tts: tts}
    num_pipelines: 1
    options: {enable_live_transcription: false}
```

要点：

- **v1 文件不需要迁移即可加载**。不含 `nodes:` 的 profile 保持 `schema_version: 1`。
- **v2 中 `options` 禁用已迁移键**：`enable_visemes`、`stv_model_name`、`stv_device`、`diarization`、`diarization_model_name`、`diarization_revision`、`diarization_device`、`diarization_dtype`、`diarization_streaming_mode`、`diarization_threshold`。它们在 v2 只能以节点形式出现，避免同一能力两种写法。
- **v1 → v2 升级**是纯函数 `lift_v1_to_v2(document) -> (document, changes)`：把上述 options 翻成 `nodes.visemes` / `nodes.diarization`。console 提供"升级预览"，逐项列出变更，确认后才改写文件。
- **console 渲染器保留 base 文件的 `schema_version`**。ParamsView 改一个参数不会把 v1 profile 悄悄改写成 v2；画布编辑要求 v2，未升级时提示升级。

#### 5.2 节点类型目录（首期）

节点目录是引擎代码里的只读注册表，不进 YAML：

| type | impl | 锚点 | 输入 → 输出 | contexts | 启动失败默认 | 运行失败默认 |
|---|---|---|---|---|---|---|
| `speaker_diarization` | `worker` | `vad.post`（分接） | 音频分接 → 富化 `TranscriptionCompletedEvent` | `cancel` | `disable_node` | `skip` |
| `lipsync` | `handler_thread`（**内联**） | `tts.inline_post` | `audio → audio` + viseme 事件 | `cancel`、`text_output_queue` | `pass_through` | `pass_through` |
| `frame_extractor` | `placeholder` | `vad.post` | `video → image_batch` | — | — | — |
| `vision_captioner` | `placeholder` | `llm.pre` | `image_batch → text` | — | — | — |

说明：

- `lipsync` 按真实拓扑定义为内联 handler。画布上用"内联"徽标区分于分接节点，让用户知道它在音频路径上。
- 视觉理解不设独立节点：`llm` backend 的 `llm_is_vlm` 已表达"模型原生看图"。`vision_captioner` 留给不支持多模态的 LLM（帧 → 文字描述 → 注入 prompt），P3 视需求决定是否实装。
- emotion 与 voiceprint 的挂接关系**未在本次评审中核实**（转写事件带 `emotion` 字段，声纹是独立 HTTP 端点）。首期不进节点目录，列为待核实项。

#### 5.3 归约与校验

引擎加载后得到 `ResolvedGraph`：主干四节点 + 按 `attach` 挂接的节点列表。校验输出**结构化诊断列表**，而不是抛出一个异常：

```
Diagnostic { level: error|warning, code: str, path: tuple[str|int,...], message: str, params: dict }
```

| 码 | 触发条件 | 级别 |
|---|---|---|
| `NODE_UNKNOWN_TYPE` | `nodes.<id>.type` 不在目录 | error |
| `NODE_BAD_ANCHOR` | `attach` 不在类型允许的锚点集合 | error |
| `NODE_PLACEHOLDER_ENABLED` | `impl: placeholder` 且 `enabled: true` | error |
| `NODE_BAD_FAILURE_POLICY` | `on_failure` 不在该 impl 的允许集合 | error |
| `NODE_CONTEXT_UNAVAILABLE` | 节点声明的 context 引擎未提供 | error |
| `NODE_DUP_TYPE_SINGLETON` | 单例类型出现多次 | error |
| `NODE_NEEDS_STT` | `speaker_diarization` 启用但 `stt: none` | error |
| `NODE_SR_MISMATCH` | 节点采样率与 VAD 不一致 | error |
| `OPTIONS_KEY_MOVED` | v2 的 `options` 含已迁移键 | error |
| `BACKEND_VISION_REQUIRED` | `frame_extractor` 启用但 LLM 不支持图像输入且无 `vision_captioner` | error |
| `DEPENDENCY_MISSING` | `required_extra` 未安装 | warning |
| `PLATFORM_LIVE_TRANSCRIPTION` | macOS 且 `num_pipelines > 1` 且开启 live transcription（引擎会强制关闭） | warning |
| `ENV_MISSING` | `{env: NAME}` 在合并环境中不存在 | error（runtime / engine 模式） |

`validate_config` 保留现有异常签名（兼容调用方），内部改为 `collect_diagnostics` 后抛出第一条。`/internal/validate` 直接返回完整列表。

`NODE_NEEDS_STT`、`NODE_BAD_ANCHOR` 的规则随 catalog 下发，画布据此禁用不兼容选项（解决 E1）。

---

### 6. 模块划分

#### 6.1 引擎（`src/speech_to_speech/`）

```
pipeline/
  spec/
    document.py      PipelineSpecV2 / NodeEntry 的 Pydantic 模型；key 顺序规范化
    lift_v1.py       lift_v1_to_v2()
    graph.py         ResolvedGraph、derive_edges()、跨节点约束
    diagnostics.py   Diagnostic、collect_diagnostics()
    diff.py          结构级 diff（两份文档 → 节点增删 / backend 变更 / 参数变更）
  node_registry.py   NodeSpec 注册表（type / impl / anchors / ports / contexts / 失败策略 / since）
  ports.py           PortRegistry（unit 持有：命名队列、分接器 Tap）
  assemble.py        assemble_graph()：按 ResolvedGraph 构造 handlers 与连线
  observe/
    metrics.py       有界环形缓冲 + 计数器（替代 _times）
    sampler.py       进程级单线程采样器，遍历所有 unit
    mirror.py        非阻塞镜像队列，满则丢弃并计数
    clock.py         单调钟 ↔ 墙钟锚点对
  dry_run/           python -m speech_to_speech.pipeline.dry_run（子进程入口）
config.py            接受 schema_version 1|2；validate/resolve 同源
baseHandler.py       node_id / unit_index / 有界指标 / 错误计数 / drop 原因钩子
stage_rebuild.py     改用 PortRegistry 与角色查找
api/openai_realtime/
  internal_routes.py /internal/validate|catalog|graph|metrics/stream|mock/*
```

#### 6.2 console 后端（`console/backend/app/`）

```
models/pipeline_draft.py          草稿表
models/pipeline_turn_event.py     turn 帧归档表
routers/pipeline.py               草稿 / 校验 / diff / 发布 / catalog / graph / 事件流 / 干跑
services/pipeline_document_service.py   文档读写、key 规范化、v1→v2 升级预览
services/pipeline_validate_service.py   三模式校验调度
services/pipeline_diff_service.py       调引擎 diff；标注 startup / hot
services/pipeline_metrics_service.py    订阅 SSE、扇出、归档
services/pipeline_dryrun_service.py     触发子进程干跑、收集报告
services/validator_service.py           结构校验与引擎对齐（加 models、nodes）
services/publish_flow_service.py        新增 publish_document() 入口
alembic 迁移 + 重新生成 alembic/sql/init-*.sql
```

#### 6.3 console 前端（`console/frontend/src/`）

```
views/PipelineView.vue
features/pipeline/
  model/types.ts             spec 文档、catalog、诊断、diff 的 TS 类型
  pipeline.viewmodel.ts      纯函数：spec↔画布投影、锚点合法性、路径映射、确定性布局、diff 高亮
  api/pipeline.ts
components/pipeline/
  CanvasTopology.vue         编辑态画布（路由级懒加载 Vue Flow）
  RuntimeTopology.vue        运行态只读拓扑（复用现有 TopoChart / PPipe）
  NodeInspector.vue          参数表单（复用 ParamField）
  TurnSwimlane.vue           泳道时序图（实时 / 回放共用）
  DiagnosticsDrawer.vue      校验错误列表
  PublishChecklist.vue       发布检查清单
i18n/locales/{zh-CN,en-US}/pipeline.ts
```

---

### 7. 接口定义

#### 7.1 console API（`/api/pipeline/*`，需登录）

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| GET | `/catalog` | `?instance_id=` | `{mode, engine_version, node_types[], backends[], constraints[]}` |
| GET | `/draft` | `?profile=` | `{profile, schema_version, base_version, live_version, document, dirty}` |
| PUT | `/draft` | `{profile, base_version, document}` | 200 / 409 `base_version_conflict` |
| POST | `/draft/discard` | `{profile}` | 204 |
| POST | `/validate` | `{profile, document, instance_id?}` | `{ok, mode, engine_version, diagnostics[], checks{}}` |
| POST | `/diff` | `{profile, from, to}` | `{nodes[], params[], requires_restart, hot_applicable[]}` |
| POST | `/upgrade/preview` | `{profile}` | `{document, changes[]}` |
| POST | `/publish` | `{profile, base_version, note, instance_ids?}` | 现有 publish 结果 |
| GET | `/graph` | `?instance_id=` | `{instance_id, spec_hash, schema_version, nodes[], edges[], drift}` |
| GET | `/events` | `?instance_id=&profile=` | SSE，透传引擎帧 |
| POST | `/dry-run` | `{profile, document}` | `{run_id}` |
| GET | `/dry-run/{run_id}` | — | `{status, report?}` |
| GET | `/sessions/{id}/turn-events` | — | 归档 turn 帧 |

`from` / `to` 取 `{version: int}` 或 `{document: object}`，用于"草稿 vs 运行版本""任意两版本"的对比。

#### 7.2 引擎内部端点（`/internal/*`）

鉴权统一：`Authorization: Bearer $S2S_INTERNAL_TOKEN`，未配置 token 时全部返回 503（沿用现有 fail-closed 写法）。

| 方法 | 路径 | 请求 | 响应 |
|---|---|---|---|
| POST | `/validate` | `{yaml_text, environ?}` | `{ok, engine_version, diagnostics[]}` |
| GET | `/catalog` | — | `{engine_version, node_types[], backends[], constraints[]}` |
| GET | `/graph` | — | `{spec_hash, schema_version, nodes[{id,type,impl,backend,enabled,state}], edges[]}` |
| GET | `/metrics/stream` | `Last-Event-ID` 可选 | SSE |
| POST | `/mock/run` | `{yaml_text}` | `{run_id}` |
| POST | `/mock/step` | `{run_id, node_id, action}` | P2 前返回 501 |

`/mock/*` 额外要求环境变量 `S2S_ENABLE_MOCK_INJECT=1`，默认关闭。

#### 7.3 SSE 帧协议

```
hello    {protocol:1, engine_version, instance_id, spec_hash, replay_buffer:512}
graph    {seq, spec_hash, schema_version, nodes[], edges[]}
stats    {seq, ts_mono_ms, ts_wall_ms, unit,
          nodes:[{id, q_in, q_out, last_s, p50_s, p95_s, n, err, state}],
          state: ready|drain|uneven|empty}
turn     {seq, ts_mono_ms, ts_wall_ms, unit, conn_id, node_id?,
          turn_id, rev, response_key?, kind, reason?, detail}
session  {seq, ts_mono_ms, ts_wall_ms, unit, conn_id, state, usage{tokens_in,tokens_out,audio_s}}
ping     {}
```

- 每帧带 `seq` 与 `ts_mono_ms`；`hello` 帧后引擎每 15 s 发一次 `ping`。
- 引擎保留最近 512 条 `turn` 帧的重放缓冲；重连带 `Last-Event-ID` 时先重放，超出缓冲的由 console 从归档补齐，并下发一条 `gap` 帧说明缺口区间。
- 背压：每连接一个有界队列（256）。满时先丢 `stats`，再丢 `session`，`turn` 最后丢且计数。

#### 7.4 turn 帧的 kind 与数据来源

原方案缺的就是这张表。每一类都必须有明确来源，没有来源的要新增钩子：

| kind | 来源 | 是否新增 |
|---|---|---|
| `speech_started` | `SpeechStartedEvent`，`reopened=true` 时 reason=`reopen` | 否 |
| `speech_stopped` | `SpeechStoppedEvent` | 否 |
| `partial_transcription` | `PartialTranscriptionEvent`（节流后镜像） | 否 |
| `stt_final` / `stt_failed` | `TranscriptionCompletedEvent` / `TranscriptionFailedEvent` | 否 |
| `audio_input_completed` | `AudioInputCompletedEvent` | 否 |
| `llm_first_token` | `TurnLatencyTracker.record_llm_ttft` | 新增：回调钩子 |
| `llm_first_tts` | `record_llm_first_tts` | 新增：回调钩子 |
| `tts_first_audio` | `TTSResponseTimer.first_provider_audio` | 新增：回调钩子 |
| `vad_decision` | Smart Turn 判定处 | 新增：回调钩子 |
| `tool_call_ready` | `AssistantToolCallReadyEvent` | 否 |
| `response_done` | `AssistantResponseDoneEvent` + TURN_LATENCY metadata | 否 |
| `response_failed` | `ResponseFailedEvent` | 否 |
| `barge_in` | `RealtimeService` 处理 `speech_started` 触发打断处 | 新增：钩子，带被中断的 `response_key` |
| `cancel` | `handle_response_cancel` | 新增：钩子，带 `cancel_generation` |
| `drop_stale` | `BaseHandler.should_process_input` 返回 False 处 | 新增：只做计数 + 采样上报（每节点每秒最多 1 帧），不逐条发 |
| `node_error` | `BaseHandler._run_loop` 异常分支 | 新增：计数 + 首次错误发帧 |

#### 7.5 数据表

```sql
pipeline_draft (
  id            INTEGER PK,
  profile       VARCHAR(64) UNIQUE NOT NULL,
  base_version  INTEGER NOT NULL,
  schema_version INTEGER NOT NULL,
  document      JSON NOT NULL,          -- v2 文档全文
  updated_by    VARCHAR(64) NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL
)

pipeline_turn_event (
  id                 BIGSERIAL PK,
  instance_id        VARCHAR(64) NOT NULL,
  profile            VARCHAR(64) NOT NULL,
  session_record_id  INTEGER NULL,
  conn_id            VARCHAR(64),
  seq                BIGINT NOT NULL,
  ts_mono_ms         BIGINT,
  ts_wall_ms         BIGINT,
  unit               INTEGER,
  node_id            VARCHAR(64),
  turn_id            VARCHAR(64),
  rev                INTEGER,
  response_key       VARCHAR(64),
  kind               VARCHAR(32),
  payload_json       JSONB,
  PRIMARY KEY (id)
);
CREATE INDEX ON pipeline_turn_event (instance_id, seq);
CREATE INDEX ON pipeline_turn_event (session_record_id, ts_wall_ms);
```

保留策略：按 `ts_wall_ms` 分区或定期删除，默认 14 天，可配置。payload 中转写文本的写入受 `log_transcripts` 门控，关闭时只存事件骨架。

---

### 8. 关键交互流程

#### 8.1 编辑 → 校验 → 发布

1. 进入 `/console/pipeline?profile=prod`。前端加载 catalog 与草稿；无草稿时以 `live_version` 的文档为基线。若存在 ParamsView 的补丁草稿，提示"有未发布的参数草稿"，并在基线上叠加该补丁后显示。
2. 拖入节点 / 切换 backend / 改参数。viewmodel 把改动写成文档操作，防抖 500 ms `PUT /draft`；本地即时校验只做锚点、类型、必填三项。
3. 点"校验"：`POST /validate`。实例在线走 engine 模式；离线走 runtime；包不可导入走 structural，且**拒绝发布**。
4. 点"发布"：先 `POST /diff`，弹窗列出节点增删、backend 变更、参数变更，并标注"需重启 / 可热更"。
5. 确认后 `POST /publish`：
   - 检查 `base_version == live_version`，否则 409。
   - 渲染文档（复用现有 `dump_yaml`，env 类参数仍写入 `.env`）。
   - 走现有 写文件 → 校验 → 重启 → 探活 → 失败回滚 流程。
   - 写入 `param_version`（`yaml_text` 快照）与 `param_audit`。
6. 仅涉及 `effect: hot` 的参数时，清单提供"免重启应用"：调用现有热更流程，并记审计。

#### 8.2 运行观测与漂移对账

1. 页面选定实例后建立 SSE。`hello` 帧带回 `spec_hash`。
2. 前端比较三方的 `spec_hash`：草稿、已发布版本、运行实例。不一致时顶栏显示"运行态与发布版本不一致"，点开看结构 diff。
3. `stats` 帧驱动节点染色与队列深度；`turn` 帧驱动泳道图与"当前 turn 游标"。

#### 8.3 回放

1. 从会话记录进入，按 `session_record_id` 拉取归档 turn 帧。
2. 时钟锚点：会话建立时浏览器上报 `client_t0`，引擎在首个事件回传 `(ts_mono_ms, ts_wall_ms)`；前端以 `ts_wall_ms` 对齐 clip 的播放轴，误差在 ±50 ms 内可接受，超出时显示"对齐不确定"。
3. 泳道组件复用；点击事件跳到 clip 对应时间。

#### 8.4 干跑

1. `POST /dry-run` → console 把文档写入临时文件 → 引擎 `POST /mock/run` → 引擎 `subprocess.Popen` 启动 `python -m speech_to_speech.pipeline.dry_run --spec <file>`，硬超时 60 s。
2. 子进程用同一 `assemble_graph` 装配，模型 handler 换成 mock（延迟取 catalog 区间）。独立的模型监控实例。
3. 输出每节点收发计数、事件序列、预估轮延迟区间，标注"仅验证拓扑"。
4. 子进程异常退出时把 stderr 尾部 4 KB 附在报告里。

---

### 9. 全双工可视化

保持原方案的两个视图，数据源按 §7.4 补齐：

- **泳道时序图**：横轴时间、纵轴 turn / revision。`barge_in` 画剪刀并标注被中断的 `response_key`；`speech_started(reopened)` 画分叉；`drop_stale` 以节点上方的细线计数表示，不逐条画。
- **主干双工光带**：audio 下行与事件上行两条反向光带；节点角标显示正在处理的 `turn/rev` 与队列积压。

新增一条状态带：`LISTENING / SOFT_ENDED / ANSWERING / CLOSED` 直接读取 `TurnPhase`，与 `TurnGateAction`（accept / drop / hold）并列显示。

---

### 10. 边界场景与容错

| 场景 | 处理 |
|---|---|
| 主干节点 `process()` 运行期异常 | `on_failure: fail_turn`：计数，发 `node_error` 帧，发 `ResponseFailedEvent` 收尾当前 response；连续 N 次（默认 3）→ 该 unit 标记 `degraded`，`/v1/pool` 可见 |
| 内联节点（lipsync）运行期异常 | `pass_through`：透传当前条目，发 `node_error`，连续失败后置 `skip=True` 但保持线程在链上（与现状一致） |
| 分接节点运行期异常 | `skip`：丢弃当轮结果；连续失败 → `disable_node`，`graph` 帧状态变 `disabled` |
| 分接节点处理慢于上游 | 分接队列 `maxsize=64`、`put_nowait`，满则丢最旧并计数；永不阻塞主干 |
| `SESSION_END` 到达时分接节点仍有积压 | 分接队列清空；主线上 `SESSION_END` 仍按原路径级联 |
| 模型重载 | `StageRebuilder` 通过 `PortRegistry` 取真实队列，通过角色查找取 handler；重载后校验连线完整性 |
| 占位节点被启用 | 校验错误，画布节点禁用开关并提示"当前引擎版本未实装" |
| 发布时存在在途会话 | 清单显示 `/v1/pool` 的 `in_use`；提供"有会话时阻止发布"开关（默认开） |
| 引擎不支持 v2（旧实例） | `/internal/validate` 返回 `engine_version` 与 `supported_schema: [1]`；console 拒绝发布 v2 并提示升级引擎 |
| 多实例版本不一致 | catalog 按实例缓存；画布顶部显示各实例版本，不一致时告警 |
| 实例离线 | 观测面板显示离线；校验降级到 runtime / structural；禁止发布 |
| SSE 中途断开 | 重连带 `Last-Event-ID`；引擎重放，缺口由归档补；仍缺则发 `gap` |
| console 重启 | 草稿在 DB 中不丢；SSE 自动重连 |
| 文件被手工修改 | 下次 `graph` 帧的 `spec_hash` 与版本不一致 → 漂移提示；发布时 etag + base_version 双重校验 |
| `{env: NAME}` 缺失 | 发布前解析失败，定位到节点字段；错误信息不回显值 |
| macOS + `num_pipelines > 1` + live transcription | 校验 warning，说明引擎会强制关闭 |
| 视频节点启用但客户端没有视频轨 | 运行期 `frame_extractor` 进入 idle，不报错；会话事件里标 `vision: inactive` |

---

### 11. 性能策略

**引擎热路径**（改动点全部列出，可逐项评审）：

| 位置 | 改动 | 成本 |
|---|---|---|
| `BaseHandler._run_loop` emit 分支 | `_times.append` 改为有界环形缓冲（256 槽，存耗时与单调时间戳） | 与现状相同量级的一次写入；内存从无界变为固定 |
| `should_process_input` 返回 False | 计数器 +1；每秒最多镜像 1 帧 | 一次整数加法 |
| `process()` 异常分支 | 计数器 +1、保存最近一条错误摘要、镜像一帧 | 仅异常时发生 |
| 采样器 | 进程级单线程，1 s 周期，读取各 unit 各节点的快照 | 与数据面无锁竞争：快照对象原子替换 |
| 镜像队列 | 有界、非阻塞 `put_nowait` | 满则丢弃，不等待 |

**背压**：主线队列保持无界（不改现状）；分接队列有界丢最旧。

**SSE**：每连接有界队列；`stats` 批量帧；console 扇出前合并同一实例的多个浏览器订阅者，只向引擎开一条连接。

**前端**：泳道图超过 2000 个事件时切换为聚合柱状视图；画布节点数上限 32（目录约束），不需要虚拟化。

**干跑**：子进程，硬超时，不占用在线 unit。

---

### 12. 多端适配

| 维度 | 涉及对象 | 处理 |
|---|---|---|
| 客户端接入端 | WebSocket、WebRTC、本地音频客户端 | 都经 `RealtimeService`，事件与帧来源一致 |
| 接入端（绕过 service） | LiveKit worker local ASR、嵌入式 agent、内嵌 SER | 不再扫描 `unit.handlers` 列表，改用 `unit.by_role("stt")`；装配器保证角色查找对三者一致 |
| 平台 | Linux/CUDA、macOS（MLX 全局锁）、CPU-only、NPU | 校验 warning 反映平台特例；资源徽标按平台取值；无 `nvidia-smi` 时显存预算跳过（现有行为） |
| 部署形态 | split（pipeline:8765 + console:8010）、单进程 | 内部端点地址由现有 `PIPELINE_BASE_URL` 决定；单进程形态走回环 |
| 反向代理 | SSE 经 console 反代 | 响应头 `X-Accel-Buffering: no`、`Cache-Control: no-cache`；心跳 15 s 防空闲断开 |
| 浏览器 | 桌面优先 | 宽度 < 1024 px 时画布降级为节点列表 + 状态徽标；泳道图支持横向滚动 |
| 键盘与读屏 | 画布、检视器、诊断抽屉 | Tab 可达全部节点；节点用 `role="treeitem"`；诊断列表可点击定位 |
| 语言 | 全部界面文案 | zh-CN / en-US 双语，沿用现有 i18n 约定 |

---

### 13. 技术选型

| 项 | 选型 | 理由 | 备选与放弃原因 |
|---|---|---|---|
| 画布库 | Vue Flow | MIT、Vue 3 原生、无重传递依赖；布局受锚点约束，不需要自由画布能力 | 自绘 SVG：节点类型固定，但拖拽、缩放、连线命中要自己写，收益不大 |
| 引擎配置模型 | Pydantic v2 模型 + 现有 dataclass 参数类 | 与 `BackendSpec.config_type` 校验链一致 | JSON Schema 文件：多一份事实源 |
| 结构化诊断 | 自定义 `Diagnostic` 列表 | 需要带 YAML 路径并与 console 现有 `{field, message}` 格式对接 | — |
| 观测传输 | SSE | 单向流、经过反代简单、浏览器原生重连；console 已有 `live_transcripts` SSE 先例 | WebSocket：双向能力用不上 |
| console → 浏览器 | SSE | 同上 | — |
| 干跑 | 子进程 + 同一装配代码 | 隔离 GIL 与全局状态 | 进程内 mock unit：干扰在线会话 |
| diff | 引擎内结构级 diff + console 现有值级 diff | 结构与参数分开展示 | — |
| 存档 | PostgreSQL / SQLite 现有 console 库，JSONB（SQLite 用 JSON） | 不引入新存储 | 时序库：量级不需要 |

---

### 14. 落地路径

每个里程碑可独立合并、独立回滚。

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M0 引擎内部重构（行为不变）** | `PortRegistry`、角色查找、`StageRebuilder` 改造、有界指标、`node_id` 注入 | 现有测试全绿；按 AGENTS.md 跑 Big Bench Audio eval 无回归；重载后连线完整性有单测 |
| **M1 配置模型** | schema_version 2 增量、`lift_v1_to_v2`、`collect_diagnostics`；console 结构校验对齐（加 `models`、`nodes`） | v1 profile 原样加载；v1→v2 升级再降级往返等价 |
| **M2 内部端点** | `/internal/catalog`、`/graph`、`/validate`（含 token fail-closed） | 端点契约测试 |
| **M3 console 后端** | `pipeline_draft`、diff、`publish_document()`、升级预览 | 仿 `test_drafts.py` / `test_publish.py` 的集成测试 |
| **M4 编辑器** | 拓扑画布、检视器、诊断回显、发布清单 | 画布切换 TTS backend、关闭 diarization → 校验 → 发布 → 全链路对话正常 |
| **M5 实时观测** | 采样器、镜像、SSE、泳道图、漂移对账 | 真实会话可见 speech_started → reopen → barge_in → tts_first_audio |
| **M6 回放与干跑** | turn 帧归档、clip 联动、A 档单步、子进程干跑 | 含占位节点的草稿干跑通过；慢会话回放能定位瓶颈 |
| **M7 视频** | 视频上行、`frame_extractor` 实装 | 视频 + 语音混合会话端到端 |

与原方案相比，P0 被拆成 M0–M4 五步：M0 不改任何用户可见行为，先消除隐式耦合，后面的按图装配才有安全的地基。

**风险与缓解**

| 风险 | 缓解 |
|---|---|
| M0 改动全双工核心 | 行为保持；先跑通全部现有测试；音频路径按 AGENTS.md 跑 eval |
| 配置同步回写覆盖 | base_version + etag 双重校验；升级 v2 需预览确认 |
| 观测拖慢热路径 | 改动点逐项列出；有界结构；SSE 断开不影响 pipeline |
| 引擎与 console 版本偏斜 | 结果带 `engine_version`；v2 发布要求引擎声明支持 |
| 泳道数据源缺失 | §7.4 逐项列出来源；未实现的 kind 在前端显示"未采集"而不是空白 |

---

### 15. 待确认事项

以下决策会改变原设计已确认的结论，需要确认后我再合并回原设计文件：

1. **D1**：v2 改为"v1 + `nodes:`"的增量扩展，而不是把 `blocks` 重命名为 `nodes`。这是影响面最大的修订。
2. **D4**：草稿用新表 `pipeline_draft`，而不是扩展 `param_draft`。
3. **D11**：不设独立 `vlm` 节点，视觉作为 llm backend 能力位；只保留 `frame_extractor`（和可选的 `vision_captioner`）。
4. **D8**：干跑从进程内 mock unit 改为子进程。
5. **泳道图范围**：按 §7.4 需要在引擎新增 6 类钩子。是否全部放进 M5，还是 M5 先做已有数据源的 kind？
6. **emotion / voiceprint**：是否纳入首期节点目录？需要先核实它们的实际挂接关系。

**评审中未核实、需要在 M0 前确认的点**

- `StageRebuilder` 重载后是否接到空队列（L14）。
- `docs/parameter-catalog.yaml` 的生成脚本位置，以确认新增展示元数据的正确写入方式。
