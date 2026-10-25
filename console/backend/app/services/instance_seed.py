"""声明式 seed → 幂等 upsert（spec §7）。DB 是真相源：seed 冲突不覆盖 DB 的
base_url，seed 里消失的实例不删除，只告警。审计动作 `instance.seed`。"""

from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger
from sqlalchemy.orm import Session

from app.config import allocator
from app.repositories.instance_repository import InstanceRepository


def load_seed(path: str) -> list[dict]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    items = raw.get("instances") or []
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("id") or not item.get("base_url"):
            logger.warning("instances seed: skipping malformed entry {}", item)
            continue
        out.append(
            {
                "instance_id": str(item["id"]),
                "base_url": str(item["base_url"]).rstrip("/"),
                "weight": int(item.get("weight") or 1),
                "max_sessions_hint": item.get("max_sessions_hint"),
                "labels": dict(item.get("labels") or {}),
            }
        )
    return out


def apply_seed(session: Session) -> list[str]:
    """返回告警列表（`name:instance_id`）；未配置路径或文件缺失 → 空列表，不做任何事。"""
    if not allocator.seed_path.strip():
        return []
    path = Path(allocator.seed_path)
    if not path.is_file():
        logger.warning("instances seed configured but {} missing", path)
        return []
    repo = InstanceRepository(session)
    alerts: list[str] = []
    seeded: set[str] = set()
    for item in load_seed(str(path)):
        _, alert = repo.upsert_seed(**item, updated_by="seed")
        seeded.add(item["instance_id"])
        if alert:
            alerts.append(f"{alert}:{item['instance_id']}")
    for row in repo.list_all():
        if row.instance_id not in seeded:
            alerts.append(f"instance_removed_from_seed:{row.instance_id}")
    for alert in alerts:
        logger.warning("instances seed alert: {}", alert)
    return alerts
