from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Any, Literal

from speech_to_speech.api.openai_realtime.audio_client import (
    RealtimeAudioClientConfig,
    load_realtime_tool_module,
    run_realtime_audio_client,
)
from speech_to_speech.console_integration import (
    AUTOSTART_ENV,
    ConsoleIntegrationError,
    ConsoleOptions,
    StartupError,
    parse_console_arguments,
)
from speech_to_speech.pipeline.transcript_logging import (
    set_log_transcripts,
    warn_if_log_transcripts_enabled,
)

Command = Literal["serve", "talk", "local", "models"]

_LEGACY_MODE_COMMANDS: dict[str, Command] = {
    "realtime": "serve",
    "local": "local",
}

CONSOLE_HELP = """
Console integration (same process, same port):
  --with-console        Merge the console backend into this process and publish
                        the console frontend on the same port. Off by default.
  --no-with-console     Override CONSOLE_AUTOSTART for this run.

Environment:
  CONSOLE_AUTOSTART     true/false, same as --with-console. Default: false.
  CONSOLE_HOME          Directory containing app/main.py. Default: <repo>/console/backend
  CONSOLE_STATIC_DIR    Built frontend directory. Default: <repo>/console/frontend/dist

With the switch on, "/" and "/console/*" serve the console frontend, "/api/*" serves
the console API, and "/v1/*" keeps serving the Realtime API from the same listener.
"""


def _command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="speech-to-speech",
        description="Run or connect to the Realtime speech-to-speech pipeline.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.add_parser("serve", add_help=False, help="Run the Realtime pipeline server.")
    subparsers.add_parser("talk", add_help=False, help="Connect microphone and speakers to a Realtime URL.")
    subparsers.add_parser("local", add_help=False, help="Run the server and audio client together over loopback.")
    subparsers.add_parser("models", add_help=False, help="List registered model cards.")
    return parser


def _extract_legacy_mode(command_args: list[str], parser: argparse.ArgumentParser) -> tuple[str | None, list[str]]:
    """Remove one legacy ``--mode`` option without parsing command-owned flags."""

    mode: str | None = None
    remaining: list[str] = []
    index = 0
    while index < len(command_args):
        argument = command_args[index]
        if argument == "--mode":
            if mode is not None:
                parser.error("--mode may only be specified once")
            if index + 1 == len(command_args) or command_args[index + 1].startswith("-"):
                parser.error("--mode requires a value: realtime or local")
            mode = command_args[index + 1]
            index += 2
            continue
        if argument.startswith("--mode="):
            if mode is not None:
                parser.error("--mode may only be specified once")
            mode = argument.partition("=")[2]
            if not mode:
                parser.error("--mode requires a value: realtime or local")
            index += 1
            continue
        remaining.append(argument)
        index += 1
    return mode, remaining


def parse_command(argv: Sequence[str] | None = None) -> tuple[Command, list[str]]:
    """Split the top-level command from arguments owned by that command."""

    command_args = list(sys.argv[1:] if argv is None else argv)
    parser = _command_parser()
    if not command_args:
        parser.error("a command is required: serve, talk, local, or models")
    if command_args[0] in {"-h", "--help"}:
        parser.print_help()
        raise SystemExit(0)
    if command_args[0] not in {"serve", "talk", "local", "models"}:
        legacy_mode, remaining = _extract_legacy_mode(command_args, parser)
        if legacy_mode is not None:
            legacy_command = _LEGACY_MODE_COMMANDS.get(legacy_mode)
            if legacy_command is None:
                parser.error(
                    f"--mode {legacy_mode!r} is no longer supported; only 'realtime' and 'local' remain "
                    "temporarily. Use 'speech-to-speech serve' or 'speech-to-speech local' instead."
                )
            print(
                f"Warning: '--mode {legacy_mode}' is deprecated and will stop working soon; "
                f"use 'speech-to-speech {legacy_command}' instead.",
                file=sys.stderr,
            )
            return legacy_command, remaining
    command = command_args[0]
    if command not in {"serve", "talk", "local", "models"}:
        parser.error(f"unknown command {command!r}; choose serve, talk, local, or models")
    return command, command_args[1:]  # type: ignore[return-value]


