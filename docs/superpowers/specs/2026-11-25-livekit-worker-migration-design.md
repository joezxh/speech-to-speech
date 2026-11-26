# LiveKit 房间转写、说话人分离与可配置回调子系统迁移设计

- 日期：2026-11-25
- 状态：已确认，待实施
- 来源工程：`d:/work/mediation_platform/mediation-deploy/livekit-worker`
- 目标工程：本仓 `speech-to-speech`

## 1. 背景与目标

livekit-worker 工程具备两项能力：LiveKit 房间转写（Agent worker 进房、VAD 切段、ASR、可选 SER、回推 Java）与说话人分离（独立 sherpa-onnx HTTP 服务 + worker 侧子段拆分/声纹归属）。本设计把这两项能力迁移进 speech-to-speech，并升级为**可配置回调子系统**，通过 CLI 开关控制是否随 `serve` 一并启动：

- `--with-diarization`（用户输入写作 `--with-diatization`，按仓库既有参数名规范修正为 `diarization`）
- `--with-livekitworker`

已确认的关键决策：

1. 转写输出**双路**：默认进本地实时转写/console；回调目标按配置投递。
2. `--with-diarization` **复用现有流式分离**（`module_arguments.diarization` → `StreamingDiarizer`/`DiarizationWorker`），不移植 sherpa-onnx 服务代码。
3. worker ASR **双模式可切换**：默认外部语音网关（OpenAI 兼容），可切本地 STT 后端。
4. 迁移形态为**方案 A：内嵌附属服务**——worker 以线程 + asyncio loop 跑在 serve 进程内，与 `--with-console`/voiceprint 同模式。
5. 回调子系统：**console 可视化配置 + DB 持久化 + 多目标（Java/Python）+ 协议自动适配 + 执行日志 + 动态生效**（§8）。

## 2. 范围与非目标

范围内：

- 新包 `src/speech_to_speech/livekit_worker/`：移植 worker 核心与各 provider。
- 两个 CLI 开关（`serve`/`local`），含 `--no-with-*` 与环境变量覆盖。
- worker ASR 双模式（gateway / local）。
- 回调子系统：DB 表、console CRUD API、前端配置界面、dispatcher、执行日志、热加载。
- extra 依赖、启动期校验、错误处理、离线单测、文档。

非目标：

- 不移植 sherpa-onnx diarization 服务（worker 的 `DIARIZATION_BASE_URL` 仍指向外部部署，见 §7）。
- 不改动现有 pipeline 各 stage 行为；`--with-diarization` 只是把既有能力接到开关上。
- 不迁移 livekit-worker 的 Docker/compose 部署件。

## 3. 总体架构

```
speech-to-speech serve --with-diarization --with-livekitworker [--with-console]
        │
        ├─ Realtime pipeline（现有，不变）
        │     └─ --with-diarization ⇒ diarization=True → StreamingDiarizer + DiarizationWorker（现有链路）
        │
        ├─ livekit_worker 线程（新增，asyncio loop 内跑 livekit-agents WorkerServer）
        │     AgentDispatch 进房 → 订阅音频轨 → silero VAD 切段
        │       → ASR（gateway / local）→ SER（默认 none）
        │       → [DIARIZATION_BASE_URL] 子段拆分 + 声纹归属
        │       → 本地实时转写 + CallbackDispatcher.dispatch(event)
        │
        └─ callback 子系统（新增）
              console 后端（CRUD/日志 API）↔ callback_target / callback_delivery_log 表
              dispatcher（serve 进程内）← 配置热加载（TTL 缓存）← DB
              → 按目标协议适配投递（java / python）→ 重试 → 日志落库
```

两个开关相互独立；`--with-console` 决定回调配置界面的部署形态（同进程或独立 console）。

## 4. CLI 开关

沿用 `--with-console` 的既有模式（`serve`/`local` 接受，`talk` 报参数错误）：

| 开关 | 环境变量覆盖 | 默认 | 行为 |
|---|---|---|---|
| `--with-diarization` / `--no-with-diarization` | `DIARIZATION_AUTOSTART` | false | 等价 `diarization=True`，启用现有流式分离 |
| `--with-livekitworker` / `--no-with-livekitworker` | `LIVEKIT_WORKER_AUTOSTART` | false | 进程内启动 LiveKit worker 线程 |

- 布尔解析与优先级（显式 flag > env > 默认）对齐 `--with-console` 的现有实现。
- 未装 `livekit` extra 时传 `--with-livekitworker`：参数解析照常通过，启动期给出可操作 `ImportError`（见 §9）。

