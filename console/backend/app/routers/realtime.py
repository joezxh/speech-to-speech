"""`/v1/realtime*`：浏览器进入 S2S 的唯一通道（§10.2.3 / spec 2026-11-16）。

两种模式：
- `CONSOLE_LB_MODE=off`（默认）：回环 pipeline，逐字保持改造前的行为。
- `CONSOLE_LB_MODE=proxy`：按注册表选台转发，上游满员时静默换台。

静默换台的由来（spec §5.3）：pipeline 满员时是**握手成功之后**才回一个
`error`(session_limit_reached) 事件再 close 1008。nginx 这类透明代理必须先把 101
交给客户端，撤不回来；console 自己是 WebSocket 服务端，可以在 accept 浏览器之前
先与上游完成握手、校验第一帧，失败就换一台——浏览器因此看不到中间态。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress

import websockets
from fastapi import APIRouter, Depends, Request, WebSocket
from loguru import logger

from app.config import allocator as allocator_settings
from app.config import console
from app.core.security import CurrentUser, require_user
from app.schemas.common import ok
from app.services import allocator, calls_service, proxy_counters, realtime_ticket, upstream_resolver

router = APIRouter(tags=["realtime"])


@router.post("/api/v1/realtime/ticket")
def issue_realtime_ticket(user: CurrentUser = Depends(require_user)):
    """WS 短票据换发（Task 16）：用户 JWT 换 60s 一次性票据，JWT 不上查询串。"""
    return ok({"ticket": realtime_ticket.issue(user.username, user.role), "ttl_s": int(realtime_ticket.TTL_S)})


def routing_for_websocket(db, websocket) -> "RoutingDecision":
    """WS 握手参数 → 路由决策（Task 17 接线）：票据一次性消费，tenant_tag 可选。"""
    from app.services.routing_service import RoutingEngine, context_from_ticket  # noqa: PLC0415

    query = websocket.query_params
    ctx = context_from_ticket(
        query.get("ticket", ""),
        session_key=query.get("session_key") or uuid.uuid4().hex,
        tenant_tag=query.get("tenant_tag", ""),
    )
    return RoutingEngine(db).resolve(ctx)


def _routing_decision_for_ws(websocket):
    """规则表未部署/读失败 → None（routing=None 走改前逐字一致路径）。"""
    from app.db.database import SessionLocal  # noqa: PLC0415

    try:
        session = SessionLocal()
    except Exception:  # noqa: BLE001
        return None
    try:
        return routing_for_websocket(session, websocket)
    except Exception:  # noqa: BLE001 - 路由是增强，不能让代理握手失败
        return None
    finally:
        session.close()


def _drop_sticky_for_ws(key: str) -> None:
    from app.db.database import SessionLocal  # noqa: PLC0415
    from app.services.routing_service import drop_sticky  # noqa: PLC0415

    try:
        session = SessionLocal()
    except Exception:  # noqa: BLE001
        return
    try:
        drop_sticky(session, key)
    except Exception:  # noqa: BLE001
        pass
    finally:
        session.close()

SESSION_CREATED = "session.created"
SESSION_LIMIT_REACHED = "session_limit_reached"


def _upstream_url(url) -> str:
    """`http://127.0.0.1:8765` + 浏览器的 path/query → `ws://…`（https→wss）。"""
    base = console.pipeline_base_url.strip().rstrip("/")
    if "://" not in base:
        base = "http://" + base
    scheme, host = base.split("://", 1)
    query = f"?{url.query}" if url.query else ""
    return f"{'wss' if scheme == 'https' else 'ws'}://{host}{url.path}{query}"


def _upstream_ws_url(base_url: str, path: str, query: str) -> str:
    """实例 base_url + 浏览器路径 → 上游 ws:// 地址。"""
    base = base_url.strip().rstrip("/")
    if "://" not in base:
        base = "http://" + base
    scheme, host = base.split("://", 1)
    suffix = f"?{query}" if query else ""
    return f"{'wss' if scheme == 'https' else 'ws'}://{host}{path}{suffix}"


def _subprotocols(websocket: WebSocket) -> list[str]:
    raw = websocket.headers.get("sec-websocket-protocol", "")
    return [item.strip() for item in raw.split(",") if item.strip()]


