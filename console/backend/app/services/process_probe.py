"""What is running, as opposed to what the console believes (A.10).

A seam on purpose: Task 14 supplies the supervisor-backed probe. Everything in
this task works against `NullProbe`, which reports failure instead of raising —
`/instances` must stay a 200 exactly when the pipeline is down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProcessInfo:
    name: str
    running: bool
    pid: int | None = None
    state: str = "unknown"
    detail: str = ""


class ProcessProbe(Protocol):
    def state(self, name: str) -> ProcessInfo: ...


class NullProbe:
    def __init__(self, detail: str = "supervisor probe not installed") -> None:
        self._detail = detail

    def state(self, name: str) -> ProcessInfo:
        return ProcessInfo(name=name, running=False, state="unknown", detail=self._detail)


_probe: ProcessProbe | None = None


def get_probe() -> ProcessProbe:
    global _probe
    if _probe is None:
        _probe = _build()
    return _probe


def set_probe(probe: ProcessProbe | None) -> None:
    """Test seam. `None` re-resolves on next access."""
    global _probe
    _probe = probe


def _build() -> ProcessProbe:
    # Task 14 replaces this body with the XML-RPC-over-unix-socket probe.
    return NullProbe("supervisor probe not installed")
