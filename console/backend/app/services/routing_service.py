"""RoutingEngine（Task 17，spec 2026-11-17 §7.4）。

规则评估 → 粘性 → 金丝雀，产出 CandidateSpec 交 rank_session 过滤候选。
硬规则：规则空/无票据时行为与改前逐字一致；粘性过期视为新路由；亲和键
派生自票据 username（跨用户写不了别人的 key）；金丝雀按 share_pct 掷骰。
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.repositories import lb_repository


@dataclass(frozen=True)
class SessionContext:
    session_key: str
    username: str = ""
    tenant_tag: str = ""


@dataclass(frozen=True)
class CandidateSpec:
    kind: str  # pinned_instance | machine_filter | default
    instance_id: str | None = None
    instance_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RoutingDecision:
    rule_id: int | None
    sticky_hit: bool
    is_canary: bool
    affinity_key: str
    candidates: CandidateSpec


def sticky_key(ctx: SessionContext) -> str:
    """亲和键派生：含票据 username——A 的会话永远写不到 B 名下的 key（§7.4 越权防线）。"""
    return f"{ctx.username or 'anon'}:{ctx.session_key}"


def _match(rule, ctx: SessionContext) -> bool:
    kind = rule.match_type
    if kind == "default":
        return True
    if kind == "user_signed":
        return bool(ctx.username) and ctx.username == rule.match_value
    if kind == "session_prefix":
        return ctx.session_key.startswith(rule.match_value)
    if kind == "tenant_tag":
        return bool(ctx.tenant_tag) and ctx.tenant_tag == rule.match_value
    if kind == "header":
        return False  # WS 升级头映射是 Task 18 的记账域；本任务只认前四种
    return False


class RoutingEngine:
    def __init__(self, db: Session, rng: random.Random | None = None) -> None:
        self.db = db
        self._rng = rng or random.Random()

    def resolve(self, ctx: SessionContext) -> RoutingDecision:
        key = sticky_key(ctx)
        # 1) 粘性优先：未过期的亲和行直连目标。
        affinity = lb_repository.get_affinity(self.db, key)
        if (
            affinity is not None
            and affinity.instance_id
            and affinity.expires_at is not None
            and _expired(affinity.expires_at) is False
        ):
            return RoutingDecision(None, True, False, key, CandidateSpec("pinned_instance", instance_id=affinity.instance_id))

        # 2) 规则按 priority 升序取第一条 enabled 且命中。
        for rule in lb_repository.rules_ordered(self.db):
            if not rule.enabled or not _match(rule, ctx):
                continue
            is_canary = False
            instance_id = rule.target_value if rule.target_kind == "instance" else None
            if rule.share_pct is not None:
                if self._rng.random() * 100 < rule.share_pct:
                    is_canary = True
                    instance_id = rule.target_value
                else:
                    continue  # 未进金丝雀分组 → 落到后续规则（近似分流）
            if rule.target_kind == "machine":
                return RoutingDecision(rule.id, False, is_canary, key, self._machine_instances(rule.target_value))
            if instance_id:
                return RoutingDecision(rule.id, False, is_canary, key, CandidateSpec("pinned_instance", instance_id=instance_id))
            return RoutingDecision(rule.id, False, is_canary, key, CandidateSpec("default"))

        return RoutingDecision(None, False, False, key, CandidateSpec("default"))

    def _machine_instances(self, machine_id: str) -> CandidateSpec:
        from sqlalchemy import select  # noqa: PLC0415

        from app.models.param_instance import ParamInstance  # noqa: PLC0415

        ids = frozenset(
            self.db.scalars(
                select(ParamInstance.instance_id).where(ParamInstance.machine_id == machine_id)
            ).all()
        )
        return CandidateSpec("machine_filter", instance_ids=ids)

    def remember_sticky(self, key: str, *, requested_by: str, instance_id: str, ttl_s: int) -> None:
        """选台成功后写亲和。key 派生含 username：跨用户写键一律 403。"""
        owner = key.split(":", 1)[0]
        if owner != (requested_by or "anon"):
            raise ApiError("forbidden", "affinity key belongs to another identity", 403)
        lb_repository.put_affinity(
            self.db, key, machine_id=None, instance_id=instance_id, rule_id=None, ttl_s=ttl_s
        )


def _expired(expires_at) -> bool:
    from datetime import UTC, datetime  # noqa: PLC0415

    from app.db.base import utcnow  # noqa: PLC0415

    moment = expires_at
    if moment is not None and moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment <= utcnow()
