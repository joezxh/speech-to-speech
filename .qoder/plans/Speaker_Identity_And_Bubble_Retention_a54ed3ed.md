# 说话人身份绑定与气泡保留策略

## 已确认的决策

| 议题 | 结论 |
|---|---|
| 跨会话身份 | 做，走独立 speaker embedding + console 声纹库（自动认人） |
| 8 条口径 | user / assistant / tool / 语音占位全部计入；正在增量的用户气泡与正在输出/播放的助手气泡受保护；若全部受保护则退化为撤最旧 |
| 占位兜底 | 内容气泡无定时器；仅 `voice` 占位保留 30s 无更新自杀，且命中时同样从最旧端撤 |
| 改造范围 | 先只改 console；demo 保持"3 条 + 定时消失"，差异写入代码注释与文档 |

## 现状基线（不改动，仅引用）

- 分离链路已存在：`src/speech_to_speech/diarization/{streaming,worker}.py`，VAD 在 `VAD/vad_handler.py:870-904` 产出 `PendingSpeakerAttribution`，`STT/base_stt_handler.py:37-40` 在 STT 后解析且不等待。
- 分离结果目前只进 LLM：`pipeline/speaker_metadata.py:31-44` 的 `for_llm()` + `api/openai_realtime/service.py:826-827`；客户端可见转写刻意不含 speaker。
- 扩展事件先例：`api/openai_realtime/input_state.py:16-25` + `runtime_config.py:90-100` + console `s2s-client.ts:341` 的 `providerData.extensions`；console 反代 `console/backend/app/routers/realtime.py` 逐帧透传，新事件类型无需改后端即可到达前端。
- 气泡：`console/frontend/src/features/voice/useBubbles.ts`（上限 3、4s/6s/30s 三档、单一定时器）；`demo/ui/chat.js:154-159` 同等规则（本阶段不动）。

---

## 阶段 A：气泡保留策略（console only）

### A1 `console/frontend/src/features/voice/useBubbles.ts`

- 删除常量 `MAX_VISIBLE`(3)、`DEFAULT_DISMISS_MS`(4000)、`TURN_STOP_MS`(6000)、`TURN_FAILSAFE_MS`(30000)；新增 `export const MAX_VISIBLE_BUBBLES = 8` 与 `const VOICE_FAILSAFE_MS = 30_000`。
- 删除 `expiry` Map、`bump()`、`scheduleReaper()`、`reap()`、`reaperHandle`，以及 `dismiss()` 里的 `expiry.delete`。
- 新增 `let activeAssistantId = 0`：`assistantTranscript()` 新建气泡时写入，`responseFinished()` 命中同一响应时清空。
- `dismiss(id)` 追加两条清理：
  - 遍历 `asstByResp` 删除值等于 `id` 的条目（否则该 response 的后续增量会静默落到一条已经不存在的气泡上）；
  - `activeAssistantId === id` 时归零（`activeId` 归零已有）。
- 新增 `evictToLimit()`：`while (items.value.length > MAX_VISIBLE_BUBBLES)` 取最旧的、且 `id !== activeId && id !== activeAssistantId` 的一条淘汰；若候选全被保护，淘汰 `items.value[0]`。`spawn()` 末尾调用它，替代现有第 127-130 行的 3 条截断。
- `spawnVoice()`：唯一保留定时器的位置——30s 内未 `setText` / 未 `setVoiceState` 则淘汰自己；`setText`、`setVoiceState`、`bump` 替代品均需重置该定时器。
- `userTranscript()`：若 `activeId` 指向的气泡已不在栈上，改为新建而不是 `setText`（保护逻辑的兜底，防丢字）。
- `reset()` 里一并清零 `activeAssistantId` 与占位定时器句柄。

### A2 `console/frontend/src/features/voice/useBubbles.spec.ts`

现有 12 条用例中与计时相关的需改写。目标用例集：

1. 不推进任何定时器，气泡不消失（对应"常驻"）。
2. 连续 10 条后恰好 8 条，且被淘汰顺序为第 1、2 条。
3. 正在增量的用户气泡不被淘汰（沿用并改造现有第 85-96 行用例的意图）。
4. 正在输出的助手气泡不被淘汰，`responseFinished` 后保护解除。
5. 气泡被淘汰后，同一 `responseId` 再来增量会重建一条完整文本的气泡（验证 `asstByResp` 清理）。
6. 语音占位 30s 无更新自杀；被 `setText` 接管后不再自杀。
7. `assistantActivity()` 仍能撤掉占位（保留现有第 71-83 行语义）。
8. `reset()` 清空全部状态与定时器。

