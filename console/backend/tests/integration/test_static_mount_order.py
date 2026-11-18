import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "index.html").write_text("<!doctype html><div id=app></div>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))
    return TestClient(create_app())


def test_api_survives_the_spa_catch_all(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_unknown_console_route_returns_index_not_404(client):
    response = client.get("/console/versions")
    assert response.status_code == 200
    assert "<div id=app>" in response.text
    assert response.headers["cache-control"] == "no-store"


def test_hashed_asset_is_cached_hard(client):
    response = client.get("/assets/app.js")
    assert response.status_code == 200
    assert "immutable" in response.headers["cache-control"]


def test_docs_is_the_api_reference_not_the_spa(client):
    """`/docs` used to be swallowed by the SPA catch-all.

    With FastAPI's docs disabled the path fell through to index.html, the
    browser booted the console bundle and the router guard bounced the user to
    /console/login?next=/ — the API reference sat behind the login page.
    """
    response = client.get("/docs")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "swagger-ui" in response.text
    assert "<div id=app>" not in response.text


def test_openapi_json_is_a_schema(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    schema = response.json()
    assert schema["info"]["title"] == "s2s-console"
    assert "/api/v1/auth/login" in schema["paths"]


def test_docs_page_gets_its_own_csp(client):
    """The strict 'self'-only CSP would render Swagger UI blank.

    FastAPI serves the page from a CDN and boots it with an inline <script>,
    so the docs routes get a policy of their own; the SPA keeps the strict one.
    """
    docs = client.get("/docs")
    assert "cdn.jsdelivr.net" in docs.headers["content-security-policy"]
    spa = client.get("/console/versions")
    assert spa.headers["content-security-policy"] == (
        "default-src 'self'; "
        "connect-src 'self' ws: wss:; "
        "img-src 'self' data: blob:; "
        "media-src 'self' blob:; "
        "worker-src 'self' blob:; "
        "script-src 'self' 'wasm-unsafe-eval'; "
        "style-src 'self' 'unsafe-inline'"
    )
