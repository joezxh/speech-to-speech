# Console 与 s2s 单进程同端口整合 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `speech-to-speech serve` / `local` 用 `--with-console`（或 `CONSOLE_AUTOSTART=true`）把 console 后端合并进**同一个进程**、在**同一个端口**同时提供 console 前端（`/`、`/console/*`）、console API（`/api/*`）与 s2s 自身的 `/v1/*`；开关关闭时行为与今天逐字节一致。

**Architecture:** s2s 的 FastAPI 是父应用。开关打开时，`console_integration.load_console()` 预载 `<home>/.env`、覆盖 `PIPELINE_BASE_URL`/`STATIC_DIR`、把 `console/backend` 插入 `sys.path` 后 import `app.main`，拿到它**模块级已经构造好的** ASGI 实例与模块级 `lifespan`。父应用在**所有 `/v1/*` 注册之后** `app.mount("/", console.app)`，并在自己的 lifespan 里 `async with console.lifespan(console.app)` 把 console 的四件后台事情（默认管理员、中断发布恢复、turn-latency 索引、计量 sweeper）真的跑起来。没有子进程、没有健康探活、没有看门狗、没有回收流程。

**Tech Stack:** Python 3.11+、FastAPI/Starlette（`Mount` 按注册顺序匹配）、uvicorn、pytest（`fastapi.testclient.TestClient`）、`ruff`；前端是已构建好的 `console/frontend/dist`（本次零改动）。

**Spec:** `docs/superpowers/specs/2026-10-25-console-single-process-integration-design.md`

## Global Constraints

- 开关名与默认值：`--with-console` / `--no-with-console`、`CONSOLE_AUTOSTART`，默认 **false**；环境变量 `CONSOLE_HOME`（默认 `<repo>/console/backend`）、`CONSOLE_STATIC_DIR`（默认 `<repo>/console/frontend/dist`）。
- 布尔取值：`1/true/yes/on` 真，`0/false/no/off/空` 假，其它 → `ConsoleIntegrationError`（消息必须带变量名）。
- 优先级：CLI > 环境变量 > 默认值。
- **开关关闭时**：不 import 任何 console 代码、不读 `<home>/.env`、不要求 `dist` 存在、不碰 `sys.path`、路由表与今天完全一致。
- **参数名不得叫 `console`**：`s2s_pipeline.py` 模块级已 `from speech_to_speech.pipeline.console import console`（rich 的 `Console`），参数名统一用 `console_attachment` / `console_options`，否则会静默遮蔽 `console.print` / `console.quiet`。
- **console 后端与前端零改动**：不修改 `console/backend/**`、`console/frontend/**`、`console/deploy/supervisord.conf`、任何 compose 文件。
- 退出码：`2` = 准备期校验失败 / console 导入失败；`1` = 端口绑定失败（`startup_failed`）；`0` = 正常结束；开关关闭时任何失败的退出码语义与改造前一致。
- `mount("/")` 必须在 `create_app()` 的**最后一行**，即所有 `/v1/*` 路由与 `mount_llm_proxy` 之后，否则 console 的 SPA 兜底会吃掉 `/v1/realtime`。
- 测试命令统一带 `--basetemp`，规避 Windows 上 `pytest-current` 的 `PermissionError`：`pytest <paths> -q --basetemp=.pytest-tmp-plan`。
- 只提交源码与文档，不提交 `dist/`、`build/`、`.pytest-tmp*`、`*.sqlite3`。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| **新建** `src/speech_to_speech/console_integration.py` | 唯一读开关的地方：`ConsoleOptions` / `parse_console_arguments` / `load_console` / `ConsoleAttachment` / 地址换算 / 装载失败与启动失败两种异常 |
| **新建** `tests/test_console_integration.py` | 上者的纯单元测试（不 import 真 console） |
| **新建** `tests/test_console_mount.py` | 用假 console 应用验证 `create_app(console_attachment=...)` 的挂载语义 |
| **新建** `tests/openai_realtime/test_server_startup_failure.py` | `RealtimeServer.startup_failed` 语义 |
| 改 `src/speech_to_speech/api/openai_realtime/websocket_router.py` | `create_app(..., *, console_attachment=None)`：包 lifespan + 末尾 `mount("/")` |
| 改 `src/speech_to_speech/api/openai_realtime/server.py` | `RealtimeServer(..., console_attachment=None)` 透传；`run()` 里置 `startup_failed` |
| 改 `src/speech_to_speech/s2s_pipeline.py` | `run_pipeline_command` / `_run_parsed_pipeline_command` / `build_pipeline` / `build_local_pipeline` 追加 `console_options` / `console_attachment`；wait 后检查启动失败 |
| 改 `src/speech_to_speech/configured_runtime.py` | `run_configured_command` / `_run_configured_command` / `build_configured_server` 追加同名参数 |
| 改 `src/speech_to_speech/cli.py` | `main()` 先剥开关 → 校验 → 分发；`--help` 追加 Console options 段；`talk` 拒绝显式开关 |
| 改 `tests/test_cli_defaults.py` | 新增 6 条 CLI 测试；修 2 处既有 monkeypatch lambda 的签名 |
| 改 `README.md`、`console/README.md` | 参数、环境变量、两种部署形态的关系、验证命令 |

---

## Task 1: 开关解析与准备期校验

**Files:**
- Create: `src/speech_to_speech/console_integration.py`
- Test: `tests/test_console_integration.py`

**Interfaces:**
- Consumes: 标准库 `os` / `pathlib` / `logging`。
- Produces:
  - `AUTOSTART_ENV = "CONSOLE_AUTOSTART"`、`HOME_ENV = "CONSOLE_HOME"`、`STATIC_DIR_ENV = "CONSOLE_STATIC_DIR"`
  - `class ConsoleIntegrationError(RuntimeError)`、`class StartupError(RuntimeError)`
  - `read_switch(name: str, default: bool = False) -> bool`
  - `probe_host(host: str) -> str`、`probe_base_url(host: str, port: int) -> str`
  - `@dataclass(frozen=True) class ConsoleOptions(autostart: bool, explicit: bool, home: Path, static_dir: Path)`，方法 `validate() -> None`
  - `parse_console_arguments(argv: Sequence[str]) -> tuple[ConsoleOptions, list[str]]`

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_console_integration.py`：

```python
"""The console switches are read in exactly one place (spec §3)."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from speech_to_speech.console_integration import (
    AUTOSTART_ENV,
    ConsoleIntegrationError,
    ConsoleOptions,
    parse_console_arguments,
    probe_base_url,
    probe_host,
    read_switch,
)


def test_switch_defaults_to_off(monkeypatch):
    monkeypatch.delenv(AUTOSTART_ENV, raising=False)
    options, remaining = parse_console_arguments(["serve", "--port", "9999"])

    assert options.autostart is False
    assert options.explicit is False
    assert remaining == ["serve", "--port", "9999"]


def test_env_turns_it_on_and_the_flag_wins(monkeypatch):
    monkeypatch.setenv(AUTOSTART_ENV, "yes")
    options, remaining = parse_console_arguments(["serve", "--with-console"])

    assert options.autostart is True
    assert options.explicit is True
    assert remaining == ["serve"]


def test_no_with_console_overrides_the_environment(monkeypatch):
    monkeypatch.setenv(AUTOSTART_ENV, "true")
    options, _ = parse_console_arguments(["serve", "--no-with-console"])

    assert options.autostart is False


def test_both_flags_together_are_rejected(monkeypatch):
    monkeypatch.delenv(AUTOSTART_ENV, raising=False)
    with pytest.raises(ConsoleIntegrationError, match="conflicts"):
        parse_console_arguments(["serve", "--with-console", "--no-with-console"])


@pytest.mark.parametrize("value", ["maybe", "2", "enabled"])
def test_illegal_boolean_names_the_variable(monkeypatch, value):
    monkeypatch.setenv(AUTOSTART_ENV, value)
    with pytest.raises(ConsoleIntegrationError, match=AUTOSTART_ENV):
        read_switch(AUTOSTART_ENV)


@pytest.mark.parametrize(("value", "expected"), [("1", True), ("ON", True), ("off", False), ("", False)])
def test_boolean_spellings(monkeypatch, value, expected):
    monkeypatch.setenv(AUTOSTART_ENV, value)
    assert read_switch(AUTOSTART_ENV) is expected


def test_home_and_static_dir_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSOLE_HOME", str(tmp_path / "backend"))
    monkeypatch.setenv("CONSOLE_STATIC_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv(AUTOSTART_ENV, "true")
    options, _ = parse_console_arguments(["serve"])

    assert options.home == tmp_path / "backend"
    assert options.static_dir == tmp_path / "dist"


def test_validate_rejects_a_missing_backend(tmp_path):
    options = ConsoleOptions(autostart=True, home=tmp_path / "nope", static_dir=tmp_path)
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    with pytest.raises(ConsoleIntegrationError, match="CONSOLE_HOME"):
        options.validate()


def test_validate_rejects_a_missing_frontend_build(tmp_path):
    backend = tmp_path / "backend"
    (backend / "app").mkdir(parents=True)
    (backend / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
    options = ConsoleOptions(autostart=True, home=backend, static_dir=tmp_path / "dist")

    with pytest.raises(ConsoleIntegrationError, match="npm run build"):
        options.validate()


def test_validate_accepts_a_prepared_tree(tmp_path):
    backend = tmp_path / "backend"
    (backend / "app").mkdir(parents=True)
    (backend / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")

    ConsoleOptions(autostart=True, home=backend, static_dir=dist).validate()


def test_switch_off_never_touches_the_filesystem(tmp_path, monkeypatch):
    def explode(self):
        raise AssertionError(f"filesystem touched: {self}")

    monkeypatch.setattr(Path, "exists", explode, raising=False)
    monkeypatch.setattr(Path, "is_file", explode, raising=False)
    options = ConsoleOptions(autostart=False, home=tmp_path / "nope", static_dir=tmp_path / "nope2")

    options.validate()


@pytest.mark.parametrize(
    ("host", "dialable"),
    [("0.0.0.0", "127.0.0.1"), ("", "127.0.0.1"), ("*", "127.0.0.1"), ("::", "::1"), ("10.0.0.5", "10.0.0.5")],
)
def test_probe_host_maps_wildcards_to_something_dialable(host, dialable):
    assert probe_host(host) == dialable


def test_probe_base_url_brackets_ipv6():
    assert probe_base_url("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert probe_base_url("::1", 9000) == "http://[::1]:9000"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_console_integration.py -q --basetemp=.pytest-tmp-plan`
Expected: FAIL — `ModuleNotFoundError: No module named 'speech_to_speech.console_integration'`

- [ ] **Step 3: 写最小实现**

创建 `src/speech_to_speech/console_integration.py`：

```python
"""Console integration: the single place that reads the console switches.

