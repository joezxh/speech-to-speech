"""模板数据的读写（原型「模板管理」）。

数据量小（几十行级），列表一次全取、筛选交给 SQL where；name 唯一由
UniqueConstraint 兜底，服务层先查再插给出友好错误。
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.template import ParamTemplate


class TemplateRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(
        self,
        *,
        effect: str = "",
        platform: str = "",
        status: str = "",
        q: str = "",
    ) -> list[ParamTemplate]:
        stmt = select(ParamTemplate).order_by(ParamTemplate.updated_at.desc())
        if effect:
            stmt = stmt.where(ParamTemplate.effect == effect)
        if platform:
            stmt = stmt.where(ParamTemplate.platform == platform)
        if status:
            stmt = stmt.where(ParamTemplate.status == status)
        if q:
            # 搜索覆盖名称与描述（原型：按名称、ID 或描述搜索）。
            like = f"%{q}%"
            stmt = stmt.where(or_(ParamTemplate.name.like(like), ParamTemplate.description.like(like)))
        return list(self.session.scalars(stmt))

    def get(self, template_id: int) -> ParamTemplate | None:
        return self.session.get(ParamTemplate, template_id)

    def get_by_name(self, name: str) -> ParamTemplate | None:
        return self.session.scalar(select(ParamTemplate).where(ParamTemplate.name == name))

    def create(self, *, row: ParamTemplate) -> ParamTemplate:
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete(self, template_id: int) -> bool:
        row = self.get(template_id)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True
