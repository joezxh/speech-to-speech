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