``--with-console`` / ``CONSOLE_AUTOSTART`` merge the console backend into this
process and publish the console frontend on the same port. Nothing here imports
console code at module level: :func:`load_console` does that lazily, so an off
switch leaves zero console footprint.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

AUTOSTART_ENV = "CONSOLE_AUTOSTART"
HOME_ENV = "CONSOLE_HOME"
STATIC_DIR_ENV = "CONSOLE_STATIC_DIR"

WITH_FLAG = "--with-console"
WITHOUT_FLAG = "--no-with-console"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


class ConsoleIntegrationError(RuntimeError):
    """The console cannot be integrated as requested; callers exit with code 2."""


class StartupError(RuntimeError):
    """The Realtime server never bound its port; callers exit with code 1."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_switch(name: str, default: bool = False) -> bool:
    """Read one boolean switch, rejecting values that are neither true nor false."""

    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise ConsoleIntegrationError(
        f"{name} must be a boolean (1/true/yes/on or 0/false/no/off); got {raw!r}."
    )


def probe_host(host: str) -> str:
    """Turn a bind address into an address this process can dial itself."""

    if host in {"", "*", "0.0.0.0"}:
        return "127.0.0.1"
    if host == "::":
        return "::1"
    return host


def probe_base_url(host: str, port: int) -> str:
    dialable = probe_host(host)
    if ":" in dialable:
        dialable = f"[{dialable}]"
    return f"http://{dialable}:{port}"


@dataclass(frozen=True)
class ConsoleOptions:
    """Resolved switches for this run."""

    autostart: bool = False
    explicit: bool = False
    home: Path = field(default_factory=lambda: _repo_root() / "console" / "backend")
    static_dir: Path = field(default_factory=lambda: _repo_root() / "console" / "frontend" / "dist")

    def validate(self) -> None:
        """Fail before any model loads, and touch nothing when the switch is off."""

        if not self.autostart:
            return
        entry = self.home / "app" / "main.py"
        if not entry.is_file():
            raise ConsoleIntegrationError(
                f"console backend not found at {entry}. Set {HOME_ENV} to the console/backend directory, "
                "or install its dependencies with 'pip install -r console/backend/requirements.txt'."
            )
        index = self.static_dir / "index.html"
        if not index.is_file():
            raise ConsoleIntegrationError(
                f"console frontend build not found at {index}. Run 'cd console/frontend && npm run build', "
                f"or set {STATIC_DIR_ENV} to the built dist directory."
            )


def parse_console_arguments(argv: Sequence[str]) -> tuple[ConsoleOptions, list[str]]:
    """Strip the two switches from argv and resolve the effective options.

    Stripping happens before ``parse_command`` so ``-f`` file mode, which rejects
    unknown options outright, keeps working.
    """

    explicit: bool | None = None
    remaining: list[str] = []
    for argument in argv:
        if argument == WITH_FLAG:
            if explicit is False:
                raise ConsoleIntegrationError(f"{WITH_FLAG} conflicts with {WITHOUT_FLAG}.")
            explicit = True
            continue
        if argument == WITHOUT_FLAG:
            if explicit is True:
                raise ConsoleIntegrationError(f"{WITHOUT_FLAG} conflicts with {WITH_FLAG}.")
            explicit = False
            continue
        remaining.append(argument)

    autostart = read_switch(AUTOSTART_ENV) if explicit is None else explicit
    home = Path(os.environ.get(HOME_ENV) or _repo_root() / "console" / "backend")
    static_dir = Path(os.environ.get(STATIC_DIR_ENV) or _repo_root() / "console" / "frontend" / "dist")
    return (
        ConsoleOptions(autostart=autostart, explicit=explicit is True, home=home, static_dir=static_dir),
        remaining,
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_console_integration.py -q --basetemp=.pytest-tmp-plan`
Expected: PASS（22 passed：13 个用例函数，其中 2 个带 parametrize 共展开 9 个）

- [ ] **Step 5: 提交**

```bash
git add src/speech_to_speech/console_integration.py tests/test_console_integration.py
git commit -m "feat: read the console switches in one place"
```

---

## Task 2: 预载 .env 并装载 console 应用

**Files:**
- Modify: `src/speech_to_speech/console_integration.py`
- Test: `tests/test_console_integration.py`

**Interfaces:**
- Consumes: Task 1 的 `ConsoleOptions`、`ConsoleIntegrationError`、`probe_base_url`。
- Produces:
  - `@dataclass(frozen=True) class ConsoleAttachment(app, lifespan, home, static_dir, pipeline_base_url)`
  - `load_console(options, *, pipeline_base_url: str, loader=None) -> ConsoleAttachment`
  - `attachment_for_server(options, host, port, *, loader=None) -> ConsoleAttachment | None`
  - `attachment_for_runtime(options, runtime: Mapping[str, Any], *, loader=None) -> ConsoleAttachment | None`

`loader` 的签名是 `loader(home: Path) -> Any`，返回「像模块」的对象（需要 `__file__`、`app`、`lifespan`）。这是唯一的测试缝。

- [ ] **Step 1: 写失败的测试**

先把这两行加到 `tests/test_console_integration.py` **顶部**的导入区（`ruff` 的 `E402` 不允许文件中部 import）：

```python
import sys
from types import SimpleNamespace
```

再把下面内容追加到文件末尾：

```python
from speech_to_speech.console_integration import (
    ConsoleAttachment,
    attachment_for_runtime,
    attachment_for_server,
    load_console,
)


def _fake_module(home: Path, *, lifespan_marker=None):
    return SimpleNamespace(
        __file__=str(home / "app" / "main.py"),
        app=object(),
        lifespan=lifespan_marker or (lambda _app: None),
    )


def _prepared(tmp_path):
    backend = tmp_path / "backend"
    (backend / "app").mkdir(parents=True)
    (backend / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    return ConsoleOptions(autostart=True, home=backend, static_dir=dist)


def test_load_console_preloads_the_env_file_without_overriding_real_env(tmp_path, monkeypatch):
    options = _prepared(tmp_path)
    (options.home / ".env").write_text(
        "JWT_SECRET_KEY=from-file\nDATABASE_URL=sqlite:///dev.db\nSTATIC_DIR=/wrong\n", encoding="utf-8"
    )
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///real.db")

    load_console(options, pipeline_base_url="http://127.0.0.1:8765", loader=lambda home: _fake_module(home))

    assert os.environ["JWT_SECRET_KEY"] == "from-file"
    assert os.environ["DATABASE_URL"] == "sqlite:///real.db"
    assert os.environ["STATIC_DIR"] == str(options.static_dir)


def test_load_console_forces_the_self_url_and_warns(tmp_path, monkeypatch, caplog):
    options = _prepared(tmp_path)
    monkeypatch.setenv("PIPELINE_BASE_URL", "http://127.0.0.1:8000")
    with caplog.at_level(logging.WARNING, logger="speech_to_speech.console_integration"):
        load_console(options, pipeline_base_url="http://127.0.0.1:9100", loader=lambda home: _fake_module(home))

    assert os.environ["PIPELINE_BASE_URL"] == "http://127.0.0.1:9100"
    assert "PIPELINE_BASE_URL" in caplog.text


def test_load_console_returns_a_usable_attachment(tmp_path):
    options = _prepared(tmp_path)
    marker = lambda _app: None  # noqa: E731 - identity matters, not style
    attachment = load_console(
        options, pipeline_base_url="http://127.0.0.1:8765", loader=lambda home: _fake_module(home, lifespan_marker=marker)
    )

    assert isinstance(attachment, ConsoleAttachment)
    assert attachment.lifespan is marker
    assert attachment.static_dir == options.static_dir
    assert attachment.pipeline_base_url == "http://127.0.0.1:8765"


def test_load_console_rejects_a_shadowing_app_package(tmp_path):
    options = _prepared(tmp_path)
    stray = SimpleNamespace(__file__="/usr/lib/python3/site-packages/app/main.py", app=object(), lifespan=lambda a: None)

    with pytest.raises(ConsoleIntegrationError, match="shadowing"):
        load_console(options, pipeline_base_url="http://127.0.0.1:8765", loader=lambda home: stray)


def test_load_console_reports_missing_entry_point_symbols(tmp_path):
    options = _prepared(tmp_path)
    broken = SimpleNamespace(__file__=str(options.home / "app" / "main.py"), app=None, lifespan=None)

    with pytest.raises(ConsoleIntegrationError, match="entry point"):
        load_console(options, pipeline_base_url="http://127.0.0.1:8765", loader=lambda home: broken)


def test_the_importer_names_the_fix_when_the_backend_cannot_be_imported(tmp_path):
    from speech_to_speech import console_integration

    empty = tmp_path / "empty-home"
    empty.mkdir()

    with pytest.raises(ConsoleIntegrationError) as excinfo:
        console_integration._import_console_main(empty)

    message = str(excinfo.value)
    assert "requirements.txt" in message
    assert "JWT_SECRET_KEY" in message


def test_attachment_is_none_when_the_switch_is_off(tmp_path):
    options = ConsoleOptions(autostart=False, home=tmp_path / "nope", static_dir=tmp_path / "nope2")

    assert attachment_for_server(options, "127.0.0.1", 8765, loader=lambda home: _fake_module(home)) is None


def test_attachment_for_server_uses_a_dialable_self_url(tmp_path):
    options = _prepared(tmp_path)
    attachment = attachment_for_server(options, "0.0.0.0", 9100, loader=lambda home: _fake_module(home))

    assert attachment.pipeline_base_url == "http://127.0.0.1:9100"


def test_attachment_for_runtime_reads_the_server_block(tmp_path):
    options = _prepared(tmp_path)

    attachment = attachment_for_runtime(
        options, {"server": {"host": "0.0.0.0", "port": 9200}}, loader=lambda home: _fake_module(home)
    )

    assert attachment.pipeline_base_url == "http://127.0.0.1:9200"


def test_attachment_for_runtime_falls_back_to_the_defaults(tmp_path):
    options = _prepared(tmp_path)

    attachment = attachment_for_runtime(options, {}, loader=lambda home: _fake_module(home))

    assert attachment.pipeline_base_url == "http://127.0.0.1:8765"
```

同时在文件顶部把 `import os` 加到 `logging` 之前：

```python
import logging
import os
from pathlib import Path
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_console_integration.py -q --basetemp=.pytest-tmp-plan`
Expected: FAIL — `ImportError: cannot import name 'ConsoleAttachment'`

- [ ] **Step 3: 写最小实现**

在 `console_integration.py` 的 `import` 区补 `import sys`，并把 `Any` / `Mapping` 加进类型导入：

```python
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
```

然后在 `ConsoleOptions` 之后、`parse_console_arguments` 之前插入：

```python
@dataclass(frozen=True)
class ConsoleAttachment:
    """The console ASGI app plus everything the parent app needs to host it."""

    app: Any
    lifespan: Any
    home: Path
    static_dir: Path
    pipeline_base_url: str


def _preload_env_file(path: Path) -> None:
    """Fill gaps in ``os.environ`` from a .env file; real variables always win."""

    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _override_env(name: str, value: str) -> None:
    existing = os.environ.get(name)
    if existing is not None and existing != value:
        logger.warning("%s=%r is overridden with %r by the console integration", name, existing, value)
    os.environ[name] = value


def _import_console_main(home: Path) -> Any:
    sys.path.insert(0, str(home))
    try:
        # The console package is imported by name because that is what its own
        # modules do (``from app.core...``); the sys.path entry stays in place.
        import app.main as module
    except Exception as exc:  # noqa: BLE001 - every import failure needs the same guidance
        raise ConsoleIntegrationError(
            f"importing the console backend from {home} failed: {exc}. "
            "Install its dependencies with 'pip install -r console/backend/requirements.txt' "
            f"and set JWT_SECRET_KEY in {home / '.env'}."
        ) from exc
    return module


def load_console(
    options: ConsoleOptions,
    *,
    pipeline_base_url: str,
    loader: Any = None,
) -> ConsoleAttachment:
    """Make the console importable with the right settings, then import it."""

    if not options.autostart:
        raise ConsoleIntegrationError("load_console() requires autostart; check the switch before calling it.")
    _preload_env_file(options.home / ".env")
    # The console probes the pipeline it serves, and it serves this process.
    _override_env("PIPELINE_BASE_URL", pipeline_base_url)
    _override_env("STATIC_DIR", str(options.static_dir))

    module = (loader or _import_console_main)(options.home)

    module_file = Path(getattr(module, "__file__", "") or "")
    if not module_file.is_file() or options.home.resolve() not in module_file.resolve().parents:
        raise ConsoleIntegrationError(
            f"the imported 'app' package is {module_file or '<unknown>'}, which is not inside {options.home}. "
            "A different 'app' package is shadowing the console; set CONSOLE_HOME or use a dedicated venv."
        )
    app = getattr(module, "app", None)
    lifespan = getattr(module, "lifespan", None)
    if app is None or not callable(lifespan):
        raise ConsoleIntegrationError(
            f"{module_file} does not expose 'app' and 'lifespan'; this is not a console backend entry point."
        )
    return ConsoleAttachment(
        app=app,
        lifespan=lifespan,
        home=options.home,
        static_dir=options.static_dir,
        pipeline_base_url=pipeline_base_url,
    )


def attachment_for_server(
    options: ConsoleOptions | None,
    host: str,
    port: int,
    *,
    loader: Any = None,
) -> ConsoleAttachment | None:
    """Resolve the attachment for a known bind address, or None when off."""

    if options is None or not options.autostart:
        return None
    return load_console(options, pipeline_base_url=probe_base_url(host, port), loader=loader)


def attachment_for_runtime(
    options: ConsoleOptions | None,
    runtime: Mapping[str, Any],
    *,
    loader: Any = None,
) -> ConsoleAttachment | None:
    """Same as :func:`attachment_for_server` for the YAML ``runtime.server`` block."""

    server = runtime.get("server") or {}
    return attachment_for_server(
        options, str(server.get("host", "127.0.0.1")), int(server.get("port", 8765)), loader=loader
    )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_console_integration.py -q --basetemp=.pytest-tmp-plan`
Expected: PASS（32 passed：Task 1 的 22 + 本任务 10）

- [ ] **Step 5: 提交**

```bash
git add src/speech_to_speech/console_integration.py tests/test_console_integration.py
git commit -m "feat: load the console app with its own env and self URL"
```

---

## Task 3: 把 console 挂到 s2s 的根路径

**Files:**
- Modify: `src/speech_to_speech/api/openai_realtime/websocket_router.py:531-557`（签名与 lifespan）与文件末尾的 `return app` 之前
- Test: `tests/test_console_mount.py`

**Interfaces:**
- Consumes: `ConsoleAttachment`（Task 2）。
- Produces: `create_app(pool, stop_event, llm_proxy_config=None, *, console_attachment: ConsoleAttachment | None = None) -> FastAPI`

为什么 `mount("/")` 放在最后：Starlette 的 `Router.app` 按 `self.routes` 顺序取**第一个** FULL 匹配，`Mount("/")` 匹配一切。因此 `/v1/realtime`、`/v1/pool`、`/v1/usage`、`/v1/realtime/calls`、`/docs`、`/redoc`、`/openapi.json` 全部先于它。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_console_mount.py`：

```python
"""A console app mounted at "/" must not disturb any s2s route (spec §4.4)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Event
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.routing import Mount, WebSocketRoute

