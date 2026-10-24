from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.param_user import ParamUser


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def by_username(self, username: str) -> ParamUser | None:
        return self.session.scalar(select(ParamUser).where(ParamUser.username == username))

    def create(self, username: str, password_hash: str, role: str = "operator") -> ParamUser:
        row = ParamUser(username=username, password_hash=password_hash, role=role)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def touch_login(self, user: ParamUser) -> None:
        user.last_login_at = utcnow()
        self.session.commit()
