# `db_session` comes from tests/conftest.py; the settings singleton is patched
# per test because it is read at call time, not at import time.
from __future__ import annotations

import pytest

from app.config import bootstrap as bootstrap_settings
from app.repositories.user_repository import UserRepository
from app.services import bootstrap_service
from app.services.auth_service import hash_password, verify_password


@pytest.fixture
def configure(monkeypatch):
    def _configure(username: str = "root", password: str = "admin123456", role: str = "admin") -> None:
        monkeypatch.setattr(bootstrap_settings, "default_admin_username", username)
        monkeypatch.setattr(bootstrap_settings, "default_admin_password", password)
        monkeypatch.setattr(bootstrap_settings, "default_admin_role", role)

    return _configure


def test_creates_the_configured_admin(db_session, configure):
    configure()
    assert bootstrap_service.ensure_default_admin(db_session) == "root"
    row = UserRepository(db_session).by_username("root")
    assert row is not None and row.role == "admin"
    assert verify_password("admin123456", row.password_hash)


def test_second_boot_is_a_no_op(db_session, configure):
    configure()
    bootstrap_service.ensure_default_admin(db_session)
    assert bootstrap_service.ensure_default_admin(db_session) is None


def test_an_existing_account_is_never_touched(db_session, configure):
    UserRepository(db_session).create("root", hash_password("someone-chose-this"), "operator")
    configure()
    assert bootstrap_service.ensure_default_admin(db_session) is None
    row = UserRepository(db_session).by_username("root")
    assert row.role == "operator"
    assert verify_password("someone-chose-this", row.password_hash)


def test_empty_password_keeps_the_bootstrap_off(db_session, configure):
    configure(password="")
    assert bootstrap_service.ensure_default_admin(db_session) is None
    assert UserRepository(db_session).by_username("root") is None


def test_short_password_is_refused(db_session, configure):
    configure(password="short")
    assert bootstrap_service.ensure_default_admin(db_session) is None
    assert UserRepository(db_session).by_username("root") is None


def test_unknown_role_is_refused(db_session, configure):
    configure(role="superuser")
    assert bootstrap_service.ensure_default_admin(db_session) is None
    assert UserRepository(db_session).by_username("root") is None


def test_operator_role_is_honoured(db_session, configure):
    configure(role="operator")
    assert bootstrap_service.ensure_default_admin(db_session) == "root"
    assert UserRepository(db_session).by_username("root").role == "operator"


def test_blank_username_keeps_the_bootstrap_off(db_session, configure):
    configure(username="   ")
    assert bootstrap_service.ensure_default_admin(db_session) is None
