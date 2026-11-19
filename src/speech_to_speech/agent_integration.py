"""Agent integration: the single place that reads the agent switches.

``--with-agent`` / ``S2S_AGENT_AUTOSTART`` merge the s2s-agent into this
process: the agent's heartbeat loop runs next to the speech pipeline and the
``/v1/agent/*`` control endpoints are published on the same port.

The shape mirrors :mod:`speech_to_speech.console_integration` deliberately —
same switch-stripping discipline (the flags must be removed *before*
``parse_command``, because the ``-f`` file mode rejects unknown options
outright), same "off means no footprint" rule, and the same fail-fast
validation that runs before any model is loaded.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from speech_to_speech.agent.collectors import Usage
    from speech_to_speech.agent.embedded import EmbeddedAgent

AUTOSTART_ENV = "S2S_AGENT_AUTOSTART"

WITH_FLAG = "--with-agent"
WITHOUT_FLAG = "--no-with-agent"

# The same value set the console switch accepts; anything else is a
# configuration mistake rather than a silent "off".
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


class AgentIntegrationError(RuntimeError):
    """The agent cannot be integrated as requested; callers exit with code 2."""


@dataclass(frozen=True)
class AgentOptions:
    """Resolved switches for this run."""

    autostart: bool = False
    explicit: bool = False

    @property
    def enabled(self) -> bool:
        """Whether the agent should run inside this process."""

        return self.autostart


def read_switch(name: str, default: bool = False) -> bool:
    """Read one boolean switch, rejecting values that are neither true nor false."""

    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise AgentIntegrationError(
        f"{name} must be a boolean (1/true/yes/on or 0/false/no/off); got {raw!r}."
    )


def parse_agent_arguments(argv: Sequence[str]) -> tuple[AgentOptions, list[str]]:
    """Strip the two switches from argv and resolve the effective options.

    Stripping happens before ``parse_command`` so ``-f`` file mode, which
    rejects unknown options outright, keeps working.
    """

    explicit: bool | None = None
    remaining: list[str] = []
    for argument in argv:
        if argument == WITH_FLAG:
            if explicit is False:
                raise AgentIntegrationError(f"{WITH_FLAG} conflicts with {WITHOUT_FLAG}.")
            explicit = True
            continue
        if argument == WITHOUT_FLAG:
            if explicit is True:
                raise AgentIntegrationError(f"{WITHOUT_FLAG} conflicts with {WITH_FLAG}.")
            explicit = False
            continue
        remaining.append(argument)

    autostart = read_switch(AUTOSTART_ENV) if explicit is None else explicit
    return AgentOptions(autostart=autostart, explicit=explicit is True), remaining


def validate_agent_options(options: AgentOptions | None) -> None:
    """Fail before any model loads, and touch nothing when the switch is off.

    The agent needs a console to talk to and an identity to report as; both
    are checked here so a misconfigured deployment fails in seconds instead of
    after the pipeline has already claimed the GPU.
    """

    if options is None or not options.autostart:
        return

    missing = [
        name
        for name in ("S2S_AGENT_CONSOLE_URL", "S2S_AGENT_MACHINE_ID")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        raise AgentIntegrationError(
            "the embedded agent needs "
            + " and ".join(missing)
            + f"; set them (or drop {WITH_FLAG}) before starting the server."
        )


def build_embedded_agent(
    options: AgentOptions | None,
    *,
    stop_event: object | None = None,
    usage_provider: Callable[[], Usage] | None = None,
) -> EmbeddedAgent:
    """Build the in-process agent for an enabled run.

    ``stop_event`` is the caller's shared shutdown event: the agent must stop
    with the server, and the server must not wait for the agent to time out.
    ``usage_provider`` lets the agent read the pool's counters in-process
    instead of calling its own HTTP server.
    """

    from speech_to_speech.agent.embedded import EmbeddedAgent
    from speech_to_speech.agent.settings import AgentSettings

    if options is None or not options.autostart:
        raise AgentIntegrationError("build_embedded_agent() requires an enabled AgentOptions.")
    validate_agent_options(options)

    settings = AgentSettings.from_env()
    return EmbeddedAgent(
        settings,
        stop_event=stop_event,  # type: ignore[arg-type]
        embedded=True,
        usage_provider=usage_provider,
    )


def pool_usage_provider(pool: Iterable[Any]) -> Callable[[], Usage]:
    """Usage source for an embedded agent: read the pool's counters in-process.

    The alternative — the agent calling its own ``GET /v1/usage`` — depends on
    the declared pipeline port and breaks whenever the server listens
    elsewhere.
    """

    from speech_to_speech.agent.collectors import Usage
    from speech_to_speech.api.openai_realtime.usage import pool_usage_snapshot

    def provider() -> Usage:
        return Usage(**pool_usage_snapshot(pool))

    return provider


__all__ = [
    "AUTOSTART_ENV",
    "WITH_FLAG",
    "WITHOUT_FLAG",
    "AgentIntegrationError",
    "AgentOptions",
    "build_embedded_agent",
    "parse_agent_arguments",
    "pool_usage_provider",
    "read_switch",
    "validate_agent_options",
]
