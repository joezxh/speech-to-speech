# 声纹嵌入服务（Voiceprint Embedding Service）设计

> 日期：2026-11-12　状态：**设计稿（未实施）**　语言：中文
> 落点：`speech-to-speech-src`（137 语音网关侧）
> 上游设计：`mediation-docs/superpowers/specs/2026-11-04-voiceprint-verify-design.md`（SP-6，跨仓契约在 §3.3 / §6.2）、`mediation-docs/superpowers/specs/2026-11-10-ai-capability-demo-design.md`（调用端 Demo 形态）

---

## 0. 文档定位与阅读指引

### 0.1 本设计要解决什么

SP-6 声纹能力的**平台侧已交付**（24 类、7 端点、3 个 SQL、前端 8 交互区），但**能力侧为 0%**：
137 语音网关（`192.168.1.137:8765`，即本仓 `speech-to-speech` 服务）至今没有
`POST /v1/audio/embeddings` 与 `GET /v1/audio/embeddings/capability` 两个端点。

`mediation-deploy/tools/voiceprint/g0-report-20261106-035456.md` 的实测登记：

| 探测 | 结果 |
|---|---|
| `GET /v1/pool` | HTTP 200，网关主机可达，ASR/TTS 池在线 |
| `GET /v1/audio/embeddings/capability` | HTTP **404** |
| `POST /v1/audio/embeddings` | HTTP **404** → **G0-a 未通过** |
| `POST /v1/audio/transcriptions`（对照） | HTTP 500（业务错误）→ 证明 ASR 端点存在 |

因此 `VOICEPRINT_POC_PASSED=false`、`voiceprint.g0-passed=false`、`voiceprint.enabled=false`，
G1/G2/G3 全部未通过，平台侧以 **fail-closed 双开关**交付。

SP-6 §11.1 的移交表把这条明确归属为**跨仓任务**：

> | 137 embedding 端点实现、模型权重分发、端点持久化、鉴权 | 137 语音服务（跨仓任务） | §3.3 端点契约 ＋ §0.2 四项 G0 取证判据 |

**本设计即该跨仓任务的落地设计**，同时补齐 §11.1 移交表要求的四项内容：端点实现、模型权重分发、端点持久化、鉴权。

### 0.2 与既有文档的关系

| 文档 | 定位 | 本设计的关系 |
|---|---|---|
| SP-6 `2026-11-04-voiceprint-verify-design.md` | 平台侧声纹总体设计（判定规则、门禁、合规） | **上位契约**，本设计只实现 §3.3 / §6.2 的网关侧 |
| `2026-11-10-ai-capability-demo-design.md` | 五项能力独立 Demo 页面 | **调用端设计**，本设计是 `VoiceprintDemo` 的真实模式上游 |
| `mediation-deploy/tools/voiceprint/g0-probe.ps1` | G0-a/b/c/d 取证脚本 | **验收基准**，§9 逐条对齐其判据 |
| `mediation-deploy/tools/voiceprint/smoke-10.4-checklist.md` | §10.4 九步冒烟清单 | **集成验收**，§9.2 说明网关侧如何满足其中 4 步 |
| 本仓 `docs/local-thirdparty-deployment-CN.md` | 本地部署与 ASR/TTS 独立端点 | **同仓先例**：独立端点用构建期补丁注入的机制沿用 |

### 0.3 事实基线（本设计的唯一依据，逐条已核验）

| # | 事实 | 核验方式 | 结论 |
|---|---|---|---|
| F1 | 网关现有独立端点仅 `/v1/audio/transcriptions`、`/v1/audio/speech` | 镜像内 `websocket_router.py` grep | 二者由 `scripts/patch_pipeline_rest.py` 在**构建期**注入 |
| F2 | 网关无 `/v1/audio/embeddings*` 任何形态 | 同上 | 需新增 |
| F3 | `patch_pipeline_rest.py` 可向 `websocket_router.py` 的 FastAPI app 注入新路由 | 读源码 + 本仓实测构建成功 | 复用此机制 |
| F4 | 容器内无 `modelscope` SDK；`transformers`/`torchaudio`/`librosa`/`soundfile`/`numpy`/`fastapi`/`uvicorn` 齐备 | `docker exec … find_spec` | 加载链路**不能依赖 modelscope SDK** |
| F5 | `Qwen/Qwen3-Speaker-Embedding`（SP-6 §3.3 假定的模型名）**在 ModelScope 不存在** | `GET /api/v1/models/Qwen/Qwen3-Speaker-Embedding/repo/files` → `record not found` | **SP-6 的模型名与 192 维均为未验证假设** |
| F6 | `Qwen/Qwen3-TTS-12Hz-1.7B-Base` 存在，`Architectures=Qwen3TTSForConditionalGeneration`，**License=apache-2.0**，`model.safetensors` 3.86GB | ModelScope `repo/files` + 模型元信息 API | 官方同栈可用（G3 第②项许可可落地） |
| F12 | **Base 比 CustomVoice 多 22.9 MiB**（`model.safetensors` 3857413744 B vs 3833402552 B），差额即 `speaker_encoder.*`（ECAPA-TDNN）张量 | 两仓库 `repo/files` 的 Size 字段对比 | 要做声纹**必须用 Base 权重**；CustomVoice 权重不含 encoder |
| F13 | 用 Base 的 config 加载 CustomVoice 的权重 → `speaker_encoder.*` **20 个张量全部 MISSING**（"newly initialized because missing from the checkpoint"）→ 向量是**随机权重**产物，毫无意义 | 容器内实测（`FasterQwen3TTS.from_pretrained` 的 LOAD REPORT） | **禁止**"换 config 不换权重"的省事做法；声纹向量必须来自真正的 Base 权重 |
| F14 | Base config：`tts_model_type="base"`、`speaker_encoder_config={enc_dim:2048, sample_rate:24000}`、`spk_id={}`；CustomVoice config：`tts_model_type="custom_voice"`、`spk_id` 9 个预设音色、`codec_language_id` 多 2 个方言 | 两份 config.json 逐字段对比 | 声纹向量维度预期 **2048**、输入采样率 **24kHz**（非 16k）；统一用 Base 会失去预设音色与 2 个方言 |
| F7 | 本地 `cache/` 只有 `qwen3-tts-model`（CustomVoice），**无 Base 权重** | 目录列举 | 需新增权重分发 |
| F8 | 网关运行在 `speech-to-speech` 容器内（`0.0.0.0:8765`），与 ASR/TTS 同进程 | `docker ps` | 独立端点天然同端口 |
| F9 | 网关**现有端点无鉴权**（ASR/TTS 直连可调） | 实测无 Authorization 头亦返回 200 | 新端点必须单独加鉴权（G0-d 要求） |
| F10 | 本机 RTX 5070 Ti 12GB，ASR+TTS 已占 9.4GB | `nvidia-smi` | 声纹模型须极小或走 CPU |
| F11 | 既有 `/v1/audio/transcriptions` 对 **440Hz 纯正弦波**（g0-probe 的探测音频）返回 **200** + `{"text":"","language":null}`；表单中多余的 `model`/`purpose` 字段被忽略 | 本机实测（复刻 `New-ProbeWav` 生成音频后调端点） | **拒收策略的硬约束**：网关不得拒收"有声但非语音"，否则 G0-a/G0-c 恒失败（§5.3、§9.1） |

### 0.4 差异登记（与 SP-6 原文的差异，先读这里）

| # | SP-6 原文 | 本设计决定 | 差异性质 | 理由 |
|---|---|---|---|---|
| T1 | §3.3 请求含 `model`、`purpose`（`enroll`/`verify`），"服务端据此决定是否允许重复注册" | 保留 `model`（校验并回显），`purpose` **仅作审计标注，不改变网关行为** | **收窄** | SP-6 说服务端据此决定，但网关**无底库**（§6.2 明确禁止在网关做底库逻辑），无法判断"是否重复"；重复注册控制属平台侧 |
| T2 | §3.3 响应含 `dim`，必须等于 `voiceprint.embedding-dim`，`192` 为设计取值 | `dim` 由**启动期实测**并由 `capability` 自报；平台侧以实测值回填配置 | **细化** | F5：`192` 对应模型不存在，维度不可预设；g0-probe.ps1 本身已按"capability 自报为准"设计（R8 注释） |
| T3 | §3.3 响应含 `quality`、`speechDurationMs` | 保留；`quality` 定义为复合技术质量分（§5.4），`speechDurationMs` 为 VAD 有效语音毫秒 | **细化** | SP-6 未定义口径，不定义则平台侧无法解释 |
| T4 | §3.3 "探活复用 `GET /v1/pool`；另增 capability" | `capability` **同样要求 Bearer**（比 g0 脚本更严） | **加严** | 脚本对 capability 始终带鉴权探测，加严不影响取证；避免模型信息与维度被匿名读取 |
| T5 | §8.4 平台侧有界队列 16 / 熔断 5 次 60s / 读超时 3000ms | 网关侧**同步实现等价保护**：独立线程池 + 有界队列 + 推理超时 + 与 ASR 的优先级隔离 | **加严** | G0-c 要求"字幕 ASR 优先"，只靠平台侧保护不足——ASR 就在同进程 |
| T6 | §6.2 "禁止在网关侧新增注册/验证/底库/同意等业务逻辑端点" | 严守：网关只做"一次音频 → 一次向量" | 一致 | — |

