"""What is running, as opposed to what the console believes (A.10).

A seam on purpose: Task 14 supplies the supervisor-backed probe. Everything in
this task works against `NullProbe`, which reports failure instead of raising —
`/instances` must stay a 200 exactly when the pipeline is down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.services import supervisor_client


@dataclass(frozen=True)
class ProcessInfo:
    name: str
    running: bool
    pid: int | None = None
    state: str = "unknown"
    detail: str = ""

    def confirmed_stopped(self) -> bool:
        """Supervisor positively reports the program is not running.

        `unknown` (no socket — a dev box, or a console not co-located with the
        pipeline's supervisord) is *absence of evidence*, not evidence of a
        stopped process, so it must never be reported as stopped. This is the
        same rule `status_service._pipeline_ok` and `runtime_service`
        already apply, so `/instances` no longer contradicts the top bar.
        """
        return not self.running and self.state not in ("", "unknown")


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


class SupervisorProbe:
    """read-only：问 supervisor「这个 program 现在什么状态」（§10.3）。"""

    def state(self, name: str) -> ProcessInfo:
        try:
            info = supervisor_client.state(name)
        except supervisor_client.SupervisorError as exc:
            return ProcessInfo(name=name, running=False, state="unknown", detail=str(exc))
        statename = str(info.get("statename", "unknown")).lower()
        pid = info.get("pid")
        return ProcessInfo(
            name=name,
            running=statename == "running",
            pid=pid if isinstance(pid, int) and pid > 0 else None,
            state=statename,
            detail=str(info.get("spawnerr") or ""),
        )


def _build() -> ProcessProbe:
    return SupervisorProbe()