### A3 `console/frontend/src/styles/voice.less`

`.v-bubbles`（当前 506-515 行）改为底部锚定，避免 8 条时最新一条被舞台切掉：补 `bottom: 8px`、`justify-content: flex-end`、`max-height: 100%`、`overflow: hidden`。`TransitionGroup` 的 leave 过渡已存在（605-608 行），无需新增动画。

### A4 文档

在 `docs/console-service.md`（或对应语音页章节）记录一条：console 气泡常驻上限 8，demo 仍为 3 条 + 定时消失，属有意分叉。

### A 验收

- 静置 60s 气泡不消失；连续 10 条恒为 8 条；活动气泡不被撤；历史抽屉文本与音频播放不受淘汰影响；`npm run test`（vitest）全绿。

---

## 阶段 B：说话人分离 + 会话内身份绑定

前置：起一台带 `--diarization` 的环境，确认权重可离线预置、日志出现 `Diarization at transcription: speakers=...`、`turn_latency` 无明显抬升、显存有余量。若显存不足，B 降级为"标签可选开启"，C 暂缓。

### B1 服务端：身份注册表 `src/speech_to_speech/pipeline/speaker_identity.py`（新增）

纯逻辑、无 IO，便于单测：

- `SpeakerProfile`：`slot`、`display_name`、`aliases`、`source`（`anon`/`self_intro`/`voiceprint`/`operator`）、`utterance_count`、`last_seen_turn`。
- `SpeakerIdentityRegistry.observe(attribution, transcript) -> SpeakerTurn`：按 `attribution.intervals` 里时长最大的槽位定主导槽位；覆盖率不足或 `available=False` 时返回"无标签"；维护每槽位的发言计数。
- 自报解析：规则式正则（`我是X` / `我叫X` / `我这边是X` / `I'm X` / `My name is X` / `This is X`），命中即取名字，不做 LLM 解析（确定性、零延迟、可单测）。
- 冲突规则（按此顺序判定）：
  1. 槽位未具名 + 自报 → 绑定，`source=self_intro`，置信度 high。
  2. 槽位已具名 A + 自报 B（B≠A）→ 不改名；记 `alias_candidate=B`；本轮前缀标 `[A; 自称 B，待确认]`。
  3. 同槽位连续两轮自报同一新名字 → 改名，A 转 alias。
  4. 两槽位自报同名 → 后者显示 `X (2)`，事件带 `conflict: duplicate_name`。
  5. 本轮重叠（≥2 槽位）且命中自报 → 不绑定，`confidence=low`。
  6. `available=False` → 名字保留但不再更新。
- `format_for_llm()`：有名字用 `[张三] ...`；无名字用 `[speaker_2; 第4句，身份未知] ...`（在第 3 句起追加后半句，驱动模型主动询问一次）。

### B2 服务端：协议事件

- 新增 `src/speech_to_speech/api/openai_realtime/speaker_events.py`，照 `input_state.py` 的风格定义 `SpeechToSpeechInputAudioSpeakerAssignedEvent`（`type="speech_to_speech.input_audio_speaker.assigned"`，字段 `item_id`、`content_index`、`turn_id`、`turn_revision`、`speaker{slot,label,source,confidence,anonymous}`、`overlap{multiple,slots,words_attributed}`、`identity{utterance_index,needs_introduction,conflict}`、`segments[]`）。阶段 C 再追加 `embedding` 字段。
- `api/openai_realtime/runtime_config.py`：新增 `input_audio_speaker_enabled`，读 `session.extensions` 里的 `speech_to_speech.input_audio_speaker`，写法与 `input_audio_transcription_snapshots_enabled`（90-100 行）一致。
- `api/openai_realtime/service.py::_on_transcription_completed`：在 826-827 行处改为调用 registry（先 `observe` 再 `format_for_llm`），并把 speaker 事件插入返回的 `ServerEvent` 列表。registry 实例随 `_state(conn_id)` 存放，`on_session_end` 清空。

