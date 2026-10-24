from fastapi.testclient import TestClient

from app.main import create_app


def test_health_is_a_bare_object(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    monkeypatch.setattr("app.main.console_settings.static_dir", str(dist))

    response = TestClient(create_app()).get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # Bare object: no code/message/data envelope (A.0.1).
    assert set(body) == {"status", "version"}