---

## 1. 目标与范围

### 1.1 目标

1. 在 137 语音网关提供**两个**端点，使 SP-6 平台侧的 `VoiceGatewayClient.embed()` 与 `getEmbeddingCapability()` 有真实上游可调；
2. 端点行为**逐条满足** `g0-probe.ps1` 的 G0-a/b/c/d 判据，使 G0 可取证；
3. 端点**在容器重建后依然存在**（G0-b），不依赖运行时 `docker exec` 打补丁；
4. 端点**拒绝裸请求**（G0-d），且不因引入声纹能力而削弱现有 ASR/TTS 链路的时延；
5. 音频**不落盘、不入库、不进日志**；日志与响应均不含敏感内容。

### 1.2 非目标（逐条给归属，不留悬空）

| 不做 | 归属与理由 |
|---|---|
| 说话人底库、注册状态、模板存储 | 平台侧（SP-6 §3.4，`ai_voiceprint_template`）；网关无状态 |
| 1:1 / 1:N 比对、相似度计算 | 平台侧（SP-6 §4 判定门）；网关只出向量 |
| 阈值标定（FAR/FRR）、置信度分档 | 平台侧 G1（SP-6 §4.4）；网关**不出** `confidence` |
| 动态口令挑战、防回放、活体检测 | 平台侧（SP-6 §5.5 / §9.5） |
| 质检门业务判定（低 SNR / 重叠语音 → `VP_*` 未知态） | 平台侧（SP-6 §3.7）；网关只做**可判定的技术性拒收**（解码失败/静音/超限） |
| 同意门、留存期、撤回删除 | 平台侧（SP-6 §9） |
| 产出任何身份结论 | 红线：网关响应中**不存在** `verdict` / `confidence` / `matched` 字段 |

### 1.3 职责切分（跨仓边界）

```text
┌──────────────────────── 平台侧（Java，mediation-ai）────────────────────────┐
│ 同意门 → 质检门 → 挑战门 → [调网关 embedding] → 比对门 → 判定门 → 落记录      │
│ 持模板、持阈值、持口令、出结论；零外呼门禁排在最前                          │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ ① GET  /v1/audio/embeddings/capability   （探活 / 门禁）
                │ ② POST /v1/audio/embeddings  (multipart)  （一次音频 → 一次向量）
┌───────────────▼──────── 137 语音网关（本设计，speech-to-speech）──────────┐
│ 鉴权 → 解码归一(16k mono) → 技术性拒收 → 说话人嵌入模型 → {embedding,dim,…} │
│ 无状态、无底库、无结论、无落盘                                              │
└───────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 服务功能范围与边界

### 2.1 功能清单

| 能力 | 说明 | 边界 |
|---|---|---|
| 说话人嵌入提取 | 单段音频 → 固定维度浮点向量（L2 归一化） | 仅单段；多段聚合属平台侧 |
| 有效语音检测 | 输出有效语音毫秒与质量分 | 只做**技术性**判定，不做 SNR/重叠语音的业务结论 |
| 能力探活 | 返回 `dim`/`model`/`ready` | 模型未就绪时 `ready=false`，**不报错**（区别于 5xx） |
| 鉴权 | Bearer Token | 网关侧强制，fail-closed |
| 背压与限流 | 有界队列 + 独立线程池 | 队列满 → 503（`QUEUE_FULL`），不阻塞 ASR |

### 2.2 明确不做的事（技术层面）

| 不做 | 原因 |
|---|---|
| 不做 1:N 检索、不建向量索引 | SP-6 §0.1 约束 2；底库在平台侧 |
| 不在响应中回显原始音频路径、base64、频谱 | SP-6 §3.6 / §9.3 |
| 不返回 `confidence` / `verdict` / `matched` | 网关不出结论 |
| 不做「ASR 文本比对冒充声纹」降级 | SP-6 §8.3 禁止 |
| 失败时**不**回 `200` + 全零/默认向量 | SP-6 §3.3 硬要求（对齐 SP-4 §10.5） |
| 不做模型热切换 | 换模型须改配置并重建，避免 G0-b 语义漂移 |

### 2.3 合规边界

| 约束 | 落地方式 |
|---|---|
| 音频不落盘 | 全链路只在请求期内存：`UploadFile` → `bytes` → `soundfile` 解码 → numpy 数组；不写临时文件 |
| 音频不进日志 | 日志只打 `purpose`/`model`/`dim`/`durationMs`/`quality`/失败阶段；**禁止** `base64`、向量数组、文件名 |
| 向量不进日志 | 只打 `dim` 与 `quality`；禁止打印向量内容 |
| 请求体大小上限 | `≤10MB`（SP-6 §3.3），超限 413 |
| 音频时长上限 | `≤30s`（SP-6 §3.3），超限 422 |
| 请求期内存即释放 | 处理完立即释放引用，不缓存音频 |

---

## 3. 模型选型

### 3.1 候选对比

| 候选 | 状态 | 许可 | 维度 | 与本仓栈的关系 | 结论 |
|---|---|---|---|---|---|
| `Qwen/Qwen3-Speaker-Embedding` | **不存在**（F5，ModelScope API `record not found`） | — | SP-6 假定的 192 无依据 | — | **排除**；模型名与维度须回退重定 |
| `Qwen/Qwen3-TTS-12Hz-1.7B-Base` 的官方 speaker encoder（ECAPA-TDNN） | 存在（F6）；权重比 CustomVoice 多 22.9 MiB（F12） | **apache-2.0** | **2048**（`enc_dim`，F14） | **同栈**（本仓已用 Qwen3-TTS 的 torch 后端） | **首选** |
| 社区从 Base 抽出的 ECAPA 版本 | 存在 | 需逐项核实 | 2048（社区说明） | 同栈 | 备选（许可留档不如官方直接） |
| 第三方通用说话人嵌入（WeSpeaker ECAPA / 3D-Speaker / CAM++） | 存在 | 逐项核实 | 常见 192/256/512 | 需新依赖 | 备选（许可与维护成本更高） |

### 3.2 选型结论

**首选：`Qwen/Qwen3-TTS-12Hz-1.7B-Base` 中的官方 speaker encoder。**

理由：

1. **许可清晰**（apache-2.0），可直接支撑 SP-6 G3 第②项「模型权重商用许可逐项核实、法务留档」；
2. **同栈**：本仓 `TTS/qwen3_tts_handler.py` 已在用 Qwen3-TTS 的 `torch` 后端，`Base` 变体提供 voice cloning（依赖 speaker encoder），权重结构与运行依赖一致；
3. **不引入新依赖**：容器内 `transformers`/`torchaudio`/`librosa` 均已具备（F4），**无需 modelscope SDK**；
4. **规模可控**：可**只加载 speaker encoder 分量**，避免把整个 TTS 塞进常驻显存。

> ⚠️ **CustomVoice 不含 speaker encoder**：只有 `*-Base` 变体支持（voice cloning 依赖它）。
> 必须新增 `Base` 权重分发，不能复用现有 `cache/qwen3-tts-model`。

### 3.3 维度口径与回填流程

| 项 | 规定 |
|---|---|
| 维度来源 | **启动期实测**：首次成功推理后取 `embedding.shape[0]`，写入进程内 `EMBEDDING_DIM`；**预期值 2048**（Base config 的 `speaker_encoder_config.enc_dim`，F14） |
| 自报 | `capability.dim` 返回实测值；`POST` 响应的 `dim` 与 `embedding` 长度恒等 |
| 平台侧回填 | 以 `capability.dim` 为准回填 `voice.gateway.embedding-dim`（g0-probe.ps1 的 R8 注释已如此设计） |
| 漂移防护 | 响应 `dim` 与启动期实测值不一致 → 500 `DIM_DRIFT`，**不截断、不零填充**（SP-6 §8.3） |
| 模型标识 | `model` 返回 `<模型目录名>@<权重修订短哈希>`，含版本，便于平台侧做漂移检查 |

> **实施期第一步必须先实测维度**，再回填平台配置；SP-6 文档中的 192 需在 `mediation-ai` 侧
> 同步订正为实测值（**不在本仓改跨仓文档**，见 §10 R2）。

### 3.4 权重分发与许可（G3 支撑材料）

| 项 | 内容 |
|---|---|
| 权重 | `Qwen/Qwen3-TTS-12Hz-1.7B-Base`；`model.safetensors` sha256 `38fc7fc51c5e776e840414b6fd443962e9411b9654888fd7913e4da643cb857c`（3.86GB）+ `speech_tokenizer/` 682MB；仓库 `StorageSize` 4.54GB |
| 许可 | ModelScope 元信息 `License=apache-2.0` |
| 分发形态 | 挂载 `cache/qwen3-tts-base/`（推荐，便于灰度与许可留档）；或随镜像 `COPY` |
| 离线导入 | 外网机器 `modelscope download` → 打包 → 内网解包到 `cache/`（容器内**不需要** modelscope，见 F4） |
| 留档 | 权重 sha256、许可快照、下载时间、用途说明 → 归档至 G3 留档目录 |

### 3.5 「TTS 与声纹能否统一用一份权重」——三方案对比

背景：本仓 pipeline 已用 CustomVoice 做 TTS（`cache/qwen3-tts-model`）；声纹需要 Base 里的
`speaker_encoder.*`（F12/F13）。Base 与 CustomVoice 是**同一模型家族的两个变体**，
talker 主体完全相同，Base 只多 22.9 MiB 的 ECAPA-TDNN。

| 方案 | 权重与加载 | TTS 行为 | 声纹 | 磁盘 | 显存 | 评价 |
|---|---|---|---|---|---|---|
| **A. 统一用 Base**（一份权重，TTS 与声纹共用同一模型对象） | 目录下放 Base 的 `model.safetensors` + `config.json`；**加载一次**（~30~40s），TTS talker 与 speaker encoder 同属一个模型对象 | ⚠️ `spk_id={}` → **无预设音色**，必须给 `--qwen3_tts_ref_audio` + `ref_text` 走克隆；`codec_language_id` 少 2 个方言（四川话/北京话）；克隆路径的 TTFA 与音质须重测 | 直接取同一模型的 `speaker_encoder`，**零额外加载** | +22.9 MiB（1 份权重） | 无增量 | ✅ **最省**：一份权重、一个模型对象；代价是 TTS 音色模式变更 |
| **B. 两份权重**（CustomVoice 做 TTS + 完整 Base 做声纹） | 两份 3.8GB 各自加载 | 零变更（预设音色 + 方言全保留） | 需完整 Base | +3.86 GB | **+3.8 GB**（talker 重复） | ❌ 本机 12GB 装不下（已占 9.4GB），且白白多加载一次 3.8GB |
| **C. 切分 encoder**（CustomVoice 做 TTS + 从 Base 切出 `speaker_encoder.*` 单独存） | 一次性切分工具把 22.9 MiB 的 `speaker_encoder.*` 另存小权重；声纹服务**只加载它** | 零变更 | 只加载 encoder，无 talker | +22.9 MiB | +46 MB（bf16） | ✅ **最保守**：TTS 行为零风险、声纹不碰 GPU 显存；代价是多一个切分工具与许可再分发确认 |

**推荐**：

- 若业务**接受改用克隆音色**（或本来就需要克隆特定人声）→ **方案 A**。它同时满足"统一一个 TTS 权重"
  与"省一次权重加载"两个诉求，且实现最简单（一份权重、一个模型对象）。
- 若业务**必须保留预设音色 Aiden 与方言** → **方案 C**（不要方案 B：显存装不下且白加载 3.8GB）。
- 无论选哪个，**都不得**"只换 config.json 不换权重"（F13：encoder 会随机初始化，向量无意义）。

> 方案 A 的实施前提：TTS 从 `generate_custom_voice_streaming` 切到 `generate_voice_clone_streaming`。
> 本仓 handler 的分支顺序是 **`_has_voice_clone_reference()` 优先于 `model_type`**，
> 即"给了参考音频就走克隆"——因此方案 A 只需配 `--qwen3_tts_ref_audio` + `--qwen3_tts_ref_text`，
> 并把权重换成 Base 即可，无需改代码。

---

## 4. 对外接口

### 4.1 端点总览

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| `POST` | `/v1/audio/embeddings` | **必需** Bearer | 一次音频 → 一次说话人向量 |
| `GET` | `/v1/audio/embeddings/capability` | **必需** Bearer | 探活：返回 `dim`/`model`/`ready` |

两者均挂在既有 `0.0.0.0:8765`，与 `/v1/realtime`、`/v1/audio/transcriptions`、`/v1/audio/speech` 同端口。

### 4.2 `POST /v1/audio/embeddings`

**请求**：`multipart/form-data`

| 字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | 音频文件；服务端重采样为 16kHz 单声道 |
| `model` | 否 | 模型名；缺省用服务端配置的默认模型；**与配置不符 → 400 `MODEL_MISMATCH`** |
| `purpose` | 否 | `enroll` / `verify`；**仅审计标注**，不改变行为（T1） |

**成功响应** `200`：

```json
{
  "embedding": [0.0123, -0.0345, 0.0067, 0.0211],
  "dim": 1024,
  "model": "qwen3-tts-base-speaker@53a097f",
  "quality": 0.87,
  "speechDurationMs": 9200
}
```

| 字段 | 约束 | 说明 |
|---|---|---|
| `embedding` | 长度 **必须等于** `dim` | L2 归一化后的浮点数组 |
| `dim` | 整数 | 启动期实测值；与 `embedding` 长度恒等 |
| `model` | 非空字符串 | 含权重修订短哈希，供漂移检查 |
| `quality` | `0.0 ~ 1.0` 浮点 | 复合质量分（§5.4），**恒有值**，不返回 `null` |
| `speechDurationMs` | 整数 | VAD 有效语音毫秒 |

> 数组示例只列前 4 个示意值；实际长度必须等于 `dim`（SP-6 §3.3 明确要求）。
> `quality` 必须**非 null**（g0-probe.ps1 判据：`model` 非空白且 `quality -ne $null`）。

**curl 示例**：

```bash
curl -X POST http://127.0.0.1:8765/v1/audio/embeddings \
  -H "Authorization: Bearer $VOICEPRINT_API_KEY" \
  -F "file=@sample.wav" \
  -F "model=qwen3-tts-base-speaker" \
  -F "purpose=verify"
