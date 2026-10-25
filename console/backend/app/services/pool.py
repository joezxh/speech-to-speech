"""Talking to the pipeline's own loopback API (A.10's `pool` section).

No docker here: the console and the pipeline share a container, so “what is
running” is supervisor's answer, and “is it serving” is `/v1/pool`'s.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import console

POLL_SECONDS = 2.0
DEFAULT_TIMEOUT = 180.0
# `stuck` is the one pool state that means "this unit will not serve again
# without a restart" (websocket_router.py:660-695).
BAD_STATES = frozenset({"stuck"})


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


def pool_url(base_url: str | None = None) -> str:
    """`base_url` lets a caller probe *another* instance (P1.1); without it the
    console keeps talking to its own co-located pipeline exactly as before."""
    return (base_url or console.pipeline_base_url).rstrip("/")


def read_pool(timeout: float = 5.0, base_url: str | None = None) -> PoolState:
    try:
        response = httpx.get(f"{pool_url(base_url)}/v1/pool", timeout=timeout)
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


def read_usage(timeout: float = 5.0, base_url: str | None = None) -> dict[str, Any] | None:
    """`None` rather than an empty dict: “no data” must not look like zero."""
    try:
        response = httpx.get(f"{pool_url(base_url)}/v1/usage", timeout=timeout)
        response.raise_for_status()
        body = response.json()
    except (httpx.HTTPError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def wait_healthy(
    expected_size: int | None, *, timeout: float = DEFAULT_TIMEOUT, interval: float = POLL_SECONDS
) -> HealthResult:
    """Poll until the pool is the size the new YAML asked for.

    A pool larger or smaller than `expected_size` means the process is still
    serving the old config (or a partially started one), so neither counts.
    `expected_size=None` (num_pipelines is `{env: N}`) judges reachability only.
    Active sessions do not fail the publish — they keep running on the handler
    that accepted them — but they are reported.
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
                reason=f"after {timeout:g}s: {reason}",
                elapsed_s=round(time.monotonic() - started, 1),
                attempts=attempts,
                pool=last,
            )
        time.sleep(interval)


def _judge(state: PoolState, expected_size: int | None) -> tuple[bool, str]:
    if not state.reachable:
        return False, state.error or "pool unreachable"
    if state.stuck:
        return False, f"{state.stuck} unit(s) stuck"
    if expected_size is not None and state.size != expected_size:
        return False, f"pool size {state.size}, expected {expected_size}"
    return True, f"pool size {state.size}, {state.in_use} in use"
