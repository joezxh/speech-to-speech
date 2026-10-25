import httpx

from app.services import pool


def test_read_pool_marks_an_unreachable_pool(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(pool.httpx, "get", boom)
    state = pool.read_pool()
    assert state.reachable is False
    assert "ConnectError" in state.error


def test_read_pool_counts_busy_and_stuck_units(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "size": 3,
                "in_use": 2,
                "units": [
                    {"index": 0, "state": "active", "session_id": "s1"},
                    {"index": 1, "state": "draining", "session_id": "s2"},
                    {"index": 2, "state": "stuck", "session_id": "s3"},
                ],
            }

    monkeypatch.setattr(pool.httpx, "get", lambda *a, **k: _Response())
    state = pool.read_pool()
    assert (state.reachable, state.size, state.in_use) == (True, 3, 2)
    assert state.busy == 1  # only `active` is a live conversation
    assert state.stuck == 1


def test_wait_healthy_gives_up_after_the_deadline(monkeypatch):
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=False, error="refused")
    )
    result = pool.wait_healthy(2, timeout=0.2, interval=0.1)
    assert result.ok is False
    assert result.reason.startswith("after 0.2s")


def test_wait_healthy_accepts_only_the_expected_size(monkeypatch):
    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=True, size=1, in_use=0)
    )
    assert pool.wait_healthy(2, timeout=0.2, interval=0.1).ok is False

    monkeypatch.setattr(
        pool, "read_pool", lambda timeout=5.0: pool.PoolState(reachable=True, size=2, in_use=0)
    )
    assert pool.wait_healthy(2, timeout=1.0, interval=0.01).ok is True


def test_wait_healthy_fails_on_a_stuck_unit(monkeypatch):
    state = pool.PoolState(
        reachable=True, size=2, units=({"index": 0, "state": "stuck", "session_id": "s1"},)
    )
    monkeypatch.setattr(pool, "read_pool", lambda timeout=5.0: state)
    result = pool.wait_healthy(2, timeout=0.2, interval=0.1)
    assert result.ok is False
    assert "stuck" in result.reason


def test_read_pool_with_explicit_base_url_hits_that_host(monkeypatch):
    seen = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"size": 2, "in_use": 0, "units": []}

    def fake_get(url, timeout):
        seen["url"] = url
        return _Resp()

    monkeypatch.setattr(pool.httpx, "get", fake_get)
    state = pool.read_pool(base_url="http://192.168.40.32:8765/")
    assert seen["url"] == "http://192.168.40.32:8765/v1/pool"  # 尾斜杠被剥
    assert state.reachable and state.size == 2


def test_read_pool_without_argument_still_uses_console_default(monkeypatch):
    # spec P1.0 验收：无参行为不变——新参数只能有默认值，不能动位置参顺序。
    seen = {}

    class _Resp:
        def raise_for_status(self): pass
        def json(self): return {"size": 1, "in_use": 0, "units": []}

    monkeypatch.setattr(pool.httpx, "get", lambda url, timeout: seen.update(url=url) or _Resp())
    monkeypatch.setattr("app.services.pool.console.pipeline_base_url", "http://127.0.0.1:8765")
    pool.read_pool()
    assert seen["url"] == "http://127.0.0.1:8765/v1/pool"