def _frame_field(frame: str | bytes, *names: str) -> str:
    """从一帧 JSON 里取第一个非空的字符串字段；解析失败返回空串。"""
    if isinstance(frame, bytes):
        try:
            frame = frame.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    try:
        payload = json.loads(frame)
    except (TypeError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for name in names:
        value = payload.get(name)
        if isinstance(value, dict):
            value = value.get("type")
        if isinstance(value, str) and value:
            return value
    return ""


def _is_session_limit_error(frame: str | bytes) -> bool:
    """上游说"我满了"：要换一台，别让浏览器看见。"""
    return (
        _frame_field(frame, "type") == "error"
        and _frame_field(frame, "error") == SESSION_LIMIT_REACHED
    )


def _is_session_created(frame: str | bytes) -> bool:
    return _frame_field(frame, "type") == SESSION_CREATED


async def _close_quietly(upstream) -> None:
    with suppress(Exception):
        await upstream.close()


async def _client_to_upstream(client: WebSocket, upstream) -> None:
    while True:
        message = await client.receive()
        if message["type"] == "websocket.disconnect":
            return
        if message.get("text") is not None:
            await upstream.send(message["text"])
        elif message.get("bytes") is not None:
            await upstream.send(message["bytes"])


async def _upstream_to_client(client: WebSocket, upstream) -> None:
    async for message in upstream:
        if isinstance(message, bytes):
            await client.send_bytes(message)
        else:
            await client.send_text(message)


async def _pump(websocket: WebSocket, upstream) -> None:
    """双向逐帧转发；一侧关闭就关另一侧，否则端口会积压僵尸连接。"""
    tasks = [
        asyncio.create_task(_client_to_upstream(websocket, upstream)),
        asyncio.create_task(_upstream_to_client(websocket, upstream)),
    ]
    _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)
    with suppress(Exception):
        await upstream.close()
    with suppress(Exception):
        await websocket.close()


@router.websocket("/v1/realtime")
async def realtime(websocket: WebSocket) -> None:
    """把浏览器的 Realtime WS 接到上游 pipeline。

    不改路径、不缓冲帧（缓冲会把 TTS 首字节延迟放大，§12 R20）——两边都是逐帧转发。
    """
    if console.lb_mode == "proxy":
        await _proxy_with_failover(websocket)
        return
    await _proxy_to_loopback(websocket)


async def _proxy_to_loopback(websocket: WebSocket) -> None:
    """改造前的路径：固定回环 pipeline（CONSOLE_LB_MODE=off）。"""
    try:
        upstream = await websockets.connect(
            _upstream_url(websocket.url),
            subprotocols=_subprotocols(websocket) or None,
            max_size=None,  # base64 音频帧可能超过默认 1 MiB
            # R20: deflate 会把帧缓冲到凑满一个块，TTS 首字节因此晚到。
            compression=None,
            open_timeout=5.0,
        )
    except Exception as exc:
        logger.warning("realtime upstream unreachable: {}", exc)
        # 还没 accept：ASGI 会把这次握手判为失败，而不是收下一个谁也服务不了的会话。
        await websocket.close(code=1013)
        return

    await websocket.accept(subprotocol=upstream.subprotocol)
    await _pump(websocket, upstream)


