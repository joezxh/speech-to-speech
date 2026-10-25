"""Both runtime paths must hand the attachment to the server, and fail loudly (spec §5.1-5.3)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from speech_to_speech import s2s_pipeline as pipeline_module
from speech_to_speech.console_integration import ConsoleOptions, StartupError


def _args(host="127.0.0.1", port=9999):
    return SimpleNamespace(
        module_kwargs=SimpleNamespace(num_pipelines=1, enable_llm_proxy=False, log_level="info", log_transcripts=False),
        realtime_server_kwargs=SimpleNamespace(host=host, port=port),
        local_audio_kwargs=SimpleNamespace(verbose=False, local_audio_print_json=False),
        vad_handler_kwargs=SimpleNamespace(),
        stt_backend=SimpleNamespace(),
        llm_backend=SimpleNamespace(),
        tts_backend=SimpleNamespace(),
    )


def test_build_pipeline_hands_the_attachment_to_the_server(monkeypatch):
    captured = {}

    class FakeServer:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.handlers = []

        def run(self):  # pragma: no cover - never started here
            pass

    monkeypatch.setattr("speech_to_speech.api.openai_realtime.server.RealtimeServer", FakeServer)
    monkeypatch.setattr(pipeline_module, "_build_pipeline_unit", lambda **kwargs: SimpleNamespace(handlers=[]))
    attachment = SimpleNamespace()

    pipeline_module.build_pipeline(_args(), stop_event=None, console_attachment=attachment)

    assert captured["console_attachment"] is attachment


def test_build_pipeline_defaults_to_no_attachment(monkeypatch):
    captured = {}

    class FakeServer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("speech_to_speech.api.openai_realtime.server.RealtimeServer", FakeServer)
    monkeypatch.setattr(pipeline_module, "_build_pipeline_unit", lambda **kwargs: SimpleNamespace(handlers=[]))

    pipeline_module.build_pipeline(_args(), stop_event=None)

    assert captured["console_attachment"] is None


def _patch_run_prerequisites(monkeypatch, handlers):
    class FakeManager:
        def __init__(self, manager_handlers):
            self.handlers = manager_handlers

        def start(self):
            pass

        def wait(self):
            pass

        def stop(self):
            pass

    monkeypatch.setattr(pipeline_module, "prepare_all_args", lambda _args: None)
    monkeypatch.setattr(pipeline_module, "set_log_transcripts", lambda _v: None)
    monkeypatch.setattr(pipeline_module, "warn_if_log_transcripts_enabled", lambda: None)
    monkeypatch.setattr(pipeline_module, "signal", SimpleNamespace(SIGINT=2, SIGTERM=15, signal=lambda *_a: None))
    monkeypatch.setattr(pipeline_module, "build_pipeline", lambda args, event, **kwargs: FakeManager(handlers))


def test_a_handler_reporting_a_failed_startup_raises(monkeypatch):
    _patch_run_prerequisites(monkeypatch, [SimpleNamespace(startup_failed=True)])

    with pytest.raises(StartupError):
        pipeline_module._run_parsed_pipeline_command("serve", _args())


def test_a_clean_run_does_not_raise(monkeypatch):
    _patch_run_prerequisites(monkeypatch, [SimpleNamespace(startup_failed=False)])

    pipeline_module._run_parsed_pipeline_command("serve", _args())


def test_run_pipeline_command_hands_the_options_to_the_parsed_command(monkeypatch):
    seen = {}
    options = ConsoleOptions(autostart=True, home=None, static_dir=None)

    monkeypatch.setattr(pipeline_module, "parse_arguments", lambda argv, command: _args(port=9100))
    monkeypatch.setattr(
        pipeline_module,
        "_run_parsed_pipeline_command",
        lambda command, args, **kw: seen.update(options=kw.get("console_options")),
    )

    pipeline_module.run_pipeline_command("serve", [], console_options=options)

    assert seen == {"options": options}


def test_the_console_is_resolved_from_the_server_address_and_handed_to_the_builder(monkeypatch):
    seen = {}
    options = ConsoleOptions(autostart=True, home=None, static_dir=None)

    class FakeManager:
        handlers = []

        def start(self):
            pass

        def wait(self):
            pass

        def stop(self):
            pass

    def fake_build(args, event, **kwargs):
        seen["attachment"] = kwargs.get("console_attachment")
        return FakeManager()

    monkeypatch.setattr(
        pipeline_module,
        "attachment_for_server",
        lambda opts, host, port, **kw: seen.update(host=host, port=port, options=opts) or "sentinel",
    )
    monkeypatch.setattr(pipeline_module, "prepare_all_args", lambda _args: None)
    monkeypatch.setattr(pipeline_module, "set_log_transcripts", lambda _v: None)
    monkeypatch.setattr(pipeline_module, "warn_if_log_transcripts_enabled", lambda: None)
    monkeypatch.setattr(pipeline_module, "signal", SimpleNamespace(SIGINT=2, SIGTERM=15, signal=lambda *_a: None))
    monkeypatch.setattr(pipeline_module, "build_pipeline", fake_build)

    pipeline_module._run_parsed_pipeline_command("serve", _args(port=9100), console_options=options)

    assert seen == {
        "host": "127.0.0.1",
        "port": 9100,
        "options": options,
        "attachment": "sentinel",
    }


def test_configured_runtime_forwards_the_attachment(monkeypatch):
    from speech_to_speech import configured_runtime as runtime_module

    captured = {}

    class FakeServer:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("speech_to_speech.api.openai_realtime.server.RealtimeServer", FakeServer)
    monkeypatch.setattr(runtime_module, "_validate_counts", lambda config: None)
    monkeypatch.setattr(runtime_module, "_adapt", lambda config: {"primary": _args()})
    monkeypatch.setattr(
        runtime_module,
        "_build_runtime",
        lambda arguments, stop_event: SimpleNamespace(
            _events=[None], pools={"primary": []}, server=None, client=None, _resources=[], _handlers=[]
        ),
    )
    attachment = SimpleNamespace()
    # build_configured_server itself checks len(config.pipelines) != 1.
    config = SimpleNamespace(pipelines={"primary": object()})

    runtime_module.build_configured_server(config, None, console_attachment=attachment)

    assert captured["console_attachment"] is attachment


def _patch_configured_command(monkeypatch, server, wait_error=None):
    """Stand in for the model-loading construction so only the wiring is exercised."""
    from speech_to_speech import configured_runtime as runtime_module

    seen = {}

    class FakeRuntime:
        server = None

        def start(self):
            pass

        def wait(self):
            # ConfiguredRuntime.stop() clears its server reference before returning.
            self.server = None
            if wait_error is not None:
                raise wait_error

        def stop(self):
            pass

    FakeRuntime.server = server

    def fake_build(config, stop_event, **kwargs):
        seen.update(kwargs)
        return FakeRuntime()

    monkeypatch.setattr(runtime_module, "attachment_for_runtime", lambda options, runtime, **kw: ("resolved", options))
    monkeypatch.setattr(runtime_module, "build_configured_server", fake_build)
    monkeypatch.setattr(runtime_module, "signal", SimpleNamespace(SIGINT=2, SIGTERM=15, signal=lambda *_: None, getsignal=lambda _s: None))
    return seen


def test_configured_command_resolves_the_attachment_from_the_runtime_block(monkeypatch):
    from speech_to_speech import configured_runtime as runtime_module

    seen = _patch_configured_command(monkeypatch, SimpleNamespace(startup_failed=False))
    options = ConsoleOptions(autostart=True, home=None, static_dir=None)

    runtime_module._run_configured_command(
        "serve", SimpleNamespace(runtime={}, client=None), console_options=options
    )

    assert seen["console_attachment"] == ("resolved", options)


def test_configured_command_raises_when_the_server_never_bound(monkeypatch):
    from speech_to_speech import configured_runtime as runtime_module

    _patch_configured_command(monkeypatch, SimpleNamespace(startup_failed=True))

    with pytest.raises(StartupError):
        runtime_module._run_configured_command("serve", SimpleNamespace(runtime={}, client=None))


def test_a_worker_failure_still_names_the_bind_when_the_server_never_bound(monkeypatch):
    from speech_to_speech import configured_runtime as runtime_module

    # The dying server thread records the bind failure but raises from wait(); the
    # caller must still hear about the port rather than a generic worker error.
    _patch_configured_command(
        monkeypatch,
        SimpleNamespace(startup_failed=True),
        wait_error=runtime_module.ConfiguredRuntimeError("A configured worker, listener, or client failed."),
    )

    with pytest.raises(StartupError):
        runtime_module._run_configured_command("serve", SimpleNamespace(runtime={}, client=None))


def test_a_worker_failure_without_a_bind_failure_is_not_relabelled(monkeypatch):
    from speech_to_speech import configured_runtime as runtime_module

    _patch_configured_command(
        monkeypatch,
        SimpleNamespace(startup_failed=False),
        wait_error=runtime_module.ConfiguredRuntimeError("A configured worker, listener, or client failed."),
    )

    with pytest.raises(runtime_module.ConfiguredRuntimeError):
        runtime_module._run_configured_command("serve", SimpleNamespace(runtime={}, client=None))
