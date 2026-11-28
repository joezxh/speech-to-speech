"""模板管理面（原型「模板管理」页；console:template:* 权限码）。

CRUD 之外不设只读查看端点：查看 = GET /{id}。审计已在 template_service 落
（template.create/update/delete），路由层不重复记。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.template import TemplateCreate, TemplateUpdate
from app.services import template_service

router = APIRouter(prefix="/api/v1/templates", tags=["templates"])


@router.get("")
def list_templates(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:template:query")),
    effect: str = "",
    platform: str = "",
    status: str = "",
    q: str = "",
):
    """模板列表（effect/platform/status 筛选 + 名称/描述搜索）。"""
    return ok(template_service.list_templates(db, effect=effect, platform=platform, status=status, q=q))


@router.get("/{template_id}")
def get_template(
    template_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:template:query")),
):
    try:
        return ok(template_service.get_template(db, template_id))
    except KeyError:
        raise ApiError("not_found", f"template {template_id} does not exist", 404) from None


@router.post("")
def create_template(
    payload: TemplateCreate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:template:create")),
):
    try:
        return ok(template_service.create_template(db, payload, actor=user.username))
    except ValueError:
        raise ApiError("conflict", f"template {payload.name} already exists", 409) from None


@router.put("/{template_id}")
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:template:update")),
):
    try:
        return ok(template_service.update_template(db, template_id, payload, actor=user.username))
    except KeyError:
        raise ApiError("not_found", f"template {template_id} does not exist", 404) from None
    except ValueError as exc:
        raise ApiError("conflict", f"template {exc} already exists", 409) from None


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: int,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:template:delete")),
):
    try:
        template_service.delete_template(db, template_id, actor=user.username)
    except KeyError:
        raise ApiError("not_found", f"template {template_id} does not exist", 404) from None
