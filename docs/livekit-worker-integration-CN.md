# LiveKit 房间转写 worker 集成说明

`speech_to_speech.livekit_worker` 是从 `mediation-deploy/livekit-worker` 工程迁移而来的房间转写子系统：以参会者身份进入 LiveKit 房间，订阅远端音频轨，VAD 切段后调用可插拔 ASR/SER Provider 转写与标注，结果经**双路输出**（进程内事件总线 + 可配置回调子系统）分发。本文档描述迁移后的开关、环境变量、与源工程的差异及版本约束；回调投递细节见 [callback-subsystem-CN.md](./callback-subsystem-CN.md)。

## 1. 架构总览

```
serve 进程（speech-to-speech serve --with-livekitworker [--with-console]）
│
├─ 主 pipeline（ThreadManager 线程）
│    VADAudio ─▶ BaseSTTHandler.process() ─▶ LLM ─▶ TTS ─▶ Realtime API
│         │
│         └─(local ASR 模式)─ SttHandlerAdapter ──attach──▶ LiveKitWorkerRuntime
│
├─ LiveKit worker 线程（LiveKitWorkerRuntime.run()：专用线程 + 专用 asyncio loop）
│    livekit-agents WorkerServer（健康检查 HTTP :LIVEKIT_WORKER_HEALTH_PORT，默认 18081）
│      └─ entrypoint：被 LiveKit 服务端 dispatch 后进房 → 逐轨订阅音频
│           silero VAD 切段 → diarization 主路径（可选）/ 整段回退
│             → ASR（gateway | local）+ SER（段长/断路/并发/开关四道门）
│             → emit_segments ──┬─▶ ① TranscriptEventBus（进程内单例总线）
│                               └─▶ ② CallbackDispatcher.publish_transcript
│
├─ console 后端（--with-console 同进程合并）
│    SSE GET /api/v1/live-transcripts/stream ──订阅①──▶ 前端「回调管理」页实时字幕
│    /api/v1/callbacks（targets CRUD / batch / test / logs，见回调文档）
│
└─ CallbackDispatcher（进程级单例，线程池异步投递）
     TTL 5s 热加载 DB callback_target
       ├─ java 目标：POST {base_url}/admin-api/ai/meeting/internal/transcript?roomSid=…
       └─ python 目标：POST {base_url}（统一事件 JSON）
     DB 不可用/查询失败 ─▶ env 兜底（JAVA_CALLBACK_BASE + MEETING_INTERNAL_TOKEN → 内存 java 目标）
     每次投递尝试写一行 callback_delivery_log
```

事件流向要点：

- 转写分段同时进入 ① 事件总线（console 实时字幕、进程内日志 sink）与 ② 回调子系统（DB 配置的 java/python 目标）；任一路失败仅告警，不阻断另一路。
- worker 线程与主 pipeline 通过 `ThreadManager` 共享同一个 `stop_event`：停机时 `ThreadManager.stop()` 置位信号，`LiveKitWorkerRuntime.run()` 收尾专用 loop 后线程退出；`_serve()` 协程内的任何异常（含 livekit 未安装的 ImportError）由 `_log_serve_crash` 记录，**绝不拖垮语音主流程**。
- worker 进房是被动的：只完成注册，必须由服务端调 LiveKit `CreateDispatch`（`agent_name` 与 `LIVEKIT_AGENT_NAME` 一致，默认「会议秘书」）派发 job。

## 2. 开关与环境变量全表

以下名称与默认值均以本仓实现为准（`worker_integration.py`、`livekit_worker/worker.py`、`asr_provider.py`、`ser_provider.py`、`diarization_provider.py`、`callback/dispatcher.py`）。

### 2.1 启动开关（serve 前缀参数）

