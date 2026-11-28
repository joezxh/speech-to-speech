"""工具执行分派：按 type 路由到 provider，统一 `{mode,provider,data}` 信封。"""

from __future__ import annotations

import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.config import tools
from app.core.errors import ApiError
from app.models.tool import ConsoleTool
from app.services.tool_providers import calendar as calendar_provider
from app.services.tool_providers import kb as kb_provider
from app.services.tool_providers import search as search_provider
from app.services.tool_providers import weather as weather_provider

MAX_BODY = 64 * 1024


def _validate_url(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ApiError("invalid_request", "tool endpoint must be an http(s) URL", 400)
    if not tools.http_allow_private:
        host = parsed.hostname.strip("[]").lower()
        if host in ("localhost", "localhost.localdomain") or re.fullmatch(r"[0-9]+", host):
            raise ApiError("invalid_request", "private network endpoints are not allowed", 400)
        try:
            addresses = [ipaddress.ip_address(host)]
        except ValueError:
            try:
                addresses = [
                    ipaddress.ip_address(info[4][0])
                    for info in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
                ]
            except OSError as exc:
                raise ApiError("invalid_request", f"cannot resolve tool endpoint host: {exc}", 400) from exc
        if any(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast for ip in addresses):
            raise ApiError("invalid_request", "private network endpoints are not allowed", 400)
    return endpoint


async def execute(db: Session, tool: ConsoleTool, arguments: dict, username: str) -> dict:
    if not tool.enabled and tool.scope != "session":
        raise ApiError("forbidden", f"tool {tool.id} is disabled", 403)

    kind = tool.type
    try:
        if kind == "web_search":
            data = await search_provider.search(
                str(arguments.get("query", "")),
                int(arguments.get("top_k", 5) or 5),
                tool.config or {},
            )
            return {"mode": data["mode"], "provider": data["provider"], "data": data}
        if kind == "weather":
            data = await weather_provider.weather(str(arguments.get("city", "")))
            return {"mode": data["mode"], "provider": "openweather", "data": data}
        if kind == "kb":
            data = kb_provider.kb_search(str(arguments.get("query", "")), int(arguments.get("top_k", 5) or 5))
            return {"mode": data["mode"], "provider": "local-docs", "data": data}
        if kind == "calendar":
            action = str(arguments.get("action", "list"))
            if action == "create":
                data = calendar_provider.calendar_create(db, username, arguments)
            elif action == "delete":
                data = {
                    "mode": "local",
                    "deleted": calendar_provider.calendar_delete(
                        db, username, int(arguments.get("event_id", 0) or 0)
                    ),
                }
            else:
                data = calendar_provider.calendar_list(db, username)
            return {"mode": data.get("mode", "local"), "provider": "local-calendar", "data": data}
        if kind == "http":
            url = _validate_url(tool.endpoint)
            method = (tool.method or "GET").upper()
            async with httpx.AsyncClient(timeout=8.0) as http:
                response = await http.request(method, url, json=arguments if method == "POST" else None,
                                              params=arguments if method == "GET" else None)
            response.raise_for_status()
            return {"mode": "live", "provider": "http", "data": {"body": response.text[:MAX_BODY]}}
    except ApiError:
        raise
    except Exception as exc:
        logger.warning("tool {} execution failed: {}", tool.id, exc)
        if kind in ("web_search", "weather"):
            return {"mode": "demo", "provider": "fallback", "data": {"error": str(exc)[:200]}}
        raise ApiError("provider_error", f"tool {tool.id} execution failed", 502) from exc
    raise ApiError("invalid_request", f"unsupported tool type {kind}", 400)
