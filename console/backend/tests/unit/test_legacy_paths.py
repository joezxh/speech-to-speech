"""P5: the archived demo's URLs must answer 404, not index.html.

`spa_fallback` answers every unmatched GET with index.html. Without the
suffix rule, `/main.js` returns 200 `text/html`, and the browser reports a
syntax error at line 1 — which reads as "the page is broken", not "this
asset was removed".
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "assets" / "index-abc123.js").write_text("// bundle", encoding="utf-8")
    (root / "index.html").write_text("<!doctype html><div id=app></div>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


@pytest.fixture
def client(dist):
    return TestClient(create_app())


@pytest.mark.parametrize(
    "path",
    [
        "/main.js",
        "/style.css",
        "/s2s-realtime-client.js",
        "/turn-latency.js",
        "/console.html",
        "/ui/console/api.js",
        "/ws/codec.js",
    ],
)
def test_a_removed_demo_asset_is_404(client, path):
    response = client.get(path)
    assert response.status_code == 404
    # The failure mode this test exists for: 200 with text/html.
    assert not response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/console/versions",
        "/console/profiles/prod",
        # `/v1` is deliberately NOT a wildcard reverse proxy (Task 19): an
        # unknown `/v1/...` path keeps falling through to index.html. Only
        # `/v1/realtime` and `/v1/realtime/calls` are real routes.
        "/v1/pool",
    ],
)
def test_a_client_side_route_still_gets_the_spa(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_a_real_built_asset_is_still_served(client):
    response = client.get("/assets/index-abc123.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_the_404_uses_fastapi_default_shape(client):
    # Not the console's {code, message, detail, requestId} envelope: a removed
    # static file is not an ApiError, and curl consumers should see the plain
    # FastAPI body every other 404 on this server uses.
    assert client.get("/main.js").json() == {"detail": "Not Found"}
