"""`GET /api/config`: the browser's bootstrap facts (A.13).

Deliberately env-only: no database, no identity, no pipeline call. The voice page
asks for this before it has a cookie or a token, so it must never block.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import console, demo


def ice_servers(raw: str) -> list[dict[str, Any]]:
    """JSON list / single object / comma list — same three forms as demo (§9.2)."""
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            return [data]
    except ValueError:
        pass
    return [{"urls": item.strip()} for item in raw.split(",") if item.strip()]


def config() -> dict[str, Any]:
    """A.13's key set. The LB address itself is never included."""
    return {
        "search": demo.server_search,
        "lb": bool(demo.lb_url),
        "allowDirect": not demo.lb_url,
        "s2sUrl": demo.pinned_url,
        "rtc": bool(demo.pinned_url),
        "iceServers": ice_servers(demo.rtc_ice_servers),
        "startupGreeting": demo.startup_greeting.strip(),
        "auth": demo.auth_enabled,
        # Which pipeline this console is wired to. Read from settings, so the
        # voice page shows the same host the status probe and the WS proxy use.
        "pipeline": {
            "baseUrl": console.pipeline_base_url.strip(),
            "container": console.pipeline_container.strip(),
        },
    }