| 开关 | 环境变量兜底 | 默认 | 语义 |
|---|---|---|---|
| `--with-diarization` / `--no-with-diarization` | `DIARIZATION_AUTOSTART` | off | 为主 pipeline 启用既有流式说话人分离（映射 `module_kwargs.diarization`，不新增子系统） |
| `--with-livekitworker` / `--no-with-livekitworker` | `LIVEKIT_WORKER_AUTOSTART` | off | 在 serve 进程内启动 LiveKit 房间转写 worker 线程 |

- 布尔值接受 `1/true/yes/on` 与 `0/false/no/off`（空串视为 false）；非法值抛 `WorkerIntegrationError`，进程退出码 2。
- 同一对开关的 `--with-*` 与 `--no-with-*` 同时给出即报错；**命令行显式给出（任一方向）优先于环境变量**，仅未显式时读 env。
- 开关在 `parse_command` 之前剥离，`-f` 文件模式不受未知参数影响；但 `-f` 模式下两个开关当前**未接线**：会打印 warning 且不会真正启动（`cli.py` `_run_file_command`）。
- 不加开关时零足迹：不导入 `livekit_worker` 包、不读相关 env。

### 2.2 启动前置校验（`validate_worker_options`，模型加载前 fail-fast，退出码 2）

| 环境变量 | 必填 | 语义 |
|---|---|---|
| `LIVEKIT_URL` | 是 | LiveKit server 地址（与 Java 签发 token 的 `livekit.server-url` 同一实例） |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | 是 | 与 Java 侧 `livekit.api-key` / `livekit.api-secret` 一致 |
| `LIVEKIT_WORKER_ASR_MODE` | 否 | `gateway`（默认）或 `local`；其它值报错 |
| `VOICE_GATEWAY_BASE_URL` | gateway 模式必填 | OpenAI 兼容语音网关基址；local 模式不需要（复用 pipeline STT 后端） |

### 2.3 worker 连接与容量（`livekit_worker/worker.py`，导入期常量）

| 环境变量 | 默认 | 语义 |
|---|---|---|
| `LIVEKIT_WORKER_HEALTH_PORT` | `18081` | livekit-agents 0.12.x 健康检查 HTTP 端口。上游 prod 模式默认绑 8081，本机被 Spring Boot 等占用时 Windows 报 `PermissionError [Errno 13]` 启动即失败，故默认改绑空闲的 18081 |
| `LIVEKIT_AGENT_NAME` | `会议秘书` | agent 名；服务端 `CreateDispatch` 必须携带同名 `agent_name` 才能精确派发到本 worker，两侧不一致时字幕恒空 |
| `LIVEKIT_LOAD_THRESHOLD` | `0.95` | worker 容量阈值。上游按 CPU 负载 0.75 判满（超过即 unavailable、不再派发 job），开发机负载常态在 0.75 上下，故放宽到 0.95 |

### 2.4 ASR（`asr_provider.py`，双模式）

| 环境变量 | 默认 | 语义 |
|---|---|---|
| `LIVEKIT_WORKER_ASR_MODE` | `gateway` | `gateway`：OpenAI 兼容 HTTP 转写（`POST {base}/v1/audio/transcriptions`，multipart WAV，30s 超时）；`local`：复用 pipeline 已解析的 STT handler（经 `SttHandlerAdapter` 注入，不重复加载模型） |
| `VOICE_GATEWAY_BASE_URL` | 无（gateway 必填） | 网关基址；未配置抛 `ValueError`，不静默降级 |
| `ASR_BASE_URL` | 无（可选） | 显式覆盖 gateway base（优先于 `VOICE_GATEWAY_BASE_URL`） |
| `VOICE_ASR_MODEL` | `qwen3-asr` | 网关转写请求的 `model` 字段 |
| `ASR_MAX_SEGMENT_SEC` | `25` | 超长段分块阈值（秒）：超过按块切分逐块转写再拼接，避免网关 30s 请求超时整段丢失 |
| `ASR_MAX_ATTEMPTS` | `2` | 单块 ASR 请求失败重试次数；重试仍失败才丢弃该块 |

### 2.5 SER 声学情感（`ser_provider.py`，默认关闭）

