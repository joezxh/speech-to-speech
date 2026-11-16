from __future__ import annotations

from app.services import allocator, instance_monitor, upstream_resolver
from app.services.instance_registry import RuntimeState
from app.services.pool import PoolState


def _registry(**states):
    # states = {instance_id: (size, in_use, capabilities)}
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    allocator.store._held.clear()
    upstream_resolver.reset_inflight()
    for iid, (size, in_use, caps) in states.items():
        instance_monitor.registry._states[iid] = RuntimeState(
            instance_id=iid,
            base_url="http://" + iid + ":8765",
            capabilities=frozenset(caps),
        )
        instance_monitor.registry.observe_success(
            iid, PoolState(reachable=True, size=size, in_use=in_use, units=()), 5
        )
    return instance_monitor.registry


def test_session_ranking_prefers_the_freest_instance():
    _registry(pipe_a=(4, 0, {"realtime"}), pipe_b=(5, 3, {"realtime"}))
    ranked = upstream_resolver.rank_session(store=allocator.store, capability="realtime")
    assert [a.instance_id for a in ranked] == ["pipe_a", "pipe_b"]
    assert ranked[0].connect_url == "ws://pipe_a:8765/v1/realtime"


def test_session_ranking_excludes_instances_without_the_capability():
    _registry(pipe_a=(4, 0, {"realtime"}), pipe_b=(4, 0, {"realtime", "voiceprint"}))
    ranked = upstream_resolver.rank_session(store=allocator.store, capability="voiceprint")
    assert [a.instance_id for a in ranked] == ["pipe_b"]


def test_session_ranking_excludes_full_instances():
    _registry(pipe_a=(1, 1, {"realtime"}), pipe_b=(4, 0, {"realtime"}))
    ranked = upstream_resolver.rank_session(store=allocator.store, capability="realtime")
    assert [a.instance_id for a in ranked] == ["pipe_b"]


def test_stateless_ranking_ignores_slot_occupancy():
    # ASR 不占 unit 槽位：会话占满的机器照样能接 ASR。
    _registry(pipe_a=(1, 1, {"asr"}), pipe_b=(8, 0, {"asr"}))
    ranked = upstream_resolver.rank_stateless(store=allocator.store, capability="asr")
    assert {a.instance_id for a in ranked} == {"pipe_a", "pipe_b"}


def test_stateless_ranking_prefers_the_fewer_inflight_requests():
    _registry(pipe_a=(4, 0, {"asr"}), pipe_b=(4, 0, {"asr"}))
    upstream_resolver.inflight_enter("pipe_b")
    ranked = upstream_resolver.rank_stateless(store=allocator.store, capability="asr")
    assert ranked[0].instance_id == "pipe_a"
    upstream_resolver.reset_inflight()


def test_stateless_ranking_skips_an_instance_over_the_inflight_cap():
    _registry(pipe_a=(4, 0, {"asr"}), pipe_b=(4, 0, {"asr"}))
    upstream_resolver.inflight_enter("pipe_a")
    upstream_resolver.inflight_enter("pipe_a")
    ranked = upstream_resolver.rank_stateless(
        store=allocator.store, capability="asr", max_inflight=1
    )
    assert [a.instance_id for a in ranked] == ["pipe_b"]
    upstream_resolver.reset_inflight()


def test_draining_instances_are_never_ranked():
    registry = _registry(pipe_a=(4, 0, {"asr"}))
    registry.set_drain("pipe_a", True)
    assert upstream_resolver.rank_stateless(store=allocator.store, capability="asr") == []
    assert upstream_resolver.rank_session(store=allocator.store, capability="realtime") == []


def test_an_unprobed_instance_is_still_a_candidate():
    # 能力还没探测过（capabilities 为空）时放行：冷启动不该把候选全灭。
    instance_monitor.reset_for_tests()
    allocator.store._pending.clear()
    instance_monitor.registry._states["pipe-a"] = RuntimeState(
        instance_id="pipe-a", base_url="http://pipe-a:8765"
    )
    instance_monitor.registry.observe_success(
        "pipe-a", PoolState(reachable=True, size=4, in_use=0, units=()), 5
    )
    ranked = upstream_resolver.rank_session(store=allocator.store, capability="voiceprint")
    assert [a.instance_id for a in ranked] == ["pipe-a"]


def test_the_inflight_counter_never_goes_below_zero():
    upstream_resolver.reset_inflight()
    upstream_resolver.inflight_exit("pipe-a")
    assert upstream_resolver.inflight_count("pipe-a") == 0
    upstream_resolver.inflight_enter("pipe-a")
    upstream_resolver.inflight_exit("pipe-a")
    assert upstream_resolver.inflight_count("pipe-a") == 0


def test_the_exclude_set_drops_the_instances_that_already_failed():
    _registry(pipe_a=(4, 0, {"realtime"}), pipe_b=(4, 0, {"realtime"}))
    ranked = upstream_resolver.rank_session(
        store=allocator.store, capability="realtime", exclude=frozenset({"pipe_a"})
    )
    assert [a.instance_id for a in ranked] == ["pipe_b"]
