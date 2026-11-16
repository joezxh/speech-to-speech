from __future__ import annotations

import gzip

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services import allocator, audio_proxy_service, instance_monitor, upstream_resolver
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def lb_proxy(monkeypatch):
    monkeypatch.setattr("app.main.console_settings.lb_mode", "proxy")
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._held.clear()
    upstream_resolver.reset_inflight()


def _register(capabilities, base_url="http://pipe:8765"):
    instance_monitor.registry._states["pipe"] = RuntimeState(
        instance_id="pipe",
        base_url=base_url,
        capabilities=frozenset(capabilities),
    )
    instance_monitor.registry.observe_success(
        "pipe", PoolState(reachable=True, size=4, in_use=0, units=()), 5
    )


def _fake_upstream(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        audio_proxy_service,
        "_client",
        lambda *a, **k: httpx.AsyncClient(transport=transport),
    )


def test_the_multipart_boundary_reaches_the_upstream_unchanged(dist, lb_proxy, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"text": "ok"})

    _register({"asr"})
    _fake_upstream(monkeypatch, handler)
    boundary = "----X9Y"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="a.wav"\r\n\r\n'
        "RIFFDATA\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/audio/transcriptions",
            content=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
    assert response.status_code == 200
    # boundary 与 body 都必须逐字到达：重新拼 multipart 是这类代理最常见的 bug 源。
    assert seen[0].headers["content-type"] == f"multipart/form-data; boundary={boundary}"
    assert seen[0].content == body


def test_the_wav_response_has_no_stale_encoding_headers(dist, lb_proxy, monkeypatch):
    # httpx 会解压响应体，但 headers 里仍留着 content-encoding 与压缩前的
    # content-length；照抄就会把 wav 弄坏。上游发真 gzip 字节来复现这个组合。
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=gzip.compress(b"RIFFWAVE"),
            headers={"content-type": "audio/wav", "content-encoding": "gzip"},
        )

    _register({"tts"})
    _fake_upstream(monkeypatch, handler)
    with TestClient(create_app()) as client:
        response = client.post("/v1/audio/speech", content=b"hello")
    assert response.status_code == 200
    assert response.content == b"RIFFWAVE"
    assert response.headers["content-type"] == "audio/wav"
    assert "content-encoding" not in response.headers
    assert int(response.headers["content-length"]) == len(b"RIFFWAVE")


def test_the_bearer_token_is_forwarded_verbatim(dist, lb_proxy, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    _register({"voiceprint"})
    _fake_upstream(monkeypatch, handler)
    with TestClient(create_app()) as client:
        client.post(
            "/v1/audio/embeddings", content=b"x", headers={"Authorization": "Bearer vp_key"}
        )
    assert seen[0].headers["authorization"] == "Bearer vp_key"


def test_an_upstream_error_is_passed_through(dist, lb_proxy, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"code": "unauthorized"}})

    _register({"voiceprint"})
    _fake_upstream(monkeypatch, handler)
    with TestClient(create_app()) as client:
        response = client.get("/v1/audio/embeddings/capability")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_an_oversized_body_never_reaches_the_upstream(dist, lb_proxy, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    _register({"asr"})
    _fake_upstream(monkeypatch, handler)
    monkeypatch.setattr("app.main.console_settings.lb_audio_max_bytes", 64)
    with TestClient(create_app()) as client:
        response = client.post("/v1/audio/transcriptions", content=b"x" * 128)
    assert response.status_code == 413
    # 413 的错误体是 pipeline 风格（不是 console 的 envelope）
    assert response.json()["error"]["code"] == "request_too_large"
    # 关键：超限时上游一个字节都没收到
    assert seen == []


def test_the_disabled_lb_answers_501_json_not_the_spa(dist, monkeypatch):
    monkeypatch.setattr("app.main.console_settings.lb_mode", "off")
    with TestClient(create_app()) as client:
        response = client.get("/v1/audio/embeddings/capability")
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "lb_disabled"


def test_no_available_instance_answers_503(dist, lb_proxy):
    with TestClient(create_app()) as client:
        response = client.post("/v1/audio/speech", content=b"hi")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "no_available_instance"


def test_an_instance_without_the_capability_is_not_picked(dist, lb_proxy, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    # 这台机器只有 asr，没有声纹：声纹请求不该发给它。
    _register({"asr"})
    _fake_upstream(monkeypatch, handler)
    with TestClient(create_app()) as client:
        response = client.post("/v1/audio/embeddings", content=b"x")
    assert response.status_code == 503
    assert seen == []
