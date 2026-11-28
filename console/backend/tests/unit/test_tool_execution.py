"""工具执行分派与 HTTP SSRF 防护（Task 5 RED）。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.models.tool import ConsoleTool
from app.services import tool_execution_service


def _tool(kind: str, endpoint: str = "", enabled: bool = True, config: dict | None = None) -> ConsoleTool:
    return ConsoleTool(
        id="t1", name="T", type=kind, scope="global", enabled=enabled, builtin=False,
        owner="alice", endpoint=endpoint, method="GET", params=[], config=config or {},
    )


async def test_invoke_dispatches_web_search(db_session: Session, monkeypatch):
    async def _search(query, top_k=5, config=None):
        return {"mode": "demo", "provider": "demo", "results": [{"title": query}]}

    monkeypatch.setattr(tool_execution_service.search_provider, "search", _search)
    out = await tool_execution_service.execute(db_session, _tool("web_search"), {"query": "天气"}, "alice")
    assert out["mode"] == "demo"
    assert out["data"]["results"][0]["title"] == "天气"


async def test_invoke_http_tool_rejects_private_url(db_session: Session):
    with pytest.raises(ApiError) as exc:
        await tool_execution_service.execute(
            db_session, _tool("http", "http://127.0.0.1/secret"), {}, "alice"
        )
    assert exc.value.status == 400


async def test_invoke_http_tool_allows_public_url(db_session: Session, monkeypatch):
    class _Response:
        status_code = 200
        text = "ok"

        def raise_for_status(self):
            return None

    async def _request(method, url, **kwargs):
        return _Response()

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        request = staticmethod(_request)

    monkeypatch.setattr(tool_execution_service.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(
        tool_execution_service.socket, "getaddrinfo",
        lambda host, port: [(2, 1, 6, "", ("93.184.216.34", port))],
    )
    out = await tool_execution_service.execute(
        db_session, _tool("http", "https://example.com/hook"), {}, "alice"
    )
    assert out["mode"] == "live"
    assert out["data"]["body"] == "ok"


async def test_disabled_tool_raises(db_session: Session):
    with pytest.raises(ApiError) as exc:
        await tool_execution_service.execute(
            db_session, _tool("http", "https://example.com/hook", enabled=False), {}, "alice"
        )
    assert exc.value.status == 403


async def test_calendar_dispatch(db_session: Session):
    out = await tool_execution_service.execute(
        db_session, _tool("calendar"), {"action": "list"}, "alice"
    )
    assert out["mode"] == "local"
    assert out["data"]["events"] == []


async def test_weather_dispatch(db_session: Session, monkeypatch):
    async def _weather(city):
        return {"mode": "demo", "city": city, "temperature": 20}

    monkeypatch.setattr(tool_execution_service.weather_provider, "weather", _weather)
    out = await tool_execution_service.execute(db_session, _tool("weather"), {"city": "北京"}, "alice")
    assert out["data"]["temperature"] == 20
