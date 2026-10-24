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
