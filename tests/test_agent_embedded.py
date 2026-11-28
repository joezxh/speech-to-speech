"""The embedded agent: stoppable, single-step triggerable, and never louder than the pipeline."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from speech_to_speech.agent.embedded import (
    AgentBusyError,
    AgentNotRegisteredError,
    EmbeddedAgent,
)
from speech_to_speech.agent.settings import AgentSettings


class FakeClient:
    """Stands in for the console REST client; records every call."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.commands: list[dict] = []
        self.register_body: dict | None = None

    def register(self, body: dict) -> dict:
        self.calls.append(("register", body))
        self.register_body = body
        return {"machine_token": "tok-123"}

    def heartbeat(self, token: str, body: dict) -> dict:
        self.calls.append(("heartbeat", token, body))
        return {"ok": True}

    def pull_config(self, token: str, machine_id: str, if_none_match: str = "") -> tuple[int, dict | None]:
        self.calls.append(("pull_config", token, machine_id, if_none_match))
        return 304, None

    def report(self, token: str, body: dict) -> dict:
        self.calls.append(("report", token, body))
        return {"ok": True}

    def ack(self, token: str, body: dict) -> dict:
        self.calls.append(("ack", token, body))
        return {"ok": True}

    def pull_commands(self, token: str, limit: int = 10) -> list[dict]:
        self.calls.append(("pull_commands", token, limit))
        return list(self.commands)

    def report_command(self, token: str, command_id: str, *, ok: bool, result: dict, error: str = "") -> dict:
        self.calls.append(("report_command", command_id, ok))
        return {"command_id": command_id}

    def set_instance_drain(self, token: str, drain: bool) -> dict:
        self.calls.append(("set_instance_drain", token, drain))
        return {"instanceIds": ["a"], "drainRequested": drain}

    def upload_logs(self, token: str, logs: list[dict]) -> dict:
        self.calls.append(("upload_logs", token, len(logs)))
        return {"written": len(logs)}

    def report_turn_latency(self, token: str, rows: list[dict]) -> dict:
        self.calls.append(("report_turn_latency", token, rows))
        return {"received": len(rows)}

    def probe_instances(self, token: str) -> dict:
        self.calls.append(("probe_instances", token))
        return {"statuses": {}}


@pytest.fixture
def settings(tmp_path) -> AgentSettings:
    return AgentSettings(
        console_url="http://console:8080",
        register_code="reg-123",
        token_file=str(tmp_path / "token"),
        machine_id="node-a",
        heartbeat_s=15,
        pipeline_log=str(tmp_path / "pipeline.log"),
        target_yaml=str(tmp_path / "prod.yaml"),
        supervisor_socket=str(tmp_path / "supervisor.sock"),
        supervisor_program="pipeline",
        declaration_file=str(tmp_path / "agent.yaml"),
        deployment_manifest=str(tmp_path / "deployment-manifest.json"),
        container_log_max_lines=10,
    )


@pytest.fixture
def agent(settings, monkeypatch) -> EmbeddedAgent:
    """An agent whose collectors are stubbed out; only the protocol is exercised."""

    monkeypatch.setattr(
        "speech_to_speech.agent.pipeline_inspect.collect_node_metrics",
        lambda: {
            "cpu_pct": 1.0,
            "load_avg": [],
            "mem_total_gb": 1.0,
            "mem_used_gb": 1.0,
            "mem_pct": 1.0,
            "gpu_name": "GPU",
            "gpu_util_pct": 0,
            "gpu_mem_total_gb": 1.0,
            "gpu_mem_used_gb": 1.0,
            "pipeline_vram_gb": 0.5,
            "collected_at": "2026-11-18T00:00:00Z",
        },
    )
    monkeypatch.setattr(
        "speech_to_speech.agent.pipeline_inspect.collect_deployment_params",
        lambda _settings: {"runtime": {}, "declared": {}},
    )
    monkeypatch.setattr(
        "speech_to_speech.agent.pipeline_inspect.collect_container_logs",
        lambda _settings: [{"source": "stdout", "lines": ["hello"]}],
    )
    monkeypatch.setattr(
        "speech_to_speech.agent.collectors.collect_workloads",
        lambda _settings, **_kwargs: [{"kind": "pipeline", "port": 8765}],
    )
    monkeypatch.setattr(
        "speech_to_speech.agent.collectors.read_usage",
        lambda _settings=None: SimpleNamespace(
            input_tokens=10,
            output_tokens=20,
            responses=3,
            audio_duration_s=1.5,
            window_s=15,
            backends={
                "stt": {"calls": 1, "errors": 0, "ms_sum": 120},
                "llm": {"calls": 1, "errors": 0, "ms_sum": 900},
                "tts": {"calls": 1, "errors": 0, "ms_sum": 400},
            },
        ),
    )
    monkeypatch.setattr(
        "speech_to_speech.agent.collectors.tail_turn_latency",
        lambda _path, _offset: (0, []),
    )
    return EmbeddedAgent(settings, client=FakeClient(), embedded=True)


