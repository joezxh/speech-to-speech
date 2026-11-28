"""工具 provider：有 key 走真实、无 key 降级演示（Task 4 RED）。"""

from __future__ import annotations

from app.services.tool_providers import calendar, kb, search, weather


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _fake_client(monkeypatch, module, *, get=None, post=None):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    if get is not None:
        _Client.get = staticmethod(get)

    if post is not None:
        _Client.post = staticmethod(post)

    monkeypatch.setattr(module.httpx, "AsyncClient", _Client)


async def test_search_no_key_returns_demo(monkeypatch):
    monkeypatch.setattr(search, "_api_keys", lambda: {})
    out = await search.search("天气")
    assert out["mode"] == "demo"
    assert out["results"]


async def test_search_anspire_live(monkeypatch):
    async def _get(url, **kwargs):
        assert "anspire" in url
        return _Response({"data": {"webPages": [{"name": "标题", "url": "https://a.test", "snippet": "摘要"}]}})

    _fake_client(monkeypatch, search, get=_get)
    monkeypatch.setattr(search, "_api_keys", lambda: {"anspire": "k"})
    out = await search.search("天气")
    assert out["mode"] == "live"
    assert out["provider"] == "anspire"
    assert out["results"][0]["title"] == "标题"


async def test_search_bocha_live(monkeypatch):
    async def _post(url, **kwargs):
        assert "bocha" in url
        payload = {"data": {"webPages": {"value": [{"name": "博查", "url": "https://b.test", "snippet": "结果"}]}}}
        return _Response(payload)

    _fake_client(monkeypatch, search, post=_post)
    monkeypatch.setattr(search, "_api_keys", lambda: {"bocha": "k"})
    out = await search.search("test")
    assert out["provider"] == "bocha"
    assert out["results"][0]["title"] == "博查"


async def test_search_provider_failure_falls_back_to_demo(monkeypatch):
    async def _get(url, **kwargs):
        raise RuntimeError("provider down")

    _fake_client(monkeypatch, search, get=_get)
    monkeypatch.setattr(search, "_api_keys", lambda: {"anspire": "k"})
    out = await search.search("test")
    assert out["mode"] == "demo"


async def test_weather_no_key_returns_demo(monkeypatch):
    monkeypatch.setattr(weather, "_api_key", lambda: "")
    out = await weather.weather("北京")
    assert out["mode"] == "demo"
    assert out["city"] == "北京"
    assert "temperature" in out


async def test_weather_live(monkeypatch):
    async def _get(url, **kwargs):
        return _Response(
            {
                "name": "Beijing",
                "main": {"temp": 21.5, "humidity": 60},
                "weather": [{"description": "clear sky"}],
                "wind": {"speed": 3.2},
            }
        )

    _fake_client(monkeypatch, weather, get=_get)
    monkeypatch.setattr(weather, "_api_key", lambda: "k")
    out = await weather.weather("Beijing")
    assert out["mode"] == "live"
    assert out["temperature"] == 21.5


def test_calendar_create_list_delete(db_session):
    created = calendar.calendar_create(
        db_session, "alice", {"title": "会议", "start_at": "2026-11-28T10:00", "end_at": "2026-11-28T11:00", "description": ""}
    )
    assert created["title"] == "会议"
    rows = calendar.calendar_list(db_session, "alice")
    assert len(rows["events"]) == 1
    assert calendar.calendar_delete(db_session, "alice", created["id"]) is True
    assert calendar.calendar_list(db_session, "alice")["events"] == []


def test_calendar_owner_isolation(db_session):
    calendar.calendar_create(db_session, "alice", {"title": "私密", "start_at": "", "end_at": "", "description": ""})
    assert calendar.calendar_list(db_session, "bob")["events"] == []
    assert calendar.calendar_delete(db_session, "bob", 1) is False


def test_kb_search_finds_spec_heading():
    out = kb.kb_search("工具", top_k=3)
    assert out["mode"] == "local"
    assert out["items"]
    assert any("tools" in item["path"] or "console" in item["path"] for item in out["items"])
