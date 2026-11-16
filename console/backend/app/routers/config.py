"""配置读写接口（spec 2026-11-17 §6.1）。

- `GET /api/v1/config`：全部配置项的有效值 + 来源（db/env）+ 是否需重启；
- `GET /api/v1/config/schema`：配置项元数据（前端按它渲染表单）；
- `PUT /api/v1/config`：批量写入（管理员），逐项校验，整批拒绝非法值，写审计。

审计只记字段名不记值——`param_audit.fields` 的既有口径。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.errors import ApiError
from app.core.security import CurrentUser, require_admin, require_user
from app.deps import DbSession
from app.repositories.audit_repository import AuditRepository
from app.schemas.common import ok
from app.schemas.config import ConfigUpdateRequest
from app.services import config_service
from app.services.config_service import ConfigError

router = APIRouter(prefix="/api/v1", tags=["config"])


def _request_id(request: Request) -> str:
    # 与 routers/instances.py 同一条路径：RequestIdMiddleware 已经把
    # `x-request-id` 或新生成的 hex 写进 request.state。
    return getattr(request.state, "request_id", "")


@router.get("/config")
def get_config(user: CurrentUser = Depends(require_user)):
    """读配置面。来源是 db 还是 env 一并给出，便于判断"改了 env 为什么没生效"。"""
    return ok(
        {
            "items": config_service.snapshot(),
            "source": config_service.source_summary(),
            "dbOk": config_service.db_ok(),
        }
    )


@router.get("/config/schema")
def get_config_schema(user: CurrentUser = Depends(require_user)):
    """配置项元数据：类型、取值域、说明、是否需重启。"""
    return ok({"items": config_service.schema()})


@router.put("/config")
def update_config(
    payload: ConfigUpdateRequest,
    db: DbSession,
    request: Request,
    user: CurrentUser = Depends(require_admin),
):
    """批量写配置：任一项非法就整批拒绝（400），一项都不落库。"""
    try:
        result = config_service.update(db, payload.values, actor=user.username)
    except ConfigError as exc:
        raise ApiError("invalid_request", str(exc), 400) from exc
    # 审计：只记改了哪些字段，不记值。
    AuditRepository(db).record(
        actor=user.username,
        role=user.role,
        action="config.update",
        profile="console",
        fields=list(payload.values.keys()),
        request_id=_request_id(request),
    )
    return ok(
        {
            "updated": result["changed"],
            "restartRequired": result["restart_required"],
            "source": config_service.source_summary(),
        }
    )  
