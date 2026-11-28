"""机器端 agent 命令执行器：真动作 + 真回执（TDD RED → GREEN）。"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from speech_to_speech.agent import commands


class FakeClient:
    def __init__(self, pulled=None):
        self.pulled = pulled or []
        self.calls = []

    def pull_commands(self, token, limit=10):
        self.calls.append(("pull", token, limit))
        return self.pulled

    def report_command(self, token, command_id, *, ok, result, error=""):
        self.calls.append(("report", command_id, ok, result, error))

    def set_instance_drain(self, token, drain):
        self.calls.append(("drain", drain))
        return {"instance_ids": ["pipe-a"], "drain_requested": drain}

    def probe_instances(self, token):
        self.calls.append(("probe",))
        return {"statuses": {"pipe-a": "online"}}


@pytest.fixture
def settings():
    return SimpleNamespace(
        declaration_file="/nonexistent/agent.yaml",
        supervisor_program="pipeline",
        supervisor_socket="/nonexistent/supervisor.sock",
    )


def test_drain_command_sets_drain_on_console_for_this_machine(settings):
    client = FakeClient()
    ok, result, error = commands.execute(
        {"kind": "drain", "payload": {}}, settings, client, "token"
    )
    assert (ok, error) == (True, "")
    assert ("drain", True) in client.calls
    assert result["instance_ids"] == ["pipe-a"]


def test_reboot_command_restarts_pipeline(settings, monkeypatch):
    restarted = []
    monkeypatch.setattr(
        commands.config_sync, "restart_pipeline", lambda cfg: restarted.append(cfg.program_name)
    )
    settings.program_name = settings.supervisor_program
    client = FakeClient()
    ok, result, _ = commands.execute({"kind": "reboot", "payload": {}}, settings, client, "token")
    assert ok and restarted == ["pipeline"]
    assert result == {"restarted": True}


def test_health_check_uses_declared_path_and_reports_reachable(settings, monkeypatch):
    workload = {
        "kind": "asr", "model": "qwen3-asr", "port": 8011, "listen": "127.0.0.1:8011",
        "health_path": "/health", "public_addr": "10.0.0.9:8011",
    }
    monkeypatch.setattr(commands, "collect_workloads", lambda cfg: [workload])
    seen = {}

    def fake_get(url, timeout):
        seen["url"] = url
        seen["timeout"] = timeout
        return SimpleNamespace(status_code=200, text="ok")

    monkeypatch.setattr(commands.httpx, "get", fake_get)
    ok, result, _ = commands.execute(
        {"kind": "health_check", "payload": {"service_id": "asr:8011"}},
        settings,
        FakeClient(),
        "token",
    )
    assert ok
    assert seen["url"] == "http://127.0.0.1:8011/health"
    assert result["status_code"] == 200


def test_health_check_of_unknown_service_reports_unknown_not_fabricated(settings, monkeypatch):
    monkeypatch.setattr(commands, "collect_workloads", lambda cfg: [])
    ok, result, _ = commands.execute(
        {"kind": "health_check", "payload": {"service_id": "ghost"}},
        settings,
        FakeClient(),
        "token",
    )
    assert not ok
    assert result["reachable"] is None
    assert result["reason"] == "service_not_found"


def test_poll_and_run_reports_each_command_even_when_execution_fails(settings, monkeypatch):
    monkeypatch.setattr(
        commands, "execute", lambda *args: (False, {"reason": "failed"}, "boom")
    )
    client = FakeClient(
        pulled=[{"command_id": "c1", "kind": "reboot", "payload": {}}]
    )
    assert commands.poll_and_run(client, "token", settings) == 1
    assert client.calls[-1] == ("report", "c1", False, {"reason": "failed"}, "boom")


def test_config_restart_syncs_config_then_restarts(settings, monkeypatch):
    steps = []

    def _sync(client, token, cfg):
        steps.append("sync")
        return {"configVersion": 7}

    monkeypatch.setattr(commands.config_sync, "sync_config", _sync)
    monkeypatch.setattr(
        commands.config_sync, "restart_pipeline", lambda cfg: steps.append("restart")
    )
    ok, result, error = commands.execute(
        {"kind": "config_restart", "payload": {}}, settings, FakeClient(), "token"
    )
    assert (ok, error) == (True, "")
    assert steps == ["sync", "restart"]
    assert result["config"]["configVersion"] == 7
    assert result["restart"]["restarted"] is True


def test_config_restart_reports_failed_stage(settings, monkeypatch):
    def _failure(client, token, cfg):
        raise RuntimeError("config pull failed")

    monkeypatch.setattr(commands.config_sync, "sync_config", _failure)
    restarted = []
    monkeypatch.setattr(
        commands.config_sync, "restart_pipeline", lambda cfg: restarted.append(True)
    )
    ok, _, error = commands.execute(
        {"kind": "config_restart", "payload": {}}, settings, FakeClient(), "token"
    )
    assert ok is False
    assert "config stage failed" in error
    assert "config pull failed" in error
    assert restarted == []


def test_model_reload_normalizes_modules_and_reports_accepted(settings):
    submitted = []

    def provider(request, on_progress):
        submitted.append(request)
        return "task-1"

    command = {
        "command_id": "c-reload",
        "kind": "model_reload",
        "payload": {
            "modules": ["tts", "asr", "tts"],
            "scope": "all",
            "drain": False,
            "reason": "console",
        },
    }
    ok, result, error = commands.execute(
        command, settings, FakeClient(), "token", reload_provider=provider
    )

    assert (ok, error) == (True, "")
    assert result["status"] == "accepted"
    assert result["stage"] == "queued"
    assert result["taskId"] == "task-1"
    assert submitted == [
        {
            "modules": ["asr", "tts"],
            "scope": "all",
            "unit_index": None,
            "drain": False,
            "drain_timeout_ms": 5000,
            "config_version": "",
            "reason": "console",
        }
    ]


@pytest.mark.parametrize(
    "modules",
    [
        [],
        ["gpu"],
        ["asr", "bogus"],
        "asr",
        None,
    ],
)
def test_model_reload_rejects_invalid_modules_without_calling_provider(settings, modules):
    calls = []
    command = {"kind": "model_reload", "payload": {"modules": modules}}

    ok, result, error = commands.execute(
        command,
        settings,
        FakeClient(),
        "token",
        reload_provider=lambda request, on_progress: calls.append(request),
    )

    assert ok is False
    assert result["stage"] == "validation"
    assert "modules" in error
    assert calls == []


def test_model_reload_uses_normalized_unit_index_without_drain(settings):
    seen = []
    command = {
        "kind": "model_reload",
        "payload": {
            "modules": ["llm"],
            "scope": "unit",
            "unit_index": 2,
            "drain_timeout_ms": 1500,
        },
    }

    ok, _, error = commands.execute(
        command,
        settings,
        FakeClient(),
        "token",
        reload_provider=lambda request, on_progress: seen.append(request),
    )

    assert (ok, error) == (True, "")
    assert seen[0]["unit_index"] == 2
    assert seen[0]["drain_timeout_ms"] == 1500


def test_model_reload_without_provider_degrades_to_config_restart(settings, monkeypatch):
    steps = []
    monkeypatch.setattr(
        commands.config_sync, "sync_config", lambda client, token, cfg: steps.append("sync") or {}
    )
    monkeypatch.setattr(
        commands.config_sync, "restart_pipeline", lambda cfg: steps.append("restart")
    )

    ok, result, error = commands.execute(
        {"kind": "model_reload", "payload": {"modules": ["asr"]}},
        settings,
        FakeClient(),
        "token",
    )

    assert (ok, error) == (True, "")
    assert steps == ["sync", "restart"]
    assert result["degraded"] == "config_restart"


def test_model_reload_progress_is_reported_back_to_console(settings):
    captured = {}

    def provider(request, on_progress):
        captured["on_progress"] = on_progress
        return "task-p"

    client = FakeClient()
    ok, _, error = commands.execute(
        {
            "command_id": "c-p",
            "kind": "model_reload",
            "payload": {"modules": ["asr"], "scope": "all"},
        },
        settings,
        client,
        "token",
        reload_provider=provider,
    )

    assert (ok, error) == (True, "")
    captured["on_progress"](
        {"status": "succeeded", "reloadedModules": ["asr"], "targetUnits": [0], "ready": True}
    )
    assert ("report", "c-p", True, {"status": "succeeded", "reloadedModules": ["asr"], "targetUnits": [0], "ready": True}, "") in client.calls


def test_model_reload_without_provider_in_embedded_mode_is_rejected(settings):
    ok, result, error = commands.execute(
        {"kind": "model_reload", "payload": {"modules": ["tts"]}},
        settings,
        FakeClient(),
        "token",
        allow_restart=False,
    )

    assert ok is False
    assert result["reason"] == "not_supported_in_embedded_mode"
    assert "coordinator" in error


def test_poll_and_run_keeps_reporting_after_a_report_failure(settings, monkeypatch):
    monkeypatch.setattr(commands, "execute", lambda *args: (True, {"status": "accepted"}, ""))

    class FlakyClient(FakeClient):
        def report_command(self, token, command_id, *, ok, result, error=""):
            self.calls.append(("report", command_id, ok, result, error))
            if command_id == "c1":
                raise RuntimeError("console down")

    client = FlakyClient(
        pulled=[
            {"command_id": "c1", "kind": "reboot", "payload": {}},
            {"command_id": "c2", "kind": "reboot", "payload": {}},
        ]
    )

    receipts = commands.poll_and_run_detailed(client, "token", settings)

    assert len(receipts) == 2
    assert [call[1] for call in client.calls if call[0] == "report"] == ["c1", "c2"]
