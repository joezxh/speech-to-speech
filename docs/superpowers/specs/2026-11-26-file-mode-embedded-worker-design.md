# file 模式嵌入式 livekit_worker 与 diarization 能力设计

## 背景与意图

当前 `speech-to-speech serve -f <yaml>`（file 模式）会剥离 `--with-diarization` /
`--with-livekitworker` 两个开关，但在 [_run_file_command](../../../src/speech_to_speech/cli.py) 里
仅打印两条 "not wired for -f file mode yet" 警告，随后在
[_run_configured_command](../../../src/speech_to_speech/configured_runtime.py) 用
`_ = diarization_options, livekit_options` 把它们丢弃。也就是说：file 模式下这两个能力既没接线，
也不会真正启动。

目标：把"嵌入式 livekit_worker + diarization 能力"做成 file 模式**由 YAML 配置驱动启动**的服务，
livekit_worker 不再要求独立进程。同时**在 file 模式禁用命令行 `--with-diarization` /
`--with-livekitworker` 两个开关**，逼迫配置统一写进 YAML，保持 file 模式"设置都在 YAML、命令行只
接受 `--file`/`--name`"的既有约定（见 cli.py file 模式解析段）。

flag 模式（`serve`/`local` 不带 `-f`）行为**完全不变**——两个开关继续照常生效。

### 关键事实（已核对代码）

- **diarization 在 file 模式已可用**：它是 pipeline option，`_MODULE_PIPELINE` 已登记
  `diarization` / `diarization_model_name` 等（config.py L35-L41）；[_adapt](../../../src/speech_to_speech/configured_runtime.py)
  在 `options["diarization"]` 为真且未显式给模型名时补默认 `nvidia/Nemotron-3-Diarization`（L89-L90）；
  [_build_handlers](../../../src/speech_to_speech/s2s_pipeline.py) 在 `module_kwargs.diarization_model_name`
  为真时起嵌入式 `StreamingDiarizer` + `DiarizationWorker`（L479-L517）。→ **无需新增任何配置面或接线**。
- **livekit_worker 当前无任何 YAML 面**：config.py 全篇无 livekit；`runtime` 段仅接受
  `_MODULE_PROCESS | {"server", "client"}`（L452）。worker 唯一嵌入式启动路径是 flag 模式
  [build_pipeline](../../../src/speech_to_speech/s2s_pipeline.py)（L842-L857）。
- **worker 运行参数全部 env 惰性读取**：[LiveKitWorkerRuntime](../../../src/speech_to_speech/livekit_worker/__init__.py)
  仅接受 `stop_event`；`LIVEKIT_WORKER_ASR_MODE`、`HEALTH_PORT`、`AGENT_NAME`、`LOAD_THRESHOLD`、
  VAD 调参、`JAVA_CALLBACK_BASE`、`MEETING_INTERNAL_TOKEN` 等在 [worker.py](../../../src/speech_to_speech/livekit_worker/worker.py)
  模块级/惰性读取（L59-L106）。

## 决策（用户已确认）

- ①A：用**嵌套块** `runtime.livekit_worker.enabled: true` 开启嵌入式 worker，与 `runtime.server` /
  `runtime.client` 子块风格一致。
- ②甲：YAML 只放 `enabled` 这一个开关；worker 的**密钥与运维参数继续走环境变量**，不进 YAML。
- diarization 用 YAML pipeline option（现状即可），不新增字段。
- file 模式**硬拒绝**命令行显式的 `--with-diarization` / `--no-with-diarization` /
  `--with-livekitworker` / `--no-with-livekitworker`（exit 2）；仅通过环境变量设了 autostart
  而命令行没打开关时，stderr 提示"file 模式忽略、请用 YAML/独立配置"，不打断启动（沿用
  [talk 命令先例](../../../src/speech_to_speech/cli.py) L540-L550）。

### 目标

- `serve -f x.yaml` 能仅凭 YAML 起嵌入式 livekit_worker 与 diarization。
- 能力开启时缺关键 env → 在 `_build_runtime` 加载模型之前 fail-fast，退出码 2、消息可读。
  此处"关键 env"指 `validate_worker_options` 现有集合：`LIVEKIT_URL` / `LIVEKIT_API_KEY` /
  `LIVEKIT_API_SECRET` / `LIVEKIT_WORKER_ASR_MODE`（及 gateway 模式的 `VOICE_GATEWAY_BASE_URL`）。
  Java 回调凭据 `JAVA_CALLBACK_BASE` / `MEETING_INTERNAL_TOKEN` 保持 worker.py 现有惰性校验
  （首次进房事件才 required），不进启动 fail-fast——与"不把运维项/密钥搬 YAML"边界一致。
- 关（默认）时零 footprint，与现状 flag 模式一致。worker 内部 `_serve()` 循环崩溃由
  `_log_serve_crash` 隔离（仅记日志、不拖垮 pipeline）；`run()` 前置步骤（new_event_loop /
  loop_thread.start）若抛，则与 agent/console 同型——handler 抛错即 `ConfiguredRuntime` 停线，
  这是既有嵌入式 handler 的一致语义，本次不额外加守护层。

