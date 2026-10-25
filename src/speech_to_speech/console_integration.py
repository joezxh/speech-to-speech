"""Console integration: the single place that reads the console switches.

``--with-console`` / ``CONSOLE_AUTOSTART`` merge the console backend into this
process and publish the console frontend on the same port. Nothing here imports
console code at module level: :func:`load_console` does that lazily, so an off
switch leaves zero console footprint.
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    raise ConsoleIntegrationError(f"{name} must be a boolean (1/true/yes/on or 0/false/no/off); got {raw!r}.")


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