async def _proxy_with_failover(websocket: WebSocket) -> None:
    """按注册表选台，上游满员/连不上就换一台（spec §5.3）。

    三种终态（统一口径）：
    - 成功：首帧是 session.created → accept 浏览器，转发首帧。
    - 满员：上游明确回 session_limit_reached 且换台耗尽 → accept 后转发该 error
      事件 + close 1008（与今天直连 pipeline 的表现完全一致）。
    - 不可达/无候选：不 accept，直接 close → ASGI 回 403 握手失败（close code
      送不到浏览器，这是既有事实）。
    """
    tried: set[str] = set()
    last_full_frame: str | bytes | None = None
    # Task 17：每次尝试重新评估路由（粘性失败后回落需要新决策）。
    decision = _routing_decision_for_ws(websocket)
    for _attempt in range(console.lb_failover_attempts + 1):
        ranked = upstream_resolver.rank_session(
            store=allocator.store,
            capability="realtime",
            exclude=frozenset(tried),
            rng=allocator._rng,
            routing=decision,
        )
        if not ranked:
            break
        spec = ranked[0]
        tried.add(spec.instance_id)
        if decision is not None and decision.sticky_hit and spec.instance_id != decision.candidates.instance_id:
            # 粘性目标不可达/满员 → 删亲和行并回落；下一次循环重新评估。
            _drop_sticky_for_ws(decision.affinity_key)
            logger.warning("sticky_target_unavailable: {} fallback to {}", decision.candidates.instance_id, spec.instance_id)
            decision = None
        res_key = uuid.uuid4().hex
        if not allocator.store.reserve(
            spec.instance_id, res_key, allocator_settings.grant_ttl_s
        ):
            # 本机视图里这台已经满了：换下一台，不去打扰它。
            continue
        try:
            upstream = await websockets.connect(
                _upstream_ws_url(spec.base_url, websocket.url.path, websocket.url.query),
                subprotocols=_subprotocols(websocket) or None,
                max_size=None,
                compression=None,
                open_timeout=5.0,
            )
        except Exception as exc:
            logger.warning("lb failover: upstream {} unreachable: {}", spec.instance_id, exc)
            proxy_counters.bump(
                spec.instance_id, "realtime", ok=False, fail_reason="upstream_unreachable"
            )
            allocator.store.release(res_key)
            continue
        try:
            first = await asyncio.wait_for(
                upstream.recv(), timeout=console.lb_upstream_ready_timeout_s
            )
        except asyncio.TimeoutError:
            logger.warning(
                "lb failover: upstream {} sent no first frame in time", spec.instance_id
            )
            await _close_quietly(upstream)
            allocator.store.release(res_key)
            continue
        except Exception as exc:
            logger.warning(
                "lb failover: upstream {} closed before the first frame: {}",
                spec.instance_id,
                exc,
            )
            await _close_quietly(upstream)
            allocator.store.release(res_key)
            continue

        if _is_session_limit_error(first):
            # 满员：静默换台，浏览器不该看到中间态。
            last_full_frame = first
            proxy_counters.bump(
                spec.instance_id, "realtime", ok=False, fail_reason="session_limit_reached"
            )
            await _close_quietly(upstream)
            allocator.store.release(res_key)
            continue

        await websocket.accept(subprotocol=upstream.subprotocol)
        if isinstance(first, bytes):
            await websocket.send_bytes(first)
        else:
            await websocket.send_text(first)
        # 会话已建立：占位从"预留"转成"会话期"，不再靠 TTL 回收。
        allocator.store.hold(res_key, spec.instance_id)
        upstream_resolver.inflight_enter(spec.instance_id)
        proxy_counters.bump(spec.instance_id, "realtime", ok=True)
        # Task 18：记账只入内存队列，绝不阻塞这条已建立的会话。
        from app.services.route_log_writer import RouteLogEntry, submit  # noqa: PLC0415

        submit(
            RouteLogEntry(
                session_key=decision.affinity_key if decision is not None else "anon",
                rule_id=int(decision.rule_id) if decision is not None and decision.rule_id else None,
                matched=bool(decision is not None and decision.rule_id is not None),
                sticky_hit=bool(decision is not None and decision.sticky_hit),
                is_canary=bool(decision is not None and decision.is_canary),
                instance_id=spec.instance_id,
            )
        )
        if decision is not None and not decision.sticky_hit and decision.candidates.kind == "pinned_instance":
            from app.db.database import SessionLocal  # noqa: PLC0415
            from app.services.routing_service import remember_sticky_async  # noqa: PLC0415

            remember_sticky_async(
                SessionLocal,
                decision.affinity_key,
                requested_by=decision.affinity_key.split(":", 1)[0],
                instance_id=spec.instance_id,
                ttl_s=60,
            )
        try:
            await _pump(websocket, upstream)
        finally:
            upstream_resolver.inflight_exit(spec.instance_id)
            allocator.store.release(res_key)
        return

    if last_full_frame is not None:
        # 满员终态：accept 后把上游的 error 事件原样交给浏览器（今天直连也是这个
        # 事件 + 1008），前端零改动。
        await websocket.accept()
        if isinstance(last_full_frame, bytes):
            await websocket.send_bytes(last_full_frame)
        else:
            await websocket.send_text(last_full_frame)
        await websocket.close(code=1008)
        return

    # 不可达 / 无候选：不 accept，直接 close。
    logger.warning("lb failover: no usable upstream for /v1/realtime")
    await websocket.close(code=1013)


@router.post("/v1/realtime/calls", include_in_schema=False)
async def realtime_calls(request: Request):
    """同源的 SDP 入口。

    off 模式不回填 `Location`：它指向回环，浏览器拿不到。proxy 模式回填上游的
    `/v1/realtime/calls/{id}`——console 自己也注册了这个路径，浏览器拿得到。
    """
    offer = await request.body()
    if console.lb_mode == "proxy":
        return await calls_service.forward_selected(offer, keep_location=True)
    return await calls_service.forward(
        calls_service.loopback_url(), offer, keep_location=False
    )