```

### 4.3 `GET /v1/audio/embeddings/capability`

**成功响应** `200`：

```json
{
  "dim": 1024,
  "embedding_dim": 1024,
  "model": "qwen3-tts-base-speaker@53a097f",
  "ready": true,
  "device": "cpu",
  "maxAudioMs": 30000,
  "maxBytes": 10485760
}
```

| 字段 | 说明 |
|---|---|
| `dim` | 实测维度；**未就绪时为 0** |
| `embedding_dim` | 与 `dim` 同值（兼容 g0-probe.ps1 的 `$cj.dim ?? $cj.embedding_dim` 兜底写法） |
| `model` | 模型标识；未就绪时为配置中的默认值 |
| `ready` | 模型已加载且可用；**未就绪返回 200 + `ready=false`，不是 5xx** |

> `ready=false` 的场景：模型懒加载尚未完成、权重缺失、加载失败。
> 平台侧据此把 `available` 置 false 并给真实原因（SP-6 §8.2 门禁公式）。

### 4.4 错误响应

统一结构：

```json
{
  "error": {
    "code": "AUDIO_TOO_SHORT",
    "message": "有效语音不足 800ms",
    "stage": "PREPROCESS",
    "retryable": false
  }
}
```

| 字段 | 说明 |
|---|---|
| `code` | 机器可读枚举（§8.1），平台侧据此映射，**不解析 message** |
| `message` | 人类可读，**不含**音频路径、向量、口令 |
| `stage` | 失败阶段：`AUTH` / `PREPROCESS` / `INFER` / `CAPACITY` / `INTERNAL` |
| `retryable` | 是否可重试（平台侧据此决定是否重试 1 次） |

### 4.5 鉴权

| 项 | 规定 |
|---|---|
| 头 | `Authorization: Bearer <token>` |
| 配置 | `VOICEPRINT_API_KEY`（compose 环境变量）；**未配置 → 端点一律 503 `AUTH_NOT_CONFIGURED`，fail-closed** |
| 校验 | 恒定时间比较（`secrets.compare_digest`） |
| 无凭证 | `401`；凭证不匹配 `403`（满足 G0-d 判据 401/403） |
| 与既有端点关系 | 现有 ASR/TTS 端点**无鉴权**（F9）；新端点单独加鉴权，**不改动既有端点行为**（避免破坏已上线的字幕链路）。若后续统一收口鉴权，另立任务 |

> G0-d 判据："不带凭证重发 → 401/403；若仍 200 则 G3 不得通过"。本设计满足。

### 4.6 限流、超时与背压

| 项 | 值 | 理由 |
|---|---|---|
| 推理超时 | 单请求 `≤ 3000ms`（与平台侧 `embedding-read-timeout=3000` 对齐，SP-6 §8.4） | 超时返回 `504` |
| 队列容量 | `16`，满则 `AbortPolicy` → `503 QUEUE_FULL` | SP-6 §8.4 同值 |
| 线程池 | 声纹**独立**线程池，不与 ASR/TTS 共用 | 避免声纹排队占满主链路 |
| 优先级 | 声纹请求**低于** ASR；ASR 有请求在飞时声纹让行 | SP-6 §8.4「字幕 ASR 优先」 |
| 并发上限 | 声纹并发 `≤ 4`（实施期按实测调） | 保护 G0-c 的 ASR P95 |
| 重试 | 网关侧**不重试** | 重试策略属平台侧（SP-6 §8.4：embedding 最多 1 次） |

---

## 5. 核心流程

### 5.1 注册流程（跨端）

```text
前端                Java(平台)                     网关(137)
 │  录制 3 段 16k mono WAV                              │
 │──────multipart(3 段 + 3 个 challengeId + partyId)──▶│
 │                    │ ① 同意门（VOICEPRINT_VERIFY）  │
 │                    │ ② 质检门（时长/SNR/重叠）      │
 │                    │ ③ 挑战门（ASR 口令一致性）      │
 │                    │ ④ 逐段取 embedding ───────────▶│ POST /v1/audio/embeddings
 │                    │                                 │  purpose=enroll
 │                    │◀──────── {embedding,dim,quality} ┤
 │                    │ ⑤ 内存质量加权均值 → 覆盖写 1 行模板 │
 │◀── 成功/失败（不产身份结论）──────────────────────────│
