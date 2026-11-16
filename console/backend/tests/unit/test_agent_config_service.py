"""Task 5（2026-11-17 原型对齐计划）——agent 目标配置渲染与版本内核。

复用 renderer_service.render_yaml + publish_flow_service.require_profile/entries，
不新写渲染器。profile 回落顺序：机器 profile → param_cluster.baseline_profile → prod。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401
from app.config import console as console_settings
from app.db.base import Base
from app.models.machine import ParamMachine
from app.models.param_cluster import ParamCluster
from app.models.machine_config import ParamMachineDraft
from app.repositories.machine_repository import MachineRepository
from app.services import agent_config_service
from app.services.machine_service import MachineCreate

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "parameter-catalog.min.yaml"

# 与 tests/integration/test_drafts.py 同构的最小 profile：vad-main 块带 min_silence_ms。
PROFILE_YAML = """\
schema_version: 1
runtime:
  log_level: info
blocks:
  vad-main: {kind: vad, backend: silero, settings: {min_silence_ms: 700}}
"""


@pytest.fixture
def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def config_dir(tmp_path, monkeypatch):
    directory = tmp_path / "config"
    directory.mkdir()
    # staging 的内容刻意不同，供“profile 回落”用例区分渲染源。
    (directory / "prod.yaml").write_text(PROFILE_YAML, encoding="utf-8")
    (directory / "staging.yaml").write_text(
        PROFILE_YAML.replace("log_level: info", "log_level: debug"), encoding="utf-8"
    )
    monkeypatch.setattr(console_settings, "param_config_dir", str(directory))
    monkeypatch.setattr(console_settings, "param_catalog_path", str(FIXTURE))
    return directory


def _machine(db_session, machine_id: str = "node-a01", profile: str | None = None,
             cluster_id: str = "default") -> None:
    MachineRepository(db_session).create(
        row=ParamMachine(machine_id=machine_id, cluster_id=cluster_id, profile=profile)
    )


def test_render_target_increments_version_but_keeps_stable_etag(config_dir, db_session):
    _machine(db_session)
    version_one, etag_one, _ = agent_config_service.render_target(db_session, "node-a01")
    version_two, etag_two, text = agent_config_service.render_target(db_session, "node-a01")

    assert (version_one, version_two) == (1, 2)
    assert etag_two == etag_one, "内容未变时 etag 必须稳定"
    assert "schema_version: 1" in text


def test_render_target_overlays_machine_draft(config_dir, db_session):
    _machine(db_session)
    db_session.add(ParamMachineDraft(machine_id="node-a01", param_key="vad.min_silence_ms", value="900"))
    db_session.commit()

    _, _, text = agent_config_service.render_target(db_session, "node-a01")
    assert "min_silence_ms: 900" in text


def test_draft_free_render_equals_live(config_dir, db_session):
    _machine(db_session)
    _, _, text = agent_config_service.render_target(db_session, "node-a01")
    assert "min_silence_ms: 700" in text
    assert "min_silence_ms: 900" not in text


def test_profile_falls_back_to_cluster_baseline(config_dir, db_session):
    db_session.add(ParamCluster(name="gamma", baseline_profile="staging"))
    _machine(db_session, cluster_id="gamma")
    _, _, text = agent_config_service.render_target(db_session, "node-a01")
    assert "log_level: debug" in text, "回落到集群 baseline_profile=staging"


def test_peek_version_reads_the_latest_row(config_dir, db_session):
    _machine(db_session)
    assert agent_config_service.peek_version(db_session, "node-a01") == 0
    agent_config_service.render_target(db_session, "node-a01")
    agent_config_service.render_target(db_session, "node-a01")
    assert agent_config_service.peek_version(db_session, "node-a01") == 2


def test_secret_keys_are_filtered_out():
    values = {
        "db.password": "hunter2",
        "jwt_secret": "s3cr3t",
        "service_token": "t0k3n",
        "llm.api_key": "sk-x",
        "vad.min_silence_ms": "700",
        "llm.api-key": "sk-y",
    }
    filtered = agent_config_service.secret_keys_filtered(values)
    assert filtered == {"vad.min_silence_ms": "700"}


def test_render_target_for_unknown_machine_raises_key_error(config_dir, db_session):
    with pytest.raises(KeyError):
        agent_config_service.render_target(db_session, "ghost")
