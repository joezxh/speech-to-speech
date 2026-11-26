# file 模式嵌入式 livekit_worker 与 diarization 能力 实现计划

> **给执行者**：必需子技能：使用 subagent-driven-development 逐任务实现本计划，步骤遵循 superpowers:executing-plans。每个任务用 RED → GREEN → REFACTOR 三段式提交。步骤用 `- [ ]` 复选框跟踪。

**目标**：让 `speech-to-speech serve -f <yaml>` 仅凭 YAML 启动嵌入式 livekit_worker 与 diarization 能力，并在 file 模式硬禁用 `--with-diarization` / `--with-livekitworker` 两个命令行开关。

**架构**：diarization 走既有 pipeline option（无需新接线，只补证明性测试）；livekit_worker 新增 `runtime.livekit_worker.enabled` 布尔开关，密钥/运维项继续走环境变量；`build_configured_server` 分两段接线 worker（校验在建模前、构造在 runtime 建好后），镜像现有 agent 嵌入式接线；CLI 在 file 模式拒绝显式开关、跳过 `main()` 的 worker env 预校验。flag 模式行为一字不改。

**技术栈**：Python 3.11+、pytest（`asyncio_mode=auto`）、argparse、ruff、mypy；依赖 `livekit-agents[silero]`（`livekit` extra，本地缺则以 `pytest.importorskip` / monkeypatch 替身处理）。

**设计文档**：`docs/superpowers/specs/2026-11-26-file-mode-embedded-worker-design.md`

## 测试环境说明

- 首选 `uv run pytest <path> -v`；无 uv 时用仓库 venv：`.venv\Scripts\python.exe -m pytest <path> -v`（Windows PowerShell）。
- 下文命令统一写 `uv run pytest`，执行者按本地实际替换运行器，命令名与路径不变。

## 文件结构

- `src/speech_to_speech/config.py` — 修改：新增 `runtime.livekit_worker` 能力块解析与校验（仅 `enabled`）。
- `src/speech_to_speech/configured_runtime.py` — 修改：`build_configured_server` 两段式接线嵌入式 worker；删除 `run_configured_command` / `_run_configured_command` 的 `diarization_options` / `livekit_options` 形参与丢弃行。
- `src/speech_to_speech/cli.py` — 修改：file 模式拒绝开关、抽 `_is_file_mode` 共享谓词、`main()` 依 file 模式跳过 worker 预校验、`WorkerIntegrationError` → exit 2、`WORKER_HELP` 更新、删传参。
- `tests/test_config.py` — 修改/新增：`runtime.livekit_worker.enabled` 解析与校验用例。
- `tests/test_configured_runtime.py` — 修改/新增：worker 接线（handler 追加 / 不追加 / 缺 env fail-fast）+ diarization via YAML 集成证明。
- `tests/test_cli_defaults.py` — 修改/新增：file 模式拒绝两开关、env-only 仅警告、flag 模式回归。

---

## Task 1：config schema 新增 `runtime.livekit_worker`

**Files**
- 修改：`src/speech_to_speech/config.py:446-464`（`validate_config` runtime 段）
- 修改：`src/speech_to_speech/config.py:545-561`（`resolve_config` runtime 构造）
- 测试：`tests/test_config.py`（新增用例，复用文件内既有 `_doc`/`resolve_config` 造样方式）

- [ ] **Step 1（RED）**：在 `tests/test_config.py` 追加失败用例

覆盖四条断言：
```python
def test_runtime_livekit_worker_enabled_true(tmp_path): ...
    # runtime: {livekit_worker: {enabled: true}} → resolve 后 config.runtime["livekit_worker"]["enabled"] is True
def test_runtime_livekit_worker_defaults_disabled(tmp_path): ...
    # 无 livekit_worker 段 → config.runtime.get("livekit_worker", {}).get("enabled") is falsy/None
def test_runtime_livekit_worker_unknown_key_rejected(tmp_path): ...
    # runtime: {livekit_worker: {enabled: true, bogus: 1}} → ConfigurationError
def test_runtime_livekit_worker_client_only_omits_it(...): ...
    # resolve_config(client_only=True) 结果 runtime 不含 livekit_worker
```
> 具体造样辅助（写 YAML→`load_config`→`resolve_config`）照抄本文件已有 runtime/server 用例的写法；若本文件用内存 dict + `_ConfigDocument` 辅助，则沿用之。

- [ ] **Step 2（验证 RED）**：`uv run pytest tests/test_config.py -k livekit_worker -v` → FAIL（现 schema 拒绝 `livekit_worker` 键，报 "Unknown field"）。