```

网关在注册链路中的职责**仅**：解一次音频、出一个向量。
质量加权均值、模板覆盖写、3 段的段数与时长约束全部在平台侧（SP-6 §3.4 / §3.6）。

### 5.2 验证流程（跨端）

```text
前端                Java(平台)                     网关(137)
 │  实时录音 或 文件上传                                  │
 │──────multipart(file + partyId + challengeId)────────▶│
 │                    │ ① 同意门 → ② 质检门 → ③ 挑战门  │
 │                    │                                    │
 │                    │ ④ 并行发起（压缩时延）：            │
 │                    ├── ASR 转写 ───────────────────────▶│ POST /v1/audio/transcriptions
 │                    │◀──────────────────────────── text ─┤
 │                    │    取 embedding ──────────────────▶│ POST /v1/audio/embeddings
 │                    │◀──────── {embedding,dim,quality} ──┤  purpose=verify
 │                    │ ⑤ 单次余弦比对（Java 侧）          │
 │                    │ ⑥ 短路判定 → 落记录 → 多态结论      │
 │◀──── {verdict, confidence, quality, evidence, model} ─│
```

与 SP-6 §3.5 的时序一致；**并行**是网络时序，短路判定顺序以 SP-6 §4.1 为准，两者不冲突。

### 5.3 网关侧处理流水线（单次请求）

```text
① 鉴权         Bearer 校验（未配置 → 503）
② 大小/时长闸  >10MB → 413；解码后 >30s → 422
③ 解码归一     soundfile 解码 → 单声道；**声纹 encoder 要求 24kHz**（`speaker_encoder_config.sample_rate`，F14）→ 重采样到 24k
④ 技术性拒收   仅"全静音"（能量低于绝对阈值）→ 409 AUDIO_SILENT
⑤ 有效语音时长 VAD → speechDurationMs（同时参与质量分，不作拒收）
⑥ 质量分       quality = f(有效语音占比, 信噪置信, 削波率)
⑦ 推理         说话人嵌入模型 → 向量 → L2 归一化
⑧ 响应         {embedding, dim, model, quality, speechDurationMs}
```

> ⚠️ **步骤 ④ 的边界（F11 决定）**：`g0-probe.ps1` 的探测音频是 **440Hz 纯正弦波**，不是语音。
> 既有 ASR 端点对该音频实测返回 **200**（空转写），说明"有声但非语音"在本仓属**合法输入**。
> 因此声纹端点**只拒全静音**，**不得**因"检测不到语音"而拒收，否则 G0-a / G0-c 将恒定 4xx、永远无法取证。
> 「无语音 / 低 SNR / 重叠语音」一律是**平台侧质检门**的业务判定（SP-6 §3.7），网关不越界。
> `AUDIO_TOO_SHORT` / `SPEECH_NOT_DETECTED` 保留在错误码表中，但**默认不启用**（严格模式开关关闭）。

### 5.4 质量分口径（`quality`）

| 分量 | 权重 | 说明 |
|---|---|---|
| 有效语音占比 `speechRatio` | 0.5 | 有效语音毫秒 ÷ 总毫秒 |
| 信噪置信 `snrConfidence` | 0.3 | 由噪声底与语音能量估计，映射到 `[0,1]` |
| 削波惩罚 `clippingPenalty` | 0.2 | 削波样本占比越高分越低 |

`quality = clip(0.5·speechRatio + 0.3·snrConfidence + 0.2·(1-clippingPenalty), 0, 1)`

| 区间 | 平台侧参考（**建议初值，须由 G1 标定覆盖**） |
|---|---|
| ≥ 0.7 | 可用 |
| 0.4 ~ 0.7 | 可用但需人工留意 |
| < 0.4 | 平台侧质检门可据此判 `LOW_SNR`（SP-6 §5.6 B1） |

> `quality` 是**技术质量**，**不是**身份置信度。平台侧 `confidence` 只能由阈值标定（G1）产出，
> 且非结论态必须为 `null`（SP-6 §4.2 硬不变量④）。两者不得混用。

---

## 6. 容器化部署

### 6.1 镜像

新增 `Dockerfile.voiceprint`（派生自本仓本地基座，与 `Dockerfile.local.rest` 同构）：

```dockerfile
# FROM 与 Dockerfile.local.rest 保持一致：speech-to-speech-local:cu130-1.2-rest
# 1) 应用声纹端点补丁（构建期注入 → 容器重建后端点仍在，满足 G0-b）
COPY scripts/patch_voiceprint_embeddings.py /tmp/patch_voiceprint_embeddings.py
RUN python3 /tmp/patch_voiceprint_embeddings.py \
    && grep -q "audio/embeddings" /usr/src/app/src/speech_to_speech/api/openai_realtime/websocket_router.py \
    && echo "voiceprint endpoints baked OK"
```

**为什么用构建期补丁而不是独立容器**：

| 维度 | 同进程注入（推荐） | 独立容器 |
|---|---|---|
| 显存 | 声纹分支轻量，与现有 ASR/TTS 同卡可容纳（F10） | 多一份进程与 CUDA context |
| 端口 | 复用 8765，平台侧配置零变更 | 新端口，需改平台配置 |
| G0-b 持久化 | 补丁在镜像层 → 重建后仍在 | 同等满足 |
| G0-c（ASR 优先） | 需同进程内做优先级隔离（T5） | 天然隔离，但**抢同一张卡的 GPU** |
| 部署复杂度 | 低（与既有 ASR/TTS 独立端点同机制，F1/F3） | 高（多服务、多健康检查、多权重挂载） |

> 结论：**同进程注入**，与本仓既有 `/v1/audio/transcriptions`、`/v1/audio/speech` 的做法完全一致，
> 调用端（平台侧）无需新增端口配置。

### 6.2 权重

```text
cache/
├── qwen3-asr-model-hf/            # 既有
├── qwen3-tts-model/               # 既有（CustomVoice）
├── qwen3-tts-base/                # 新增：Qwen3-TTS-12Hz-1.7B-Base（含 speaker_encoder）
└── nltk_data/                     # 既有
```

挂载：复用既有 `./cache/:/root/.cache/` 卷，无需新增卷。

> **目录内容务必整套使用**：Base 目录里的 `config.json`（`tts_model_type="base"` +
> `speaker_encoder_config`）与 `model.safetensors`（含 `speaker_encoder.*`，F12）**必须配套**。
> 不得只换 config（F13：encoder 随机初始化，向量无意义）。
>
> **方案 A（统一一份权重）下**：`qwen3-tts-base/` 即 pipeline 的 TTS 权重目录，
> compose 里 `--qwen3_tts_model_name` 指向它，并补 `--qwen3_tts_ref_audio` / `--qwen3_tts_ref_text`
> 走克隆路径（handler 分支顺序：`_has_voice_clone_reference()` 优先于 `model_type`）。
> **方案 C（切分 encoder）下**：只把 22.9 MiB 的 `speaker_encoder.*` 切出放独立目录，
> pipeline 继续用 CustomVoice（`--qwen3_tts_model_name` 不变）。

### 6.3 compose 集成

在既有编排的 `pipeline` 服务上追加参数（其余保持不变）：

```yaml
    command:
      # … 既有参数保持不变 …
      # —— 声纹嵌入端点（新增）——
      - --voiceprint_embeddings_enabled
      - "True"
      - --voiceprint_embeddings_model_name
      - /root/.cache/qwen3-tts-base
      - --voiceprint_embeddings_device
      - cpu          # ECAPA 分支很轻，CPU 即可；如需 GPU 改 cuda
      - --voiceprint_embeddings_api_key
      - "${VOICEPRINT_API_KEY}"
      - --voiceprint_embeddings_max_audio_ms
      - "30000"
      - --voiceprint_embeddings_min_speech_ms
      - "800"          # 仅参与质量分的有效语音占比计算；**不用于拒收**（F11）
      - --voiceprint_embeddings_strict_reject
      - "False"        # 严格模式：开启后对"检测不到语音"也返回 409（默认关闭）
    environment:
      # … 既有环境变量 …
      - VOICEPRINT_API_KEY=${VOICEPRINT_API_KEY}
