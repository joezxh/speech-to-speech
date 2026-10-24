from __future__ import annotations

import pytest

from app.config import console
from app.core.errors import ApiError
from app.services import process_probe, restart_runner, supervisor_client


def test_a_dead_socket_is_a_502(monkeypatch):
    monkeypatch.setattr(supervisor_client, "available", lambda: (False, "no socket"))
    with pytest.raises(ApiError) as caught:
        restart_runner.restart()
    assert caught.value.code == "restart_unavailable"
    assert caught.value.status == 502


def test_noop_mode_skips_the_restart_but_not_the_wait(monkeypatch):
    monkeypatch.setattr(console, "restart_mode", "noop")
    monkeypatch.setattr(supervisor_client, "restart", lambda name: pytest.fail("must not restart"))
    seen = []
    monkeypatch.setattr(restart_runner, "wait_running", lambda timeout=60.0: seen.append(timeout))
    restart_runner.restart()
    # 开发态不真重启，但探活必须照常跑，否则开发时看不到「重启后不健康」。
    assert seen == [60.0]


def test_wait_running_gives_up_after_the_timeout(monkeypatch):
    monkeypatch.setattr(
        process_probe,
        "get_probe",
        lambda: type(
            "_Probe",
            (),
            {"state": lambda self, name: process_probe.ProcessInfo(name=name, running=False)},
        )(),
    )
    with pytest.raises(ApiError) as caught:
        restart_runner.wait_running(timeout=0.2, interval=0.05)
    assert caught.value.code == "restart_unavailable"