- [ ] **Step 3（GREEN）**：实现 schema
1. `validate_config` 里把 runtime 允许集合从
   ```python
   runtime = _mapping(document, data.get("runtime", {}), ("runtime",), _MODULE_PROCESS | {"server", "client"})
   ```
   改为加入 `"livekit_worker"`：
   ```python
   runtime = _mapping(
       document, data.get("runtime", {}), ("runtime",), _MODULE_PROCESS | {"server", "client", "livekit_worker"}
   )
   ```
   随后校验该子块（放在 `_settings(document, runtime.get("server", {}), ...)` 之后）：
   ```python
   if "livekit_worker" in runtime:
       block = _mapping(document, runtime["livekit_worker"], ("runtime", "livekit_worker"), {"enabled"})
       _value(document, block.get("enabled", False), bool, (*("runtime", "livekit_worker"), "enabled"), None)
   ```
2. `resolve_config` 里在 `runtime["server"] = ...` 之后、`client` 分支之外新增（非 `client_only` 时写入）：
   ```python
   if not client_only:
       runtime["server"] = _settings(...)  # 既有
       worker_block = raw_runtime.get("livekit_worker", {})
       if isinstance(worker_block, dict) and "enabled" in worker_block:
           runtime["livekit_worker"] = {
               "enabled": _value(
                   document, worker_block["enabled"], bool,
                   ("runtime", "livekit_worker", "enabled"), environment,
               )
           }
       else:
           runtime["livekit_worker"] = {"enabled": False}
   ```
   `sources` 记录与既有子块保持一致（如需要，按 `_value` 内部或相邻写法补 `sources[...]`）。

- [ ] **Step 4（验证 GREEN）**：`uv run pytest tests/test_config.py -k livekit_worker -v` → PASS。

- [ ] **Step 5（REFACTOR/提交）**
```bash
git add src/speech_to_speech/config.py tests/test_config.py
git commit -m "feat(config): 新增 runtime.livekit_worker.enabled 能力开关"
```

---

## Task 2：`build_configured_server` 两段式接线嵌入式 worker

**Files**
- 修改：`src/speech_to_speech/configured_runtime.py:325-385`（`build_configured_server`）
- 修改：`src/speech_to_speech/configured_runtime.py:388-429`（删除 kwargs）
- 测试：`tests/test_configured_runtime.py`（新增接线用例 + diarization 集成证明）

- [ ] **Step 1（RED）**：新增失败用例（monkeypatch 替身，规避真实 livekit SDK）
```python
def test_build_configured_server_appends_worker_when_enabled(monkeypatch): ...
    # 设 env LIVEKIT_URL/API_KEY/API_SECRET=... ，config.runtime={"livekit_worker":{"enabled":True}}
    # 用 fake LiveKitWorkerRuntime（记录构造/attach）monkeypatch livekit_worker 包，
    # 断言返回 runtime 的 handlers 含 name=="livekit-worker" 的对象，且未进 _resources。
def test_build_configured_server_no_worker_when_disabled(monkeypatch): ...
    # enabled=False → handlers 不含 livekit-worker，且不导入 worker 模块（可用 import 哨兵）。
def test_build_configured_server_worker_missing_env_fails_before_runtime(monkeypatch): ...
    # enabled=True 但缺 LIVEKIT_API_SECRET，monkeypatch _build_runtime 为“若被调用则 raise AssertionError”，
    # 断言 build_configured_server 抛 WorkerIntegrationError 且 _build_runtime 从未被调用。
```
diarization 证明用例（放同文件）：
```python
def test_diarization_from_yaml_starts_diarization_worker(monkeypatch): ...
    # config pipeline options={"diarization": True}，monkeypatch StreamingDiarizer.from_pretrained 与
    # DiarizationWorker 为替身，走 build_configured_server→_build_runtime，断言 unit.handlers 含 DiarizationWorker 替身。
```
> 造样：参照本文件既有 `build_configured_server` 用例如何拼 `ResolvedConfig`/pipelines；若过重，改为对 `_adapt` 输出 + monkeypatch `_build_pipeline_unit` 的最小构造。执行者按现存夹具就近复用。

- [ ] **Step 2（验证 RED）**：`uv run pytest tests/test_configured_runtime.py -k "worker or diarization" -v` → FAIL（未接线/无该路径）。

- [ ] **Step 3（GREEN）**：实现两段式接线

