"""The /v1/agent/* endpoints: always published, read/write separated, fail closed."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from speech_to_speech.agent.embedded import AgentBusyError, AgentNotRegisteredError
from speech_to_speech.api.openai_realtime.agent_routes import (
    CAPABILITY_PATH,
    COMMANDS_PATH,
    COMMANDS_POLL_PATH,
    CONFIG_SYNC_PATH,
    DEPLOYMENT_PATH,
    DRAIN_PATH,
    HEARTBEAT_PATH,
    LOGS_PATH,
    METRICS_PATH,
    REGISTER_PATH,
    STATUS_PATH,
    USAGE_PATH,
    WORKLOADS_PATH,
    mount_agent,
)

ADMIN_TOKEN = "s2s-admin-token"


class FakeAgent:
    """Stands in for the embedded agent; records the actions it was asked to run."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.raises: Exception | None = None

    def _record(self, name: str, *args):
        self.calls.append((name, *args))
        if self.raises is not None:
            raise self.raises
        return {"ok": True}

    def status(self) -> dict:
        return {"enabled": True, "running": True, "registered": True, "ticks": 3}

    def capability(self) -> dict:
        return {"agent_version": "0.0.0", "embedded": True, "restart_supported": False}

    def collect_workloads(self) -> list[dict]:
        return [{"kind": "pipeline", "port": 8765}]

    def collect_metrics(self) -> dict:
        return {"cpu_pct": 3.5}

    def collect_deployment(self) -> dict:
        return {"runtime": {}, "declared": {}}

    def collect_logs(self) -> list[dict]:
        return [{"source": "stdout", "lines": ["hello"]}]

    def heartbeat_once(self) -> dict:
        return self._record("heartbeat")

    def sync_config_once(self) -> dict:
        return self._record("config_sync")

    def poll_commands_once(self, *, limit: int = 10) -> dict:
        return self._record("commands_poll", limit)

    def run_command_once(self, kind: str, payload: dict | None = None) -> dict:
        return self._record("command", kind, payload)

    def register_once(self) -> dict:
        return self._record("register")

    def set_drain(self, drain: bool) -> dict:
        return self._record("drain", drain)


@pytest.fixture
def fake_pool():
    usage = {"input_tokens": 5, "output_tokens": 7, "responses_completed": 2, "turns": 1}
    return [SimpleNamespace(service=SimpleNamespace(get_usage=lambda: dict(usage)))]


def _client(agent, pool=None) -> TestClient:
    app = FastAPI()
    mount_agent(app, agent, pool or [])
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return _client(FakeAgent())


@pytest.fixture
def admin_client(monkeypatch) -> TestClient:
    monkeypatch.setenv("S2S_ADMIN_TOKEN", ADMIN_TOKEN)
    return _client(FakeAgent())


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {ADMIN_TOKEN}"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", STATUS_PATH),
        ("get", CAPABILITY_PATH),
        ("get", WORKLOADS_PATH),
        ("get", METRICS_PATH),
        ("get", DEPLOYMENT_PATH),
        ("get", USAGE_PATH),
        ("get", LOGS_PATH),
        ("post", HEARTBEAT_PATH),
        ("post", CONFIG_SYNC_PATH),
        ("post", COMMANDS_POLL_PATH),
        ("post", COMMANDS_PATH),
        ("post", REGISTER_PATH),
        ("post", DRAIN_PATH),
    ],
)
def test_every_endpoint_answers_when_the_agent_is_not_enabled(method, path):
    response = getattr(_client(None), method)(path)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "agent_disabled"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", STATUS_PATH),
        ("get", CAPABILITY_PATH),
        ("get", WORKLOADS_PATH),
        ("get", METRICS_PATH),
        ("get", DEPLOYMENT_PATH),
        ("get", USAGE_PATH),
    ],
)
def test_read_only_endpoints_need_no_token(client, method, path):
    response = getattr(client, method)(path)

    assert response.status_code == 200


def test_the_status_endpoint_reports_the_agent_snapshot(client):
    body = client.get(STATUS_PATH).json()

    assert body["enabled"] is True
    assert body["ticks"] == 3


def test_the_usage_endpoint_mirrors_the_pool_counters(fake_pool):
    response = _client(FakeAgent(), fake_pool).get(USAGE_PATH)

    assert response.status_code == 200
    body = response.json()
    assert body["input_tokens"] == 5
    assert body["output_tokens"] == 7
    assert body["responses_completed"] == 2


