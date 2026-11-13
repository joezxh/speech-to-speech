from __future__ import annotations

import re

from app.core.errors import ApiError
from app.repositories.cluster_repository import ClusterRepository
from app.repositories.instance_repository import InstanceRepository
from app.services import instance_monitor

# 与原型 saveClusterForm（console-refactor-demo.html L2878-2908）逐字一致（spec §4.1）。
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
REGISTRY_RE = re.compile(r"^([a-z][a-z0-9+.-]*://)?[\w.-]+:\d{2,5}$", re.IGNORECASE)
POLICIES = ("least", "rr", "lat")


def _validate_fields(*, registry: str, policy: str, note: str) -> None:
    # registry 创建/更新必填：default 集群的空 registry 只是存量 seed 态，
    # 任何一次提交都必须给出合法 registry（spec §4.1）。
    if not isinstance(registry, str) or not REGISTRY_RE.match(registry or ""):
        raise ApiError("invalid_request", "registry must look like host:port or scheme://host:port", 400)
    if policy not in POLICIES:
        raise ApiError("invalid_request", f"policy must be one of {list(POLICIES)}", 400)
    if not isinstance(note, str) or len(note) > 255:
        raise ApiError("invalid_request", "note must be a string of at most 255 chars", 400)


def list_clusters(db) -> list:
    return ClusterRepository(db).list_all()


def get_cluster(db, name: str):
    row = ClusterRepository(db).get_by_name(name)
    if row is None:
        raise ApiError("cluster_not_found", f"cluster {name} does not exist", 404)
    return row


def exists(db, name: str) -> bool:
    return ClusterRepository(db).get_by_name(name) is not None


def create_cluster(db, *, name: str, registry: str, policy: str, note: str, actor: str):
    if not NAME_RE.match(name or ""):
        raise ApiError("invalid_request", "name must match ^[a-z0-9][a-z0-9-]{1,39}$", 400)
    repo = ClusterRepository(db)
    if repo.get_by_name(name) is not None:
        raise ApiError("duplicate_name", f"cluster {name} already exists", 409)
    _validate_fields(registry=registry, policy=policy, note=note)
    if repo.count_registry_conflicts(registry) > 0:
        raise ApiError("duplicate_registry", f"registry {registry} is already used by another cluster", 409)
    return repo.create(name=name, registry=registry, policy=policy, note=note, updated_by=actor)


def update_cluster(db, *, name: str, registry: str, policy: str, note: str, actor: str):
    repo = ClusterRepository(db)
    row = repo.get_by_name(name)
    if row is None:
        raise ApiError("cluster_not_found", f"cluster {name} does not exist", 404)
    _validate_fields(registry=registry, policy=policy, note=note)
    if repo.count_registry_conflicts(registry, exclude_name=name) > 0:
        raise ApiError("duplicate_registry", f"registry {registry} is already used by another cluster", 409)
    return repo.update(row, registry=registry, policy=policy, note=note, updated_by=actor)


def delete_cluster(db, *, name: str, actor: str) -> None:
    repo = ClusterRepository(db)
    row = repo.get_by_name(name)
    if row is None:
        raise ApiError("cluster_not_found", f"cluster {name} does not exist", 404)
    if len(repo.list_all()) <= 1:
        raise ApiError("last_cluster", "the last cluster cannot be deleted", 409)
    blocking: int = InstanceRepository(db).cluster_counts().get(name, 0)
    if blocking > 0:
        raise ApiError("cluster_not_empty", f"cluster {name} still has {blocking} instance(s)", 409)
    repo.delete(row)


def instance_host_stats(db, cluster_name: str) -> dict:
    """该集群的机器/实例计数（spec §4.2）：机器 = base_url host 去重；
    machines_online = 至少有一个 online 实例的 host 数。派生逻辑与 /instances summary
    共用 instances_service.derive_machine_counts，防口径漂移。"""
    from app.services import instances_service  # noqa: PLC0415 - 避免 import 环

    rows = [r for r in InstanceRepository(db).list_all() if r.cluster_id == cluster_name]
    view = instance_monitor.snapshot()
    machines_total, machines_online = instances_service.derive_machine_counts(rows, view.get)
    return {"machines_total": machines_total, "machines_online": machines_online, "instances_total": len(rows)}