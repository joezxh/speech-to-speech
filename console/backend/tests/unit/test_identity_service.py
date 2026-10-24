from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services import identity_service, metering_service


def _request(cookies=None, headers=None, host="127.0.0.1"):
    return SimpleNamespace(
        cookies=cookies or {},
        headers=headers or {},
        client=SimpleNamespace(host=host),
    )


def test_user_view_is_anonymous_without_oauth():
    # oauth_enabled is False in tests (no OAUTH_CLIENT_ID), so there is no identity.
    assert identity_service.user_view(_request()) == {"loggedIn": False, "tier": "anon"}


def test_an_expired_token_is_not_trusted():
    info = {
        "user_info": {"sub": "u"},
        "access_token": "t",
        "access_token_expires_at": datetime.now(UTC) - timedelta(seconds=1),
    }
    assert identity_service._oauth_token_expired(info) is True


def test_a_missing_expiry_is_left_to_the_hub():
    # Older huggingface_hub builds do not expose the field; the Hub validates instead.
    assert identity_service._oauth_token_expired({"user_info": {}}) is False


def test_anonymous_identity_mints_a_signed_cookie():
    tier, keys, set_cookie = identity_service.resolve_identity(
        _request(headers={"x-forwarded-for": "203.0.113.7, 10.0.0.1"})
    )
    assert tier == "anon"
    # Two keys: the IP and the cookie id, OR-matched by the limiter.
    assert len(keys) == 2 and keys[0] != keys[1]
    assert set_cookie is not None
    assert metering_service.verify_cookie(set_cookie) is not None


def test_a_forged_cookie_gets_a_new_id():
    tier, _, set_cookie = identity_service.resolve_identity(
        _request(cookies={identity_service.ANON_COOKIE: "forged.nope"})
    )
    assert tier == "anon"
    assert set_cookie is not None
    assert metering_service.verify_cookie(set_cookie) != "forged"
