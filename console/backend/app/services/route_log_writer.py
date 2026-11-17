"""路由记账异步落库（Task 18，spec 2026-11-17 §5.5/§4.3 L6）。

submit 只入内存队列，绝不阻塞选台；lifespan 周期任务调 flush 批量入库。
队列满 → 丢弃并计数（可观测），不回压数据面。
"""

from __future__ import annotations

import queue
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.repositories.lb_repository import append_route_log

MAX_QUEUE = 2000
_QUEUE: queue.Queue = queue.Queue(maxsize=MAX_QUEUE)
_DROPPED = 0


@dataclass(frozen=True)
class RouteLogEntry:
    session_key: str
    rule_id: int | None = None
    matched: bool = False
    sticky_hit: bool = False
    is_canary: bool = False
    instance_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


def submit(entry: RouteLogEntry) -> None:
    global _DROPPED  # noqa: PLW0603
    try:
        _QUEUE.put_nowait(entry)
    except queue.Full:
        _DROPPED += 1


def flush(db: Session) -> int:
    drained: list[RouteLogEntry] = []
    while len(drained) < MAX_QUEUE:
        try:
            drained.append(_QUEUE.get_nowait())
        except queue.Empty:
            break
    for entry in drained:
        append_route_log(
            db,
            session_key=entry.session_key,
            rule_id=entry.rule_id,
            matched=entry.matched,
            sticky_hit=entry.sticky_hit,
            is_canary=entry.is_canary,
            instance_id=entry.instance_id,
            input_tokens=entry.input_tokens,
            output_tokens=entry.output_tokens,
        )
    return len(drained)


def queue_stats() -> dict:
    return {"queued": _QUEUE.qsize(), "dropped": _DROPPED}


def reset_for_test() -> None:
    global _DROPPED  # noqa: PLW0603
    while not _QUEUE.empty():
        _QUEUE.get_nowait()
    _DROPPED = 0