```

> 现有 ASR/TTS 端点**不加**鉴权（保持既有行为，避免影响已上线字幕链路）；
> 声纹端点的鉴权在**端点内部**强制（§4.5），与是否开启参数无关。

### 6.4 启动与就绪

| 阶段 | 行为 |
|---|---|
| 启动 | 声纹模型**懒加载**（首次请求触发），不拖长既有 3~4 分钟启动 |
| 首次请求 | 触发加载（数秒），该次请求超时 → `504`；建议平台侧先探活 `capability` 再发业务请求 |
| 就绪后 | `capability.ready=true`；`dim` 为实测值 |
| 加载失败 | `capability.ready=false` + `error` 字段给真实原因；业务请求返回 `503 MODEL_UNAVAILABLE` |

### 6.5 资源预算

| 项 | 预算 | 依据 |
|---|---|---|
| 磁盘 | +4.5GB（Base 权重） | F6 实测 `StorageSize=4.54GB` |
| 显存 | ≤ +0.5GB（仅 speaker encoder 分量；CPU 推理则 ≈0） | 本机 12GB 已用 9.4GB（F10） |
| 内存 | ≤ +1GB | — |
| 单次时延 | P95 ≤ 3000ms | SP-6 §10.2 / G0-c 判据 |

---

## 7. 与调用端设计的对接

### 7.1 平台侧配置项（`VoiceGatewayProperties` 扩展）

| 配置 | 默认 | 说明 |
|---|---|---|
| `voice.gateway.embedding-model` | `qwen3-tts-base-speaker` | 请求 `model` 字段的期望值；与端点不符 → 400 |
| `voice.gateway.embedding-dim` | **留空，实施期按 `capability.dim` 回填** | 平台侧期望维度；不一致 → 判 `UNAVAILABLE`（SP-6 §3.3） |
| `voice.gateway.embedding-read-timeout` | `3000` | 沿用 SP-6 §8.4 |
| `voice.gateway.embedding-connect-timeout` | `5000` | 复用既有 `connectTimeout` |
| `voice.gateway.api-key` | 真实凭证 | **不得沿用 `not-needed`**（G0-d） |

### 7.2 `VoiceGatewayClient.embed()` 契约

```java
// 语义对齐 GW:28-48 既有方法风格
EmbeddingResp embed(String model, String purpose, MultipartFile file);

// 内部顺序（不可调换）：
//   1. 校验 capability.ready（若为 false 直接 UNAVAILABLE，零外呼）
//   2. 有界队列提交（queue-capacity=16，满 → UNAVAILABLE）
//   3. HTTP POST，read-timeout=3000
//   4. 校验 dim == voice.gateway.embedding-dim → 不符 → UNAVAILABLE
//   5. 校验 model 前缀一致 → 不符 → UNAVAILABLE（模型漂移）
//   6. 最多重试 1 次（仅 retryable=true 的错误）
```

**禁止**在客户端做：截断向量、零填充、把拒分类（409/422）当服务故障吞掉、把它当通过。

### 7.3 门禁公式对接

平台侧 `available(VOICEPRINT)` 公式（SP-6 §8.2）不变，本设计只提供其中「端点探活成功」这一项的真实取值：

```text
available(VOICEPRINT) = voiceprint.enabled
                       AND capability.ready == true          ← 本设计提供
                       AND capability.dim == embedding-dim   ← 本设计提供（实测回填）
                       AND g3Passed(VOICEPRINT)
```

`capability.ready=false` 时，平台侧必须给**真实原因**（如「声纹模型未就绪」），不得编造「暂不支持」。

### 7.4 `VoiceprintDemo` 页对接（2026-11-10 Demo 设计）

Demo 适配器当前是**零外呼**回显真实 reason（§4.3 `VoiceprintDemoAdapter`）。本设计落地后：

| 项 | 变化 |
|---|---|
| `status()` | 仍**零外呼**（保持 Demo 纪律：不因能力可用就自动外呼） |
| `run()` | 仍**不接受音频**（Demo 红线：不上传音频）；可增加一个「只读探活」动作，展示 `capability` 的 `dim`/`model`/`ready` |
| 结论 | 仍**不产** `VP_MATCHED`/`VP_MISMATCH`（红线） |
| 文案 | 可明示「137 端点已具备 / G0 是否通过」 |

> 端点具备**不等于**门禁通过。`voiceprint.enabled=false` 与 `VOICEPRINT_POC_PASSED` 仍由运维人工置位，
> 本设计与本仓**均不代置任何门禁位**。

### 7.5 错误映射（网关 → 平台）

| 网关 HTTP | `error.code` | 平台侧映射 | `failStage` | 可重试 |
|---|---|---|---|---|
| 401 / 403 | `UNAUTHORIZED` / `FORBIDDEN` | `UNAVAILABLE` | `AVAILABILITY` | 否（凭证问题） |
| 404 | `NOT_FOUND` | `UNAVAILABLE` | `AVAILABILITY` | 否 |
| 400 | `MODEL_MISMATCH` / `INVALID_REQUEST` | `UNAVAILABLE` | `FEATURE` | 否 |
| 413 | `AUDIO_TOO_LARGE` | `VOICEPRINT_AUDIO_INVALID`(1_040_066_001) | `QUALITY` | 否 |
| 422 | `AUDIO_TOO_LONG` / `AUDIO_UNDECODABLE` | `VOICEPRINT_AUDIO_INVALID`(1_040_066_001) | `QUALITY` | 否 |
| 409 | `AUDIO_SILENT` / `AUDIO_TOO_SHORT` / `SPEECH_NOT_DETECTED` | `VOICEPRINT_AUDIO_INVALID`(1_040_066_001) | `QUALITY` | 否（可重录） |
| 503 | `QUEUE_FULL` / `MODEL_UNAVAILABLE` / `AUTH_NOT_CONFIGURED` | `VOICEPRINT_SERVICE_UNAVAILABLE`(1_040_066_004) | `AVAILABILITY` | 是 |
| 504 | `INFERENCE_TIMEOUT` | `VOICEPRINT_SERVICE_UNAVAILABLE`(1_040_066_004) | `FEATURE` | 是（≤1 次） |
| 500 | `INFERENCE_FAILED` / `DIM_DRIFT` | `VOICEPRINT_SERVICE_UNAVAILABLE`(1_040_066_004) | `FEATURE` | 否（漂移需重注册） |

> 平台侧错误码段 `1_040_066_000–008`（SP-6 §6.5）**不在本仓定义**，本仓只提供 `error.code` 机器可读枚举；
> 映射关系由平台侧实现，本表是双方对齐依据。

---

## 8. 错误处理与返回码规范

### 8.1 网关侧 `error.code` 枚举（穷举）

| code | HTTP | stage | retryable | 触发条件 |
|---|---|---|---|---|
| `UNAUTHORIZED` | 401 | AUTH | 否 | 缺失/空 Bearer |
| `FORBIDDEN` | 403 | AUTH | 否 | 凭证不匹配 |
| `AUTH_NOT_CONFIGURED` | 503 | AUTH | 否 | 服务端未配置 API Key（fail-closed） |
| `INVALID_REQUEST` | 400 | PREPROCESS | 否 | 缺 `file`、表单不合法 |
| `MODEL_MISMATCH` | 400 | PREPROCESS | 否 | `model` 与配置不符 |
| `AUDIO_TOO_LARGE` | 413 | PREPROCESS | 否 | > 10MB |
| `AUDIO_TOO_LONG` | 422 | PREPROCESS | 否 | 解码后 > 30s |
| `AUDIO_UNDECODABLE` | 422 | PREPROCESS | 否 | 解码失败/非音频 |
| `AUDIO_SILENT` | 409 | PREPROCESS | 否 | 全静音（绝对能量低于阈值） |
| `AUDIO_TOO_SHORT` | 409 | PREPROCESS | 否 | **严格模式专用，默认不启用**（见 §5.3 F11 约束） |
| `SPEECH_NOT_DETECTED` | 409 | PREPROCESS | 否 | **严格模式专用，默认不启用** |
| `MODEL_UNAVAILABLE` | 503 | CAPACITY | 是 | 权重缺失/加载失败 |
| `QUEUE_FULL` | 503 | CAPACITY | 是 | 有界队列已满 |
| `INFERENCE_TIMEOUT` | 504 | INFER | 是 | 推理超 3000ms |
| `INFERENCE_FAILED` | 500 | INFER | 是 | 推理异常 |
| `DIM_DRIFT` | 500 | INFER | 否 | 响应维度 ≠ 启动期实测值 |
| `INTERNAL_ERROR` | 500 | INTERNAL | 是 | 未预期异常 |

### 8.2 规范约束（写入单测钉死）

| # | 约束 |
|---|---|
| 1 | 任何失败**不得**返回 `200`；任何成功**不得**返回 4xx/5xx |
| 2 | 失败**不得**返回全零或默认向量（SP-6 §3.3） |
| 3 | 失败响应体**不得**含音频路径、base64、向量数组、口令 |
| 4 | `error.message` **不得**含底层异常原文中的路径/凭据片段（统一映射为固定文案） |
| 5 | `error.code` 必须是 §8.1 枚举之一；未预期异常映射为 `INTERNAL_ERROR` |
| 6 | 响应体**不得**出现 `verdict` / `confidence` / `matched` 字段（网关不出结论，红线） |
| 7 | `embedding` 长度 == `dim` == 启动期实测值 |
| 8 | `capability` 无论就绪与否都返回 `200`（未就绪 → `ready=false`） |
| 9 | 拒收策略**只拒全静音**；不得因"检测不到语音"拒收"有声但非语音"的音频（F11：g0-probe 探测音频即此类） |

### 8.3 fail-closed 原则

| 触发 | 行为 | 禁止 |
|---|---|---|
| 未配置 API Key | 所有声纹请求 503 `AUTH_NOT_CONFIGURED` | 禁止匿名放行 |
| 模型未就绪 | `capability.ready=false`；业务请求 503 | 禁止回 `200` + 空向量 |
| 队列满 | 503 `QUEUE_FULL` | 禁止无限排队拖垮 ASR |
| 维度漂移 | 500 `DIM_DRIFT` | 禁止截断/零填充后返回 200 |
| ASR 满载 | 声纹请求让行或 503 | 禁止让声纹挤占字幕链路 |

---

## 9. 与现有测试要求的一致性

### 9.1 `g0-probe.ps1` 逐条对照

| 探测项 | 脚本判据 | 本设计如何满足 | 残余风险 |
|---|---|---|---|
| **G0-a** 端点可达 | `POST /v1/audio/embeddings` 返回 **200**；`$j.embedding.Count -eq $j.dim`；`$j.dim -eq 192`；`model` 非空；`quality` 非 null | 端点存在并返回上述五项。**探测音频是 440Hz 纯正弦波（非语音）**，故拒收策略只拒全静音（F11、§5.3）；**但 `dim` 实测值大概率 ≠ 192**（F5：192 对应模型不存在） | ⚠️ **脚本会因维度判 G0-a 未通过**——这是**正确行为**：必须先以实测维度回填脚本 `-ExpectedDim` 与平台配置（脚本注释 R8 已如此要求）。**不得**为迎合 192 而截断/零填充向量 |
| **G0-b** 容器重建后仍在 | 重建容器后重发同一请求仍 200 | 端点由**构建期补丁**固化进镜像（§6.1），重建不丢 | 无 |
| **G0-c** 并发容量 | 3×8=24 并发：P95 ≤ 3000ms、5xx=0、超时=0；且**字幕 ASR P95 劣化 ≤ 20%** | 独立线程池 + 有界队列 16 + 并发上限 4 + ASR 优先让行（T5、§4.6） | 需实测调并发上限；模型走 CPU 可完全避开 GPU 争抢 |
| **G0-d** 鉴权 | 不带凭证重发 → **401/403** | 端点强制 Bearer；未配置则 503（**非 200**） | 若运维忘配 Key，脚本得到 503 → 判未通过（符合 fail-closed） |
| **维度漂移**（脚本附加项） | embedding 实测 dim / capability 自报 dim / `-ExpectedDim` 三源一致 | `capability.dim` 与响应 `dim` 同源，恒一致 | 需回填 `-ExpectedDim` |
| **capability** | `GET` 返回 200，且 `dim` 或 `embedding_dim` 可解析 | 返回 `dim` **且**同时返回 `embedding_dim` 别名，兼容脚本的 `??` 兜底 | 无 |

> 脚本用 `$cj.dim ?? $cj.embedding_dim ?? 0` 取值，`??` 需 PowerShell 7+（脚本头已 `#Requires -Version 7.0`）✓。
> 脚本的 G0-c 对照基线把 `model`/`purpose` 一并放进 `/v1/audio/transcriptions` 的表单；
> **实测**（F11）该端点对 440Hz 纯音 + 多余表单字段返回 200 + 空转写，故对照探测不受影响，
> 声纹端点的响应形状也必须做到"对纯音返回 200 + 向量"，否则 G0-a 不可取证。