| 环境变量 | 默认 | 语义 |
|---|---|---|
| `SER_PROVIDER` | `none` | `none` 不启用；`emotion2vec`（自建容器）与 `sensevoice`（137 语音情感识别服务）走同一 `HttpSerProvider` HTTP 契约；其余值显式 raise，绝不产假标签 |
| `SER_GATEWAY_BASE_URL`（兼容旧名 `SER_BASE_URL`） | 无（启用时必填） | SER 服务基址；`POST {base}/v1/audio/emotion`（multipart WAV，`sample_rate`/`language=zh`） |
| `SER_API_KEY` | 空 | 非 空 时携带 `X-API-Key` 头 |
| `SER_TIMEOUT_MS` | `1500` | 单次预测超时 |
| `SER_HEALTH_PATH` | `/health` | 探活路径；指向 137 时须为 `/v1/audio/emotion/health` |

服务端开关快照（每房间 30s 轮询 `GET {JAVA_CALLBACK_BASE}/admin-api/ai/meeting/internal/analyze/switch`）显式 `ser=true` 且 `serPolicy` 五字段完整时才发起外呼；策略阈值（`minSegSec=1.0`、`maxSegSec=30.0`、`maxConcurrency=2`、`failThreshold=3`、`cooldownSec=60`）由 Java 下发，本地常量仅为快照异常时的 fail-closed 兜底。HTTP 409（静音/低置信拒答）不计断路失败；5xx/网络异常计入断路器。

### 2.6 说话人分离（worker 侧，`diarization_provider.py`）

| 环境变量 | 默认 | 语义 |
|---|---|---|
| `DIARIZATION_BASE_URL` | 空（关闭） | 外部离线 diarization 服务地址（`POST {base}/v1/audio/diarization`，multipart WAV，响应 `{"segments":[{"speaker","startSec","endSec"}]}`）；未配置即功能关闭，走整段路径 |
| `DIARIZATION_TIMEOUT_SEC` | `30` | 单段分离请求超时 |
| `DIARIZATION_MIN_SUB_SEC` | `0.8` | 子段最短秒数（更短的碎片丢弃） |
| `DIARIZATION_MAX_SUBSEGMENTS` | `16` | 单段子段数上限，超过视为服务异常输出、回退整段 |

任何失败（超时/4xx/5xx/坏包/空结果）抛 `DiarizationUnavailableException`，worker 回退整段路径，字幕不丢。与主 pipeline 的流式分离是**两套独立能力**，见 §5。

### 2.7 VAD 切段调参（`worker.py`）

| 环境变量 | 默认 | 语义 |
|---|---|---|
| `VAD_MIN_SILENCE_SEC` | `0.8` | 静默门：放宽后段落贴近自然句长，减少 1~3 字碎段 |
| `VAD_MIN_SPEECH_SEC` | `0.2` | 最短语音门 |
| `VAD_PREFIX_PADDING_SEC` | `0.5` | 起始前缀 padding |
| `MAX_SPEECH_SEC` | `20` | 说话中强制切段阈值：持续长声音不让 VAD 产生结束事件时，每 20s 把已积累缓冲强制送转写，避免「转写一直没有结果」 |

### 2.8 Java 内部接口凭据（`worker.py` + `callback/dispatcher.py`）

| 环境变量 | 默认 | 语义 |
|---|---|---|
| `JAVA_CALLBACK_BASE` | 无 | ai-server 基址。两个用途：worker 拉取 SER/声纹开关快照；dispatcher 的 env 兜底 java 目标（DB 不可用时）。两者都回推/请求 `/admin-api/ai/meeting/internal/**` |
| `MEETING_INTERNAL_TOKEN` | 无 | 内部接口令牌，请求头 `X-Internal-Token`；与 Java 侧 `meeting.internal-transcript-token` 严格一致，否则 Java 拒绝 |
| `MEETING_TENANT_ID` | `1` | 内部 `/admin-api/**` 请求的 `tenant-id` 头 |

