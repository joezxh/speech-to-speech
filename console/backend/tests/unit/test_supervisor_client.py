from __future__ import annotations

import xmlrpc.client

import pytest

from app.config import console
from app.services import supervisor_client


def _fake(monkeypatch, supervisor):
    class _Proxy:
        pass

    proxy = _Proxy()
    proxy.supervisor = supervisor
    monkeypatch.setattr(supervisor_client, "_proxy", lambda: proxy)


def test_available_reports_a_missing_socket(monkeypatch, tmp_path):
    monkeypatch.setattr(console, "supervisor_socket", str(tmp_path / "nope.sock"))
    ok, detail = supervisor_client.available()
    assert ok is False
    assert "nope.sock" in detail


def test_restart_stops_waiting_then_starts(monkeypatch):
    calls: list[tuple] = []

    class _Supervisor:
        def stopProcess(self, name, wait):
            calls.append(("stop", name, wait))

        def startProcess(self, name):
            calls.append(("start", name))

    _fake(monkeypatch, _Supervisor())
    supervisor_client.restart("pipeline")
    # `wait=True` matters: without it the start can race the stop and fail.
    assert calls == [("stop", "pipeline", True), ("start", "pipeline")]


def test_a_refused_restart_is_a_supervisor_error(monkeypatch):
    class _Supervisor:
        def stopProcess(self, name, wait):
            raise xmlrpc.client.Fault(90, "RUNNING")

    _fake(monkeypatch, _Supervisor())
    with pytest.raises(supervisor_client.SupervisorError, match="RUNNING"):
        supervisor_client.restart("pipeline")


def test_the_program_name_comes_from_settings_not_from_the_caller(monkeypatch):
    monkeypatch.setattr(console, "supervisor_program", "pipeline")
    assert supervisor_client.program() == "pipeline"