在 `build_configured_server` 顶部读到 `arguments = _adapt(config)` 之后、`result = _build_runtime(arguments, stop_event)` **之前**插入第一段（建模前 fail-fast）：
```python
worker_enabled = bool(config.runtime.get("livekit_worker", {}).get("enabled", False))
if worker_enabled:
    from speech_to_speech.s2s_pipeline import validate_local_asr_mode
    from speech_to_speech.worker_integration import SwitchOptions, validate_worker_options

    args = next(iter(arguments.values()))
    validate_worker_options(SwitchOptions(autostart=True))  # 抛 WorkerIntegrationError，不吞
    validate_local_asr_mode(stt_backend_name=args.stt_backend.name)
```
第二段在既有 agent 接线块之后、`result.server = RealtimeServer(...)` 之前（或紧随其后，`result._events[0]`/`pool` 已就绪）插入，整体处于既有 `try:` 内：
```python
if worker_enabled:
    from speech_to_speech.livekit_worker import LiveKitWorkerRuntime
    from speech_to_speech.livekit_worker.asr_provider import SttHandlerAdapter
    from speech_to_speech.STT.base_stt_handler import BaseSTTHandler

    livekit = LiveKitWorkerRuntime(event)
    sample_rate = args.vad_handler_kwargs.sample_rate
    for unit in pool:
        for handler in unit.handlers:
            if isinstance(handler, BaseSTTHandler):
                livekit.attach_stt_handler(SttHandlerAdapter(handler, sample_rate))
                break
    result._handlers.append(livekit)
```
> `event`、`pool`、`args` 沿用函数体内既有变量（`event = result._events[0]`、`pool = next(iter(result.pools.values()))`、`args = next(iter(arguments.values()))`）。**不**加入 `result._resources`。

删除 kwargs：
- `run_configured_command`（L388-395 签名、L405-412 转调）与 `_run_configured_command`（L415-422 签名、L429 `_ = ...`）去掉 `diarization_options` / `livekit_options` 形参、传参、丢弃行。
- 若 `from speech_to_speech.worker_integration import SwitchOptions`（L23）此后不再被本文件其它处引用，删除该 import（先 grep 确认，再删）。

- [ ] **Step 4（验证 GREEN）**：`uv run pytest tests/test_configured_runtime.py -v` → PASS（新用例 + 既有用例全绿）。

- [ ] **Step 5（REFACTOR/提交）**
```bash
git add src/speech_to_speech/configured_runtime.py tests/test_configured_runtime.py
git commit -m "feat(runtime): file 模式按 YAML 起嵌入式 livekit_worker"
```

---

## Task 3：CLI file 模式门禁与错误映射

**Files**
- 修改：`src/speech_to_speech/cli.py`（`_run_file_command`、`_dispatch`、`main`、`WORKER_HELP`、worker 传参、import）
- 测试：`tests/test_cli_defaults.py`（新增 file 模式拒绝用例 + flag 模式回归）

- [ ] **Step 1（RED）**：新增失败用例
```python
def test_file_mode_rejects_with_diarization(): ...
    # argv=["serve","-f","x.yaml","--with-diarization"] → SystemExit code 2，stderr 含 “pipelines” 与 “diarization” YAML 指引
def test_file_mode_rejects_with_livekitworker(): ...
    # 含 --with-livekitworker → SystemExit 2，stderr 含 “runtime.livekit_worker.enabled”
def test_file_mode_rejects_no_with_variants(): ...
    # --no-with-diarization / --no-with-livekitworker 同样 exit 2，消息按用户拼写回显
def test_file_mode_env_autostart_only_warns(monkeypatch, capsys): ...
    # 仅 DIARIZATION_AUTOSTART=true（命令行无开关）→ 不 exit 2，stderr 有“忽略/用 YAML”警告，继续走 run_configured_command
def test_flag_mode_worker_switch_still_works(monkeypatch): ...
    # serve --with-livekitworker（无 -f）→ 不进 file 分支，main() 仍调 validate_worker_options（回归）
```

- [ ] **Step 2（验证 RED）**：`uv run pytest tests/test_cli_defaults.py -k "file_mode or worker_switch" -v` → FAIL（现为“仅警告不报错”，且 main 预校验抢先）。

- [ ] **Step 3（GREEN）**：实现 CLI 改动

1. 抽共享谓词（模块级函数，供 `_dispatch` 与 `main` 复用）：
```python
def _is_file_mode(command_args: Sequence[str]) -> bool:
    return any(
        argument.startswith("-f") or argument == "--file" or argument.startswith("--file=")
        for argument in command_args
    )
```
`_dispatch`（L467-471）内的同款 `any(...)` 改为 `if _is_file_mode(command_args):`。

