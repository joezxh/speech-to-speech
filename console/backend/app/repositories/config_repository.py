"""配置项读写（spec 2026-11-17 §2.1）。

播种语义在这里：**只写缺失的键**，已存在的键不覆盖——这是"env 仅首次播种、
之后以表为准"的落点（设计 §4.5）。运维写的值不该被一次重启冲掉。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.param_config import ParamConfig


class ConfigRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[ParamConfig]:
        return list(self.session.scalars(select(ParamConfig).order_by(ParamConfig.config_key)))

    def values(self) -> dict[str, str]:
        """库里的全部键值（只有真正写进表里的键）。"""
        return {row.config_key: row.value for row in self.list_all()}

    def get(self, key: str) -> ParamConfig | None:
        return self.session.scalar(select(ParamConfig).where(ParamConfig.config_key == key))

    def upsert(
        self,
        *,
        key: str,
        value: str,
        value_type: str,
        section: str,
        description: str,
        restart_required: bool,
        updated_by: str,
    ) -> ParamConfig:
        """写一个键（运维写入用）：已存在则更新并把版本号 +1。"""
        row = self.get(key)
        if row is None:
            row = ParamConfig(
                config_key=key,
                value=value,
                value_type=value_type,
                section=section,
                description=description,
                restart_required=restart_required,
                updated_by=updated_by,
                version=1,
            )
            self.session.add(row)
            self.session.commit()
            self.session.refresh(row)
            return row
        row.value = value
        row.value_type = value_type
        row.section = section
        row.description = description
        row.restart_required = restart_required
        row.updated_by = updated_by
        row.version = (row.version or 0) + 1
        self.session.commit()
        self.session.refresh(row)
        return row

    def insert_missing(self, rows: Sequence[tuple[str, str, str, str, str, bool]]) -> list[str]:
        """播种：只插缺失的键。返回真正写入的键列表。

        rows 每项是 (key, value, value_type, section, description, restart_required)。
        """
        existing = set(self.values())
        written: list[str] = []
        for key, value, value_type, section, description, restart_required in rows:
            if key in existing:
                continue
            self.session.add(
                ParamConfig(
                    config_key=key,
                    value=value,
                    value_type=value_type,
                    section=section,
                    description=description,
                    restart_required=restart_required,
                    updated_by="seed",
                    version=1,
                )
            )
            existing.add(key)
            written.append(key)
        if written:
            self.session.commit()
        return written

    def delete(self, key: str) -> bool:
        row = self.get(key)
        if row is None:
            return False
        self.session.delete(row)
        self.session.commit()
        return True  
