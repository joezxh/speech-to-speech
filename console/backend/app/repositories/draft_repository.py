from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.param_draft import ParamDraft


class DraftRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, profile: str) -> ParamDraft | None:
        return self.session.scalar(select(ParamDraft).where(ParamDraft.profile == profile))

    def put(self, profile: str, *, base_version: int, patch: dict, actor: str) -> ParamDraft:
        row = self.get(profile)
        if row is None:
            row = ParamDraft(profile=profile, base_version=base_version, patch=patch, updated_by=actor)
            self.session.add(row)
        else:
            row.base_version = base_version
            row.patch = patch
            row.updated_by = actor
        self.session.commit()
        self.session.refresh(row)
        return row

    def drop(self, profile: str) -> bool:
        row = self.get(profile)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True
