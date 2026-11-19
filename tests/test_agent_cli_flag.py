"""The agent switches are read in exactly one place, and only 'serve' hosts them."""

from __future__ import annotations

import pytest

from speech_to_speech.agent_integration import (
    AUTOSTART_ENV,
    AgentIntegrationError,
    AgentOptions,
    build_embedded_agent,
    parse_agent_arguments,
    read_switch,
    validate_agent_options,
)


def test_switch_defaults_to_off(monkeypatch):
    monkeypatch.delenv(AUTOSTART_ENV, raising=False)
    options, remaining = parse_agent_arguments(["serve", "--port", "9999"])

    assert options.autostart is False
    assert options.explicit is False
    assert remaining == ["serve", "--port", "9999"]


def test_env_turns_it_on_and_the_flag_wins(monkeypatch):
    monkeypatch.setenv(AUTOSTART_ENV, "yes")
    options, remaining = parse_agent_arguments(["serve", "--with-agent"])

    assert options.autostart is True
    assert options.explicit is True
    assert remaining == ["serve"]


def test_no_with_agent_overrides_the_environment(monkeypatch):
    monkeypatch.setenv(AUTOSTART_ENV, "true")
    options, _ = parse_agent_arguments(["serve", "--no-with-agent"])

    assert options.autostart is False


def test_both_flags_together_are_rejected(monkeypatch):
    monkeypatch.delenv(AUTOSTART_ENV, raising=False)
    with pytest.raises(AgentIntegrationError, match="conflicts"):
        parse_agent_arguments(["serve", "--with-agent", "--no-with-agent"])


@pytest.mark.parametrize("value", ["maybe", "2", "enabled"])
def test_illegal_boolean_names_the_variable(monkeypatch, value):
    monkeypatch.setenv(AUTOSTART_ENV, value)
    with pytest.raises(AgentIntegrationError, match=AUTOSTART_ENV):
        read_switch(AUTOSTART_ENV)


@pytest.mark.parametrize(("value", "expected"), [("1", True), ("ON", True), ("off", False), ("", False)])
def test_boolean_spellings(monkeypatch, value, expected):
    monkeypatch.setenv(AUTOSTART_ENV, value)
    assert read_switch(AUTOSTART_ENV) is expected


def test_the_switch_is_stripped_before_the_file_mode_sees_it(monkeypatch):
    """`-f` mode rejects unknown options outright, so the flag must be gone by then."""

    monkeypatch.delenv(AUTOSTART_ENV, raising=False)
    _, remaining = parse_agent_arguments(["serve", "-f", "prod.yaml", "--with-agent"])

    assert "--with-agent" not in remaining
    assert remaining == ["serve", "-f", "prod.yaml"]


def test_validation_is_a_no_op_when_the_switch_is_off(monkeypatch):
    monkeypatch.delenv("S2S_AGENT_CONSOLE_URL", raising=False)
    monkeypatch.delenv("S2S_AGENT_MACHINE_ID", raising=False)

    validate_agent_options(AgentOptions(autostart=False))
    validate_agent_options(None)


def test_validation_names_the_missing_variables(monkeypatch):
    monkeypatch.setenv(AUTOSTART_ENV, "true")
    monkeypatch.delenv("S2S_AGENT_CONSOLE_URL", raising=False)
    monkeypatch.setenv("S2S_AGENT_MACHINE_ID", "node-a")

    with pytest.raises(AgentIntegrationError, match="S2S_AGENT_CONSOLE_URL"):
        validate_agent_options(AgentOptions(autostart=True))

    monkeypatch.setenv("S2S_AGENT_CONSOLE_URL", "http://console:8080")
    validate_agent_options(AgentOptions(autostart=True))


def test_building_an_agent_requires_the_switch(monkeypatch):
    monkeypatch.delenv(AUTOSTART_ENV, raising=False)
    with pytest.raises(AgentIntegrationError):
        build_embedded_agent(AgentOptions(autostart=False))


def test_building_an_agent_shares_the_given_stop_event(monkeypatch, tmp_path):
    import threading

    monkeypatch.setenv(AUTOSTART_ENV, "true")
    monkeypatch.setenv("S2S_AGENT_CONSOLE_URL", "http://console:8080")
    monkeypatch.setenv("S2S_AGENT_MACHINE_ID", "node-a")
    monkeypatch.setenv("S2S_AGENT_TOKEN_FILE", str(tmp_path / "token"))
    event = threading.Event()

    agent = build_embedded_agent(AgentOptions(autostart=True), stop_event=event)

    assert agent.stop_event is event
    assert agent.embedded is True
