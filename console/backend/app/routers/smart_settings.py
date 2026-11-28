"""智能设置面（原型 smartPanel；console:machine:query / console:smart:analyze）。

fetch 读取机器实际参数与最近日志（与机器面同权限码）；analyze 是付费 LLM 副作用，
独立权限码 console:smart:analyze（admin/operator）。审计已在 service 落。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.errors import ApiError
from app.core.permissions import require_permission
from app.core.security import CurrentUser
from app.deps import DbSession
from app.schemas.common import ok
from app.schemas.smart_settings import SmartAnalyzeIn, SmartFetchIn
from app.services import smart_settings_service

router = APIRouter(prefix="/api/v1/smart-settings", tags=["smart-settings"])


@router.post("/fetch")
def fetch(
    payload: SmartFetchIn,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:machine:query")),
):
    """机器当前参数 + 最近日志（原型「从 Agent 拉取当前参数」）。"""
    try:
        return ok(smart_settings_service.fetch(db, payload.machineId))
    except KeyError:
        raise ApiError("not_found", f"machine {payload.machineId} does not exist", 404) from None


@router.post("/analyze")
def analyze(
    payload: SmartAnalyzeIn,
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:smart:analyze")),
):
    """AI 分析故障并给出参数推荐（LLM 优先，规则兜底时 source=rules）。"""
    return ok(smart_settings_service.analyze(db, payload, actor=user.username))
