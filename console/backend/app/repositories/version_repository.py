from __future__ import annotations

from hashlib import sha256

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.param_version import ParamVersion


def _sha(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


class VersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def next_number(self, profile: str) -> int:
        current = self.session.scalar(select(func.max(ParamVersion.version)).where(ParamVersion.profile == profile))
        return int(current or 0) + 1

    def create(
        self, profile: str, *, status: str, yaml_text: str, env_sha256: str, note: str, author: str
    ) -> ParamVersion:
        row = ParamVersion(
            profile=profile,
            version=self.next_number(profile),
            status=status,
            note=note[:500],
            author=author,
            yaml_text=yaml_text,
            yaml_sha256=_sha(yaml_text),
            env_sha256=env_sha256,
        )
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def set_status(
        self,
        row: ParamVersion,
        status: str,
        *,
        error_code: str | None = None,
        duration_s: float | None = None,
        rolled_back_to: int | None = None,
    ) -> ParamVersion:
        row.status = status
        row.error_code = error_code
        row.duration_s = duration_s
        row.rolled_back_to = rolled_back_to
        self.session.commit()
        self.session.refresh(row)
        return row

    def get(self, profile: str, version: int) -> ParamVersion | None:
        return self.session.scalar(
            select(ParamVersion).where(ParamVersion.profile == profile, ParamVersion.version == version)
        )

    def latest_live(self, profile: str, *, exclude: int | None = None) -> ParamVersion | None:
        stmt = select(ParamVersion).where(ParamVersion.profile == profile, ParamVersion.status == "live")
        if exclude is not None:
            stmt = stmt.where(ParamVersion.version != exclude)
        return self.session.scalar(stmt.order_by(ParamVersion.version.desc()).limit(1))

    def list(self, profile: str, *, page: int = 1, page_size: int = 20) -> tuple[list[ParamVersion], int]:
        base = select(ParamVersion).where(ParamVersion.profile == profile)
        total = self.session.scalar(select(func.count()).select_from(base.subquery())) or 0
        rows = self.session.scalars(
            base.order_by(ParamVersion.version.desc()).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)

    def dangling(self) -> list[ParamVersion]:
        return list(self.session.scalars(select(ParamVersion).where(ParamVersion.status == "publishing")).all())
