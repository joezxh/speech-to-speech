"""The console switches are read in exactly one place (spec §3)."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from speech_to_speech.console_integration import (
    AUTOSTART_ENV,
    ConsoleAttachment,
    ConsoleIntegrationError,
    ConsoleOptions,
    attachment_for_runtime,
    attachment_for_server,
    load_console,
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


def _fake_module(home: Path, *, lifespan_marker=None):
    return SimpleNamespace(
        __file__=str(home / "app" / "main.py"),
        app=object(),
        lifespan=lifespan_marker or (lambda _app: None),
    )


def _prepared(tmp_path):
    backend = tmp_path / "backend"
    (backend / "app").mkdir(parents=True)
    (backend / "app" / "main.py").write_text("app = None\n", encoding="utf-8")
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html></html>", encoding="utf-8")
    return ConsoleOptions(autostart=True, home=backend, static_dir=dist)


def test_load_console_preloads_the_env_file_without_overriding_real_env(tmp_path, monkeypatch):
    options = _prepared(tmp_path)
    (options.home / ".env").write_text(
        "JWT_SECRET_KEY=from-file\nDATABASE_URL=sqlite:///dev.db\nSTATIC_DIR=/wrong\n", encoding="utf-8"
    )
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("STATIC_DIR", raising=False)
    monkeypatch.setenv("DATABASE_URL", "sqlite:///real.db")

    load_console(options, pipeline_base_url="http://127.0.0.1:8765", loader=lambda home: _fake_module(home))

    assert os.environ["JWT_SECRET_KEY"] == "from-file"
    assert os.environ["DATABASE_URL"] == "sqlite:///real.db"
    assert os.environ["STATIC_DIR"] == str(options.static_dir)


def test_load_console_forces_the_self_url_and_warns(tmp_path, monkeypatch, caplog):
    options = _prepared(tmp_path)
    monkeypatch.setenv("PIPELINE_BASE_URL", "http://127.0.0.1:8000")
    with caplog.at_level(logging.WARNING, logger="speech_to_speech.console_integration"):
        load_console(options, pipeline_base_url="http://127.0.0.1:9100", loader=lambda home: _fake_module(home))

    assert os.environ["PIPELINE_BASE_URL"] == "http://127.0.0.1:9100"
    assert "PIPELINE_BASE_URL" in caplog.text


def test_load_console_returns_a_usable_attachment(tmp_path):
    options = _prepared(tmp_path)
    marker = lambda _app: None  # noqa: E731 - identity matters, not style
    attachment = load_console(
        options,
        pipeline_base_url="http://127.0.0.1:8765",
        loader=lambda home: _fake_module(home, lifespan_marker=marker),
    )

    assert isinstance(attachment, ConsoleAttachment)
    assert attachment.lifespan is marker
    assert attachment.static_dir == options.static_dir
    assert attachment.pipeline_base_url == "http://127.0.0.1:8765"


def test_load_console_rejects_a_shadowing_app_package(tmp_path):
    options = _prepared(tmp_path)
    stray = SimpleNamespace(
        __file__="/usr/lib/python3/site-packages/app/main.py", app=object(), lifespan=lambda a: None
    )

    with pytest.raises(ConsoleIntegrationError, match="shadowing"):
        load_console(options, pipeline_base_url="http://127.0.0.1:8765", loader=lambda home: stray)


def test_load_console_reports_missing_entry_point_symbols(tmp_path):
    options = _prepared(tmp_path)
    broken = SimpleNamespace(__file__=str(options.home / "app" / "main.py"), app=None, lifespan=None)

    with pytest.raises(ConsoleIntegrationError, match="entry point"):
        load_console(options, pipeline_base_url="http://127.0.0.1:8765", loader=lambda home: broken)


def test_the_importer_names_the_fix_when_the_backend_cannot_be_imported(tmp_path):
    from speech_to_speech import console_integration

    empty = tmp_path / "empty-home"
    empty.mkdir()

    with pytest.raises(ConsoleIntegrationError) as excinfo:
        console_integration._import_console_main(empty)

    message = str(excinfo.value)
    assert "requirements.txt" in message
    assert "JWT_SECRET_KEY" in message


def test_attachment_is_none_when_the_switch_is_off(tmp_path):
    options = ConsoleOptions(autostart=False, home=tmp_path / "nope", static_dir=tmp_path / "nope2")

    assert attachment_for_server(options, "127.0.0.1", 8765, loader=lambda home: _fake_module(home)) is None


def test_attachment_for_server_uses_a_dialable_self_url(tmp_path):
    options = _prepared(tmp_path)
    attachment = attachment_for_server(options, "0.0.0.0", 9100, loader=lambda home: _fake_module(home))

    assert attachment.pipeline_base_url == "http://127.0.0.1:9100"


def test_attachment_for_runtime_reads_the_server_block(tmp_path):
    options = _prepared(tmp_path)

    attachment = attachment_for_runtime(
        options, {"server": {"host": "0.0.0.0", "port": 9200}}, loader=lambda home: _fake_module(home)
    )

    assert attachment.pipeline_base_url == "http://127.0.0.1:9200"


def test_attachment_for_runtime_falls_back_to_the_defaults(tmp_path):
    options = _prepared(tmp_path)

    attachment = attachment_for_runtime(options, {}, loader=lambda home: _fake_module(home))

    assert attachment.pipeline_base_url == "http://127.0.0.1:8765"


def test_the_off_switch_logs_one_line(tmp_path, caplog):
    options = ConsoleOptions(autostart=False, home=tmp_path / "nope", static_dir=tmp_path / "nope2")

    with caplog.at_level(logging.INFO, logger="speech_to_speech.console_integration"):
        attachment_for_server(options, "127.0.0.1", 8765, loader=lambda home: _fake_module(home))

    assert [record.getMessage() for record in caplog.records] == ["console: integrated=false"]


def test_the_on_switch_logs_where_things_mounted(tmp_path, caplog):
    options = _prepared(tmp_path)

    with caplog.at_level(logging.INFO, logger="speech_to_speech.console_integration"):
        attachment_for_server(options, "0.0.0.0", 9100, loader=lambda home: _fake_module(home))

    messages = [record.getMessage() for record in caplog.records]
    assert (
        "console: integrated=true | http://127.0.0.1:9100  ui=/  console=/console  api=/api  realtime=/v1/realtime"
        in messages
    )
    assert any(f"static={options.static_dir}" in message for message in messages)
    assert "console: PIPELINE_BASE_URL=http://127.0.0.1:9100 (self)" in messages
