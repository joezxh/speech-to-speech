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
