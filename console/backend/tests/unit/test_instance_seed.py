from __future__ import annotations

from app.config import allocator as allocator_settings
from app.repositories.instance_repository import InstanceRepository
from app.services import instance_seed

SEED = """\
instances:
  - id: pipe-a
    base_url: http://192.168.40.31:8765
    weight: 2
    max_sessions_hint: 4
    labels: {rack: A, gpu: "4090"}
  - id: pipe-b
    base_url: http://192.168.40.32:8765
    weight: 1
"""


def _seed_file(tmp_path):
    path = tmp_path / "instances.yaml"
    path.write_text(SEED, encoding="utf-8")
    return str(path)


def test_empty_seed_path_is_a_noop(db_session, monkeypatch):
    monkeypatch.setattr(allocator_settings, "seed_path", "")
    assert instance_seed.apply_seed(db_session) == []
    assert InstanceRepository(db_session).list_all() == []


def test_seed_is_idempotent_and_keeps_ops_flags(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(allocator_settings, "seed_path", _seed_file(tmp_path))
    assert instance_seed.apply_seed(db_session) == []
    repo = InstanceRepository(db_session)
    repo.set_drain("pipe-a", drain=True, updated_by="alice")
    repo.set_enabled("pipe-b", enabled=False, updated_by="bob")
    assert instance_seed.apply_seed(db_session) == []  # 第二次：不重复、不覆盖
    rows = {row.instance_id: row for row in repo.list_all()}
    assert len(rows) == 2
    assert rows["pipe-a"].drain_requested is True
    assert rows["pipe-b"].enabled is False
    assert rows["pipe-a"].weight == 2 and rows["pipe-a"].labels_json == {"rack": "A", "gpu": "4090"}


def test_base_url_conflict_warns_and_keeps_db_value(db_session, tmp_path, monkeypatch):
    repo = InstanceRepository(db_session)
    repo.upsert_seed(instance_id="pipe-a", base_url="http://old:8765", weight=1,
                     max_sessions_hint=None, labels={})
    monkeypatch.setattr(allocator_settings, "seed_path", _seed_file(tmp_path))
    alerts = instance_seed.apply_seed(db_session)
    # 告警带实例 id（`name:instance_id`），多 console 排障时要知道是哪台。
    assert "instance_seed_conflict:pipe-a" in alerts
    assert repo.get_by_instance_id("pipe-a").base_url == "http://old:8765"  # DB 为准（spec §7）


def test_instance_missing_from_seed_only_warns(db_session, tmp_path, monkeypatch):
    repo = InstanceRepository(db_session)
    repo.upsert_seed(instance_id="pipe-z", base_url="http://z:8765", weight=1,
                     max_sessions_hint=None, labels={})
    monkeypatch.setattr(allocator_settings, "seed_path", _seed_file(tmp_path))
    alerts = instance_seed.apply_seed(db_session)
    assert "instance_removed_from_seed:pipe-z" in alerts
    assert repo.get_by_instance_id("pipe-z") is not None  # 不删除
