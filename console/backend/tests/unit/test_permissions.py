from __future__ import annotations

import pytest

from app.core.errors import ApiError
from app.core.permissions import PERMISSION_ROLES, ensure_permission, require_permission
from app.core.security import CurrentUser


def test_registry_contains_the_registered_codes():
    assert set(PERMISSION_ROLES) == {
        "console:cluster:query",
        "console:cluster:switch",
        "console:cluster:create",
        "console:cluster:update",
        "console:cluster:delete",
        # 机器与 agent 面（spec 2026-11-17 §7.3）
        "console:machine:query",
        "console:machine:create",
        "console:machine:update",
        "console:machine:delete",
        "console:agent:enroll",
    }
    assert PERMISSION_ROLES["console:cluster:switch"] == frozenset({"admin", "operator"})
    assert PERMISSION_ROLES["console:cluster:create"] == frozenset({"admin"})
    assert PERMISSION_ROLES["console:machine:query"] == frozenset({"admin", "operator"})
    assert PERMISSION_ROLES["console:machine:delete"] == frozenset({"admin"})


def test_unknown_permission_code_raises_at_factory_time():
    with pytest.raises(RuntimeError):
        require_permission("console:cluster:teleport")


def test_operator_passes_query_switch_and_fails_create():
    ensure_permission("console:cluster:query", CurrentUser(username="op", role="operator"))
    ensure_permission("console:cluster:switch", CurrentUser(username="op", role="operator"))
    with pytest.raises(ApiError) as excinfo:
        ensure_permission("console:cluster:create", CurrentUser(username="op", role="operator"))
    assert excinfo.value.code == "forbidden"
    assert excinfo.value.status == 403


def test_client_role_fails_even_query():
    with pytest.raises(ApiError) as excinfo:
        ensure_permission("console:cluster:query", CurrentUser(username="c", role="client"))
    assert excinfo.value.code == "forbidden"