### 非目标

- 不把 worker 运维项/密钥搬进 YAML。
- 不改 flag 模式任何行为。
- 不新增独立 worker 进程入口的改动。
- 不引入 livekit worker 的多实例/并发调度（沿用现有单 runtime 线程模型）。

## 方案对比

- **选定方案（config 布尔开关 + 复用现有嵌入式接线）**：改动集中在 config schema、
  `build_configured_server` 接线、cli file 模式开关校验三处；worker 配置来源与 flag 模式统一（env）。
  成本最低、语义最一致。
- 备选（把运维项全搬 YAML）：需要重做 env↔YAML 覆盖优先级 + 密钥处理，面大且与 flag 模式割裂。已排除。
- 备选（file 模式仅拒绝开关、不支持内嵌 worker）：无法满足"配置驱动启动嵌入式 worker"这一核心诉求。已排除。

## 具体改动

### 1. config.py：新增 `runtime.livekit_worker` 能力块

- 在 `validate_config` 的 runtime 允许集合（L452）加入 `"livekit_worker"`。
- 新增对 `runtime.livekit_worker` 的解析：必须是 mapping，允许键仅 `{"enabled"}`；`enabled` 经
  `_value(document, value, bool, path, environment)` 解析（支持字面 bool 与 `{env: VAR}` 形式），
  缺省视为 `False`。校验期不读 env（`environment=None`）。
- 在 `resolve_config` 构造 `runtime` 字典时写入 `runtime["livekit_worker"] = {"enabled": <bool>}`
  （`client_only` 分支不写，与 server/client 处理对齐；worker 只在 serve/local 生效）。
- 不加入 `_MODULE_PROCESS`（那是 ModuleArguments 字段）；作为独立子块单独解析，风格同 `server`。

### 2. configured_runtime.py：`build_configured_server` 接线嵌入式 worker

- 新增参数 `config` 已具备；在构造 server、pool、agent 之后，读取
  `enabled = config.runtime.get("livekit_worker", {}).get("enabled", False)`。
- 当 `enabled` 为真，**镜像 flag 模式 [build_pipeline](../../../src/speech_to_speech/s2s_pipeline.py) 的 worker 块 + agent 接线块**，分两段插入以满足"建模型前 fail-fast"：
  - **第一段（在 `_adapt(config)` 之后、`_build_runtime(...)` 之前，此时 pool/event 尚未创建）**：
    fail-fast env 校验。调用 worker_integration 的
    `validate_worker_options(SwitchOptions(autostart=True))`（检查 LIVEKIT_URL/API_KEY/API_SECRET、
    `LIVEKIT_WORKER_ASR_MODE`、gateway 模式需 VOICE_GATEWAY_BASE_URL）；再
    `validate_local_asr_mode(stt_backend_name=args.stt_backend.name)`（local 模式需 STT backend，
    `args` 取 `next(iter(arguments.values()))`）。两者抛 `WorkerIntegrationError`，**原样向上传播**，
    不得被吞成 `ConfiguredRuntimeError`（供 cli 层转 exit 2，见改动 4）。
  - **第二段（在 server/agent 构造完成后，`result._events` 与 `pool` 已就绪）**：
    1. `from speech_to_speech.livekit_worker import LiveKitWorkerRuntime` 等延迟导入。
    2. `livekit = LiveKitWorkerRuntime(event)`，`event = result._events[0]`（与 agent 共享同一 pipeline
       stop event，`ConfiguredRuntime.stop()` 置位它即可收掉 worker loop）。
    3. 遍历 `pool` 每个 unit 的 `handlers`，命中 `BaseSTTHandler` 首个即
       `livekit.attach_stt_handler(SttHandlerAdapter(handler, args.vad_handler_kwargs.sample_rate))` 后 break
       （gateway 模式 attach 无害，`_resolve_stt_handler` 会因非 local 返回 None）。
    4. `result._handlers.append(livekit)`。**不**加入 `_resources`（与 agent 同：作为 handler 线程运行，
       生命周期由共享 event 控制，无需 `_cleanup`）。第二段整体放在 server 构造 try 之内，其
       构造异常沿用现有 `except BaseException` → `_failure` + `stop()` + 抛 `ConfiguredRuntimeError`。

### 3. cli.py：file 模式禁用两个开关

- 在 `_run_file_command` 里删除两条 "not wired for -f file mode yet" 警告。
- 新增（在 file 模式参数校验通过后、`run_configured_command` 调用前）：
  - 若 `diarization_options.explicit` → `parser.error("file mode does not accept --with-diarization / "
    "--no-with-diarization; set pipelines.<name>.options.diarization in the YAML.")`（用
    `explicit_flag` 还原用户实际拼写，缺省回退常量，沿用 talk 段做法）。
  - 若 `livekit_options.explicit` → `parser.error(... --with-livekitworker ...; set "
    "runtime.livekit_worker.enabled: true in the YAML.")`。
  - 若 `not explicit and autostart`（仅 env 触发）→ stderr 警告"file 模式忽略 <FLAG> 的环境变量 "
    "autostart，请用 YAML"，不打断。
