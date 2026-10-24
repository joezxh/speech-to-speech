from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def dist(tmp_path, monkeypatch):
    root = tmp_path / "dist"
    (root / "vendor" / "local-vad").mkdir(parents=True)
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "vendor" / "openai-realtime-agents.umd.js").write_text("// umd", encoding="utf-8")
    (root / "vendor" / "local-vad" / "bundle.min.js").write_text("// vad", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(root))
    return root


def test_agents_bundle_is_served_as_javascript(dist):
    response = TestClient(create_app()).get("/vendor/openai-realtime-agents.umd.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert "immutable" in response.headers["cache-control"]


def test_a_whitelisted_vad_asset_is_served(dist):
    response = TestClient(create_app()).get("/vendor/local-vad/bundle.min.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")


def test_an_unlisted_vad_filename_is_404(dist):
    # A.13: only the six pinned names exist; anything else must look absent.
    response = TestClient(create_app()).get("/vendor/local-vad/secrets.txt")
    assert response.status_code == 404


def test_a_missing_whitelisted_asset_is_503_asset_missing(dist):
    (dist / "vendor" / "local-vad" / "bundle.min.js").unlink()
    response = TestClient(create_app()).get("/vendor/local-vad/bundle.min.js")
    assert response.status_code == 503
    assert response.json()["code"] == "asset_missing"


def test_the_spa_fallback_still_serves_console_routes(dist):
    # Registering /vendor must not reorder anything: deep links still get index.html.
    response = TestClient(create_app()).get("/console/versions")
    assert response.status_code == 200
    assert response.text == "<html></html>"