### 9.2 `smoke-10.4-checklist.md` 九步中网关侧的责任

| 步骤 | 与本设计的关系 | 本设计如何支撑 |
|---|---|---|
| 1 G0 取证 | **直接依赖** | §9.1 逐条对齐 |
| 2 菜单 SQL | 无关 | — |
| 3 `voiceprint.enabled=false` 时 capability 回显 | 平台侧行为 | 网关端点**始终可用**（不随业务开关变化）；开关在平台侧，保证"零外呼" |
| 4 写入有效同意 → 3 段注册 | 依赖 embedding 端点 | 步骤 4~7 的"容器/服务端无音频文件"由 §2.3 内存链路保证 |
| 5 口令核验 | 依赖 ASR 端点（既有） | 声纹端点不参与口令判定 |
| 6 关开关重灌同段 → 零外呼 | 平台侧行为 | 网关不产生记录 |
| 7 播注册音频重放 → `CHALLENGE_FAILED` | 平台侧短路 | 网关**不做**防回放；回放音频仍会出向量，但挑战门在比对前短路（SP-6 §3.5） |
| 8 撤回同意 → 模板零行 | 平台侧 | — |
| 9 三项巡检（容器音频文件数 0、日志 base64 命中 0） | **本设计负责** | 音频不落盘（§2.3）；日志只打字段名与指标，不打 base64/向量 |

### 9.3 巡检与日志纪律

| 巡检项 | 期望 | 本设计的保证 |
|---|---|---|
| 容器内音频文件数 | `0` | 不写临时文件；`find / -name "*.wav"` 应为 0（镜像自带 `ref_audio.wav` 等只读样例除外） |
| 日志命中 `base64` / 音频文件名 | `0` | 日志白名单字段：`purpose`/`model`/`dim`/`durationMs`/`quality`/`stage`/`code` |
| 日志命中向量内容 | `0` | 只打 `dim` 与 `quality`，不打数组 |
| 非结论态 `confidence IS NOT NULL` | `0` | 网关无 `confidence` 字段；平台侧非结论态恒 `null`（SP-6 §4.2 ④） |

### 9.4 本仓需新增的测试

| 类别 | 用例 | 落点 |
|---|---|---|
| 单元 | 鉴权：无 Key / 错 Key / 对 Key → 401 / 403 / 200 | `tests/test_voiceprint_embeddings.py` |
| 单元 | 拒分类：静音 / 过大 / 超长 / 非音频 → 409 / 413 / 422 + 对应 `error.code` | 同上 |
| 单元 | **纯音不拒收**：440Hz 正弦波（复刻 `g0-probe.ps1` 的 `New-ProbeWav`）必须返回 **200 + 向量**，而非 409（F11） | 同上 |
| 单元 | 响应形状：`len(embedding) == dim`；`model`/`quality` 非空；无 `verdict`/`confidence` 字段 | 同上 |
| 单元 | capability：`ready=false` 时仍 200 且 `dim` 为 0 | 同上 |
| 集成 | 真实音频 → embedding 长度与 capability 一致；两次同音频余弦 ≈ 1.0 | 同上（需权重） |
| 集成 | 并发：8 路并发零 5xx、P95 ≤ 3000ms | `scripts/voiceprint_probe.py`（对齐 g0-c 口径） |
| 回归 | 既有 ASR/TTS 端点行为不变（补丁只增路由） | 既有 `tests/test_openai_stt_handler.py` 等用例 |

> 既有补丁脚本 `patch_pipeline_rest.py` 已有幂等检测（`if "rest_transcriptions" in content`），
> 新补丁 `patch_voiceprint_embeddings.py` 沿用同样模式，便于反复构建。

---

## 10. 风险与遗留

| # | 风险 / 遗留 | 影响 | 处置 | 归属 |
|---|---|---|---|---|
| R1 | SP-6 假定的 `qwen3-speaker-embedding` 模型与 192 维**均不存在**（F5） | g0-probe 默认 `-ExpectedDim 192` 会判 G0-a 未通过 | 以实测维度回填脚本参数与 `voice.gateway.embedding-dim`；在 `mediation-ai` 侧订正 SP-6 §3.3 | 本仓（回填参数）+ 平台侧（订正文档） |
| R2 | 跨仓文档仍写 192 与旧模型名 | 两端口径漂移 | 本设计登记 T2；实施完成后向 SP-6 提修订 | 平台侧（文档维护） |
| R3 | Base 权重 4.5GB 需分发 | 交付包变大 | 挂载 `cache/qwen3-tts-base/`，不入镜像层；离线打包分发 | 本仓 + 运维 |
| R4 | 声纹推理与 ASR 争抢资源 → G0-c 劣化超 20% | G0-c 不通过 | 默认 `device=cpu`（不占 GPU）+ 并发上限 4 + ASR 优先让行；必要时调整 | 本仓（实施期实测） |
| R5 | 现有 ASR/TTS 端点无鉴权（F9），与声纹端点有鉴权不一致 | 运维困惑 | 文档明示差异与理由（§4.5）；统一收口另立任务 | 本仓（文档） |
| R6 | G1/G2/G3 门禁未过 | 平台侧仍 fail-closed | 本设计只交付端点与取证条件，**不代置任何门禁位** | 运维 / 法务 / 算法 |
| R7 | `quality` 口径为设计值，未标定 | 平台侧误用为置信度 | 文档明示其为技术质量；G1 标定前不作判定依据 | 算法（G1） |
| R8 | 模型许可留档（Apache-2.0）需法务确认 | G3 ②项 | 归档权重 sha256 + 许可快照 | 法务 |
| R9 | 若采用方案 A（统一用 Base 做 TTS），**预设音色消失、2 个方言不可用**，克隆路径的 TTFA/音质需重测 | 语音品质与方言能力回退 | 业务确认是否接受；不接受则改走方案 C（切分 encoder，TTS 零变更） | 业务 + 本仓 |
| R10 | 若误用「只换 config 不换权重」 | 声纹向量为随机权重产物，**静默错误**（不报错但比对全失效） | 构建期自检：加载后校验 `speaker_encoder.*` 全部命中（不得有 MISSING）；F13 已实证该失效形态 | 本仓（实施期） |

---

## 11. 实施顺序

