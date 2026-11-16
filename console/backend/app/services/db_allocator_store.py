"""AllocatorStore 的数据库实现（spec 2026-11-17 §3.2，Phase 2）。

为什么需要它：内存版按"本机看到的余量"预留，两个控制台副本会各自看到同一台
机器还有空位，于是同时派发过去 → 会话数超过 pipeline 的池容量。落库之后
占位是共享的，`reserved` 列是唯一的真相源。

三条设计约束：

1. **不用行锁**：SQLite 没有 `SELECT … FOR UPDATE`。占位判定与递增合并成一条
   带条件的 UPDATE，看 `rowcount`（两个方言语义一致）。
2. **时间用墙钟**：跨进程必须共享时间基准（内存版的 monotonic 只在本进程内有效）。
3. **进程内的事（去重、grant 缓存、满员队列、计数器）仍留在内存**：它们本来就是
   单副本语义，共享反而会出错。

降级：DB 不可用时占位直接失败（选台返回 503），**绝不用陈旧租约继续派发**——
宁可少派不超发（设计 §5.1）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from loguru import logger

from app.repositories.allocator_lease_repository import PENDING, AllocatorLeaseRepository
from app.repositories.instance_runtime_repository import InstanceRuntimeRepository
from app.services import instance_monitor
from app.services.allocator_store import InMemoryAllocatorStore, InstanceSpec, QueueTicket
from app.services.instance_registry import RuntimeState


def _default_session_factory():
    # 延迟导入：app.db.database 依赖 app.config，模块级导入会成环。
    from app.db.database import SessionLocal

    return SessionLocal


class DbAllocatorStore:
    """占位跨副本共享的 store；进程内事务仍走内存实现。"""

    def __init__(self, session_factory=None, *, console_id: str = "") -> None:
        self._session_factory = session_factory
        self._console_id = console_id
        # 去重键 / grant 缓存 / 满员队列 / 计数器：单副本语义，留在进程内。
        self._local = InMemoryAllocatorStore()

    # ── 会话 ────────────────────────────────────────────────────────────
    def _session(self):
        factory = self._session_factory or _default_session_factory()
        return factory()

    # ── 注册表视图（与内存版同源：内存注册表已从库里恢复）────────────────
    def list_instances(self) -> list[InstanceSpec]:
        out = []
        for state in instance_monitor.registry.snapshot().values():
            capacity = state.pool.size if state.pool else 0
            out.append(
                InstanceSpec(
                    instance_id=state.instance_id,
                    base_url=state.base_url,
                    weight=state.weight,
                    enabled=state.enabled,
                    effective_free=state.effective_free,
                    capacity=capacity,
                    status=state.status,
                )
            )
        return out

    def snapshot_runtime(self) -> dict[str, RuntimeState]:
        return instance_monitor.registry.snapshot()

    def upsert_runtime(self, state: RuntimeState) -> None:
        instance_monitor.registry._states[state.instance_id] = state

    # ── 占位（共享）─────────────────────────────────────────────────────
    def reserve(self, instance_id: str, session_id: str, ttl_s: int) -> bool:
        """预留一个槽位：条件 UPDATE 判定 + 递增，与明细行同一事务提交。"""
        session = None
        try:
            session = self._session()
            runtime = InstanceRuntimeRepository(session)
            if not runtime.reserve(instance_id, commit=False):
                session.rollback()
                return False
            AllocatorLeaseRepository(session).insert(
                lease_key=session_id,
                instance_id=instance_id,
                state=PENDING,
                expires_at=datetime.now(UTC) + timedelta(seconds=ttl_s),
                console_id=self._console_id,
                commit=False,
            )
            session.commit()
            return True
        except Exception as exc:  # noqa: BLE001 - 占位失败按"没有余量"处理
            logger.warning("db reserve failed for {}: {}", instance_id, exc)
            if session is not None:
                session.rollback()
            return False
        finally:
            if session is not None:
                session.close()

    def release(self, session_id: str) -> None:
        session = None
        try:
            session = self._session()
            lease = AllocatorLeaseRepository(session).delete(session_id, commit=False)
            if lease is not None:
                InstanceRuntimeRepository(session).release_reserved(lease.instance_id, commit=False)
            session.commit()
        except Exception as exc:  # noqa: BLE001 - 释放失败会漏一个占位，记日志继续
            logger.warning("db release failed for {}: {}", session_id, exc)
            if session is not None:
                session.rollback()
        finally:
            if session is not None:
                session.close()

    def hold(self, session_id: str, instance_id: str) -> None:
        """预留转成会话期占位：不再靠 TTL 回收，随会话结束 release。"""
        session = None
        try:
            session = self._session()
            AllocatorLeaseRepository(session).mark_held(session_id, instance_id, commit=False)
            session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("db hold failed for {}: {}", session_id, exc)
            if session is not None:
                session.rollback()
        finally:
            if session is not None:
                session.close()

    def expire_pending(self) -> list[str]:
        """回收到期未连接的预留（墙钟）。"""
        session = None
        try:
            session = self._session()
            now = datetime.now(UTC)
            repo = AllocatorLeaseRepository(session)
            gone = repo.expired_pending(now, commit=False)
            for lease in gone:
                InstanceRuntimeRepository(session).release_reserved(lease.instance_id, commit=False)
            session.commit()
            return [lease.lease_key for lease in gone]
        except Exception as exc:  # noqa: BLE001
            logger.warning("db expire_pending failed: {}", exc)
            if session is not None:
                session.rollback()
            return []
        finally:
            if session is not None:
                session.close()

    def pending_count(self, instance_id: str) -> int:
        """该实例上的占位数（pending + held，跨副本共享）。

        取运行时行的 `reserved` 聚合列：它与租约明细同事务更新，不会漂移。
        """
        session = None
        try:
            session = self._session()
            return InstanceRuntimeRepository(session).reserved_count(instance_id)
        except Exception as exc:  # noqa: BLE001 - 读不到就按"没有占位"算，宁可多派
            logger.warning("db pending_count failed for {}: {}", instance_id, exc)
            if session is not None:
                session.rollback()
            return 0
        finally:
            if session is not None:
                session.close()

    def occupied_count(self) -> int:
        """全部实例上的占位总数（共享）。"""
        session = None
        try:
            session = self._session()
            return sum(
                int(row.reserved or 0)
                for row in InstanceRuntimeRepository(session).list_all()
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("db occupied_count failed: {}", exc)
            if session is not None:
                session.rollback()
            return 0
        finally:
            if session is not None:
                session.close()

    def pending_total(self) -> int:
        """本副本已签发未领取的 grant 数（pending 租约）。"""
        session = None
        try:
            session = self._session()
            return AllocatorLeaseRepository(session).count(
                state=PENDING, console_id=self._console_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("db pending_total failed: {}", exc)
            if session is not None:
                session.rollback()
            return 0
        finally:
            if session is not None:
                session.close()

    # ── 进程内事务（单副本语义，留在内存）──────────────────────────────
    def begin_once(self, dedupe_key: str, window_s: int) -> str | None:
        return self._local.begin_once(dedupe_key, window_s)

    def remember_grant(self, dedupe_key: str, grant: dict) -> None:
        self._local.remember_grant(dedupe_key, grant)

    def grant_for(self, dedupe_key: str) -> dict | None:
        return self._local.grant_for(dedupe_key)

    def enqueue(self, ticket_id: str, meta: dict) -> int:
        return self._local.enqueue(ticket_id, meta)

    def peek_queue(self) -> list[QueueTicket]:
        return self._local.peek_queue()

    def pop_queue(self) -> QueueTicket | None:
        return self._local.pop_queue()

    def bump(self, counter: str, delta: int = 1) -> int:
        return self._local.bump(counter, delta)

    def drain_counters(self) -> dict[str, int]:
        return self._local.drain_counters()  
