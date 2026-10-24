from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.config import console as console_settings
from app.core.errors import ApiError
from app.db.database import SessionLocal
from app.models import ParamVersion
from app.repositories.draft_repository import DraftRepository
from app.repositories.version_repository import VersionRepository
from app.services import pool, publish_flow_service, restart_runner

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"
BASE_YAML = "schema_version: 1\npipelines:\n  prod:\n    num_pipelines: 1\n"


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    (directory / "prod.yaml").write_text(BASE_YAML, encoding="utf-8")
    monkeypatch.setattr(console_settings, "param_config_dir", str(directory))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    return directory


@pytest.fixture
def healthy(monkeypatch):
    monkeypatch.setattr(restart_runner, "restart", lambda: 1.0)
    monkeypatch.setattr(
        pool,
        "wait_healthy",
        lambda expected, timeout=180.0, interval=2.0: pool.HealthResult(
            ok=True,
            reason="pool size 1, 0 in use",
            elapsed_s=1.0,
            attempts=1,
            pool=pool.PoolState(reachable=True, size=1),
        ),
    )


def test_an_env_field_is_refused_before_anything_is_written(config_dir, healthy, db_session):
    DraftRepository(db_session).put(
        "prod", base_version=0, patch={"env.GPUSTACK_API_KEY": "gsk-x"}, actor="alice"
    )
    before = (config_dir / "prod.yaml").read_bytes()

    with pytest.raises(ApiError) as caught:
        publish_flow_service.publish(db_session, "prod", actor="alice", role="admin")

    assert caught.value.code == "env_requires_recreate"
    assert caught.value.status == 409
    # Only the variable name, never its value (B7).
    assert caught.value.detail == [{"var": "GPUSTACK_API_KEY"}]
    assert (config_dir / "prod.yaml").read_bytes() == before
    assert VersionRepository(db_session).list("prod")[1] == 0
    assert DraftRepository(db_session).get("prod") is not None


def test_a_dead_supervisor_aborts_and_restores_the_backup(config_dir, db_session, monkeypatch):
    original = (config_dir / "prod.yaml").read_bytes()
    DraftRepository(db_session).put(
        "prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice"
    )
    monkeypatch.setattr("app.services.publish_flow_service.render", _rendered)
    monkeypatch.setattr(
        restart_runner,
        "restart",
        lambda: (_ for _ in ()).throw(
            ApiError(code="restart_unavailable", message="no socket", status=502)
        ),
    )

    with pytest.raises(ApiError) as caught:
        publish_flow_service.publish(db_session, "prod", actor="alice", role="admin")

    assert caught.value.code == "restart_unavailable"
    # The whole point: what runs must be what ran before, byte for byte.
    assert (config_dir / "prod.yaml").read_bytes() == original
    row = VersionRepository(db_session).list("prod")[0][0]
    assert row.status == "rolled_back"


def test_a_healthcheck_timeout_marks_rolled_back(config_dir, db_session, monkeypatch):
    DraftRepository(db_session).put(
        "prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice"
    )
    monkeypatch.setattr("app.services.publish_flow_service.render", _rendered)
    monkeypatch.setattr(restart_runner, "restart", lambda: 1.0)
    monkeypatch.setattr(
        pool,
        "wait_healthy",
        lambda expected, timeout=180.0, interval=2.0: pool.HealthResult(
            ok=False, reason="after 180s: pool size 0, expected 1", elapsed_s=180.0, attempts=90
        ),
    )

    with pytest.raises(ApiError) as caught:
        publish_flow_service.publish(db_session, "prod", actor="alice", role="admin")

    assert (caught.value.code, caught.value.status) == ("healthcheck_timeout", 504)
    assert VersionRepository(db_session).list("prod")[0][0].status == "rolled_back"


def test_a_second_publish_is_refused_while_the_first_holds_the_lock(config_dir, healthy, db_session):
    DraftRepository(db_session).put(
        "prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice"
    )
    assert publish_flow_service._lock.acquire(blocking=False)
    try:
        with pytest.raises(ApiError) as caught:
            publish_flow_service.publish(db_session, "prod", actor="alice", role="admin")
        assert (caught.value.code, caught.value.status) == ("publish_in_progress", 409)
    finally:
        publish_flow_service._lock.release()


def test_the_draft_disappears_only_after_a_successful_publish(
    config_dir, healthy, db_session, monkeypatch
):
    DraftRepository(db_session).put(
        "prod", base_version=0, patch={"vad.min_silence_ms": 900}, actor="alice"
    )
    monkeypatch.setattr("app.services.publish_flow_service.render", _rendered)

    result = publish_flow_service.publish(db_session, "prod", actor="alice", role="admin", note="tune")

    assert result["status"] == "live"
    assert result["version"] == 1
    assert DraftRepository(db_session).get("prod") is None
    assert VersionRepository(db_session).latest_live("prod").version == 1


def _rendered(profile, values, environ=None):
    text = BASE_YAML.replace("num_pipelines: 1", "num_pipelines: 1\n    seed: 1")
    return publish_flow_service.Rendered(
        text=text, values=values, applied=sorted(values), expected_size=1, resolved={"pipelines": [profile]}
    )