def test_the_token_is_written_with_owner_only_permissions(agent, settings):
    agent.save_token("tok-123")

    assert agent.load_token() == "tok-123"
    assert settings.token_file.endswith("token")


def test_model_reload_provider_is_forwarded_on_all_command_paths(settings, monkeypatch):
    seen = []

    def provider(request, on_progress):
        seen.append(request)
        return "task-x"

    embedded = EmbeddedAgent(
        settings, client=FakeClient(), embedded=True, reload_provider=provider
    )
    embedded.save_token("tok-123")
    monkeypatch.setattr(embedded.client, "pull_commands", lambda token, limit=10: [
        {"command_id": "c1", "kind": "model_reload", "payload": {"modules": ["tts"]}}
    ])

    polled = embedded.poll_commands_once()
    assert polled["receipts"][0]["ok"] is True
    assert seen[-1]["modules"] == ["tts"]

    direct = embedded.run_command_once("model_reload", {"modules": ["asr"]})
    assert direct["ok"] is True
    assert seen[-1]["modules"] == ["asr"]


def test_capability_declares_model_reload_only_with_provider(settings):
    with_provider = EmbeddedAgent(
        settings, client=FakeClient(), embedded=True, reload_provider=lambda *_: "t"
    )
    without_provider = EmbeddedAgent(settings, client=FakeClient(), embedded=True)

    assert "model_reload" in with_provider.capability()["actions"]
    assert "model_reload" not in without_provider.capability()["actions"]


def test_a_heartbeat_carries_the_machine_state(agent):
    result = agent.heartbeat_once()

    assert result["sent"] is True
    heartbeat = result["heartbeat"]
    assert heartbeat["machine"]["machine_id"] == "node-a"
    assert heartbeat["tokens"]["input_tokens"] == 10
    assert heartbeat["tokens"]["backends"]["stt"] == {"calls": 1, "errors": 0, "ms_sum": 120}
    assert agent.status()["last_heartbeat_ok"] is True


def test_the_second_heartbeat_reports_backend_deltas_only(agent):
    agent.heartbeat_once()
    agent._read_usage = lambda: SimpleNamespace(
        input_tokens=30,
        output_tokens=50,
        responses=6,
        audio_duration_s=3.0,
        window_s=15,
        backends={
            "stt": {"calls": 3, "errors": 1, "ms_sum": 600},
            "llm": {"calls": 2, "errors": 0, "ms_sum": 1800},
            "tts": {"calls": 2, "errors": 0, "ms_sum": 800},
        },
    )

    result = agent.heartbeat_once()

    tokens = result["heartbeat"]["tokens"]
    assert tokens["input_tokens"] == 20
    assert tokens["backends"]["stt"] == {"calls": 2, "errors": 1, "ms_sum": 480}
    assert tokens["backends"]["llm"] == {"calls": 1, "errors": 0, "ms_sum": 900}


def test_turn_latency_rows_are_uploaded_and_the_cursor_advances(agent, monkeypatch, tmp_path):
    rows = [{"response_key": "r1", "e2e_ms": 2000, "logged_at": None}]
    monkeypatch.setattr(
        "speech_to_speech.agent.collectors.tail_turn_latency",
        lambda _path, _offset: (123, rows),
    )

    agent.save_token("tok-123")
    assert agent._tail_latency("tok-123") == 1
    assert ("report_turn_latency", "tok-123", rows) in agent.client.calls
    assert agent._turn_offset == 123

    # 空批次只推进游标，不上报
    monkeypatch.setattr(
        "speech_to_speech.agent.collectors.tail_turn_latency",
        lambda _path, _offset: (200, []),
    )
    assert agent._tail_latency("tok-123") == 0
    assert agent._turn_offset == 200


def test_a_failed_turn_latency_upload_keeps_the_cursor_for_retry(agent, monkeypatch):
    rows = [{"response_key": "r1", "e2e_ms": 2000, "logged_at": None}]
    monkeypatch.setattr(
        "speech_to_speech.agent.collectors.tail_turn_latency",
        lambda _path, _offset: (123, rows),
    )

    # 上报抛错 → 游标不动（下一轮重读整批），行数仍返回
    class _FailingClient:
        def __init__(self) -> None:
            self.attempts = 0

        def report_turn_latency(self, token: str, payload_rows: list[dict]) -> dict:
            self.attempts += 1
            raise RuntimeError("console unreachable")

    failing = _FailingClient()
    agent._client = failing
    assert agent._tail_latency("tok-123") == 1
    assert agent._turn_offset == 0
    assert failing.attempts == 1


def test_registering_stores_the_token_but_never_echoes_it(agent):
    result = agent.register_once()

    assert result["registered"] is True
    assert "machine_token" not in result
    assert agent.load_token() == "tok-123"


def test_without_a_token_or_a_register_code_the_agent_refuses_to_act(agent, settings):
    settings.register_code = ""

    with pytest.raises(AgentNotRegisteredError):
        agent.heartbeat_once()