### B3 服务端：提示词与参数

- `LLM/voice_prompt.py`：追加一条策略——"同一说话人连续 3 句仍无名字时，主动且仅一次询问对方怎么称呼"。静态写入系统提示，不改动每轮指令（避免破坏缓存）。
- `arguments_classes/module_arguments.py`：新增 `speaker_identity: bool = True`（仅在 `diarization` 为真时生效），并同步 `docs/parameter-catalog.yaml` 的 runtime 段（紧跟现有 `diarization_*` 条目之后）与 `console/backend/tests/integration/test_catalog_api.py` 的期望。
- 注意：本阶段不新增 STT/TTS/VAD handler，故**无需**改动 `backend_registry.py`；分离与嵌入都按 `s2s_pipeline.py:446-460` 构造 `DiarizationWorker` 的既有方式旁路装配。

### B4 console 前端

- `console/frontend/src/features/voice/transport/events.ts`：`apply()` 新增 `speech_to_speech.input_audio_speaker.assigned` 分支，把 speaker 挂到 `u:<item_id>` 条目，合并规则与 audio/latency 一致（`write()` 里透传 `previous.speaker`）。
- `console/frontend/src/features/voice/types.ts`：新增 `SpeakerLabel` 与 `TranscriptEntry.speaker?`、`Bubble.speakerName?`。
- `console/frontend/src/features/voice/transport/s2s-client.ts`：`providerData.extensions`（341 行）追加 `speech_to_speech.input_audio_speaker`，并把该事件转发为 `speaker-assigned` 自定义事件。
- `console/frontend/src/views/VoiceView.vue`：订阅 `speaker-assigned`，转给 `useBubbles.setSpeaker(itemId, label)`。
- `console/frontend/src/features/voice/useBubbles.ts`：新增 `setSpeaker(itemId, label)`，命中 `activeUserId` 时写入当前气泡的 `speakerName`。
- `console/frontend/src/features/voice/components/TranscriptList.vue` 与 `BubbleStack.vue`：role 标签取 `speakerName ?? ROLE_LABEL[role]`。

### B 验收

两人交替 6 轮只出现 2 个稳定标签；说"我叫张三"后下一轮标签变名字且模型能称呼；已具名 A 说"我是 B"时不改名且模型追问；同一人 3 句未报名时模型主动问一次且仅一次；`--diarization` 关闭时前端行为与今天一致；`turn_latency` 的 `stt_s`/`e2e_s` 无显著抬升。

---

## 阶段 C：跨会话声纹库

### C1 服务端：嵌入通路

- 新增 `src/speech_to_speech/speaker/embedding.py`：`SpeakerEmbedder`，默认 `transformers.AutoModelForAudioXVector` + `microsoft/wavlm-base-plus-sv`（零新依赖）；对外只暴露 `embed(audio_16k, sr) -> np.ndarray`（L2 归一化）。模型可换后端时，保持该接口不变。
- 新增 `src/speech_to_speech/speaker/worker.py`：`SpeakerEmbeddingWorker`，有界队列 + 非阻塞；队列溢出或推理失败 → 本次会话停用嵌入（语义对齐 `diarization/worker.py:74-82`）；仅在"单槽位、时长 ≥1s"的句子上计算，重叠句跳过。
- `s2s_pipeline.py::_build_handlers`：按 `--speaker_embedding` 旁路构造（与 446-460 行的 diarizer 同款），参数加 `speaker_embedding`、`speaker_embedding_model_name`、`speaker_embedding_device`、`speaker_embedding_dtype`、`speaker_match_high`、`speaker_match_low`，并同步 `docs/parameter-catalog.yaml`。
- `pipeline/speaker_identity.py`：新增 `match(embedding) -> (profile_id, name, score)`，cosine 双阈值：`score >= speaker_match_high` 认人；`<= speaker_match_low` 判陌生人；中间带返回"待确认"。阈值必须现场标定（先用 20 对真人对做 ROC），代码里给保守默认值并允许 CLI 覆盖。

### C2 服务端：registry 注入与事件

- `runtime_config.py`：解析 `session.extensions` 里的 `speech_to_speech.speaker.registry=<base64 json>`（`[{id,name,embedding}]`）与 `speech_to_speech.speaker.enroll`（是否把本句 embedding 回传）。
- `speaker_events.py`：事件追加 `embedding`（仅当客户端 opt-in `speech_to_speech.speaker.enroll` 时填充）。