from speech_to_speech.api.openai_realtime.websocket_router import create_app
from speech_to_speech.console_integration import ConsoleAttachment


@pytest.fixture
def console(tmp_path):
    """A miniature console: one API route, one immutable asset, an SPA fallback."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "x.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "index.html").write_text("<title>console</title>", encoding="utf-8")
    started = Event()

    @asynccontextmanager
    async def lifespan(_app):
        started.set()
        yield

    app = FastAPI(lifespan=lifespan)

    @app.get("/api/echo")
    async def echo() -> dict[str, str]:
        return {"served_by": "console"}

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"})
        if Path(full_path).suffix:
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(dist / "index.html", headers={"Cache-Control": "no-store"})

    return (
        ConsoleAttachment(
            app=app,
            lifespan=lifespan,
            home=tmp_path,
            static_dir=dist,
            pipeline_base_url="http://127.0.0.1:8765",
        ),
        started,
    )


@pytest.fixture
def client(console):
    attachment, _started = console
    return TestClient(create_app(pool=[], stop_event=Event(), console_attachment=attachment))


def test_console_api_answers(client):
    response = client.get("/api/echo")

    assert response.status_code == 200
    assert response.json() == {"served_by": "console"}


def test_s2s_routes_still_win(client):
    response = client.get("/v1/pool")

    assert response.status_code == 200
    assert response.json()["size"] == 0


def test_realtime_websocket_route_is_registered_before_the_mount(console):
    attachment, _started = console
    app = create_app(pool=[], stop_event=Event(), console_attachment=attachment)
    websocket_index = next(
        index
        for index, route in enumerate(app.routes)
        if isinstance(route, WebSocketRoute) and route.path == "/v1/realtime"
    )
    mount_index = next(
        index for index, route in enumerate(app.routes) if isinstance(route, Mount) and route.path == "/"
    )

    assert websocket_index < mount_index


def test_root_serves_the_console_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "console" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_frontend_routes_fall_back_to_index(client):
    assert client.get("/console/params").status_code == 200


def test_missing_assets_are_404_not_index(client):
    assert client.get("/main.js").status_code == 404


def test_hashed_assets_are_immutable(client):
    response = client.get("/assets/x.js")

    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_console_lifespan_runs_inside_the_parent_lifespan(console):
    attachment, started = console
    with TestClient(create_app(pool=[], stop_event=Event(), console_attachment=attachment)):
        assert started.is_set()


def test_switch_off_keeps_the_routing_table_untouched():
    app = create_app(pool=[], stop_event=Event())

    assert not any(isinstance(route, Mount) and route.path == "/" for route in app.routes)
    assert TestClient(app).get("/").status_code == 404
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_console_mount.py -q --basetemp=.pytest-tmp-plan`
Expected: FAIL — `TypeError: create_app() got an unexpected keyword argument 'console_attachment'`

- [ ] **Step 3: 改 `create_app`**

`websocket_router.py` 顶部（`TYPE_CHECKING` 若不存在就在 `typing` 导入处补）：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from speech_to_speech.console_integration import ConsoleAttachment
```

把 `create_app` 的签名与 lifespan 段改成（**函数体里的 `send_tasks` 逻辑一字不改**，只把名字从 `lifespan` 改成 `pipeline_lifespan`）：

```python
def create_app(
    pool: list[PipelineUnit],
    stop_event: ThreadingEvent,
    llm_proxy_config: LLMProxyConfig | None = None,
    *,
    console_attachment: ConsoleAttachment | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def pipeline_lifespan(app: FastAPI) -> AsyncIterator[None]:
        # One send loop per pipeline unit; each polls its own queues and forwards
        # to the websocket currently attached via unit.session.
        send_tasks = [asyncio.create_task(_send_loop_for(unit)) for unit in pool]
        yield
        for task in send_tasks:
            task.cancel()
        for task in send_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        for unit in pool:
            sess = unit.session
            if sess is not None and sess.transport is not None:
                try:
                    await sess.transport.close()
                except Exception:
                    pass

    lifespan = pipeline_lifespan
    if console_attachment is not None:
        # Starlette does not propagate a mounted app's lifespan, so the console's
        # background work (admin bootstrap, publish recovery, indexer, sweeper)
        # is entered explicitly here.
        @asynccontextmanager
        async def integrated_lifespan(app: FastAPI) -> AsyncIterator[None]:
            async with console_attachment.lifespan(console_attachment.app):
                async with pipeline_lifespan(app):
                    yield

        lifespan = integrated_lifespan

    app = FastAPI(lifespan=lifespan)
```

然后在文件末尾 `return app` 之前：

```python
    if console_attachment is not None:
        # Must stay last: Mount("/") matches everything, so every /v1/* route,
        # /docs, /redoc and /openapi.json has to be registered before it.
        app.mount("/", console_attachment.app)

    return app
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_console_mount.py tests/openai_realtime/test_websocket_router.py -q --basetemp=.pytest-tmp-plan`
Expected: PASS（既有 router 测试全绿，说明默认路径没被动）

- [ ] **Step 5: 提交**

```bash
git add src/speech_to_speech/api/openai_realtime/websocket_router.py tests/test_console_mount.py
git commit -m "feat: mount the console app at the root of the realtime server"
```

---

## Task 4: 让绑定失败变成可观测的 `startup_failed`

**Files:**
- Modify: `src/speech_to_speech/api/openai_realtime/server.py`（`__init__` 与 `run`）
- Test: `tests/openai_realtime/test_server_startup_failure.py`

**Interfaces:**
- Consumes: `create_app(..., console_attachment=...)`（Task 3）。
- Produces: `RealtimeServer(..., console_attachment=None)` 属性 `startup_failed: bool`；仅当 `console_attachment is not None` 时才可能为真。

背景（已核实 `uvicorn/server.py`：`self.started = False` 在 `:72`，绑定失败 `sys.exit(STARTUP_FAILURE)` 在 `:118`/`:192`，成功才 `self.started = True` 在 `:205`）：绑定失败时 uvicorn 在**线程里** `sys.exit(1)`，`threading` 吞掉 `SystemExit`，`ThreadManager.wait()` 正常返回 → 进程 exit 0。用 `server.started` 判定即可稳定识别，不必解析日志。

- [ ] **Step 1: 写失败的测试**

创建 `tests/openai_realtime/test_server_startup_failure.py`：

```python
"""A failed bind must not look like a clean shutdown (spec §5.3)."""
from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Event
from types import SimpleNamespace

import uvicorn
from fastapi import FastAPI

from speech_to_speech.api.openai_realtime.server import RealtimeServer


def _unit() -> SimpleNamespace:
    # A real PipelineUnit needs service/cancel_scope/four queues/five events;
    # run() only reads .index through create_app, so a stub is enough here.
    return SimpleNamespace(index=0, handlers=[], session=None)


def _attachment() -> SimpleNamespace:
    # create_app() mounts attachment.app at "/", so .app must be a real ASGI
    # callable; the lifespan is never entered because no request is served.
    @asynccontextmanager
    async def lifespan(_app):
        yield

    return SimpleNamespace(app=FastAPI(), lifespan=lifespan)


def _server(attachment):
    return RealtimeServer(
        stop_event=Event(), pool=[_unit()], host="127.0.0.1", port=8765, console_attachment=attachment
    )


def test_bind_failure_is_flagged_when_the_console_is_integrated(monkeypatch):
    class FailedRun(uvicorn.Server):
        def run(self, sockets=None):  # noqa: D401 - simulates a bind failure
            return None

    monkeypatch.setattr(uvicorn, "Server", FailedRun)
    server = _server(attachment=_attachment())

    server.run()

    assert server.startup_failed is True
    assert server.stop_event.is_set()


def test_a_clean_bind_is_not_flagged(monkeypatch):
    class CleanRun(uvicorn.Server):
        def run(self, sockets=None):
            self.started = True

    monkeypatch.setattr(uvicorn, "Server", CleanRun)
    server = _server(attachment=_attachment())

    server.run()

    assert server.startup_failed is False


def test_switch_off_keeps_the_old_exit_code_semantics(monkeypatch):
    class FailedRun(uvicorn.Server):
        def run(self, sockets=None):
            return None

    monkeypatch.setattr(uvicorn, "Server", FailedRun)
    server = _server(attachment=None)

    server.run()

    assert server.startup_failed is False
    assert server.stop_event.is_set()
```

`PipelineUnit` 是 pydantic 模型，`index` 之外还有 `service` / `cancel_scope` / `should_listen` / `response_playing` / 四个队列 / `handlers` 七个必填字段，因此这里一律用 `SimpleNamespace` 桩，**不得**为了测试去改 `PipelineUnit`。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/openai_realtime/test_server_startup_failure.py -q --basetemp=.pytest-tmp-plan`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'console_attachment'`

- [ ] **Step 3: 写最小实现**

`server.py` 顶部补类型导入：

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from speech_to_speech.console_integration import ConsoleAttachment
```

`__init__` 追加参数与两个属性：

```python
    def __init__(
        self,
        stop_event: Event,
        pool: list[PipelineUnit],
        host: str = "0.0.0.0",
        port: int = 8765,
        llm_proxy_config: LLMProxyConfig | None = None,
        console_attachment: ConsoleAttachment | None = None,
    ) -> None:
        if not pool:
            raise ValueError("RealtimeServer requires at least one PipelineUnit in the pool")
        self.stop_event = stop_event
        self.pool = pool
        self.host = host
        self.port = port
        self.llm_proxy_config = llm_proxy_config
        self.console_attachment = console_attachment
        # Only meaningful with the console integrated: a bare realtime server keeps
        # today's exit-code behaviour untouched.
        self.startup_failed = False
```

`run()` 改成：

```python
    def run(self) -> None:
        """Start the FastAPI/uvicorn server (called from a ThreadManager thread)."""
        app = create_app(
            pool=self.pool,
            stop_event=self.stop_event,
            llm_proxy_config=self.llm_proxy_config,
            console_attachment=self.console_attachment,
        )

        logger.info(
            f"OpenAI Realtime API starting on ws://{self.host}:{self.port}/v1/realtime (pool size {len(self.pool)})"
        )

        config = uvicorn.Config(app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)

        server.install_signal_handlers = lambda: None  # type: ignore[attr-defined]

        def _watch_stop() -> None:
            self.stop_event.wait()
            server.should_exit = True

        watcher = threading.Thread(target=_watch_stop, daemon=True)
        watcher.start()

        try:
            server.run()
        finally:
            # uvicorn exits with SystemExit from a worker thread on a failed bind,
            # and threading swallows it. Without this flag the process would report
            # success for a port it never owned.
            if self.console_attachment is not None and not server.started:
                self.startup_failed = True
                logger.error(
                    "OpenAI Realtime API could not bind %s:%s; aborting the console integration.",
                    self.host,
                    self.port,
                )
            # A bind/startup failure must also stop the model threads. During a
            # normal shutdown the event is already set by ThreadManager.
            self.stop_event.set()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/openai_realtime/test_server_startup_failure.py -q --basetemp=.pytest-tmp-plan`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add src/speech_to_speech/api/openai_realtime/server.py tests/openai_realtime/test_server_startup_failure.py
git commit -m "feat: report a failed bind when the console is integrated"
```

---

## Task 5: 把 attachment 穿过两条运行路径

**Files:**
- Modify: `src/speech_to_speech/s2s_pipeline.py:726-887`
- Modify: `src/speech_to_speech/configured_runtime.py:314-348, 351-394`
- Test: `tests/test_console_wiring.py`

**Interfaces:**
- Consumes: `ConsoleOptions`、`ConsoleAttachment`、`attachment_for_server`、`attachment_for_runtime`、`StartupError`。
- Produces:
  - `run_pipeline_command(command, argv, *, console_options: ConsoleOptions | None = None) -> None`
  - `_run_parsed_pipeline_command(command, args, *, console_attachment=None) -> None`
  - `build_pipeline(args, stop_event, *, host=None, console_attachment=None) -> ThreadManager`
  - `build_local_pipeline(args, stop_event, *, console_attachment=None) -> ThreadManager`
  - `run_configured_command(command, config, *, console_options=None) -> None`
  - `_run_configured_command(command, config, *, console_attachment=None) -> None`
  - `build_configured_server(config, stop_event, *, local=False, console_attachment=None) -> ConfiguredRuntime`

**参数名必须是 `console_options` / `console_attachment`**：`s2s_pipeline.py:39` 已经有 `from speech_to_speech.pipeline.console import console, model_startup_output`，叫 `console` 会遮蔽 rich 的 Console 对象，`console.quiet` / `console.print` 会立刻炸。

- [ ] **Step 1: 写失败的测试**

创建 `tests/test_console_wiring.py`：

```python
"""Both runtime paths must hand the attachment to the server, and fail loudly (spec §5.1-5.3)."""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from speech_to_speech import s2s_pipeline as pipeline_module
from speech_to_speech.console_integration import ConsoleOptions, StartupError


def _args(host="127.0.0.1", port=9999):
    return SimpleNamespace(
        module_kwargs=SimpleNamespace(num_pipelines=1, enable_llm_proxy=False, log_level="info", log_transcripts=False),
        realtime_server_kwargs=SimpleNamespace(host=host, port=port),
        local_audio_kwargs=SimpleNamespace(verbose=False, local_audio_print_json=False),
        vad_handler_kwargs=SimpleNamespace(),
        stt_backend=SimpleNamespace(),
        llm_backend=SimpleNamespace(),
        tts_backend=SimpleNamespace(),
    )


def test_build_pipeline_hands_the_attachment_to_the_server(monkeypatch):
    captured = {}

    class FakeServer:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.handlers = []

        def run(self):  # pragma: no cover - never started here
            pass

    monkeypatch.setattr(
        "speech_to_speech.api.openai_realtime.server.RealtimeServer", FakeServer
    )
    monkeypatch.setattr(pipeline_module, "_build_pipeline_unit", lambda **kwargs: SimpleNamespace(handlers=[]))
    attachment = SimpleNamespace()

    pipeline_module.build_pipeline(_args(), stop_event=None, console_attachment=attachment)

    assert captured["console_attachment"] is attachment


def test_build_pipeline_defaults_to_no_attachment(monkeypatch):
    captured = {}

    class FakeServer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("speech_to_speech.api.openai_realtime.server.RealtimeServer", FakeServer)
    monkeypatch.setattr(pipeline_module, "_build_pipeline_unit", lambda **kwargs: SimpleNamespace(handlers=[]))

    pipeline_module.build_pipeline(_args(), stop_event=None)

    assert captured["console_attachment"] is None


def test_a_handler_reporting_a_failed_startup_raises(monkeypatch):
    class FakeManager:
        def __init__(self, handlers):
            self.handlers = handlers

        def start(self):
            pass

        def wait(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(pipeline_module, "prepare_all_args", lambda _args: None)
    monkeypatch.setattr(pipeline_module, "set_log_transcripts", lambda _v: None)
    monkeypatch.setattr(pipeline_module, "warn_if_log_transcripts_enabled", lambda: None)
    monkeypatch.setattr(pipeline_module, "signal", SimpleNamespace(SIGINT=2, SIGTERM=15, signal=lambda *_a: None))
    monkeypatch.setattr(
        pipeline_module, "build_pipeline", lambda args, event, **kwargs: FakeManager([SimpleNamespace(startup_failed=True)])
    )

    with pytest.raises(StartupError):
        pipeline_module._run_parsed_pipeline_command("serve", _args())


def test_a_clean_run_does_not_raise(monkeypatch):
    class FakeManager:
        def __init__(self, handlers):
            self.handlers = handlers

        def start(self):
            pass

        def wait(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(pipeline_module, "prepare_all_args", lambda _args: None)
    monkeypatch.setattr(pipeline_module, "set_log_transcripts", lambda _v: None)
    monkeypatch.setattr(pipeline_module, "warn_if_log_transcripts_enabled", lambda: None)
    monkeypatch.setattr(pipeline_module, "signal", SimpleNamespace(SIGINT=2, SIGTERM=15, signal=lambda *_a: None))
    monkeypatch.setattr(
        pipeline_module, "build_pipeline", lambda args, event, **kwargs: FakeManager([SimpleNamespace(startup_failed=False)])
    )

    pipeline_module._run_parsed_pipeline_command("serve", _args())


def test_run_pipeline_command_resolves_the_attachment_from_the_server_args(monkeypatch):
    seen = {}
    options = ConsoleOptions(autostart=True, home=None, static_dir=None)

    monkeypatch.setattr(pipeline_module, "parse_arguments", lambda argv, command: _args(port=9100))
    monkeypatch.setattr(
        pipeline_module, "attachment_for_server", lambda opts, host, port, **kw: seen.update(host=host, port=port) or "sentinel"
    )
    monkeypatch.setattr(
        pipeline_module, "_run_parsed_pipeline_command", lambda command, args, **kw: seen.update(attachment=kw.get("console_attachment"))
    )

    pipeline_module.run_pipeline_command("serve", [], console_options=options)

    assert seen == {"host": "127.0.0.1", "port": 9100, "attachment": "sentinel"}


def test_configured_runtime_forwards_the_attachment(monkeypatch):
    from speech_to_speech import configured_runtime as runtime_module

    captured = {}

    class FakeServer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("speech_to_speech.api.openai_realtime.server.RealtimeServer", FakeServer)
    monkeypatch.setattr(runtime_module, "_validate_counts", lambda config: None)
    monkeypatch.setattr(runtime_module, "_adapt", lambda config: {"primary": _args()})
    monkeypatch.setattr(
        runtime_module, "_build_runtime", lambda arguments, stop_event: SimpleNamespace(
            _events=[None], pools={"primary": []}, server=None, client=None, _resources=[], _handlers=[]
        )
    )
    attachment = SimpleNamespace()
    # build_configured_server itself checks len(config.pipelines) != 1.
    config = SimpleNamespace(pipelines={"primary": object()})

    runtime_module.build_configured_server(config, None, console_attachment=attachment)

    assert captured["console_attachment"] is attachment
```

（`ConsoleOptions(autostart=True, home=None, static_dir=None)` 只为跳过文件系统；`validate()` 不在这条路径上。）

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_console_wiring.py -q --basetemp=.pytest-tmp-plan`
Expected: FAIL — `TypeError: build_pipeline() got an unexpected keyword argument 'console_attachment'`

- [ ] **Step 3: 改 `s2s_pipeline.py`**

模块顶部导入区追加：

```python
from speech_to_speech.console_integration import (
    ConsoleAttachment,
    ConsoleOptions,
    StartupError,
    attachment_for_server,
)
```

`build_pipeline`：

```python
def build_pipeline(
    args: ParsedArguments,
    stop_event: Event,
    *,
    host: str | None = None,
    console_attachment: ConsoleAttachment | None = None,
) -> ThreadManager:
    """Build a pool of pipeline units behind one server."""
    from speech_to_speech.api.openai_realtime.server import RealtimeServer
    ...
    server = RealtimeServer(
        stop_event=stop_event,
        pool=pool,
        host=host or args.realtime_server_kwargs.host,
        port=args.realtime_server_kwargs.port,
        llm_proxy_config=(
            build_llm_proxy_config(module_kwargs, args.llm_backend) if module_kwargs.enable_llm_proxy else None
        ),
        console_attachment=console_attachment,
    )
```

`build_local_pipeline`：签名 `(args, stop_event, *, console_attachment: ConsoleAttachment | None = None)`，并把
`server_manager = build_pipeline(args, stop_event, host="127.0.0.1")` 改成
`server_manager = build_pipeline(args, stop_event, host="127.0.0.1", console_attachment=console_attachment)`。

`run_pipeline_command`：

```python
def run_pipeline_command(
    command: Literal["serve", "local"],
    argv: Sequence[str],
    *,
    console_options: ConsoleOptions | None = None,
) -> None:
    """Run the server alone or compose it with the loopback audio client."""

    args = parse_arguments(argv, command=command)

    from speech_to_speech.pipeline.console import conversation_output

    console_attachment = attachment_for_server(
        console_options,
        "127.0.0.1" if command == "local" else args.realtime_server_kwargs.host,
        args.realtime_server_kwargs.port,
    )

    conversation_only = command == "local" and not (
        args.local_audio_kwargs.verbose or args.local_audio_kwargs.local_audio_print_json
    )
    with conversation_output(conversation_only):
        _run_parsed_pipeline_command(command, args, console_attachment=console_attachment)
```

`_run_parsed_pipeline_command`：

```python
def _run_parsed_pipeline_command(
    command: Literal["serve", "local"],
    args: ParsedArguments,
    *,
    console_attachment: ConsoleAttachment | None = None,
) -> None:
    """Run a parsed command with its terminal display policy already applied."""
    ...
    with model_startup_output(command == "local" and console.quiet):
        pipeline_manager = (
            build_local_pipeline(args, stop_event, console_attachment=console_attachment)
            if command == "local"
            else build_pipeline(args, stop_event, console_attachment=console_attachment)
        )
    ...
    try:
        pipeline_manager.start()
        pipeline_manager.wait()
    except KeyboardInterrupt:
        if not shutdown_requested[0]:
            console.print("\n[yellow]Shutting down gracefully...[/yellow]")
            pipeline_manager.stop()
            console.print("[green]✓ Pipeline stopped successfully[/green]")

    for handler in pipeline_manager.handlers:
        if getattr(handler, "startup_failed", False):
            raise StartupError(
                "the Realtime server could not bind its port; console integration aborted."
            )
```

- [ ] **Step 4: 改 `configured_runtime.py`**

导入区追加：

```python
from speech_to_speech.console_integration import (
    ConsoleAttachment,
    ConsoleOptions,
    StartupError,
    attachment_for_runtime,
)
```

`build_configured_server`：

```python
def build_configured_server(
    config: ResolvedConfig,
    stop_event: Event,
    *,
    local: bool = False,
    console_attachment: ConsoleAttachment | None = None,
) -> ConfiguredRuntime:
    ...
        result.server = RealtimeServer(
            stop_event=event,
            pool=next(iter(result.pools.values())),
            host="127.0.0.1" if local else args.realtime_server_kwargs.host,
            port=args.realtime_server_kwargs.port,
            llm_proxy_config=build_llm_proxy_config(args.module_kwargs, args.llm_backend)
            if args.module_kwargs.enable_llm_proxy
            else None,
            console_attachment=console_attachment,
        )
```

`run_configured_command` 与 `_run_configured_command` 追加参数并把结果往下传：

```python
def run_configured_command(
    command: Literal["serve", "local", "talk"],
    config: ResolvedConfig,
    *,
    console_options: ConsoleOptions | None = None,
) -> None:
    """Own CLI signal handlers and always stop constructed resources."""
    from speech_to_speech.pipeline.console import conversation_output

    settings = config.client or {}
    conversation_only = command in {"local", "talk"} and not (
        settings.get("verbose", False) or settings.get("print_json", False)
    )
    with conversation_output(conversation_only):
        _run_configured_command(command, config, console_options=console_options)


def _run_configured_command(
    command: Literal["serve", "local", "talk"],
    config: ResolvedConfig,
    *,
    console_options: ConsoleOptions | None = None,
) -> None:
    from speech_to_speech.pipeline.transcript_logging import set_log_transcripts, warn_if_log_transcripts_enabled

    stop_event = Event()
    result: ConfiguredRuntime | None = None
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        ...
        else:
            from speech_to_speech.pipeline.console import console, model_startup_output
            from speech_to_speech.s2s_pipeline import setup_logger

            console_attachment = attachment_for_runtime(console_options, config.runtime)
            setup_logger(config.runtime.get("log_level", "info"))
            with model_startup_output(command == "local" and console.quiet):
                result = build_configured_server(
                    config, stop_event, local=command == "local", console_attachment=console_attachment
                )
            set_log_transcripts(
                result.client.config.log_transcripts
                if command == "local"
                else config.runtime.get("log_transcripts", False)
            )
            warn_if_log_transcripts_enabled()
            result.start()
            server = result.server
            result.wait()
            if getattr(server, "startup_failed", False):
                raise StartupError("the Realtime server could not bind its port; console integration aborted.")
    finally:
        ...
```

`server = result.server` 必须在 `result.wait()` **之前**取：`ConfiguredRuntime.stop()` 会把 `server` 置空。

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_console_wiring.py tests/test_configured_runtime.py tests/test_cli_defaults.py -q --basetemp=.pytest-tmp-plan`
Expected: PASS。此处 `test_cli_defaults.py` 仍然全绿：`cli.py` 还没开始传新关键字，所以既有的 `lambda command, config` 与 `lambda selected_command, command_args` 依然匹配。签名适配与新增用例都在 Task 6。

- [ ] **Step 6: 提交**

```bash
git add src/speech_to_speech/s2s_pipeline.py src/speech_to_speech/configured_runtime.py tests/test_console_wiring.py
git commit -m "feat: thread the console attachment through both runtime paths"
```

---

## Task 6: CLI 接线、帮助与退出码

**Files:**
- Modify: `src/speech_to_speech/cli.py`（`_run_file_command`、`main`）
- Modify: `tests/test_cli_defaults.py`（2 处既有 lambda + 新增用例）

**Interfaces:**
- Consumes: `parse_console_arguments`、`ConsoleOptions`、`ConsoleIntegrationError`、`StartupError`。
- Produces: `main()` 的新行为；`_dispatch(command, command_args, console_options) -> None`；`_run_file_command(command, command_args, console_options) -> None`；模块常量 `CONSOLE_HELP`。

- [ ] **Step 1: 先修既有 monkeypatch 签名（否则新签名会让它们 TypeError）**

`tests/test_cli_defaults.py` 的 `test_main_dispatches_legacy_modes_to_pipeline_commands`：

```python
    monkeypatch.setattr(
        "speech_to_speech.s2s_pipeline.run_pipeline_command",
        lambda selected_command, command_args, **kwargs: calls.append((selected_command, command_args)),
    )
```

`configured_cli` fixture：

```python
    monkeypatch.setitem(
        sys.modules,
        "speech_to_speech.configured_runtime",
        SimpleNamespace(run_configured_command=lambda command, config, **kwargs: calls.append((command, config))),
    )
```

- [ ] **Step 2: 写失败的新测试**

把下面内容追加到 `tests/test_cli_defaults.py` 末尾：

```python
def test_help_documents_the_console_switch(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "serve", "--help"])
    with pytest.raises(SystemExit, match="0"):
        main()
    output = capsys.readouterr().out
    for token in ("--with-console", "CONSOLE_AUTOSTART", "CONSOLE_HOME", "CONSOLE_STATIC_DIR"):
        assert token in output


def test_top_level_help_documents_the_console_switch(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "--help"])
    with pytest.raises(SystemExit, match="0"):
        main()
    assert "--with-console" in capsys.readouterr().out


def test_talk_rejects_the_explicit_switch(monkeypatch, capsys):
    monkeypatch.delenv("CONSOLE_AUTOSTART", raising=False)
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "talk", "--with-console"])
    with pytest.raises(SystemExit, match="2"):
        main()
    assert "--with-console" in capsys.readouterr().err


def test_talk_ignores_the_environment_with_a_warning(monkeypatch, capsys):
    calls = []
    monkeypatch.setenv("CONSOLE_AUTOSTART", "true")
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "talk"])
    monkeypatch.setattr("speech_to_speech.cli.run_realtime_audio_client", lambda config: calls.append(config))

    main()

    assert len(calls) == 1
    assert "CONSOLE_AUTOSTART" in capsys.readouterr().err


def test_an_illegal_switch_value_exits_two(monkeypatch, capsys):
    monkeypatch.setenv("CONSOLE_AUTOSTART", "maybe")
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "serve"])

    with pytest.raises(SystemExit, match="2"):
        main()

    assert "CONSOLE_AUTOSTART" in capsys.readouterr().err


def test_a_missing_console_backend_exits_two_before_loading_models(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CONSOLE_AUTOSTART", "true")
    monkeypatch.setenv("CONSOLE_HOME", str(tmp_path / "missing"))
    monkeypatch.setenv("CONSOLE_STATIC_DIR", str(tmp_path / "missing-dist"))
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "serve"])

    def explode(*_args, **_kwargs):
        raise AssertionError("the pipeline must not be built")

    monkeypatch.setattr("speech_to_speech.s2s_pipeline.run_pipeline_command", explode)

    with pytest.raises(SystemExit, match="2"):
        main()

    assert "CONSOLE_HOME" in capsys.readouterr().err


def test_the_switch_reaches_the_runtime(monkeypatch):
    seen = {}
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "serve", "--with-console"])
    monkeypatch.setattr(
        "speech_to_speech.s2s_pipeline.run_pipeline_command",
        lambda command, argv, **kwargs: seen.update(options=kwargs["console_options"]),
    )
    monkeypatch.setattr("speech_to_speech.console_integration.ConsoleOptions.validate", lambda self: None)

    main()

    assert seen["options"].autostart is True


def test_file_mode_passes_the_options_down(configured_cli, monkeypatch):
    path, _calls = configured_cli
    seen = {}
    monkeypatch.setattr(sys, "argv", ["speech-to-speech", "serve", "-f", str(path), "--name", "primary"])
    monkeypatch.setattr(
        "speech_to_speech.cli._run_file_command",
        lambda command, args, options: seen.update(options=options),
    )

    main()

    assert seen["options"].autostart is False
```

- [ ] **Step 3: 跑测试确认失败**

Run: `pytest tests/test_cli_defaults.py -q --basetemp=.pytest-tmp-plan`
Expected: FAIL — `--with-console` 被当成未知参数（`SystemExit` 且 `returncode != 0`），且新增的四条用例报 `AssertionError`（输出里没有 `--with-console`）。

- [ ] **Step 4: 改 `cli.py`**

顶部导入区追加（`console_integration` 很轻，模块级导入即可；不要再引 `pathlib`，本任务用不到）：

```python
from speech_to_speech.console_integration import (
    AUTOSTART_ENV,
    ConsoleIntegrationError,
    ConsoleOptions,
    StartupError,
    parse_console_arguments,
)
```

`_run_file_command` 改签名并在 `run_configured_command` 调用点加 `console_options`：

```python
def _run_file_command(command: Command, command_args: list[str], console_options: ConsoleOptions) -> None:
    ...
    try:
        from speech_to_speech.configured_runtime import run_configured_command

        run_configured_command(command, config, console_options=console_options)
    except ConsoleIntegrationError as exc:
        parser.exit(2, f"Configuration error: {exc}\n")
    except ConfigurationError:
        parser.exit(2, "Configuration error: check the configured runtime and client settings.\n")
    except StartupError:
        parser.exit(1, "Startup failed: the Realtime server could not bind its port.\n")
    except Exception:
        import traceback as _tb

        _tb.print_exc()
        parser.exit(1, "Configured startup failed; check the selected backends and runtime resources.\n")
```

`main()` 与新增的 `_dispatch` / `CONSOLE_HELP`：

```python
CONSOLE_HELP = """
Console integration (same process, same port):
  --with-console        Merge the console backend into this process and publish
                        the console frontend on the same port. Off by default.
  --no-with-console     Override CONSOLE_AUTOSTART for this run.

