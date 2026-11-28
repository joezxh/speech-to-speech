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
    # 命令下发（排空/重启/恢复/检查）：机器写操作只给 admin。
    "console:machine:operate": frozenset({"admin"}),
    # Token 观测（T1–T5）：只读；operator 可看，改不了。
    "console:token:query": frozenset({"admin", "operator"}),
    # LB 策略/规则（L1–L6）：规则写只给 admin。
    "console:lb:query": frozenset({"admin", "operator"}),
    "console:lb:rule:write": frozenset({"admin"}),
    # 发布台账（Task 24）：记账写只给 admin；CI 回填走同一权限（服务凭据是 admin 角色）。
    "console:release:query": frozenset({"admin", "operator"}),
    "console:release:write": frozenset({"admin"}),
    # 全局审计（Task 25）：查询 operator 可看；导出（含全部字段行）只给 admin。
    "console:audit:query": frozenset({"admin", "operator"}),
    "console:audit:export": frozenset({"admin"}),
    # 仅登记（防打字错误占位）：agent 面不走角色，按 machine token 映射（§7.3）。
    "console:agent:enroll": frozenset({"admin", "operator"}),
    # 回调子系统（spec 2026-11-25 §8.4）：查询 operator 可看，写仅管理员。
    "console:callback:query": frozenset({"admin", "operator"}),
    "console:callback:manage": frozenset({"admin"}),
    # 参数模板（原型「模板管理」）：查询 operator 可看，写仅管理员。
    "console:template:query": frozenset({"admin", "operator"}),
    "console:template:create": frozenset({"admin"}),
    "console:template:update": frozenset({"admin"}),
    "console:template:delete": frozenset({"admin"}),
    # 智能设置（原型 smartPanel）：AI 分析是付费副作用，独立权限码。
    "console:smart:analyze": frozenset({"admin", "operator"}),
    # 会话记录（对话页「会话记录」面板 + 历史页）：查询与写均 operator 可用；
    # 保存入口（POST ""）用 write 码——保存自己的通话不需要管理员。
    "console:session:query": frozenset({"admin", "operator"}),
    "console:session:write": frozenset({"admin", "operator"}),
    # 会话工具（原型「工具」页）：四个码都给 operator；全局作用域与内置删除
    # 由 tool_service 再按 role==admin 校验，启停只要求登录。
    "console:tool:query": frozenset({"admin", "operator"}),
    "console:tool:create": frozenset({"admin", "operator"}),
    "console:tool:update": frozenset({"admin", "operator"}),
    "console:tool:delete": frozenset({"admin", "operator"}),
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