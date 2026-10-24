"""The demo face: byte-compatible with `demo/server.py` (A.13), never enveloped."""

from . import calls, config, me, queue, search, session

# Order is the A.13 table's order; nothing here overlaps another prefix.
ROUTERS = (config.router, me.router, search.router, calls.router, session.router, queue.router)

__all__ = ["ROUTERS", "calls", "config", "me", "queue", "search", "session"]
