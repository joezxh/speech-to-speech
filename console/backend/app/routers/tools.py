"""会话工具管理面（原型「工具」页；console:tool:* 权限码）。

启停只要求登录（operator 也必须能在语音演示里切换工具）；全局作用域与内置
删除的 admin 边界在 tool_service 里校验。审计由 service 落，路由层不重复。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.tool import ToolCreate, ToolInvoke, ToolUpdate
from app.services import tool_service
from app.services.tool_execution_service import execute

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])


@router.get("")
def list_tools(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:tool:query")),
    q: str = "",
):
    return ok({"tools": tool_service.list_tools(db, user.username, q=q)})


@router.get("/{tool_id}")
def get_tool(
    tool_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:tool:query")),
):
    try:
        return ok(tool_service.get_tool(db, tool_id, username=user.username))
    except KeyError:
        raise ApiError("not_found", f"tool {tool_id} does not exist", 404) from None


@router.post("")
def create_tool(
    payload: ToolCreate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:tool:create")),
):
    try:
        return ok(tool_service.create_tool(db, payload, actor=user.username, username=user.username, role=user.role))
    except ValueError as exc:
        raise ApiError("conflict", f"tool {exc} already exists", 409) from None


@router.put("/{tool_id}")
def update_tool(
    tool_id: str,
    payload: ToolUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:tool:update")),
):
    try:
        return ok(tool_service.update_tool(db, tool_id, payload, actor=user.username, username=user.username, role=user.role))
    except KeyError:
        raise ApiError("not_found", f"tool {tool_id} does not exist", 404) from None
    except ValueError as exc:
        raise ApiError("conflict", f"tool {exc} already exists", 409) from None


@router.delete("/{tool_id}", status_code=204)
def delete_tool(
    tool_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:tool:delete")),
):
    try:
        tool_service.delete_tool(db, tool_id, actor=user.username, username=user.username, role=user.role)
    except KeyError:
        raise ApiError("not_found", f"tool {tool_id} does not exist", 404) from None


@router.post("/{tool_id}/copy")
def copy_tool(
    tool_id: str,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:tool:create")),
):
    try:
        return ok(tool_service.copy_tool(db, tool_id, actor=user.username, username=user.username, role=user.role))
    except KeyError:
        raise ApiError("not_found", f"tool {tool_id} does not exist", 404) from None


@router.put("/{tool_id}/enabled")
def toggle_tool(
    tool_id: str,
    payload: ToolUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    if payload.enabled is None:
        raise ApiError("invalid_request", "enabled is required", 400)
    try:
        return ok(tool_service.toggle_tool(db, tool_id, payload.enabled, actor=user.username, username=user.username))
    except KeyError:
        raise ApiError("not_found", f"tool {tool_id} does not exist", 404) from None


@router.post("/{tool_id}/invoke")
async def invoke_tool(
    tool_id: str,
    payload: ToolInvoke,
    db: DbSession,
    user: CurrentUser = Depends(require_user),
):
    from app.repositories.tool_repository import ToolRepository

    row = ToolRepository(db).get(tool_id)
    if row is None or not tool_service._visible(row, username=user.username):
        raise ApiError("not_found", f"tool {tool_id} does not exist", 404)
    return ok(await execute(db, row, payload.arguments, user.username))