### C3 console 后端：声纹库

按 `voices` 的既有范式逐层复制，不发明新结构：

- `app/models/speaker_profile.py`：`id`、`name`、`owner`、`embedding_enc`（BLOB）、`embedding_dim`、`sample_count`、`status`、`created_by`、`consent_ack_at`、`retention_days`（字段形状对齐 `app/models/voice.py:20-45`）。
- `alembic/versions/0006_speaker_profiles.py`：建表 + 唯一约束 + 过期索引。
- `app/repositories/speaker_profile_repository.py`、`app/schemas/speaker_profile.py`、`app/services/speaker_profile_service.py`（加密/解密、保留期、软删）、`app/routers/speaker_profiles.py`（列表/注册/重命名/删除，RBAC 与 `routers/voices.py` 一致）。
- `app/config.py`：新增 `voiceprint_key`（AES-GCM 密钥，生产走 secret 挂载而非明文 env）、`speaker_profile_retention_max_days`。
- `app/routers/realtime.py`：握手后拦截首条客户端 `session.update`，合并注入 `session.extensions`（`speech_to_speech.input_audio_speaker`、`speaker.registry=...`、透传客户端的 enroll 选择），再转发上游。同步更新 `console/backend/tests/integration/test_realtime_proxy.py`（新增"注入后 extensions 合并、原始字段不丢"用例）。
- 删除路径：DELETE 单条 + 用户删除时的级联清理 + 写入既有 audit 记录（`app/repositories/audit_repository.py`）。

### C4 console 前端：声纹库与确认交互

- 新增声纹库页面（列表、注册、重命名、删除、保留期），沿用 `features/voice` 之外的管理页布局。
- 注册流程：先一次显式同意勾选（文案必须说明"声纹属生物特征识别信息"），再把本会话中该槽位的最近 N 句 embedding 提交 `POST /api/speaker-profiles`。
- 会话内："待确认" 或第 3 句未具名时，在气泡下给一个轻量确认条（"这是谁？"），选择即写入会话内 registry，并可选"存为长期声纹"。

### C 验收

同一人两次独立会话被分到同一 profile 并显示名字；未注册者不被误认（用 10 位未注册者测误接受率）；双阈值中间带落到"待确认"而非猜；删除 profile 后下一次会话不再认人；`retention_days` 到期后行被清理；未勾选同意时无法注册；反代注入不改动客户端原有 `session.update` 字段。

---

## 测试与验证

- 阶段 A：`console/frontend` 下 `npm run test`（vitest，`useBubbles.spec.ts`）+ 手工验证 8 条上限与静置不消失。
- 阶段 B：新增 `tests/test_speaker_identity.py`（冲突规则 C1–C6、计数、`format_for_llm`）、`tests/openai_realtime/test_speaker_events.py`（opt-in 开关、事件字段）；回归 `tests/test_streaming_diarization.py`、`tests/test_diarization_worker.py`、`tests/openai_realtime/test_speaker_conversation.py`。
- 阶段 C：`test_speaker_embedding_worker.py`（队列溢出降级、短句跳过、重叠跳过）、`test_speaker_match.py`（双阈值三档）、console 后端 `test_speaker_profiles_api.py` 与 `test_realtime_proxy.py`。
- 全量：根目录 `pytest`、`console/backend` 下 `pytest`、`console/frontend` 下 `npm run test`。

## 假设与前置条件

- 分离模型在目标卡上跑得动（每 pipeline 一份；当前 `num_pipelines=1`）。跑不动时 B 降级为可选开关、C 暂缓。
- `transformers>=5.18` 已满足（`pyproject.toml:52-53`）；分离与嵌入权重需预置到 `cache/` 以支持离线部署。
- demo 前端本轮不改，行为分叉需在文档与注释中显式标注。
- 声纹向量会短暂经过浏览器到 console 后端这一段（注册路径），属可接受但需在文档写明的信任边界；生产环境的密钥管理不在本次实现范围内，仅预留配置项。

## 不在本次范围

- 语音分离（source separation）/ 词级说话人归属（重叠时仍标 `words not attributed`）。
- demo 前端的任何改动。
- 声纹的跨租户共享、批量导入导出。