| 步 | 交付 | 验收 |
|---|---|---|
| 1 | 权重分发到位（`cache/qwen3-tts-base/`，sha256 校验） | `ls` + sha256 一致 |
| 2 | `scripts/patch_voiceprint_embeddings.py`（构建期注入两个路由 + 鉴权 + 质检 + 推理） | 镜像构建日志出现 `voiceprint endpoints baked OK` |
| 3 | `Dockerfile.voiceprint` + compose 参数（§6.3） | 容器启动无回归；既有 5 项验证全绿 |
| 4 | **实测维度**并回填：脚本 `-ExpectedDim`、平台 `embedding-dim` | `capability.dim` == 实测 == 配置 |
| 5 | 单元/集成测试（§9.4） | 全绿 |
| 6 | **G0 取证**：`g0-probe.ps1 -ApiKey '<real>'` → 四项全「通过」 | 生成 `g0-report-<ts>.md` 归档 |
| 7 | 重建容器后 `-AfterRebuild` 复测 G0-b | 报告四项仍全通过 |
| 8 | 平台侧 `VoiceGatewayClient.embed()` 接线 + 配置项 | 平台侧单测与联调通过 |
| 9 | 交付 `mediation-deploy/tools/voiceprint/` 取证报告与本文 | 归档到实施前置证据目录 |

> 第 6~7 步**必须**在平台侧 `voiceprint.enabled=true` **之前**完成；
> 第 8 步的接线**不解除**任何门禁（`VOICEPRINT_POC_PASSED` 仍由运维人工置位）。

---

## 12. 附录

### 12.1 配置项总表

| 位置 | 变量 | 默认 | 说明 |
|---|---|---|---|
| compose（command） | `--voiceprint_embeddings_enabled` | `False` | 端点总开关；关闭时两个端点均 404（平台侧据此得 `UNAVAILABLE`） |
| compose（command） | `--voiceprint_embeddings_model_name` | `/root/.cache/qwen3-tts-base` | 权重目录（容器内） |
| compose（command） | `--voiceprint_embeddings_device` | `cpu` | `cpu` / `cuda` |
| compose（command） | `--voiceprint_embeddings_api_key` | 空 | **空则端点 503（fail-closed）** |
| compose（command） | `--voiceprint_embeddings_max_audio_ms` | `30000` | 时长上限 |
| compose（command） | `--voiceprint_embeddings_max_bytes` | `10485760` | 大小上限 |
| compose（command） | `--voiceprint_embeddings_min_speech_ms` | `800` | 有效语音下限，**仅参与质量分，不用于拒收**（F11） |
| compose（command） | `--voiceprint_embeddings_strict_reject` | `False` | 严格模式：开启后"检测不到语音"也返回 409（默认关闭，避免与 g0-probe 冲突） |
| compose（command） | `--voiceprint_embeddings_queue_capacity` | `16` | 有界队列容量 |
| compose（command） | `--voiceprint_embeddings_max_concurrency` | `4` | 并发上限 |
| compose（command） | `--voiceprint_embeddings_infer_timeout_ms` | `3000` | 推理超时 |
| 平台（`application.yaml`） | `voice.gateway.embedding-model` | `qwen3-tts-base-speaker` | 请求 `model` 期望值 |
| 平台 | `voice.gateway.embedding-dim` | **待实测回填** | 与 `capability.dim` 一致 |
| 平台 | `voice.gateway.embedding-read-timeout` | `3000` | 读超时 |
| 平台 | `voice.gateway.api-key` | **真实凭证** | 不得沿用 `not-needed`（G0-d） |

### 12.2 新增文件清单（实施期）

| 文件 | 说明 |
|---|---|
| `scripts/patch_voiceprint_embeddings.py` | 构建期注入两个路由（沿用 `patch_pipeline_rest.py` 的幂等模式） |
| `Dockerfile.voiceprint` | 派生镜像：应用声纹补丁 + 自检行 |
| `src/speech_to_speech/voiceprint/__init__.py` | 包声明 |
| `src/speech_to_speech/voiceprint/embedder.py` | 模型加载 + 推理 + L2 归一化 |
| `src/speech_to_speech/voiceprint/preprocess.py` | 解码、16k 归一、有效语音检测、质量分 |
| `src/speech_to_speech/voiceprint/errors.py` | `error.code` 枚举与 HTTP 映射 |
| `src/speech_to_speech/arguments_classes/voiceprint_arguments.py` | CLI 参数（对应 §12.1） |
| `tests/test_voiceprint_embeddings.py` | 单元 + 集成测试（§9.4） |
| `scripts/voiceprint_probe.py` | 并发与时延自测（对齐 g0-c 口径） |
| `scripts/extract_speaker_encoder.py` | **方案 C 专用**：从 Base 的 safetensors 抽出 `speaker_encoder.*` 另存小权重（22.9 MiB）；含 MISSING 自检 |
| `docs/voiceprint-embedding-service-design-CN.md` | 本设计 |

### 12.3 手工验证命令速查

```bash
# ① capability（带凭证）
curl -s -H "Authorization: Bearer $VOICEPRINT_API_KEY" \
  http://127.0.0.1:8765/v1/audio/embeddings/capability

# ② 生成 embedding
curl -s -X POST http://127.0.0.1:8765/v1/audio/embeddings \
  -H "Authorization: Bearer $VOICEPRINT_API_KEY" \
  -F "file=@sample.wav" -F "purpose=verify" | head -c 200

# ③ 裸请求（应 401/403，G0-d）
curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST http://127.0.0.1:8765/v1/audio/embeddings -F "file=@sample.wav"

# ④ 官方取证脚本（四项一次跑完）
#    ./g0-probe.ps1 -ApiKey '<real-key>' -BaseUrl 'http://192.168.1.137:8765'
#    重建容器后： ./g0-probe.ps1 -ApiKey '<real-key>' -AfterRebuild
```

### 12.4 与本仓既有文档的关系

| 本仓文档 | 关联点 |
|---|---|
| `docs/local-thirdparty-deployment-CN.md` §4 | 同款"独立端点"机制的部署写法（构建期补丁 + 端点清单） |
| `docs/local-thirdparty-deployment-CN.md` §5 | ASR/TTS 独立接口的调用示例（本设计的调用方式与其同构） |
| `docs/private-deployment-manual-CN.md` §7 | 换模型与权重离线导入的通用做法（本设计的权重分发沿用） |
| `docs/private-deployment-manual-CN.md` §9.2 | 故障速查表（新增声纹条目） |




---

## 13. 实施记录（2026-11-12，方案 C）

### 13.1 落地形态

最终按 §3.5 的**方案 C**落地：**TTS 继续用 `Qwen3-TTS-12Hz-1.7B-CustomVoice`**（预设音色，首音 1.85s），
声纹侧只加载从 Base 权重切出的 **22.9 MiB speaker encoder** —— 不加载 talker、不占显存、不改变 TTS 行为。

> **为何不是方案 A**：方案 A（一份 Base 权重同时做 TTS + 声纹）功能成立、声纹性能达标，
> 但 Base 权重**没有预设音色**，TTS 必须走参考音频克隆路径，实测首音 **37s**（CustomVoice 为 1.85s）、
> RTF 0.03 → 语音合成不可接受。故生产采用方案 C，声纹与 TTS 各自独立、互不干扰。

| 交付物 | 路径 |
|---|---|
| 派生镜像 | `Dockerfile.voiceprint` → `speech-to-speech-local:cu130-1.3-voiceprint` |
| 增量重建 | `Dockerfile.voiceprint.hotfix`（基座已被清理时只覆盖 `voiceprint/` 模块） |
| 编排 | `docker-compose.voiceprint.yml`（与 `docker-compose.thirdparty.yml` 仅三处差异） |
| 端点注入 | `scripts/patch_voiceprint_embeddings.py`（构建期固化，满足 G0-b） |
| 服务实现 | `src/speech_to_speech/voiceprint/{__init__,errors,preprocess,embedder,service,standalone}.py` |
| 权重切分 | `scripts/extract_speaker_encoder.py` → `cache/qwen3-speaker-encoder/` |
| 自测脚本 | `scripts/voiceprint_probe.py`（capability / 鉴权 / 单次 / 并发 P95） |
| 单元测试 | `tests/test_voiceprint_embeddings.py`（25 例） |

### 13.2 权重分发

`cache/qwen3-tts-base/` 由 `modelscope download --model Qwen/Qwen3-TTS-12Hz-1.7B-Base` 得到，
`model.safetensors` = 3,857,413,744 B（与官方一致，比 CustomVoice 多 22.9 MiB，即 `speaker_encoder.*`）。

### 13.3 实施中踩到的两个真实问题

| # | 问题 | 根因 | 处置 |
|---|---|---|---|
| 1 | 容器启动即 `ModuleNotFoundError: No module named 'speech_to_speech.console_integration'` | 派生镜像曾用宿主工作树的 `s2s_pipeline.py` 覆盖基座文件，而基座镜像（cu130-1.1）**不含 console 模块**，宿主版本已引入该依赖 | 不再覆盖 `s2s_pipeline.py` / `module_arguments.py`；声纹配置**统一走环境变量**（补丁层读取），不经过 CLI 参数 |
| 2 | `POST /v1/audio/embeddings` 返回 500 `INFERENCE_FAILED` | speaker encoder 需要**批量维**：传 1D 波形触发 `IndexError: Dimension out of range (expected to be in range of [-1, 0], but got 1)` | encoder 调用改为 `(批量维 × 签名 × dtype)` 组合试探，失败才报错 |