Environment:
  CONSOLE_AUTOSTART     true/false, same as --with-console. Default: false.
  CONSOLE_HOME          Directory containing app/main.py. Default: <repo>/console/backend
  CONSOLE_STATIC_DIR    Built frontend directory. Default: <repo>/console/frontend/dist

With the switch on, "/" and "/console/*" serve the console frontend, "/api/*" serves
the console API, and "/v1/*" keeps serving the Realtime API from the same listener.
"""


def _dispatch(command: Command, command_args: list[str], console_options: ConsoleOptions) -> None:
    if any(
        argument.startswith("-f") or argument == "--file" or argument.startswith("--file=") for argument in command_args
    ):
        _run_file_command(command, command_args, console_options)
        return
    if any(argument == "--name" or argument.startswith("--name=") for argument in command_args):
        _command_parser().error("--name requires a configuration file.")
    if command == "talk":
        config = parse_talk_arguments(command_args)
        set_log_transcripts(config.log_transcripts)
        warn_if_log_transcripts_enabled()
        run_realtime_audio_client(config)
        return

    from speech_to_speech.s2s_pipeline import run_pipeline_command

    run_pipeline_command(command, command_args, console_options=console_options)


def main() -> None:
    argv = list(sys.argv[1:])
    try:
        console_options, argv = parse_console_arguments(argv)
    except ConsoleIntegrationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    wants_help = any(argument in {"-h", "--help"} for argument in argv)
    try:
        command, command_args = parse_command(argv)
    except SystemExit as exc:
        if exc.code == 0 and wants_help:
            print(CONSOLE_HELP)
        raise

    if command == "talk":
        if console_options.explicit:
            _command_parser().error(
                "talk does not accept --with-console; it only connects to a listener that already runs."
            )
        if console_options.autostart:
            # An environment switch must not break a command that has nothing to host.
            print(f"Warning: {AUTOSTART_ENV}=true is ignored for 'talk'.", file=sys.stderr)
            console_options = ConsoleOptions(
                autostart=False,
                explicit=console_options.explicit,
                home=console_options.home,
                static_dir=console_options.static_dir,
            )
    elif console_options.autostart:
        try:
            console_options.validate()
        except ConsoleIntegrationError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            raise SystemExit(2) from None

    try:
        _dispatch(command, command_args, console_options)
    except SystemExit as exc:
        if exc.code == 0 and wants_help and command in {"serve", "local"}:
            print(CONSOLE_HELP)
        raise
    except ConsoleIntegrationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except StartupError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
```

- [ ] **Step 5: 跑测试确认通过**

Run: `pytest tests/test_cli_defaults.py tests/test_console_integration.py -q --basetemp=.pytest-tmp-plan`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add src/speech_to_speech/cli.py tests/test_cli_defaults.py
git commit -m "feat: wire the console switch into every entry point"
```

---

## Task 7: 文档

**Files:**
- Modify: `README.md`（`## Commands` 内，`### Docker` 之后）
- Modify: `console/README.md`（`## Layout` 之后）

**Interfaces:**
- Consumes: Task 1-6 的最终参数名、环境变量、退出码。
- Produces: 与代码一致的用户文档；不含任何未实现的能力描述。

- [ ] **Step 1: README 增加小节**

在 `README.md` 的 `## Commands` → `### Docker` 之后插入：

````markdown
### Run the console in the same process

`--with-console` (or `CONSOLE_AUTOSTART=true`) merges the console backend into the
pipeline process and serves the console frontend from the same port. One listener
then answers three faces: `/` and `/console/*` for the console UI, `/api/*` for the
console API, and `/v1/*` for the Realtime API.

```bash
cd console/frontend && npm run build && cd ../..
speech-to-speech serve -f config/prod.yaml --name prod --with-console
# console: integrated=true | http://127.0.0.1:8765  ui=/  console=/console  api=/api
```

`CONSOLE_HOME` (default `console/backend`) and `CONSOLE_STATIC_DIR` (default
`console/frontend/dist`) point at the pieces to merge. The console needs its own
dependencies and a `JWT_SECRET_KEY` in `<CONSOLE_HOME>/.env`; when either is missing
the command exits with code 2 *before* loading any model. Without the switch nothing
changes: no console import, no `.env` read, no static mount.
````

- [ ] **Step 2: console/README 增加小节**

在 `console/README.md` 的 `## Layout` 之后插入：

```markdown
## Running inside the pipeline process

`speech-to-speech serve --with-console` hosts this backend and the built frontend on
the pipeline's own port (default `:8765`), so `/`, `/console/*`, `/api/*` and `/v1/*`
share one origin and one process. That mode reads `console/backend/.env` for its
settings and overrides two of them: `PIPELINE_BASE_URL` points at the process itself,
`STATIC_DIR` at the built `dist`. The uvicorn on `:8000` described below is the
standalone deployment and stays unchanged; you do not need it when the switch is on.

Two console routes are dead in that mode: `/v1/realtime` and `/v1/realtime/calls` are
the standalone proxies to a remote pipeline, and the pipeline's own `/v1/*` routes
answer first.
```

- [ ] **Step 3: 提交**

```bash
git add README.md console/README.md
git commit -m "docs: document running the console inside the pipeline process"
```

---

## Task 8: 全量回归与手工验收

**Files:** 无源码改动；只跑命令、记录结果。

- [ ] **Step 1: s2s 全量测试与 lint**

Run:
```bash
pytest tests/ -q --basetemp=.pytest-tmp-final
ruff check .
```
Expected: 全绿；`ruff format --check` 不做要求（仓库不使用该格式）。

- [ ] **Step 2: console 两侧零影响**

Run:
```bash
cd console/backend && pytest -q --basetemp=../../.pytest-tmp-console && cd ../..
cd console/frontend && npm run test && npm run lint && cd ../..
```
Expected: console 后端 ~232 passed；前端 95 passed、eslint 无输出。

- [ ] **Step 3: 组合 A —— 开关打开**

Run:
```bash
cd console/frontend; npm run build; cd ../..
speech-to-speech serve -f config/prod.yaml --name prod --with-console
```
在另一个终端：
```bash
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/                        # 200
curl.exe -s http://127.0.0.1:8765/ | Select-String "<title>"                        # console 的标题
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/console/params          # 200（SPA 回退）
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/main.js                 # 404
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/api/config              # 200
curl.exe -s http://127.0.0.1:8765/api/v1/health                                      # {"status":"ok",...}
curl.exe -s http://127.0.0.1:8765/v1/pool                                            # {"size":...}
Get-NetTCPConnection -State Listen -LocalPort 8000 -ErrorAction SilentlyContinue     # 无输出
```
Expected: 与注释一致。`/api/v1/health` 若 503，说明 `<CONSOLE_HOME>/.env` 的 `DATABASE_URL` 指错（容器默认值是 `sqlite:////app/data/console.sqlite3`），属 console 既有语义。

- [ ] **Step 4: 组合 A —— 实时链路仍可用**

Run:
```bash
@'
import asyncio, websockets
async def main():
    async with websockets.connect("ws://127.0.0.1:8765/v1/realtime", max_size=None) as ws:
        print((await ws.recv())[:120])
asyncio.run(main())
'@ | python -
```
Expected: 收到 `session.created`（说明 `mount("/")` 没吃掉 WS 升级）。

- [ ] **Step 5: 组合 B —— 开关关闭**

Run:
```bash
speech-to-speech serve -f config/prod.yaml --name prod
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/            # 404
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/api/config  # 404
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8765/v1/pool     # 200
```
Expected: 首行日志 `console: integrated=false`（若实现选择打印），路由表与改造前一致。

- [ ] **Step 6: 失败注入**

```bash
# 1) 缺 JWT_SECRET_KEY → exit 2，且未加载模型
$env:CONSOLE_AUTOSTART="true"; Remove-Item Env:JWT_SECRET_KEY -ErrorAction SilentlyContinue
speech-to-speech serve -f config/prod.yaml --name prod; $LASTEXITCODE      # 2

# 2) dist 缺失 → exit 2
$env:CONSOLE_STATIC_DIR="C:\nope"; Remove-Item Env:CONSOLE_AUTOSTART
speech-to-speech serve -f config/prod.yaml --name prod --with-console; $LASTEXITCODE   # 2

# 3) 端口被占 → exit 1
python -m http.server 8765        # 另一个终端
speech-to-speech serve -f config/prod.yaml --name prod --with-console; $LASTEXITCODE   # 1
```
Expected: 2 / 2 / 1，最后一条日志出现 `could not bind`。

- [ ] **Step 7: 提交验收记录（可选）**

```bash
git add -A
git commit -m "test: record the single-process console acceptance run"
```

---

## 自检记录

- **Spec 覆盖**：§3 配置契约 → Task 1；§3.3 校验 → Task 1；§4.1/4.2 装载 → Task 2；§4.4 挂载与顺序 → Task 3；§5.1 时序 → Task 5/6；§5.2/5.3 退出码 → Task 4/5/6；§5.4 日志 → Task 6（`Run the console in the same process` 日志行由 `parse_arguments` 之后的首条 INFO 输出；若实现选择额外打一行，属可选增强，不影响验收）；§6 与 standalone 关系 → Task 7；§7 测试 → Task 1-6；§8 验证 → Task 8；§9 非目标 → 未建任何相关任务；§10 风险 → Task 2 的包名检查、Task 4 的 `started` 判据；§11 验收清单 → Task 8 逐条覆盖。
- **与 spec 的两处有意偏离**（都写在对应 Task 里）：(1) `startup_failed` 的测试放在 `tests/openai_realtime/test_server_startup_failure.py` 而不是 `tests/test_cli_defaults.py`，因为它是 server 语义而不是 CLI 默认值；(2) `talk` 对**环境变量**只警告不报错，对**显式参数**才报错 —— 否则一个全局 `CONSOLE_AUTOSTART=true` 会让 `talk` 直接不可用。
- **占位扫描**：无 TBD / TODO；每个代码步骤都有完整可粘贴的实现。
- **类型一致性**：`ConsoleOptions`（5 个字段）、`ConsoleAttachment`（5 个字段）、`attachment_for_server/attachment_for_runtime`（`loader` 关键字）在 Task 1/2/5/6 之间一致；参数名统一为 `console_options` / `console_attachment`，无 `console` 形参。