## 5. livekit_worker 包结构

```
src/speech_to_speech/livekit_worker/
├── __init__.py             # LiveKitWorkerRuntime：线程 + loop 生命周期
├── worker.py               # 移植核心：job 接入、轨订阅、VAD 切段、ASR/SER 并行、
│                           #   diarization 子段拆分、重复过滤、事件产出
├── asr_provider.py         # 双模式 ASR
├── ser_provider.py         # 移植：HTTP SER（409 fail-closed 语义保留）
├── diarization_provider.py # 移植：HTTP 分离客户端（超时/5xx/空结果回退整段）
├── segment_dedupe.py       # 原样移植：近重复分段抑制
└── events.py               # 转写事件构造（transcript / segment_attributed / session_end）
```

移植原则：逻辑逐段照搬源工程（行为不变），仅做三类改动——依赖注入化（ASR 可切换）、回调去向改为事件产出交给 CallbackDispatcher、模块路径/日志命名空间化。

## 6. ASR 双模式

| 模式 | 配置 | 行为 |
|---|---|---|
| `gateway`（默认） | `VOICE_GATEWAY_BASE_URL`、`VOICE_ASR_MODEL`（默认 qwen3-asr） | OpenAI 兼容 HTTP 转写，与源工程一致 |
| `local` | 复用 `--stt` 选定的本地 STT 后端实例 | 直接调用 pipeline 已解析的 STT handler，不重复加载模型 |

- 切换配置：`LIVEKIT_WORKER_ASR_MODE=gateway|local`，非法值启动期 `ValueError`。
- `local` 模式要求 `serve` 已选 STT 定义；未选时报启动错误并提示改用 gateway。
- STT handler 调用契约实现期先核对所选后端是否支持被 worker 线程并发调用，不支持时在文档标注限制。

## 7. 转写结果输出

1. **本地实时转写**（2026-11-25 实施期修订）：现有 `enable_live_transcription` 体系绑定活跃 pipeline websocket 会话，worker 事件在 pipeline 之外无法直接注入。修订为：worker 结果发布到进程内 `TranscriptEventBus`；console 后端新增 SSE 端点 `GET /api/v1/live-transcripts/stream`（JWT 鉴权）订阅该总线，console 前端「回调管理」页新增「实时字幕」页签消费该流——实现 console 实时字幕可见。`enable_live_transcription` 体系本身保持不变。standalone console 部署（worker 不在同进程）时该端点返回错误事件提示。
2. **回调投递**：所有出站投递统一走 CallbackDispatcher（§8），不再有独立 java_callback 模块。
3. **声纹归属**：优先复用进程内 `VoiceprintService`（capability.ready 时）；不可用则走外部端点；再降级 TEMP 编号。

与 `--with-diarization` 的关系说明（写入文档）：worker 的分离走外部 `DIARIZATION_BASE_URL` 离线服务（部署侧独立进程，源工程 `deploy/diarization/main.py` 不迁移）；`--with-diarization` 是主 pipeline 的流式分离。两套并存、互不调用。

## 8. 可配置回调子系统

### 8.1 数据模型（console 后端，alembic 迁移）

**`callback_target` 表**（回调目标配置）：

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | |
| `name` | str unique | 目标显示名 |
| `target_type` | enum `java` / `python` | 协议适配依据 |
| `base_url` | str | 目标基址；java 目标回调路径固定 `/admin-api/ai/meeting/internal/transcript`，python 目标为完整 webhook URL |
| `auth_type` | enum `none` / `bearer` / `header_token` | java 用 `header_token`（默认头 `MEETING_INTERNAL_TOKEN` + `tenant-id`） |
| `auth_header_name` | str nullable | `header_token` 时的头名 |
| `auth_token` | str | 凭据；日志中脱敏 |
| `extra_headers` | JSON | 附加头（如 `tenant-id`） |
| `timeout_ms` | int, default 3000 | 单次请求超时 |
| `retry_max_attempts` | int, default 3 | 总尝试次数上限 |
| `retry_backoff_ms` | int, default 500 | 指数退避基数 |
| `events` | JSON array | 订阅事件：`transcript` / `segment_attributed` / `session_end` |
| `filters` | JSON nullable | 过滤器：`{"speakers": [...], "min_text_len": N}` |
| `enabled` | bool | 启用状态 |
| `created_at` / `updated_at` / `updated_by` | | 沿用 `param_config` 风格 |

