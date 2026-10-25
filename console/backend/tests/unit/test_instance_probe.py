from __future__ import annotations

from app.services import instance_probe, pool


def test_probe_pool_ok_records_elapsed_and_snapshot(monkeypatch):
    state = pool.PoolState(reachable=True, size=2, in_use=1,
                           units=({"index": 0, "state": "active", "session_id": "s"},
                                  {"index": 1, "state": "idle", "session_id": None}))
    monkeypatch.setattr(pool, "read_pool", lambda timeout=5.0, base_url=None: state)
    out = instance_probe.probe_pool("http://h:8765", timeout=2.0)
    assert out.ok and out.state is state and out.probe_ms >= 0 and out.error == ""


def test_probe_pool_unreachable_is_not_ok(monkeypatch):
    monkeypatch.setattr(pool, "read_pool",
                        lambda timeout=5.0, base_url=None: pool.PoolState(reachable=False, error="refused"))
    out = instance_probe.probe_pool("http://h:8765")
    assert not out.ok and out.error == "refused" and out.state is None


def test_probe_usage_passthrough(monkeypatch):
    monkeypatch.setattr(pool, "read_usage", lambda timeout=5.0, base_url=None: {"turns": 1})
    assert instance_probe.probe_usage("http://h:8765") == {"turns": 1}