`JAVA_CALLBACK_BASE` / `MEETING_INTERNAL_TOKEN` 的读取是**惰性**的（`java_base()` / `internal_token()` 调用期读取，不再要求导入期存在）；当 DB 可用且存在已启用的回调目标时，env 兜底目标不生效（见回调文档 §5）。

## 3. 与源工程差异清单

迁移以「行为等价、结构适配本仓」为原则，以下差异逐条对照实际代码：

1. **ASR 依赖注入化（双模式）**。源工程只有 `QwenAsrProvider`（HTTP 网关，模块级单例）。本仓改为 `AsrProvider` 抽象基类 + `create_asr_provider(mode)`：`gateway` 与源工程行为一致（同一 OpenAI 兼容端点与 multipart 形状）；新增 `local` 模式——`build_pipeline`（`s2s_pipeline.py`）从 pipeline handlers 中按 `isinstance(handler, BaseSTTHandler)` 挑出 STT 实例，经 `SttHandlerAdapter`（把 `process(VADAudio) -> Iterator[STTOut]` 契约适配成 `transcribe_chunk(pcm16, rate) -> str`，含 PCM16→float32 归一与线性重采样）`attach_stt_handler` 注入 worker，两个子系统共享同一 STT 模型，不重复加载。已知限制：流式后端的跨段上下文不与 pipeline 会话共享（每段独立 final 语义）。
2. **回调去向统一 CallbackDispatcher（env 兜底保留）**。源工程 `worker.py` 内嵌 `push()` 直接 POST `JAVA_CALLBACK_BASE` 固定 java 端点。本仓 `emit_segments` 统一走 `callback/dispatcher.py`：目标来自 DB `callback_target`（java/python 双协议、重试、投递日志，见回调文档），java 协议的请求形状与源工程 `push()` 完全一致（`TranscriptSegmentVO` 数组 + `X-Internal-Token` + `tenant-id`）；DB 不可用/查询失败时回落 `_env_fallback_targets()`（`JAVA_CALLBACK_BASE` + `MEETING_INTERNAL_TOKEN` → 内存 java 目标），保持源工程零配置部署可用。`worker.py` 的 `java_base()`/`internal_token()` 仅剩开关快照拉取一个用途。
3. **事件双路输出**。源工程只有 Java 回调一路。本仓每个分段先 `get_event_bus().publish(...)`（进程内 `TranscriptEventBus`，console SSE `/api/v1/live-transcripts/stream` 与本地 sink 消费），再走 dispatcher；房间断开额外产出 `session_end` 事件双路分发。任一路失败仅 print 告警。
4. **模块路径命名空间化**。源工程根目录平铺（`worker.py`、`asr_provider.py`、`ser_provider.py`、`diarization_provider.py`、`audio_level.py`、`segment_dedupe.py`）→ 本仓 `src/speech_to_speech/livekit_worker/` 包，import 改包内绝对导入；WAV 封装 `_to_wav` 只保留 `asr_provider.py` 一份（ser_provider 复用，不复制第二份）。`identify_provider.py` **未迁移**：`worker.py` 以 `try/except ImportError` 探测，缺失时声纹标注 fail-closed 停用（能力快照恒不可用），不影响字幕链路。
5. **env 读取惰性化**。源工程在模块导入/独立进程启动期强制校验 Java 回调凭据；本仓改为调用期惰性读取（`_env(name, required=...)`），统一由 `validate_worker_options` 在模型加载前 fail-fast 校验 `LIVEKIT_URL/API_KEY/API_SECRET` 与 ASR 模式所需变量——校验时机从「import 即炸」变为「带开关启动但环境不齐 → 退出码 2」。worker 运行期常量（`LIVEKIT_WORKER_HEALTH_PORT`/`LIVEKIT_AGENT_NAME`/`LIVEKIT_LOAD_THRESHOLD`/VAD 调参）保持导入期读取不变。
6. **运行形态：独立进程 → serve 进程内嵌线程**。源工程 `python worker.py start`（`cli.run_app`）独立部署；本仓 `LiveKitWorkerRuntime` 在 serve 进程内的专用线程跑专用 asyncio loop + `WorkerServer`，遵循 `ThreadManager` handler 协议（`run()` + 共享 `stop_event`），`_serve()` 协程异常由 `_log_serve_crash` 记录——线程崩溃只记日志，pipeline/console 不受影响（spec §9）。