**`callback_delivery_log` 表**（执行日志）：

| 字段 | 说明 |
|---|---|
| `id`, `target_id` | 目标外键（目标删除时日志保留、target_id 置空策略为 SET NULL） |
| `event_type` | 触发事件类型 |
| `triggered_at` | 触发时间 |
| `request_url` / `request_payload` | 请求地址与参数（payload 截断存储，token 脱敏） |
| `attempt` | 第几次尝试 |
| `http_status` / `response_snippet` | 响应状态码与响应摘要 |
| `duration_ms` | 耗时 |
| `status` | `success` / `failed` / `retrying` |
| `error` | 异常摘要 |

迁移文件沿用 console 现有 alembic 编号序列（0009 之后顺延）。

### 8.2 事件与协议适配

事件 payload 统一为转写事件 JSON（房间、会话、speaker、文本、时间戳、事件类型）；触发条件 = 目标订阅的事件类型 + 过滤器（speaker 命中、文本长度阈值）。

| 目标类型 | URL 组装 | 鉴权 | 数据格式 |
|---|---|---|---|
| `java` | `base_url` + 固定内部端点路径 | `header_token`（`MEETING_INTERNAL_TOKEN` 头 + `tenant-id`） | 与源工程回推字段一致（向后兼容） |
| `python` | `base_url` 即完整 webhook | `none` / `bearer` / `header_token` | 同一份事件 JSON |

投递语义：异步线程池投递、不阻塞转写主流程；失败按 `retry_max_attempts` 指数退避重试；每次尝试写一条 `callback_delivery_log`；最终失败仅记录日志不重投（可靠投递 = 重试 + 完整日志，不引入消息队列）。

### 8.3 dispatcher 与配置热加载

- `src/speech_to_speech/callback/dispatcher.py`：serve 进程内单例；`dispatch(event)` → 读取启用目标（进程内 TTL 缓存，默认 5 秒刷新，配置变更无需重启）→ 过滤 → 按目标协议适配投递 → 写日志。
- 数据库连接：复用 console 后端的 SQLAlchemy 配置；`--with-console` 同进程时直接用其 session factory；standalone console 部署时 serve 通过 `CONSOLE_DATABASE_URL` 连同一库。
- **向后兼容**：未启用 console / DB 不可用时，若配置了旧 env `JAVA_CALLBACK_BASE` + `MEETING_INTERNAL_TOKEN`，dispatcher 自动生成一个内存默认 java 目标（不入库、不写 console UI），保持源工程零改动部署可用；DB 可用时 env 兜底失效并在启动日志提示改用界面配置。

### 8.4 CRUD API（console 后端，JWT + `console:callback:*` 权限码）

| 路由 | 方法 | 说明 |
|---|---|---|
| `/api/v1/callbacks/targets` | GET / POST | 列表（分页） / 新建 |
| `/api/v1/callbacks/targets/{id}` | GET / PUT / DELETE | 详情 / 更新 / 删除 |
| `/api/v1/callbacks/targets/batch` | POST | 批量启用/禁用/删除（body: ids + action） |
| `/api/v1/callbacks/targets/{id}/test` | POST | 发送一条测试事件，立即返回投递结果 |
| `/api/v1/callbacks/logs` | GET | 日志分页查询（按 target/status/时间过滤） |

### 8.5 console 前端界面（Vue3 + ant-design-vue）

- 新页面「回调管理」：目标列表表格（名称/类型/URL/事件/状态开关/最近投递结果），行内启用开关即时生效。
- 新建/编辑抽屉：类型单选（java/python 联动 URL 提示与鉴权字段）、鉴权方式、超时、重试策略、事件订阅复选、过滤器编辑、连接测试按钮。
- 批量操作：多选启用/禁用/删除。
- 「投递日志」页签：分页表格 + 状态筛选 + 请求/响应详情抽屉（token 脱敏展示）。

## 9. 依赖、校验与错误处理

