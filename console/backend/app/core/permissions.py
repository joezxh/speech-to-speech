"""Permission-code layer (spec 2026-11-05 §3).

角色制（require_admin/require_operator）继续服务既有端点；新模块一律挂权限码。
映射集中在此一处，前端 `utils/permissions.ts` 是同表镜像——改这里必须同步改那里，
两处不一致时以后端 403 为准。
"""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends

from app.core.errors import ApiError
from app.core.security import CurrentUser, require_user

# 未注册的码在依赖构造期直接 RuntimeError（启动即失败，防打字错误）。
PERMISSION_ROLES: dict[str, frozenset[str]] = {
    "console:cluster:query": frozenset({"admin", "operator"}),
    # switch 只是视图切换的审计留痕；限 admin 会让 operator 切集群吃 403，
    # 与原型「任何登录用户可切换」冲突（spec §3 注）。
    "console:cluster:switch": frozenset({"admin", "operator"}),
    "console:cluster:create": frozenset({"admin"}),
    "console:cluster:update": frozenset({"admin"}),
    "console:cluster:delete": frozenset({"admin"}),
    # 机器管理（spec 2026-11-17 §7.3）：读给操作员，写仅管理员。
    "console:machine:query": frozenset({"admin", "operator"}),
    "console:machine:create": frozenset({"admin"}),
    "console:machine:update": frozenset({"admin"}),
    "console:machine:delete": frozenset({"admin"}),
    # 仅登记（防打字错误占位）：agent 面不走角色，按 machine token 映射（§7.3）。
    "console:agent:enroll": frozenset({"admin", "operator"}),
}


def ensure_permission(code: str, user: CurrentUser) -> CurrentUser:
    roles = PERMISSION_ROLES.get(code)
    if roles is None:
        raise RuntimeError(f"unregistered permission code: {code}")
    if user.role not in roles:
        raise ApiError("forbidden", f"role {user.role} lacks {code}", 403)
    return user


def require_permission(code: str) -> Callable[..., CurrentUser]:
    if code not in PERMISSION_ROLES:
        raise RuntimeError(f"unregistered permission code: {code}")

    def dependency(user: CurrentUser = Depends(require_user)) -> CurrentUser:
        return ensure_permission(code, user)

    return dependency