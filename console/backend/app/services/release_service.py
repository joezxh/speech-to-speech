"""发布台账（Task 24，R1–R4 + R3b）——阶段机与 CI 回填，console 只记账。

build/staging 由外部 CI 执行；本服务只写 param_release 一行并用 changes(JSON)
记阶段历史；签名缺省放行（内网受信）但必须在审计里记 signature_absent。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.db.base import utcnow
from app.models.param_audit import ParamAudit
from app.models.release import ParamRelease
from app.schemas.release import ReleaseCreate, ReleaseOut, StageResultIn

ORDER = ("building", "staging", "canary", "rolling", "current")
ROLLBACK_FROM = {"canary", "rolling"}


def _out(row: ParamRelease) -> ReleaseOut:
    metadata = {item["stage"]: item for item in row.changes}
    return ReleaseOut(
        release_id=row.version,
        version=row.version,
        profile=row.cluster_id,
        status=row.status,
        stage=row.stage,
        created_by=row.created_by,
        artifact_ref=metadata.get("build", {}).get("artifact_ref", ""),
        changes=row.changes,
    )


def _get(db: Session, release_id: str) -> ParamRelease:
    row = db.scalar(select(ParamRelease).where(ParamRelease.version == release_id))
    if row is None:
        raise ApiError("not_found", f"release {release_id} does not exist", 404)
    return row


def profile_rollback(profile: str) -> None:
    """默认空实现：生产环境由 router 层包成真实的 profile rollback 调用。"""
    return None


def create_release(db: Session, p: ReleaseCreate, *, actor: str) -> ReleaseOut:
    row = ParamRelease(
        version=p.name,
        cluster_id=p.profile,
        status="building",
        stage="building",
        rollout_pct=0,
        nodes=[],
        changes=[
            {
                "stage": "building",
                "result": "started",
                "artifact_ref": p.artifactRef,
                "at": utcnow().isoformat(),
                "actor": actor,
            }
        ],
        created_by=actor,
    )
    db.add(row)
    db.add(ParamAudit(actor=actor, action="release.create", profile=p.profile, fields=["version", "artifact_ref"], at=utcnow()))
    db.commit()
    return _out(row)


def advance(
    db: Session, release_id: str, stage: str, result: str | None, note: str | None, actor: str
) -> ReleaseOut:
    row = _get(db, release_id)
    if stage not in ORDER:
        raise ApiError("invalid_request", f"unknown stage {stage}", 400)
    current_index = ORDER.index(row.status)
    target_index = ORDER.index(stage)
    if target_index != current_index + 1:
        raise ApiError(
            "conflict", f"cannot advance {row.status} → {stage}", 409
        )
    row.status = stage
    row.stage = stage
    row.changes = [
        *row.changes,
        {"stage": stage, "result": result or "ok", "note": note or "", "at": utcnow().isoformat(), "actor": actor},
    ]
    db.commit()
    return _out(row)


def stage_result(db: Session, release_id: str, body: StageResultIn, *, actor: str) -> ReleaseOut:
    """CI 回填阶段结论；signature 缺省放行但审计字段记 signature_absent。"""
    row = _get(db, release_id)
    stage = body.stage
    if stage not in ORDER:
        raise ApiError("invalid_request", f"unknown stage {stage}", 400)
    current_index = ORDER.index(row.status)
    target_index = ORDER.index(stage)
    if target_index != current_index + 1:
        raise ApiError("conflict", f"cannot record {stage} from {row.status}", 409)
    row.status = stage
    row.stage = stage
    row.changes = [
        *row.changes,
        {
            "stage": stage,
            "result": body.result,
            "artifact_ref": body.artifactRef,
            "note": body.note,
            "at": utcnow().isoformat(),
            "actor": actor,
            "signature": body.signature or "",
        },
    ]
    fields = ["stage", "result"]
    if body.signature is None:
        fields.append("signature_absent")
    db.add(ParamAudit(actor=actor, action="release.stage_result", profile=row.cluster_id, fields=fields, at=utcnow()))
    db.commit()
    return _out(row)


def rollback(db: Session, release_id: str, *, actor: str) -> ReleaseOut:
    row = _get(db, release_id)
    if row.status not in ROLLBACK_FROM:
        raise ApiError("conflict", f"cannot roll back from {row.status}", 409)
    profile_rollback(row.cluster_id)
    row.status = "rolled_back"
    row.changes = [
        *row.changes,
        {"stage": "rolled_back", "result": "ok", "at": utcnow().isoformat(), "actor": actor},
    ]
    db.add(ParamAudit(actor=actor, action="release.rollback", profile=row.cluster_id, fields=["version"], at=utcnow()))
    db.commit()
    return _out(row)


def summary(db: Session, *, now: datetime | None = None) -> dict:
    """停留超过 30 分钟未回填的阶段标 pending_backfill（注入时钟可测）。"""
    now = now or datetime.now(UTC)
    pending = 0
    for row in db.scalars(select(ParamRelease)).all():
        for item in row.changes:
            if item.get("result") not in ("ok", "started"):
                continue
            at = datetime.fromisoformat(item["at"])
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            if (now - at).total_seconds() > 1800 and item["stage"] in ORDER and ORDER.index(item["stage"]) < ORDER.index(row.status):
                pending += 1
    return {"pending_backfill": pending, "releases": len(list(db.scalars(select(ParamRelease)).all()))}