- 由于 file 模式不再把开关传入 configured runtime，删除 `run_configured_command` /
  `_run_configured_command` 的 `diarization_options` / `livekit_options` 形参及 `_ = ...` 丢弃行，
  并同步删除 `_run_file_command` 调用处传参（L367-L368）。保持函数签名整洁。
  （已核对：`run_configured_command`/`_run_configured_command` 无外部 kwargs 调用，
  `tests/test_configured_runtime.py:285`/`679` 与 `tests/test_console_wiring.py` 均以位置参数调用，
  删 kwarg 不破坏测试；删后若 `configured_runtime.py:23 from ...worker_integration import SwitchOptions`
  变为孤儿 import，一并删除。）
- `WORKER_HELP` 追加一行：file 模式经 YAML 配置（diarization→pipeline option；
  worker→`runtime.livekit_worker.enabled`），命令行开关仅用于 flag 模式。

### 4. cli.py：worker 校验错误映射到 exit 2

- `_run_file_command` 的 `try` 捕获链新增 `except WorkerIntegrationError as exc: parser.exit(2,
  f"Configuration error: {exc}\n")`（置于 `ConsoleIntegrationError` 同级之前），确保改动 2 的 fail-fast
  消息精确呈现，而非落入通用 `except Exception`（exit 1）。

### 5. cli.py `main()`：worker 预校验须跳过 file 模式

- 现状：[main](../../../src/speech_to_speech/cli.py) 在 `command != "talk"` 时对
  `livekit_options` 跑 `validate_worker_options`（L576-L583），该函数在 `autostart` 为真时校验 env，
  缺失即 `SystemExit(2)`。
- 问题：file 模式下若仅设了 `LIVEKIT_WORKER_AUTOSTART=true`（命令行没打开关），`parse_worker_arguments`
  解析出的 `livekit_options.autostart` 为真，会让这段预校验 exit 2——与"env-only 应忽略并警告"冲突。
- 决策（明确）：抽一个共享谓词 `_is_file_mode(command_args)`，与 [_dispatch](../../../src/speech_to_speech/cli.py)
  内现有判定完全同款（宽松式：`argument.startswith("-f") or argument == "--file" or
  argument.startswith("--file=")`，兼容 `-fpath` 连写），**`_dispatch` 与 `main()` 均改用该 helper**，避免两处发散。
  当 `_is_file_mode` 为真时**跳过** `validate_worker_options(livekit_options)`
  预校验；file 模式的 worker env 校验改由 `build_configured_server` 依 YAML `enabled` 触发（改动 2）。
  flag 模式（`_is_file_mode` 为假）预校验保持不变。
- 相应地：改动 3 里 file 模式对 env-only autostart 的"忽略并警告"负责给用户可读信号；`main()` 不再抢先 exit 2。
- `agent_options` 的 `validate_agent_options`（L567-L574）不受影响：agent 在 file 模式本就已接线并正常工作。

### 6. flag 模式运行时行为保持不变

- flag 模式（不带 `-f`）仍走 [run_pipeline_command](../../../src/speech_to_speech/s2s_pipeline.py)，
  两个命令行开关 + env autostart 语义与现状一字不改。

## 配置示例

```yaml
runtime:
  livekit_worker:
    enabled: true          # 其余 worker 参数走环境变量
pipelines:
  prod:
    stages: { vad: v, stt: s, llm: l, tts: t }
    options:
      diarization: true    # 嵌入式流式说话人分离
```

## 测试要点（供计划展开）

- config：`runtime.livekit_worker.enabled` true/false/env 形式解析与校验；非法键报错；`client_only` 不含该键。
- configured_runtime：`enabled=true` 时 `build_configured_server` 追加名为 `livekit-worker` 的 handler；
  `enabled=false` 时不追加；缺 env 时在建模型前抛 `WorkerIntegrationError`。
- cli：file 模式打 `--with-diarization`/`--with-livekitworker`（及 `--no-` 变体）→ exit 2 且消息含 YAML 指引；
  仅 env autostart → 警告不启动；flag 模式两开关行为回归不变。
- 回归：现有 diarization via YAML、flag 模式 worker 测试全绿。
- 新增一条 file 模式集成测试，证实 `serve -f` + pipeline option `diarization: true` 确实经
  `run_configured_command → build_configured_server → _build_runtime → _build_handlers` 起
  `DiarizationWorker`（验证"diarization 无需新接线"这一断言）。**不改** `_build_handlers`
  的 `if module_kwargs.diarization_model_name:` 门槛（YAML `diarization: false` + 显式 model_name
  仍会起分离属 flag 模式既有语义，本次“flag 模式完全不变”为非目标）。

## 留给实现者的自由度

- 具体导入位置（函数内延迟导入 vs 顶层）以与周边 agent/console 接线一致为准。
- 错误消息精确措辞可微调，但必须含可执行的 YAML 指引。
- file 模式 env-autostart 不导致 exit 2、但 YAML 开启时缺 env 仍 fail-fast（此时序已在改动 5 定死，非自由度）。
