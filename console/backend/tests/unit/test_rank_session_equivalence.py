"""Task 17 等价性保护：规则表清空 + 无票据时，rank_session 的返回与改动前
同一输入逐字一致（Review Focus #4）。"""

from __future__ import annotations

import random

from app.services.routing_service import CandidateSpec, RoutingDecision
from app.services.upstream_resolver import rank_session


class FakeSpec:
    def __init__(self, instance_id: str, weight: int, free: int, capacity: int):
        self.instance_id = instance_id
        self.base_url = f"http://127.0.0.1:9{instance_id[-1]}{instance_id[-1]}"
        self.weight = weight
        self.enabled = True
        self.status = "online"
        self.effective_free = free
        self.capacity = capacity


class FakeStore:
    def __init__(self, specs):
        self._specs = specs

    def list_instances(self):
        return self._specs

    def pending_count(self, _instance_id: str) -> int:
        return 0


def _store():
    return FakeStore(
        [
            FakeSpec("pipe-a", weight=1, free=4, capacity=4),
            FakeSpec("pipe-b", weight=1, free=4, capacity=4),
            FakeSpec("pipe-c", weight=2, free=2, capacity=4),
        ]
    )


def test_no_routing_is_byte_identical_to_legacy():
    # 胜者落在同分组 {pipe-a, pipe-b}（free/capacity 同为 1.0）；其余按 ratio 降序。
    ranked = rank_session(store=_store(), rng=random.Random(42))
    assert ranked[0].instance_id in {"pipe-a", "pipe-b"}
    assert [a.instance_id for a in ranked[1:]] == ["pipe-c", "pipe-b"] if ranked[0].instance_id == "pipe-a" else ["pipe-c", "pipe-a"]


def test_default_decision_behaves_like_no_routing():
    decision = RoutingDecision(None, False, False, "anon:s1", CandidateSpec("default"))
    for seed in range(6):
        without = rank_session(store=_store(), rng=random.Random(seed))
        with_routing = rank_session(store=_store(), rng=random.Random(seed), routing=decision)
        assert [(a.instance_id, a.free, a.weight) for a in without] == [
            (a.instance_id, a.free, a.weight) for a in with_routing
        ], f"seed={seed}"


def test_pinned_decision_filters_to_target_only():
    decision = RoutingDecision(3, False, False, "anon:s1", CandidateSpec("pinned_instance", instance_id="pipe-b"))
    ranked = rank_session(store=_store(), rng=random.Random(42), routing=decision)
    assert [a.instance_id for a in ranked] == ["pipe-b"]


def test_machine_filter_decision_restricts_candidates():
    decision = RoutingDecision(
        4, False, False, "anon:s1", CandidateSpec("machine_filter", instance_ids=frozenset({"pipe-a", "pipe-c"}))
    )
    ranked = rank_session(store=_store(), rng=random.Random(42), routing=decision)
    assert {a.instance_id for a in ranked} == {"pipe-a", "pipe-c"}