@pytest.mark.parametrize(
    ("method", "path", "kwargs"),
    [
        ("post", HEARTBEAT_PATH, {}),
        ("post", CONFIG_SYNC_PATH, {}),
        ("post", COMMANDS_POLL_PATH, {}),
        ("post", COMMANDS_PATH, {"json": {"kind": "health_check"}}),
        ("post", REGISTER_PATH, {}),
        ("post", DRAIN_PATH, {"json": {"drain": True}}),
        ("get", LOGS_PATH, {}),
    ],
)
def test_action_endpoints_refuse_a_missing_token(admin_client, method, path, kwargs):
    response = getattr(admin_client, method)(path, **kwargs)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_action_endpoints_refuse_a_wrong_token(admin_client):
    response = admin_client.post(HEARTBEAT_PATH, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_action_endpoints_fail_closed_without_a_configured_token(monkeypatch):
    monkeypatch.delenv("S2S_ADMIN_TOKEN", raising=False)
    response = _client(FakeAgent()).post(HEARTBEAT_PATH)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "admin_disabled"


def test_the_heartbeat_endpoint_reaches_the_agent(admin_client):
    response = admin_client.post(HEARTBEAT_PATH, headers=_auth())

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_the_command_endpoint_forwards_the_kind_and_payload(admin_client):
    response = admin_client.post(
        COMMANDS_PATH,
        headers=_auth(),
        json={"kind": "health_check", "payload": {"service_id": "pipeline"}},
    )

    assert response.status_code == 200


def test_an_unknown_command_kind_is_rejected(admin_client):
    response = admin_client.post(COMMANDS_PATH, headers=_auth(), json={"kind": "rm -rf"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request_error"


def test_the_command_poll_limit_is_bounded(admin_client):
    response = admin_client.post(f"{COMMANDS_POLL_PATH}?limit=9999", headers=_auth())

    assert response.status_code == 200


def test_a_busy_agent_is_reported_as_a_conflict(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", ADMIN_TOKEN)
    agent = FakeAgent()
    agent.raises = AgentBusyError("another agent action is already running")

    response = _client(agent).post(HEARTBEAT_PATH, headers=_auth())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_busy"


def test_an_unregistered_agent_is_reported_as_a_conflict(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", ADMIN_TOKEN)
    agent = FakeAgent()
    agent.raises = AgentNotRegisteredError("no machine token on disk")

    response = _client(agent).post(REGISTER_PATH, headers=_auth())

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "agent_not_registered"


def test_an_unreachable_console_is_reported_as_a_bad_gateway(monkeypatch):
    monkeypatch.setenv("S2S_ADMIN_TOKEN", ADMIN_TOKEN)
    agent = FakeAgent()
    agent.raises = httpx.ConnectError("connection refused")

    response = _client(agent).post(HEARTBEAT_PATH, headers=_auth())

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "console_unreachable"


def test_the_endpoints_are_documented_in_the_openapi_schema(client):
    schema = client.get("/openapi.json").json()

    agent_paths = {path for path in schema["paths"] if path.startswith("/v1/agent/")}
    assert agent_paths == {
        STATUS_PATH,
        CAPABILITY_PATH,
        WORKLOADS_PATH,
        METRICS_PATH,
        DEPLOYMENT_PATH,
        USAGE_PATH,
        HEARTBEAT_PATH,
        CONFIG_SYNC_PATH,
        COMMANDS_POLL_PATH,
        COMMANDS_PATH,
        REGISTER_PATH,
        DRAIN_PATH,
        LOGS_PATH,
    }
    operation = schema["paths"][STATUS_PATH]["get"]
    assert operation["tags"] == ["运维代理"]
    assert operation["summary"]
    assert "404" not in operation["responses"]


def test_the_documented_parameters_match_the_runtime_contract(client):
    schema = client.get("/openapi.json").json()

    poll = schema["paths"][COMMANDS_POLL_PATH]["post"]
    assert any(parameter["name"] == "limit" for parameter in poll["parameters"])

    command = schema["paths"][COMMANDS_PATH]["post"]
    body = command["requestBody"]["content"]["application/json"]["schema"]
    assert set(body["properties"]) == {"kind", "payload"}
    assert body["properties"]["kind"]["enum"] == [
        "drain",
        "resume",
        "reboot",
        "config_restart",
        "recover",
        "health_check",
    ]
