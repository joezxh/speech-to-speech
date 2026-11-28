from __future__ import annotations

from fastapi import FastAPI


def register_api_routers(app: FastAPI) -> None:
    """Single place where route groups are added, in prefix order.

    /api/v1 (JWT), /api (anonymous), /v1 (reverse proxy) — never reordered,
    because the SPA catch-all is registered after this call returns.
    """
    from app.routers import (  # noqa: PLC0415 - import cycle avoidance
        agent,
        audio_proxy,
        audit,
        auth,
        callbacks,
        catalog,
        clusters,
        config,
        health,
        instances,
        lb,
        live_transcripts,
        logs,
        machines,
        profiles,
        realtime,
        releases,
        runtime,
        sessions,
        sessions_records,
        smart_settings,
        status,
        templates,
        tokens,
        traffic,
        turn_latency,
        voices,
    )
    from app.routers.demo import ROUTERS as DEMO_ROUTERS  # noqa: PLC0415

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(catalog.router)
    app.include_router(profiles.router)
    app.include_router(instances.router)
    app.include_router(clusters.router)
    # 配置面（spec 2026-11-17 §6.1）：读给所有登录用户，写仅管理员。
    app.include_router(config.router)
    # agent 面（spec 2026-11-17 §7.2.1）：register 匿名，heartbeat 用 machine token。
    # 必须在 SPA catch-all 之前注册（C11）。
    app.include_router(agent.router)
    # 机器管理面（spec 2026-11-17 §7.2.2）：M1–M9，console:machine:* 权限码。
    app.include_router(machines.router)

    from app.config import allocator as allocator_settings  # noqa: PLC0415 - 与本函数内既有延迟 import 同层

    # spec §9.2: the hangup proxy is opt-in. Unregistered means the path never
    # reaches a handler — the SPA catch-all is GET-only, so a POST turns into a 405.
    if allocator_settings.webrtc_hangup_enabled:
        app.include_router(instances.hangup_router)
    app.include_router(runtime.router)
    app.include_router(voices.router)
    app.include_router(sessions.router)
    app.include_router(status.router)
    # 参数模板（原型「模板管理」）：查询 operator 可看，写仅管理员。
    app.include_router(templates.router)
    # 智能设置（原型 smartPanel）：拉取走机器读权限，分析独立权限码。
    app.include_router(smart_settings.router)
    # 会话记录（对话页「会话记录」面板 + 历史页）：查询 operator 可看，写 operator 可写。
    app.include_router(sessions_records.router)
    # S1 spec §10.2: read-only traffic settings snapshot; no write path, no DB, no audit.
    app.include_router(traffic.router)
    # A.15/A.16: read-only side channels; no prefix overlap with anything above.
    app.include_router(logs.router)
    app.include_router(turn_latency.router)
    # Token 观测（T1–T5）与 LB 策略/规则（L1–L6）：SPA catch-all 之前（C11）。
    app.include_router(tokens.router)
    app.include_router(lb.router)
    # 发布台账（R1–R4，Task 24）：console 只记账，CI 回填走 stage-result。
    app.include_router(releases.router)
    # 全局审计（R5/R6，Task 25）：查询分页 + CSV 导出。
    app.include_router(audit.router)
    # 回调配置面（spec 2026-11-25 §8.4）：查询 operator 可看，写仅管理员。
    app.include_router(callbacks.router)
    # 实时转写 SSE 流（Task 14A）：与 callbacks 同权限码 console:callback:query。
    app.include_router(live_transcripts.router)

    # The demo face is anonymous and unenveloped (A.13), so it goes last among the
    # API groups but still before the SPA catch-all.
    for router in DEMO_ROUTERS:
        app.include_router(router)

    # /v1 反代最后注册：它只开精确路径，不和 /api 抢前缀。
    app.include_router(realtime.router)
    # ASR/TTS/声纹/情感的反代面（spec §5.4）。路径前缀与上面不重叠。
    app.include_router(audio_proxy.router)
