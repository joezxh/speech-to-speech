"""Cumulative usage aggregation shared by ``/v1/usage`` and ``/v1/agent/usage``.

The pool is the single source of truth for usage counters. Keeping the
aggregation here means the observability endpoint and the agent's own
delta source cannot drift apart, and the agent never has to call its own
HTTP server to learn what it already knows.
"""

from __future__ import annotations

from typing import Any, Iterable


def _merge(into: dict[str, Any], src: dict[str, Any]) -> None:
    """Numeric fields sum; dict fields merge leaf-wise; other values first-wins."""

    for key, value in src.items():
        if isinstance(value, (int, float)):
            into[key] = into.get(key, 0) + value
        elif isinstance(value, dict):
            sub = into.setdefault(key, {})
            if isinstance(sub, dict):
                _merge(sub, value)
        else:
            into.setdefault(key, value)


def aggregate_pool_usage(pool: Iterable[Any]) -> dict[str, Any]:
    """Sum usage across every pipeline unit in *pool*.

    Numeric fields sum; dict fields (e.g. ``errors_by_type``) merge with their
    numeric leaves summed too, so per-unit error counts don't get dropped by
    the first unit's value.
    """

    total: dict[str, Any] = {}
    for unit in pool:
        _merge(total, unit.service.get_usage())
    return total


def pool_usage_snapshot(pool: Iterable[Any]) -> dict[str, Any]:
    """The agent's view of the pool counters.

    Same numbers, agent field names: the agent reports a window delta on every
    heartbeat, and ``responses_completed`` is the counter that actually moves.
    """

    total = aggregate_pool_usage(pool)
    return {
        "input_tokens": int(total.get("input_tokens") or 0),
        "output_tokens": int(total.get("output_tokens") or 0),
        "responses": int(total.get("responses_completed") or 0),
        "audio_duration_s": float(total.get("audio_duration_s") or 0.0),
        "window_s": int(total.get("window_s") or 0),
        # per-backend call counters; the agent diffs and reports them the same
        # way as the scalar counters. Empty when no turn has finalized yet.
        "backends": total.get("backends") or {},
    }


__all__ = ["aggregate_pool_usage", "pool_usage_snapshot"]