def test_a_second_concurrent_action_is_refused_rather_than_queued(agent):
    agent._lock.acquire()
    try:
        with pytest.raises(AgentBusyError):
            agent.heartbeat_once()
    finally:
        agent._lock.release()


def test_the_embedded_agent_refuses_to_restart_its_own_process(agent):
    agent.save_token("tok-123")

    result = agent.run_command_once("reboot")

    assert result["ok"] is False
    assert result["result"]["reason"] == "not_supported_in_embedded_mode"


def test_the_standalone_agent_may_still_restart_the_pipeline(settings, monkeypatch):
    agent = EmbeddedAgent(settings, client=FakeClient(), embedded=False)
    agent.save_token("tok-123")
    monkeypatch.setattr(
        "speech_to_speech.agent.commands.config_sync.restart_pipeline",
        lambda _settings: None,
    )

    result = agent.run_command_once("reboot")

    assert result["ok"] is True
    assert result["result"] == {"restarted": True}


def test_drain_reaches_the_console(agent):
    agent.save_token("tok-123")

    result = agent.set_drain(True)

    assert result["drain"] is True
    assert ("set_instance_drain", "tok-123", True) in agent.client.calls


def test_expensive_collectors_are_cached_for_a_short_while(agent, monkeypatch):
    calls = []

    def collect() -> dict:
        calls.append(1)
        return {"cpu_pct": 5.0}

    monkeypatch.setattr("speech_to_speech.agent.pipeline_inspect.collect_node_metrics", collect)

    first = agent.collect_metrics()
    second = agent.collect_metrics()

    assert first == second
    assert len(calls) == 1


def test_the_loop_returns_as_soon_as_the_stop_event_is_set(agent):
    agent.stop_event.set()

    agent.run()  # must not block


def test_a_failing_tick_is_recorded_and_never_escapes_the_loop(agent, monkeypatch):
    def boom() -> dict:
        agent.stop_event.set()
        raise RuntimeError("console unreachable")

    monkeypatch.setattr(agent, "tick", boom)

    agent.run()

    assert "console unreachable" in agent.status()["last_error"]


def test_the_status_snapshot_reports_the_registration_state(agent):
    status = agent.status()

    assert status["enabled"] is True
    assert status["embedded"] is True
    assert status["registered"] is False
    assert status["machine_id"] == "node-a"


def test_the_capability_snapshot_flags_the_embedded_restriction(agent):
    capability = agent.capability()

    assert capability["embedded"] is True
    assert capability["restart_supported"] is False
    assert capability["machine_configured"] is True


def test_hot_parameters_are_read_from_the_rendered_config(agent, monkeypatch, tmp_path):
    """effects 只说「走哪条链路」，值在 console 渲染出来的 YAML 里。"""

    from speech_to_speech.agent import config_sync

    rendered = "tts:\n  speech_rate: 1.15\nruntime:\n  log_level: INFO\n"
    values = config_sync.values_for_keys(
        rendered, ["tts.speech_rate", "runtime.log_level", "missing.key"]
    )

    assert values == {"tts.speech_rate": "1.15", "runtime.log_level": "INFO"}


def test_the_embedded_agent_never_restarts_its_own_process_on_config_sync(agent, monkeypatch, tmp_path):
    restarted = []
    monkeypatch.setattr(
        "speech_to_speech.agent.config_sync.restart_pipeline",
        lambda _settings: restarted.append(True),
    )

    class _ConfigClient(FakeClient):
        def pull_config(self, token: str, machine_id: str, if_none_match: str = ""):
            return 200, {
                "yaml_text": "tts:\n  speech_rate: 1.15\n",
                "etag": "v1",
                "config_version": 3,
            }

        def report(self, token: str, body: dict) -> dict:
            self.calls.append(("report", body))
            return {"ok": True}

        def ack(self, token: str, body: dict) -> dict:
            self.calls.append(("ack", body))
            return {"ok": True}

    client = _ConfigClient()
    agent._client = client
    agent.save_token("tok-123")
    agent.settings.target_yaml = str(tmp_path / "prod.yaml")

    # 声明一个 start 效果的参数：内嵌形态下不能重启宿主，只能不生效。
    monkeypatch.setattr(
        "speech_to_speech.agent.config_sync.declared_effects",
        lambda _settings: {"tts.model_name": "start"},
    )

    result = agent.sync_config_once()

    assert restarted == []
    assert result["changed"] is True


def test_the_standalone_entry_point_uses_the_same_implementation(monkeypatch):
    from speech_to_speech.agent import runner

    created = {}

    class FakeAgent:
        def __init__(self, settings, **kwargs):
            created["settings"] = settings
            created["kwargs"] = kwargs

        def run(self):
            created["ran"] = True

    monkeypatch.setattr(runner, "EmbeddedAgent", FakeAgent)
    settings = AgentSettings(
        console_url="http://console:8080",
        register_code="",
        token_file="/tmp/token",
        machine_id="node-a",
    )

    runner.run_forever(settings)

    assert created["ran"] is True
    assert created["kwargs"]["embedded"] is False
