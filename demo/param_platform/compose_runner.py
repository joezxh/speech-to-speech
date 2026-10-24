"""Drive `docker compose` for one service: chain A, steps 6 to 8.

Only three things happen here — `up -d --force-recreate <service>`, `logs`, and
an HTTP probe of `/v1/pool` — and none of them parses the compose file. The
service name and the file path come from the environment, because a platform
that guesses which container it may restart is one typo away from restarting the
wrong one.

`/v1/pool` returns `size = len(pool)`, the live pool. An HTTP 200 only proves the
process started; only `size == num_pipelines` proves the new YAML took effect.
That distinction is the whole reason the publish flow polls instead of trusting
the compose exit code.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("s2s.params")

POLL_SECONDS = 2.0
DEFAULT_TIMEOUT = 180.0
COMPOSE_TIMEOUT = 300.0
# `stuck` is the one pool state that means "this unit will not serve again
# without a restart" (websocket_router.py:639-674).
BAD_STATES = frozenset({"stuck"})


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    command: tuple[str, ...] = ()


@dataclass(frozen=True)
class PoolState:
    reachable: bool
    size: int = 0
    in_use: int = 0
    units: tuple[dict[str, Any], ...] = ()
    error: str = ""

    @property
    def stuck(self) -> int:
        return sum(1 for unit in self.units if unit.get("state") in BAD_STATES)

    @property
    def busy(self) -> int:
        return sum(1 for unit in self.units if unit.get("state") == "active")


@dataclass(frozen=True)
class HealthResult:
    ok: bool
    reason: str
    elapsed_s: float
    attempts: int = 0
    pool: PoolState | None = None
    notes: list[str] = field(default_factory=list)


# ── environment ──────────────────────────────────────────────────────────────


def compose_file() -> Path:
    explicit = os.environ.get("PARAM_COMPOSE_FILE", "").strip()
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parent.parent.parent / "docker-compose.yml"


def compose_service() -> str:
    # No default. Restarting a guessed service is worse than refusing.
    return os.environ.get("PARAM_COMPOSE_SERVICE", "").strip()


def pool_url() -> str:
    return os.environ.get("PARAM_POOL_URL", "http://127.0.0.1:8765").strip()


def config_dir() -> Path:
    explicit = os.environ.get("PARAM_CONFIG_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return Path(__file__).resolve().parent.parent.parent / "config"


# ── compose ──────────────────────────────────────────────────────────────────


def available() -> tuple[bool, str]:
    """`(usable, reason)`. A missing docker is a normal state, not an error."""
    if shutil.which("docker") is None:
        return False, "docker CLI not found on PATH"
    result = _run(["docker", "compose", "version"], timeout=20.0)
    if not result.ok:
        return False, f"docker compose not usable: {result.stderr.strip()[:200]}"
    return True, result.stdout.strip()


def recreate() -> CommandResult:
    """`up -d --force-recreate <service>`. The only write this module does."""
    service = compose_service()
    if not service:
        return CommandResult(
            ok=False,
            returncode=-1,
            stdout="",
            stderr="PARAM_COMPOSE_SERVICE is unset; refusing to guess a container",
            duration_s=0.0,
        )
    target = compose_file()
    if not target.is_file():
        return CommandResult(
            ok=False,
            returncode=-1,
            stdout="",
            stderr=f"compose file not found: {target}",
            duration_s=0.0,
        )
    return _run(
        [
            "docker",
            "compose",
            "-f",
            str(target),
            "up",
            "-d",
            "--force-recreate",
            service,
        ],
        timeout=COMPOSE_TIMEOUT,
    )


def container_status() -> dict[str, Any]:
    """A.7's `container` block: name, status, image, when it started.

    Read from `compose ps` rather than `docker inspect` so the answer carries the
    compose service label. An absent container is reported, not raised: the
    console has to render "stopped" just as readily as "running".
    """
    empty = {"name": None, "status": "unknown", "image": None, "started_at": None}
    service = compose_service()
    if not service:
        return {**empty, "error": "PARAM_COMPOSE_SERVICE is unset"}
    result = _run(
        ["docker", "compose", "-f", str(compose_file()), "ps", "--format", "json", service],
        timeout=30.0,
    )
    if not result.ok:
        return {**empty, "error": result.stderr.strip()[:300]}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        return {
            "name": row.get("Name") or row.get("Service"),
            "status": (row.get("State") or "unknown").lower(),
            "image": row.get("Image"),
            "started_at": row.get("StartedAt"),
        }
    return {**empty, "status": "not_created"}


def logs(tail: int = 200) -> str:
    service = compose_service()
    if not service:
        return ""
    result = _run(
        ["docker", "compose", "-f", str(compose_file()), "logs", "--tail", str(tail), service],
        timeout=60.0,
    )
    if not result.ok:
        return result.stderr.strip()
    return result.stdout


def _run(command: list[str], *, timeout: float) -> CommandResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            # Never inherit stdin: compose may otherwise wait for a TTY prompt.
            stdin=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        return CommandResult(False, -1, "", f"{command[0]} not found: {exc}", _elapsed(started), tuple(command))
    except subprocess.TimeoutExpired:
        return CommandResult(
            False, -1, "", f"timed out after {timeout:.0f}s", _elapsed(started), tuple(command)
        )

    return CommandResult(
        ok=completed.returncode == 0,
        returncode=completed.returncode,
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
        duration_s=_elapsed(started),
        command=tuple(command),
    )


def _elapsed(started: float) -> float:
    return round(time.monotonic() - started, 3)


# ── pool probe ───────────────────────────────────────────────────────────────


def read_pool(timeout: float = 5.0) -> PoolState:
    url = pool_url().rstrip("/") + "/v1/pool"
    try:
        response = httpx.get(url, timeout=timeout)
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError as exc:
        return PoolState(reachable=False, error=f"{type(exc).__name__}: {exc}")
    except ValueError as exc:
        return PoolState(reachable=False, error=f"invalid JSON: {exc}")

    units = body.get("units") or []
    return PoolState(
        reachable=True,
        size=int(body.get("size") or 0),
        in_use=int(body.get("in_use") or 0),
        units=tuple(unit for unit in units if isinstance(unit, dict)),
    )


def wait_healthy(
    expected_size: int, *, timeout: float = DEFAULT_TIMEOUT, interval: float = POLL_SECONDS
) -> HealthResult:
    """Poll until the pool is the size the new YAML asked for.

    A pool larger or smaller than `expected_size` means the container is still
    serving the old config (or a partially started one), so neither counts.
    Active sessions do not fail the publish — they keep running on the handler
    that accepted them — but they are reported, because "the new config is live"
    and "every user is on the new config" are different claims.
    """
    started = time.monotonic()
    deadline = started + timeout
    attempts = 0
    last: PoolState | None = None

    while True:
        attempts += 1
        last = read_pool()
        ok, reason = _judge(last, expected_size)
        if ok:
            notes = []
            if last.busy:
                notes.append(
                    f"{last.busy} session(s) still on the previous handler; "
                    "they pick up the new config when they reconnect"
                )
            return HealthResult(
                ok=True,
                reason=reason,
                elapsed_s=round(time.monotonic() - started, 1),
                attempts=attempts,
                pool=last,
                notes=notes,
            )
        if time.monotonic() + interval > deadline:
            return HealthResult(
                ok=False,
                reason=f"after {timeout:.0f}s: {reason}",
                elapsed_s=round(time.monotonic() - started, 1),
                attempts=attempts,
                pool=last,
            )
        time.sleep(interval)


def _judge(state: PoolState, expected_size: int) -> tuple[bool, str]:
    if not state.reachable:
        return False, state.error or "pool unreachable"
    if state.stuck:
        return False, f"{state.stuck} unit(s) stuck"
    if state.size != expected_size:
        return False, f"pool size {state.size}, expected {expected_size}"
    return True, f"pool size {state.size}, {state.in_use} in use"


# ── file backups (chain A, step 5 and 8) ─────────────────────────────────────


def backup(path: Path, version: int) -> Path | None:
    """`<name>.bak.<version>`. Returns None when there is nothing to keep.

    The suffix carries the version so a rollback can name exactly which state it
    restored, and two publishes never overwrite each other's backup.
    """
    if not path.is_file():
        return None
    target = path.with_suffix(path.suffix + f".bak.{version}")
    shutil.copy2(path, target)
    return target


def restore(source: Path, target: Path) -> bool:
    if not source.is_file():
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return True
