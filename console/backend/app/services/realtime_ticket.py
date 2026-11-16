"""realtime 一次性短票据（Task 16，spec 2026-11-17 §7.4 草案·WS 票据端点）。

浏览器先拿用户 JWT 换一张 60s 一次性票据，WS 升级时凭票接入——JWT 不上
查询串（会进访问日志），票据用完即焚。内存表即可：console 单进程，重启即清。
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

TTL_S = 60.0

# ticket → (username, role, issued_monotonic)；消费即删。
_TICKETS: dict[str, tuple[str, str, float]] = {}


@dataclass
class TicketIdentity:
    username: str
    role: str


def issue(username: str, role: str) -> str:
    ticket = secrets.token_urlsafe(16)  # 128bit
    _TICKETS[ticket] = (username, role, time.monotonic())
    return ticket


def consume(ticket: str) -> TicketIdentity | None:
    entry = _TICKETS.pop(ticket, None)
    if entry is None:
        return None
    username, role, issued = entry
    if time.monotonic() - issued > TTL_S:
        return None
    return TicketIdentity(username=username, role=role)