def parse_talk_arguments(argv: Sequence[str]) -> RealtimeAudioClientConfig:
    """Parse the lightweight audio client command."""

    defaults = RealtimeAudioClientConfig()
    parser = argparse.ArgumentParser(
        prog="speech-to-speech talk",
        description="Connect microphone and speakers to an OpenAI-compatible Realtime endpoint.",
    )
    parser.add_argument(
        "--url",
        default=defaults.url,
        help="Full Realtime WebSocket endpoint, including /realtime.",
    )
    parser.add_argument("--model", default=defaults.model)
    parser.add_argument(
        "--api-key",
        default=defaults.api_key,
        help=(
            "Realtime API key. Defaults to OPENAI_API_KEY, or a harmless placeholder for an unauthenticated "
            "loopback endpoint."
        ),
    )
    parser.add_argument("--send-rate", type=int, default=defaults.send_rate)
    parser.add_argument("--recv-rate", type=int, default=defaults.recv_rate)
    parser.add_argument(
        "--playback-buffer-ms",
        type=float,
        default=defaults.playback_buffer_ms,
        help="Audio to buffer before playback starts, in milliseconds.",
    )
    parser.add_argument("--chunk-size", type=int, default=defaults.chunk_size)
    parser.add_argument("--input-device", type=int, default=defaults.input_device)
    parser.add_argument("--output-device", type=int, default=defaults.output_device)
    parser.add_argument("--instructions", default=defaults.instructions)
    parser.add_argument(
        "--tool-module",
        help="Importable module defining TOOLS and async execute_tool(name, arguments).",
    )
    parser.add_argument(
        "--voice",
        default=defaults.voice,
        help="session.audio.output.voice (for example bm_fable, marin, or alloy).",
    )
    parser.add_argument("--voices", nargs="+", default=[], help="Voice names to cycle with terminal arrow keys.")
    parser.add_argument("--print-json", action="store_true", default=defaults.print_json)
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=defaults.verbose,
        help="Show routine logs, tool details, and Realtime events alongside the conversation.",
    )
    parser.add_argument(
        "--block-mic-during-playback",
        action="store_true",
        default=defaults.block_mic_during_playback,
    )
    parser.add_argument(
        "--log-transcripts",
        "--log_transcripts",
        dest="log_transcripts",
        action="store_true",
        default=defaults.log_transcripts,
        help="Write full Realtime transcript and tool error details to application logs.",
    )
    parser.add_argument(
        "--connection-retry-timeout",
        dest="connection_retry_timeout_s",
        type=float,
        default=defaults.connection_retry_timeout_s,
        help="Seconds to wait for the Realtime endpoint to become available.",
    )
    namespace = parser.parse_args(list(argv))
    tools: list[dict[str, Any]] = []
    tool_executor = None
    tool_response_create = defaults.tool_response_create
    if namespace.tool_module:
        tools, tool_executor, tool_response_create = load_realtime_tool_module(namespace.tool_module)
    return RealtimeAudioClientConfig(
        url=namespace.url,
        model=namespace.model,
        api_key=namespace.api_key,
        send_rate=namespace.send_rate,
        recv_rate=namespace.recv_rate,
        playback_buffer_ms=namespace.playback_buffer_ms,
        chunk_size=namespace.chunk_size,
        input_device=namespace.input_device,
        output_device=namespace.output_device,
        instructions=namespace.instructions,
        voice=namespace.voice,
        voice_choices=namespace.voices,
        print_json=namespace.print_json,
        verbose=namespace.verbose,
        block_mic_during_playback=namespace.block_mic_during_playback,
        log_transcripts=namespace.log_transcripts,
        connection_retry_timeout_s=namespace.connection_retry_timeout_s,
        tools=tools,
        tool_executor=tool_executor,
        tool_response_create=tool_response_create,
    )


def _run_file_command(command: Command, command_args: list[str], console_options: ConsoleOptions) -> None:
    from speech_to_speech.config import ConfigurationError, load_config, resolve_config

    parser = argparse.ArgumentParser(prog=f"speech-to-speech {command}", allow_abbrev=False, exit_on_error=False)
    parser.add_argument("-f", "--file", action="append", metavar="YAML", help="Read a YAML configuration file.")
    parser.add_argument("--name", action="append", help="Select one pipeline definition; repeat for distinct names.")
    if "-h" in command_args or "--help" in command_args:
        parser.print_help()
        raise SystemExit(0)
    try:
        namespace, unknown = parser.parse_known_args(command_args)
    except argparse.ArgumentError:
        parser.exit(2, "Configuration error: use --file YAML and optional --name values.\n")
    if unknown:
        parser.error("File mode accepts only --file and --name; put settings in the YAML file.")
    if not namespace.file or len(namespace.file) != 1:
        parser.error("Specify exactly one configuration file with -f or --file.")
    if command == "talk" and namespace.name is not None:
        parser.error("talk does not accept --name.")
    try:
        document = load_config(namespace.file[0])
        config = resolve_config(
            document,
            names=namespace.name,
            include_client=command == "local",
            client_only=command == "talk",
        )
        if command != "talk" and len(config.pipelines) != 1:
            parser.error("serve and local require exactly one selected definition; use --name.")
    except (ConfigurationError, ImportError):
        parser.exit(2, "Configuration error: check the YAML file, selected names, and required environment settings.\n")
    try:
        from speech_to_speech.configured_runtime import run_configured_command

        # "models" is short-circuited before _run_file_command; Command is wider than this runtime command set.
        run_configured_command(command, config, console_options=console_options)  # type: ignore[arg-type]
    except ConsoleIntegrationError as exc:
        parser.exit(2, f"Configuration error: {exc}\n")
    except ConfigurationError:
        parser.exit(2, "Configuration error: check the configured runtime and client settings.\n")
    except StartupError:
        parser.exit(1, "Startup failed: the Realtime server could not bind its port.\n")
    except Exception:
        parser.exit(1, "Configured startup failed; check the selected backends and runtime resources.\n")


