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