## 4. Python 版本约束

- 整仓 `requires-python >= 3.11`（`pyproject.toml`）。
- 可选 extra `livekit` 的依赖（`pyproject.toml`）：`livekit-agents[silero]>=0.12,<0.13`（0.12.x 线，PyPI 最新 0.12.21，其元数据 `requires-python >=3.9`）、`livekit-plugins-silero>=0.7,<0.8`、`av>=12.3.0,<13`、`requests>=2.31`。`av` 是 0.12 codecs 的导入期硬依赖但未被上游列为必需依赖，故显式钉住（沿用源工程 `requirements.txt` 的处理）。
- **实际可用窗口：Python 3.10–3.12**。`av` 12.x（最新即 12.3.0）的预编译 wheel 只覆盖 cp38–cp312；Python 3.13/3.14 下无 wheel，`pip install "speech-to-speech[livekit]"` 安装失败。源工程 Docker 基线即 `python:3.12-slim`。
- 本仓开发环境为 Python 3.14：extra 无法安装，`serve --with-livekitworker` 时 `validate_worker_options` 先行（环境变量齐全则通过），随后 worker 线程 `_serve()` 导入 `livekit` 抛 `ImportError`（`ModuleNotFoundError: No module named 'livekit'`）——被崩溃隔离路径捕获并记日志 `livekit-worker thread crashed; pipeline keeps running`，pipeline 与 console 正常运行。**不会**出现未捕获异常拖垮进程。
- **离线 mock 单测**：`tests/test_livekit_worker.py` 全部用例通过 `_install_livekit_stub` 注入 `livekit`/`livekit.rtc`/`livekit.agents`（含 `.job`/`.vad`）/`livekit.plugins.silero` 桩模块（voxcpm 先例），不 import 真实 livekit、不发网络请求，因此不装 extra 也能在 3.14 环境全量运行。

## 5. 两套说话人分离能力并存说明

仓库里同时存在两套「说话人分离」，**互不调用、互不影响**，按部署需求独立开关：

| | `--with-diarization`（主 pipeline） | worker 的 `DIARIZATION_BASE_URL` |
|---|---|---|
| 归属模块 | `src/speech_to_speech/diarization/`（`StreamingDiarizer`，既有能力） | `src/speech_to_speech/livekit_worker/diarization_provider.py`（HTTP 客户端） |
| 形态 | 进程内**流式**：pipeline 会话音频逐段实时分离 | **外部离线 HTTP 服务**：worker 收到整段 PCM 后事后分离（`POST {base}/v1/audio/diarization`），按说话人时间段切子段、逐子段 ASR |
| 服务对象 | Realtime API / pipeline 会话的说话人标注 | LiveKit 房间转写的多人混合音频（同一支麦克风多人发言场景） |
| 开关 | `--with-diarization` / `--no-with-diarization` / `DIARIZATION_AUTOSTART` | `DIARIZATION_BASE_URL`（未配置即关闭） |
| 失败语义 | 既有 pipeline 行为 | 任何失败回退整段路径，字幕不丢 |

- `--with-diarization` **不会**给 worker 用，`DIARIZATION_BASE_URL` 也**不会**给主 pipeline 用；一方故障或未配置不影响另一方。
- worker 依赖的外部服务 `deploy/diarization/main.py`（FastAPI + sherpa-onnx）**不在本次迁移范围**，仍按源工程 `mediation-deploy/livekit-worker` 的部署文档（`docs/diarization-deployment-CN.md`，默认 137:8770）独立部署；本仓只包含其 HTTP 客户端。