def _run_models_command(command_args: list[str]) -> None:
    import json

    from speech_to_speech.backend_registry import LLM_BACKENDS, STT_BACKENDS, TTS_BACKENDS
    from speech_to_speech.model_registry import list_models

    parser = argparse.ArgumentParser(prog="speech-to-speech models", allow_abbrev=False)
    parser.add_argument("action", choices=("list",))
    parser.add_argument("--kind", choices=("stt", "llm", "tts"), default=None)
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(command_args)

    cards = list_models(kind=args.kind)
    rows = [
        {
            "id": card.id,
            "name": card.name,
            "kind": card.kind,
            "version": card.version,
            "provider": card.provider,
            "backend": card.backend_name,
            "status": card.status,
            "weight_format": card.weight_format,
            "min_vram_gb": card.min_vram_gb,
            "license": card.license,
        }
        for card in cards
    ]
    for card in cards:
        if card.status == "deprecated":
            print(
                f"Warning: {card.id} is deprecated: {card.license}. 商用场景禁止自托管；"
                "见 docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md §6.4 路径 L / R。",
                file=sys.stderr,
            )

    known = {card.backend_name for card in list_models()}
    registries = (("stt", STT_BACKENDS), ("llm", LLM_BACKENDS), ("tts", TTS_BACKENDS))
    for kind, registry in registries:
        if args.kind is not None and args.kind != kind:
            continue
        for name in sorted(registry):
            if name in known:
                continue
            rows.append(
                {
                    "id": name,
                    "name": name,
                    "kind": kind,
                    "version": None,
                    "provider": None,
                    "backend": name,
                    "status": "unregistered",
                    "weight_format": None,
                    "min_vram_gb": None,
                    "license": None,
                }
            )

    if args.as_json:
        print(json.dumps(rows, ensure_ascii=False))
        return
    print("ID\tKIND\tVERSION\tBACKEND\tSTATUS\tVRAM\tLICENSE")
    for row in rows:
        print(
            f"{row['id']}\t{row['kind']}\t{row['version'] or '-'}\t{row['backend']}\t"
            f"{row['status']}\t{row['min_vram_gb'] if row['min_vram_gb'] is not None else '-'}\t"
            f"{row['license'] or '-'}"
        )


def _dispatch(command: Command, command_args: list[str], console_options: ConsoleOptions) -> None:
    if command == "models":
        _run_models_command(command_args)
        return
    if any(
        argument.startswith("-f") or argument == "--file" or argument.startswith("--file=") for argument in command_args
    ):
        _run_file_command(command, command_args, console_options)
        return
    if any(argument == "--name" or argument.startswith("--name=") for argument in command_args):
        _command_parser().error("--name requires a configuration file.")
    if command == "talk":
        config = parse_talk_arguments(command_args)
        set_log_transcripts(config.log_transcripts)
        warn_if_log_transcripts_enabled()
        run_realtime_audio_client(config)
        return

    from speech_to_speech.s2s_pipeline import run_pipeline_command

    run_pipeline_command(command, command_args, console_options=console_options)


def main() -> None:
    argv = list(sys.argv[1:])
    if argv and argv[0] == "models":
        _run_models_command(argv[1:])
        return
    try:
        console_options, argv = parse_console_arguments(argv)
    except ConsoleIntegrationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None

    wants_help = any(argument in {"-h", "--help"} for argument in argv)
    try:
        command, command_args = parse_command(argv)
    except SystemExit as exc:
        if exc.code == 0 and wants_help:
            print(CONSOLE_HELP)
        raise

    if command == "talk":
        if console_options.explicit:
            _command_parser().error(
                "talk does not accept --with-console; it only connects to a listener that already runs."
            )
        if console_options.autostart:
            # An environment switch must not break a command that has nothing to host.
            print(f"Warning: {AUTOSTART_ENV}=true is ignored for 'talk'.", file=sys.stderr)
            console_options = ConsoleOptions(
                autostart=False,
                explicit=console_options.explicit,
                home=console_options.home,
                static_dir=console_options.static_dir,
            )
    elif console_options.autostart:
        try:
            console_options.validate()
        except ConsoleIntegrationError as exc:
            print(f"Configuration error: {exc}", file=sys.stderr)
            raise SystemExit(2) from None

    try:
        _dispatch(command, command_args, console_options)
    except SystemExit as exc:
        if exc.code == 0 and wants_help and command in {"serve", "local"}:
            print(CONSOLE_HELP)
        raise
    except ConsoleIntegrationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except StartupError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
