from __future__ import annotations

import pytest

from app.services import metering_service


@pytest.fixture
def usage_db(tmp_path):
    metering_service.init(str(tmp_path / "usage.sqlite3"))
    yield
    metering_service._db_path = None  # module global; do not leak into the next test


def _age_session(session_id: str, seconds: float) -> None:
    """Backdate a grant so a heartbeat sees elapsed time without sleeping."""
    with metering_service._lock, metering_service._session() as con:
        con.execute(
            "UPDATE sessions SET grant_ts = grant_ts - ? WHERE session_id = ?",
            (seconds, session_id),
        )


def test_budget_for_maps_every_tier():
    assert metering_service.budget_for("anon") == 300
    assert metering_service.budget_for("free") == 600
    # Unlimited tiers report no budget at all, not a very large number.
    assert metering_service.budget_for("pro") is None
    assert metering_service.budget_for("org") is None


def test_hash_key_is_opaque_and_stable():
    first = metering_service.hash_key("sub:alice")
    assert first.startswith("k_")
    assert "alice" not in first
    assert metering_service.hash_key("sub:alice") == first
    assert metering_service.hash_key("sub:bob") != first


def test_sign_cookie_round_trips_and_rejects_a_forgery():
    signed = metering_service.sign_cookie("abc123")
    assert metering_service.verify_cookie(signed) == "abc123"
    assert metering_service.verify_cookie("abc123.deadbeef") is None
    assert metering_service.verify_cookie("") is None
    assert metering_service.verify_cookie("no-signature") is None


def test_begin_debits_one_chunk(usage_db):
    keys = ["k_a"]
    assert metering_service.begin("s1", keys, "free") == 10
    # A fresh session is not live-budget-negative: the chunk is what was reserved.
    assert metering_service.remaining(keys, "free") == 590


def test_heartbeat_grows_the_reservation_and_end_refunds_the_rest(usage_db):
    keys = ["k_b"]
    metering_service.begin("s2", keys, "free")
    assert metering_service.remaining(keys, "free") == 590

    # 25 s in: the heartbeat tops the reservation up to elapsed + one chunk (40 s).
    _age_session("s2", 25)
    assert metering_service.heartbeat("s2") is True
    assert metering_service.remaining(keys, "free") == 560

    # Clean teardown bills the elapsed time rounded up to a chunk (30 s) and
    # refunds the 10 s that was reserved but never used.
    metering_service.end("s2")
    assert metering_service.remaining(keys, "free") == 570