2. `_run_file_command`：删除 L336-345 两条 "not wired" 警告；在参数校验通过后、调用 `run_configured_command` 之前加入门禁：
```python
if diarization_options.explicit:
    reported = diarization_options.explicit_flag or DIARIZATION_WITH_FLAG
    parser.error(
        f"file mode does not accept {reported}; set pipelines.<name>.options.diarization in the YAML."
    )
if livekit_options.explicit:
    reported = livekit_options.explicit_flag or LIVEKIT_WITH_FLAG
    parser.error(
        f"file mode does not accept {reported}; set runtime.livekit_worker.enabled: true in the YAML."
    )
if not diarization_options.explicit and diarization_options.autostart:
    print("Warning: DIARIZATION_AUTOSTART is ignored in file mode; use the YAML pipeline option.", file=sys.stderr)
if not livekit_options.explicit and livekit_options.autostart:
    print("Warning: LIVEKIT_WORKER_AUTOSTART is ignored in file mode; use runtime.livekit_worker.enabled.", file=sys.stderr)
```
删除调用处 `run_configured_command(..., diarization_options=..., livekit_options=...)` 的两个 kwarg（对齐 Task 2 签名变更）。

3. `main()`：把 L576-583 的 `validate_worker_options(livekit_options)` 预校验用 file 模式判定包裹：
```python
if command != "talk":
    try:
        _, _cmd_args = ...  # 复用已解析的 command_args
        if not _is_file_mode(command_args):
            validate_worker_options(livekit_options)
    except WorkerIntegrationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
```
> `main()` 已在 `parse_command(argv)` 后拿到 `command_args`（L518）。据此调 `_is_file_mode(command_args)`。

4. `_run_file_command` 的 `try`（L358-382）新增捕获（置于 `ConsoleIntegrationError` 之前同级）：
```python
except WorkerIntegrationError as exc:
    parser.exit(2, f"Configuration error: {exc}\n")
```

5. `WORKER_HELP`（L85-105）末尾追加：file 模式下这两个能力经 YAML 配置（diarization→pipeline option；worker→`runtime.livekit_worker.enabled`），`--with-*` 命令行开关仅用于 flag 模式。

6. 校验 import：`cli.py` 已导入 `DIARIZATION_WITH_FLAG`、`LIVEKIT_WITH_FLAG`（L34-41）与 `WorkerIntegrationError`（L38）；确认在 `_run_file_command` 作用域可用（当前已在模块顶层 import）。

- [ ] **Step 4（验证 GREEN）**：`uv run pytest tests/test_cli_defaults.py -v` → PASS（新用例 + 既有 file/flag 用例全绿；`test_file_cli_accepts_attached_short_file_flag` 仍过）。

- [ ] **Step 5（REFACTOR/提交）**
```bash
git add src/speech_to_speech/cli.py tests/test_cli_defaults.py
git commit -m "feat(cli): file 模式禁用 worker 开关并映射配置错误到 exit 2"
```

---

## Task 4：回归、静态检查与手工冒烟

**Files**
- 无新增功能，跨文件验证。

- [ ] **Step 1**：跑受影响测试全量
```bash
uv run pytest tests/test_cli_defaults.py tests/test_configured_runtime.py tests/test_config.py -v
```
预期：全绿。

- [ ] **Step 2**：相关既有回归（flag 模式 worker / diarization / agent / console）
```bash
uv run pytest tests -k "worker or diarization or agent or console or file" -v
```
预期：无因本次改动而新增的失败。若有失败先定位再继续。

- [ ] **Step 3**：静态检查
```bash
uv run ruff check src/speech_to_speech/config.py src/speech_to_speech/configured_runtime.py src/speech_to_speech/cli.py
uv run mypy --config-file mypy.ini src/speech_to_speech/configured_runtime.py src/speech_to_speech/cli.py
```
预期：无新增错误；按 ruff 反馈修 import/未用变量。

- [ ] **Step 4**：手工冒烟（可选，需 livekit extra + 真实 env）
```bash
uv run speech-to-speech serve -f <含 runtime.livekit_worker.enabled: true 与 pipeline diarization: true 的 YAML>
```
预期：启动日志出现 diarization ready 与 `[worker] connected`/livekit-worker handler 线程；无 "not wired for -f file mode" 警告。无 env/依赖时该步跳过并在 PR 说明。

- [ ] **Step 5（提交收尾）**
```bash
git add -A
git commit -m "test(file-mode): 嵌入式 worker/diarization 回归与静态检查"
```

---

## 发布前上线就绪自查

- [ ] flag 模式两开关行为与现状逐条一致（有回归用例）。
- [ ] file 模式：无 `runtime.livekit_worker` 段 = 不启 worker（零 footprint）。
- [ ] YAML 缺关键 env 时在建模型前 exit 2，消息可读、含 YAML 指引。
- [ ] diarization 经 YAML 起 `DiarizationWorker` 有集成证明。
- [ ] 不把 worker 密钥/运维项引入 YAML 或日志。