- `pyproject.toml` extra：`livekit = ["livekit-agents>=0.12,<0.13"]`（含 silero VAD 插件依赖，实现期按源工程 requirements 对齐）。当前开发环境 Python 3.14，若 livekit-agents 不支持则同 voxcpm 模式：文档 + ImportError 说明，单测 mock。
- 启动期校验（`--with-livekitworker` 时）：
  - `LIVEKIT_URL`、`LIVEKIT_API_KEY`、`LIVEKIT_API_SECRET` 缺失 → `ValueError` 列出全部缺失项。
  - `gateway` 模式缺 `VOICE_GATEWAY_BASE_URL` → `ValueError`。
  - `local` 模式无 STT 定义 → `ValueError`。
  - `LIVEKIT_WORKER_ASR_MODE` 非法值 → `ValueError`。
  - 回调子系统：DB 不可用且无 env 兜底 → worker 照常启动、回调禁用并 warning（回调失败不影响转写）。
- 运行期：worker 线程崩溃隔离（不拖垮主 pipeline，健康端点 degraded）；LiveKit 断线依赖内建重连；diarization 失败沿用源工程降级策略；回调目标单点失败不影响其它目标与主流程。
- `serve` 退出时联动：取消 worker loop、等待线程 join、flush 在途回调日志。

## 10. 测试计划（全部离线，mock livekit-agents / 外部服务 / DB 用 sqlite 内存库）

1. 开关解析：`--with-*`/`--no-with-*`/env 三者优先级；`talk` 传入报错。
2. 必填 env 校验分支（逐项缺失合并报错）。
3. ASR 双模式选择与非法模式报错。
4. VAD 切段 → 子段拆分 → 去重纯函数等价性（与源工程 `tests/` 对齐用例移植）。
5. diarization 客户端超时/5xx/空结果/未配置回退整段。
6. SER 409 fail-closed、未配置跳过。
7. worker 线程崩溃隔离断言。
8. 回调：目标过滤（事件类型/过滤器）、协议适配（java 路径与头 / python 鉴权三种）、重试退避与日志落库、TTL 缓存热加载、env 兜底模式、批量 API、测试投递端点、日志脱敏。
9. console API 契约测试（鉴权 + 权限码）与 alembic 迁移可升级性。
10. 更新 README 计数类断言（如有）。

验收命令：

```bash
pytest tests/test_livekit_worker.py tests/test_cli_flags.py tests/test_callback_dispatcher.py console/backend/tests -q
pytest
ruff check .
```

## 11. 文档

- `README.md` / `README-CN.md`：开关表、`livekit` extra 安装行、回调子系统简介。
- 新增 `docs/livekit-worker-integration-CN.md`：架构图、env 全表（与源工程同名同义）、与源工程差异清单（依赖注入化、回调子系统化）、Python 版本约束、两套分离能力并存说明。
- 新增 `docs/callback-subsystem-CN.md`：数据模型、API 清单、事件 payload、协议适配矩阵、热加载与 env 兜底语义。

## 12. 风险

| 风险 | 处置 |
|---|---|
| livekit-agents 不支持 Python 3.14 | ImportError 提示 + mock 单测 + 文档（同 voxcpm 先例） |
| local ASR 模式下 handler 并发调用契约不明 | 实现期核对，不支持则文档标注仅 gateway 支持并发 |
| worker asyncio loop 与线程模型共存 | 独立线程独立 loop；共享对象只经线程安全接口 |
| env 变量与现有命名冲突 | 沿用源工程原名前缀（LIVEKIT_/SER_/DIARIZATION_），实施前 grep 排查 |
| 声纹归属依赖 VoiceprintService 状态 | 三级降级链（进程内 → 外部端点 → TEMP 编号） |
| 回调 token 泄漏（日志/DB） | 日志与响应摘要统一脱敏；DB 字段访问受 console JWT 鉴权 |
| 回调风暴（高频转写 × 多目标） | 投递线程池上限 + 每目标独立队列 + 超时熔断（连续失败暂停并标记） |
| console 与 serve 分离部署时 DB 双写 | dispatcher 只读配置、写日志；配置写入仅经 console API，无双写冲突 |

## 13. 实施清单（顺序）

1. CLI 开关解析 + env 覆盖 + 报错分支。
2. `livekit_worker/` 包骨架与线程生命周期。
3. `segment_dedupe.py`、`ser_provider.py`、`diarization_provider.py`、`events.py` 移植。
4. `asr_provider.py` 双模式。
5. `worker.py` 核心移植与事件产出。
6. 回调子系统：alembic 迁移（两表）→ dispatcher + TTL 缓存 + env 兜底 → CRUD/batch/test/logs API → 前端「回调管理」页面。
7. extra 依赖与启动期校验。
8. 测试（新增 + 既有断言更新）。
9. 文档四处（README×2 + 两个新 docs）。
10. `pytest` + `ruff check .` 修复回归。