> 问题 2 说明：**"模型里有个 encoder"不等于"能直接调用"**，必须实测其调用契约。

### 13.4 配置口径（与 §12.1 的差异）

声纹端点的配置**只走环境变量**（`VOICEPRINT_*`），不提供 CLI 参数。原因见 §13.3 问题 1：
端点由构建期补丁注入到 `create_app()`，而该函数拿不到 `ModuleArguments`；
若为支持 CLI 而覆盖基座的 `s2s_pipeline.py`，会引入基座缺失的 console 依赖。

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `VOICEPRINT_ENABLED` | `false` | 关闭时**不注册路由**（端点 404） |
| `VOICEPRINT_API_KEY` | 空 | **空则端点 fail-closed（503 AUTH_NOT_CONFIGURED）** |
| `VOICEPRINT_MODEL` | 空 | 请求 `model` 的期望值；不匹配 → 400 `MODEL_MISMATCH` |
| `VOICEPRINT_MAX_AUDIO_MS` | `30000` | 时长上限 |
| `VOICEPRINT_MAX_BYTES` | `10485760` | 大小上限 |
| `VOICEPRINT_MIN_SPEECH_MS` | `800` | **仅参与质量分，不用于拒收**（F11） |
| `VOICEPRINT_STRICT_REJECT` | `false` | 严格模式：无声也 409 |
| `VOICEPRINT_QUEUE_CAPACITY` | `16` | 有界队列，满 → 503 `QUEUE_FULL` |
| `VOICEPRINT_MAX_CONCURRENCY` | `4` | 并发上限（保护 ASR 时延，G0-c） |
| `VOICEPRINT_INFER_TIMEOUT_MS` | `3000` | 推理超时，超时 → 504 |

### 13.5 已验证项

| 项 | 结果 |
|---|---|
| 声纹与 TTS 解耦（方案 C） | ✅ 日志 `voiceprint: loaded standalone speaker encoder from ... (dim=2048)` |
| 鉴权（G0-d） | ✅ 无凭据 → **401** |
| capability | ✅ 200，返回 `dim=2048`/`model`/`ready=true`/`device` |
| 单元测试 | ✅ **25 passed**（鉴权/拒分类/纯音不拒收/响应形状/维度一致/方案 C 就绪与启动期定维/预热） |
| 纯音不拒收（F11） | ✅ 440Hz 纯音返回 200 + 向量，未被 409 拒收 |
| 并发容量 | ✅ 24 样本（8 并发 × 3 轮）5xx=0、超时=0，**P95 871ms**（预算 ≤3000ms） |

#### 单测的运行方式（2026-11-13 复测补充）

宿主机直接 `pytest` 会因**缺依赖**大面积失败（`soundfile` / `librosa` 缺失，
抛 `ModuleNotFoundError` 而非断言失败），这是环境问题、**不是实现缺陷**。两种正确跑法：

```bash
# ① 容器内跑（依赖齐备，推荐）
docker cp tests/test_voiceprint_embeddings.py <pipeline>:/tmp/test_vp.py
docker exec -w /usr/src/app <pipeline> /usr/src/app/.venv/bin/python3 -m pytest /tmp/test_vp.py -q
# → 25 passed in 4.96s

# ② 宿主机跑（需自行补齐依赖，且要指到源码树）
pip install soundfile librosa
PYTHONPATH=src python -m pytest tests/test_voiceprint_embeddings.py -q
```

> 容器镜像默认**不含 pytest**（`ModuleNotFoundError: No module named 'pytest'`），
> 需临时 `pip install pytest` 到运行中容器（不写入镜像层，重启即失效）；
> 单测不加载真实模型（用 `FakeEmbedder`），因此无需 GPU。
> 容器内 `speech_to_speech` 解析到 `/usr/src/app/src/speech_to_speech`，
> 即镜像已包含 `voiceprint` 包（`Dockerfile.voiceprint` 复制自工作树）。


### 13.6 speaker encoder 的真实调用契约（读源码实测，勿凭猜）

| 项 | 实测结论 | 依据 |
|---|---|---|
| 入口 | `model.extract_speaker_embedding(audio, sr)` —— **官方封装**，不要直接调 encoder | `qwen_tts/core/models/modeling_qwen3_tts.py:1950` |
| 入参 | `audio` = numpy float32 **一维**波形；`sr` **必须 24000**（内部 `assert sr == 24000`） | 同上 |
| 内部流程 | mel 频谱（n_fft=1024, num_mels=128, hop=256, fmax=12000）→ ECAPA-TDNN → 取 batch 0 | 同上 |
| 返回 | 形状 `(enc_dim,)` 的向量 | 同上 |
| 维度 | 官方配置默认 **192**；Base 权重实际 `enc_dim=2048` | `configuration_qwen3_tts.py:21` / Base `config.json` |
| **陷阱** | 直接调 `speaker_encoder.forward(waveform)` 会抛 `IndexError: Dimension out of range (expected to be in range of [-1, 0], but got 1)` —— 它吃的是 mel 频谱 `(B,T,mel_dim)`，不是波形 | 实测两次失败后读源码定位 |

> 结论：**"模型里有个 encoder"不等于"能直接调用"**。声纹接入必须走官方封装，
> 并按其要求准备 24kHz 波形（`preprocess.TARGET_SR = 24000` 已对齐）。

### 13.7 2026-11-13 复检：修复三个真实缺陷（并纠正文档与实现的冲突）

复检方式：`scripts/voiceprint_probe.py` 对运行容器做 capability / 鉴权 / 单次 / 并发四类探测，
配合 `pytest` 单测。发现**三个真实缺陷**与**一处文档-实现冲突**，全部已修复并回归：

| # | 问题 | 根因 | 影响 | 处置 |
|---|---|---|---|---|
| 1 | `capability.ready` 恒为 **false** | `SpeakerEmbedder.ready` 只判 `_extractor`（方案 A 的官方封装），而方案 C 绑定时显式置 `_extractor=None` | 服务实际可用，但调用端若以 `ready` 做门禁 → **全量拒绝** | `ready` 改为 `_extractor is not None or _encoder is not None` |
| 2 | 冷启动 `capability.dim` 为 **0** | `dim` 只在首次成功推理后确定 | 冷启动后首个探活拿不到维度 | 启动期定维：方案 C 从切分目录 `config.json` 的 `enc_dim` 读，方案 A 从模型 config 读 |
| 3 | **首请求 26.4s**（后续 <2s） | 解码/重采样走 librosa/numba，**首次调用触发 JIT 编译**；3s 推理超时只覆盖 `future.result(...)`，覆盖不到这段预处理 | 调用端（网关通常 3~5s 超时）首请求必然超时 | 服务启动期**预热**（`VoiceprintService.warmup()`，在 `attach_pool` 末尾调用），把 25s 成本前置到启动期 |
| 4 | 文档 §13.1/§13.5 写的是**方案 A** | 实施过程实际改用方案 C（Base 无预设音色 → 克隆路径首音 37s，生产不可用） | 文档与运行形态不符，误导后续维护 | 全文改为方案 C，并补记"为何不是方案 A" |

修复后实测（容器内实跑）：

```
capability   → {"dim":2048,"embedding_dim":2048,"model":"standalone-speaker-encoder@qwen3-speaker-encoder","ready":true,...}
无凭据        → HTTP 401
首请求        → HTTP 200，**139 ms**（修复前 26436 ms）
并发 24 样本（8 并发 × 3 轮）→ 5xx=0，超时=0，P95 884ms（预算 ≤3000ms）
启动日志      → voiceprint: loaded standalone speaker encoder from ... (dim=2048)
                voiceprint: warmup done
单元测试      → 25 passed（新增 8 例：方案 C 就绪、启动期定维、预热）
```

> 修复 #3 的**判据**值得记住：客户端观察到的耗时与 `infer_timeout_ms` 不匹配时，
> 先看耗时落在 `future.result()` 之外还是之内 —— 之内是推理超时，之外是**预处理惰性成本**。

#### 部署经验：基座镜像被清理后的增量重建

完整构建 `Dockerfile.voiceprint` 依赖基座 `speech-to-speech-local:cu130-1.1-sox`，
该镜像 11.8GB 常被 Docker 自动清理 → 构建退化为联网拉取并失败
（`dial tcp 104.23.125.189:443: connectex: connection attempt failed`）。

只改 `src/speech_to_speech/voiceprint/` 下的实现时，用 `Dockerfile.voiceprint.hotfix`
从已含全部端点补丁的镜像增量重建（端点补丁无需重打，幂等检测本来也会跳过）：

```bash
docker tag speech-to-speech-local:cu130-1.3-voiceprint speech-to-speech-local:cu130-1.3-voiceprint.bak
docker build -f Dockerfile.voiceprint.hotfix -t speech-to-speech-local:cu130-1.3-voiceprint.new .
docker tag speech-to-speech-local:cu130-1.3-voiceprint.new speech-to-speech-local:cu130-1.3-voiceprint
docker rmi speech-to-speech-local:cu130-1.3-voiceprint.new
docker compose -f docker-compose.voiceprint.yml --env-file .env.thirdparty up -d --force-recreate
```

> 若改动了 `scripts/patch_*.py` 或基座相关文件，仍须用 `Dockerfile.voiceprint` 完整重建。
