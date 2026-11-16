"""ConfigStore 的行为（spec 2026-11-17 §4.2–4.5）。

守住这几条不变量：
- 库里的值优先于 env；
- 库里没有该键才回退 env；
- 播种只写缺失的键（env 不覆盖运维写过的值）；
- 类型与取值域不合法就拒绝；
- 读库失败静默降级到 env，不让控制台起不来。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from app.config._schema import ITEMS, coerce, item_by_key
from app.config._store import ConfigStore
from app.repositories.config_repository import ConfigRepository


@pytest.fixture
def defaults() -> dict:
    return {
        "app": {"log_level": "info"},
        "console": {"lb_mode": "off", "lb_failover_attempts": 2},
        "allocator": {"mode": "off", "probe_interval_s": 5, "queue_enabled": False},
        "demo": {"space_id": ""},
        "bootstrap": {"default_admin_username": "admin"},
    }


@pytest.fixture
def factory(db_session):
    return sessionmaker(bind=db_session.get_bind(), future=True)


@pytest.fixture
def store(defaults, factory):
    # ttl=0：每次读都穿透到库，测试不依赖时间。
    return ConfigStore(defaults, session_factory=factory, ttl_s=0.0)


def test_env_is_the_fallback_when_the_key_is_absent(store):
    assert store.get("console.lb_mode") == "off"
    assert store.source("console.lb_mode") == "env"


def test_the_database_value_wins_over_env(store, db_session):
    ConfigRepository(db_session).upsert(
        key="console.lb_mode",
        value="proxy",
        value_type="str",
        section="console",
        description="",
        restart_required=False,
        updated_by="tester",
    )
    store.invalidate()
    assert store.get("console.lb_mode") == "proxy"
    assert store.source("console.lb_mode") == "db"


def test_seeding_only_writes_missing_keys(store, db_session):
    written = store.seed_missing(db_session)
    assert "console.lb_mode" in written
    # 运维改过的值不会被 env 播种冲掉。
    ConfigRepository(db_session).upsert(
        key="console.lb_mode",
        value="proxy",
        value_type="str",
        section="console",
        description="",
        restart_required=False,
        updated_by="tester",
    )
    again = store.seed_missing(db_session)
    assert again == []
    store.invalidate()
    assert store.get("console.lb_mode") == "proxy"


def test_seeding_covers_every_registered_item(store, db_session):
    store.seed_missing(db_session)
    rows = ConfigRepository(db_session).list_all()
    assert {row.config_key for row in rows} == {item.key for item in ITEMS}


def test_writes_reject_unknown_keys(store, db_session):
    with pytest.raises(KeyError):
        store.set(db_session, "console.not_a_real_key", "1", actor="tester")


def test_writes_reject_values_outside_the_domain(store, db_session):
    with pytest.raises(ValueError):
        store.set(db_session, "console.lb_mode", "nonsense", actor="tester")
    with pytest.raises(ValueError):
        store.set(db_session, "allocator.probe_interval_s", "0", actor="tester")
    with pytest.raises(ValueError):
        store.set(db_session, "allocator.probe_interval_s", "abc", actor="tester")


def test_the_registered_domain_is_enforced(store, db_session):
    store.set(db_session, "allocator.mode", "local", actor="tester")
    store.invalidate()
    assert store.get("allocator.mode") == "local"
    with pytest.raises(ValueError):
        store.set(db_session, "allocator.mode", "shared", actor="tester")


def test_a_broken_database_falls_back_to_env(defaults):
    class _Boom:
        def __call__(self):
            raise RuntimeError("db is down")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    broken = ConfigStore(defaults, session_factory=_Boom(), ttl_s=0.0)
    assert broken.get("console.lb_mode") == "off"
    assert broken.source("console.lb_mode") == "env"
    assert broken.db_ok is False


def test_the_snapshot_reports_the_source_of_every_item(store, db_session):
    store.seed_missing(db_session)
    store.set(db_session, "console.lb_mode", "proxy", actor="tester")
    store.invalidate()
    items = {item["key"]: item for item in store.snapshot()}
    assert items["console.lb_mode"]["source"] == "db"
    assert items["console.lb_mode"]["value"] == "proxy"
    assert items["allocator.mode"]["source"] == "db"
    assert len(items) == len(ITEMS)


def test_types_survive_the_round_trip(store, db_session):
    store.set(db_session, "allocator.probe_interval_s", "9", actor="tester")
    store.set(db_session, "allocator.queue_enabled", "true", actor="tester")
    store.invalidate()
    assert store.get("allocator.probe_interval_s") == 9
    assert store.get("allocator.queue_enabled") is True


def test_coerce_parses_the_registered_types():
    item = item_by_key("allocator.queue_enabled")
    assert item is not None
    assert coerce(item, "1") is True
    assert coerce(item, "off") is False
    with pytest.raises(ValueError):
        coerce(item, "maybe")  
