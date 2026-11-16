from __future__ import annotations

import httpx
import pytest

from app.services import capability_probe

VOICEPRINT_PATH = "/v1/audio/embeddings/capability"
EMOTION_PATH = "/v1/audio/emotion/health"
POOL_PATH = "/v1/pool"


def _status_handler(**paths: int):
    """按路径返回状态码；未列出的路径一律 404（= 路由没注册）。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(paths.get(request.url.path, 404))

    return handler


async def _probe(handler, timeout: float = 1.0) -> capability_probe.CapabilityReport:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await capability_probe.probe_capabilities(
            "http://x:8765", timeout=timeout, client=client
        )


async def test_voiceprint_is_present_when_the_route_answers_401():
    # 路由在、但调用方没带 Bearer → 401。这正是"路由存在"的免费信号：
    # console 不持有 VOICEPRINT_API_KEY，也不该持有。
    report = await _probe(_status_handler(**{VOICEPRINT_PATH: 401}))
    assert "voiceprint" in report.available
    assert "voiceprint" in report.present
    assert report.issues == {}


async def test_a_403_also_means_the_route_is_there():
    report = await _probe(_status_handler(**{VOICEPRINT_PATH: 403}))
    assert "voiceprint" in report.available


async def test_a_404_means_the_route_is_not_registered():
    report = await _probe(_status_handler(**{VOICEPRINT_PATH: 404}))
    assert "voiceprint" not in report.available
    assert "voiceprint" not in report.present
    assert "voiceprint" not in report.issues


async def test_a_503_means_the_route_exists_but_is_misconfigured():
    # 声纹没配 VOICEPRINT_API_KEY → AUTH_NOT_CONFIGURED → 503。
    # 路由在，但打过去必然失败：算"存在但不可用"，不能算可用。
    report = await _probe(_status_handler(**{VOICEPRINT_PATH: 503}))
    assert "voiceprint" in report.present
    assert "voiceprint" not in report.available
    assert report.issues["voiceprint"] == "misconfigured"


async def test_a_timeout_marks_the_capability_unavailable_but_present():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    report = await _probe(handler, timeout=0.01)
    assert "voiceprint" not in report.available
    assert "voiceprint" in report.present
    assert report.issues["voiceprint"] == "timeout"


async def test_emotion_404_means_absent_but_other_statuses_mean_present():
    report = await _probe(_status_handler(**{EMOTION_PATH: 404}))
    assert "emotion" not in report.present
    assert "emotion" not in report.available

    report = await _probe(_status_handler(**{EMOTION_PATH: 500}))
    assert "emotion" in report.present
    assert "emotion" not in report.available
    assert report.issues["emotion"] == "upstream_error"


async def test_emotion_2xx_is_available():
    report = await _probe(_status_handler(**{EMOTION_PATH: 200}))
    assert "emotion" in report.available
    assert report.issues == {}


async def test_realtime_is_derived_from_the_pool_endpoint():
    report = await _probe(_status_handler(**{POOL_PATH: 200}))
    assert "realtime" in report.available


async def test_asr_and_tts_are_always_available():
    # 这两条路由恒注册（mount_audio_services 无条件挂载），不探测。
    report = await _probe(_status_handler())
    assert {"asr", "tts"} <= report.available


async def test_the_probe_never_sends_an_authorization_header():
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(404)

    await _probe(handler)
    assert seen
    assert all("authorization" not in r.headers for r in seen)


async def test_probe_all_capabilities_returns_one_report_per_instance():
    reports = await capability_probe.probe_all_capabilities(
        [("pipe-a", "http://a:8765"), ("pipe-b", "http://b:8765")],
        timeout=1.0,
        client_factory=lambda timeout: httpx.AsyncClient(
            transport=httpx.MockTransport(_status_handler(**{POOL_PATH: 200}))
        ),
    )
    assert set(reports) == {"pipe-a", "pipe-b"}
    assert all("realtime" in r.available for r in reports.values())


def test_apply_capabilities_writes_into_the_registry():
    from app.services import instance_monitor

    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = _state("pipe-a")
    instance_monitor.apply_capabilities(
        {
            "pipe-a": capability_probe.CapabilityReport(
                available=frozenset({"realtime", "asr"}),
                present=frozenset({"realtime", "asr", "voiceprint"}),
                issues={"voiceprint": "misconfigured"},
            )
        }
    )
    state = instance_monitor.registry.get("pipe-a")
    assert state is not None
    assert state.capabilities == frozenset({"realtime", "asr"})
    assert state.capability_issues == {"voiceprint": "misconfigured"}


async def test_the_capability_round_is_separate_from_the_capacity_round(monkeypatch):
    # 能力轮挂在 run_forever 里，但自己是独立的一轮：它慢，它自己超时，
    # 容量探测的节奏不受影响（spec §5.1）。
    from app.services import instance_monitor

    instance_monitor.reset_for_tests()
    instance_monitor.registry._states["pipe-a"] = _state("pipe-a")
    seen: list[tuple] = []

    async def fake(base_urls, *, timeout):
        seen.append((base_urls, timeout))
        return {"pipe-a": capability_probe.CapabilityReport(available=frozenset({"realtime"}))}

    monkeypatch.setattr(capability_probe, "probe_all_capabilities", fake)
    await instance_monitor.probe_capabilities_round()
    assert seen and seen[0][0] == [("pipe-a", "http://pipe-a:8765")]


def _state(instance_id: str):
    from app.services.instance_registry import RuntimeState

    return RuntimeState(instance_id=instance_id, base_url=f"http://{instance_id}:8765")
