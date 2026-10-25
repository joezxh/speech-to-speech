"""The console switches are read in exactly one place (spec §3)."""
from __future__ import annotations

from pathlib import Path

import pytest

from speech_to_speech.console_integration import (
    AUTOSTART_ENV,
    ConsoleIntegrationError,
    ConsoleOptions,
    parse_console_arguments,
    probe_base_url,
    probe_host,
    read_switch,
)


def test_switch_defaults_to_off(monkeypatch):
    monkeypatch.delenv(AUTOSTART_ENV, raising=False)
    options, remaining = parse_console_arguments(["serve", "--port", "9999"])

    assert options.autostart is False
    assert options.explicit is False
    assert remaining == ["serve", "--port", "9999"]


def test_env_turns_it_on_and_the_flag_wins(monkeypatch):
    monkeypatch.setenv(AUTOSTART_ENV, "yes")
    options, remaining = parse_console_arguments(["serve", "--with-console"])

    assert options.autostart is True
    assert options.explicit is True
    assert remaining == ["serve"]


def test_no_with_console_overrides_the_environment(monkeypatch):
    monkeypatch.setenv(AUTOSTART_ENV, "true")
    options, _ = parse_console_arguments(["serve", "--no-with-console"])

    assert options.autostart is False


def test_both_flags_together_are_rejected(monkeypatch):
    monkeypatch.delenv(AUTOSTART_ENV, raising=False)
    with pytest.raises(ConsoleIntegrationError, match="conflicts"):
        parse_console_arguments(["serve", "--with-console", "--no-with-console"])


@pytest.mark.parametrize("value", ["maybe", "2", "enabled"])
def test_illegal_boolean_names_the_variable(monkeypatch, value):
    monkeypatch.setenv(AUTOSTART_ENV, value)
    with pytest.raises(ConsoleIntegrationError, match=AUTOSTART_ENV):
        read_switch(AUTOSTART_ENV)


@pytest.mark.parametrize(("value", "expected"), [("1", True), ("ON", True), ("off", False), ("", False)])
def test_boolean_spellings(monkeypatch, value, expected):
    monkeypatch.setenv(AUTOSTART_ENV, value)
    assert read_switch(AUTOSTART_ENV) is expected


def test_home_and_static_dir_come_from_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CONSOLE_HOME", str(tmp_path / "backend"))
    monkeypatch.setenv("CONSOLE_STATIC_DIR", str(tmp_path / "dist"))
    monkeypatch.setenv(AUTOSTART_ENV, "true")
    options, _ = parse_console_arguments(["serve"])

    assert options.home == tmp_path / "backend"
    assert options.static_dir == tmp_path / "dist"


def test_validate_rejects_a_missing_backend(tmp_path):
    options = ConsoleOptions(autostart=True, home=tmp_path / "nope", static_dir=tmp_path)
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")

    with pytest.raises(ConsoleIntegrationError, match="CONSOLE_HOME"):
        options.validate()


def test_validate_rejects_a_missing_frontend_build(tmp_path):
    backend = tmp_path / "backend"
    (backend / "app").mkdir(parents=True)
    (backend / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
    options = ConsoleOptions(autostart=True, home=backend, static_dir=tmp_path / "dist")

    with pytest.raises(ConsoleIntegrationError, match="npm run build"):
        options.validate()


def test_validate_accepts_a_prepared_tree(tmp_path):
    backend = tmp_path / "backend"
    (backend / "app").mkdir(parents=True)
    (backend / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")

    ConsoleOptions(autostart=True, home=backend, static_dir=dist).validate()


def test_switch_off_never_touches_the_filesystem(tmp_path, monkeypatch):
    def explode(self):
        raise AssertionError(f"filesystem touched: {self}")

    monkeypatch.setattr(Path, "exists", explode, raising=False)
    monkeypatch.setattr(Path, "is_file", explode, raising=False)
    options = ConsoleOptions(autostart=False, home=tmp_path / "nope", static_dir=tmp_path / "nope2")

    options.validate()


@pytest.mark.parametrize(
    ("host", "dialable"),
    [("0.0.0.0", "127.0.0.1"), ("", "127.0.0.1"), ("*", "127.0.0.1"), ("::", "::1"), ("10.0.0.5", "10.0.0.5")],
)
def test_probe_host_maps_wildcards_to_something_dialable(host, dialable):
    assert probe_host(host) == dialable


def test_probe_base_url_brackets_ipv6():
    assert probe_base_url("0.0.0.0", 8765) == "http://127.0.0.1:8765"
    assert probe_base_url("::1", 9000) == "http://[::1]:9000"
