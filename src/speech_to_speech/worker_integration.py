"""Worker integration: reads the --with-diarization / --with-livekitworker switches.

The shape mirrors :mod:`speech_to_speech.agent_integration` deliberately — same
switch-stripping discipline (flags must be removed *before* ``parse_command``,
because ``-f`` file mode rejects unknown options outright), same "off means no
footprint" rule, and the same fail-fast validation before any model loads.

``--with-diarization`` maps onto the existing streaming diarization argument
(``module_kwargs.diarization``); it adds no new subsystem. ``--with-livekitworker``
starts the embedded LiveKit transcript worker thread inside this process.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

DIARIZATION_AUTOSTART_ENV = "DIARIZATION_AUTOSTART"
LIVEKIT_WORKER_AUTOSTART_ENV = "LIVEKIT_WORKER_AUTOSTART"

DIARIZATION_WITH_FLAG = "--with-diarization"
DIARIZATION_WITHOUT_FLAG = "--no-with-diarization"
LIVEKIT_WITH_FLAG = "--with-livekitworker"
LIVEKIT_WITHOUT_FLAG = "--no-with-livekitworker"

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off", ""})


class WorkerIntegrationError(RuntimeError):
    """A worker switch cannot be applied as requested; callers exit with code 2."""


def _read_switch(name: str) -> bool:
    """Read one boolean env switch, rejecting values that are neither true nor false."""
    raw = os.environ.get(name)
    if raw is None:
        return False
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise WorkerIntegrationError(
        f"{name} must be a boolean (1/true/yes/on or 0/false/no/off); got {raw!r}."
    )


@dataclass(frozen=True)
class SwitchOptions:
    """Resolved on/off state of one switch."""

    autostart: bool = False
    explicit: bool = False


def _strip_pair(
    argv: Sequence[str],
    with_flag: str,
    without_flag: str,
    env_name: str,
    remaining: list[str],
) -> SwitchOptions:
    """Consume one flag pair from argv (left to right), resolve env fallback."""
    explicit: bool | None = None
    kept: list[str] = []
    for argument in remaining:
        if argument == with_flag:
            if explicit is False:
                raise WorkerIntegrationError(f"{with_flag} conflicts with {without_flag}.")
            explicit = True
            continue
        if argument == without_flag:
            if explicit is True:
                raise WorkerIntegrationError(f"{without_flag} conflicts with {with_flag}.")
            explicit = False
            continue
        kept.append(argument)
    remaining[:] = kept
    autostart = _read_switch(env_name) if explicit is None else explicit
    # "explicit" means the caller set the switch on the command line in either
    # direction (--with-* or --no-with-*); only absence falls back to the env.
    return SwitchOptions(autostart=autostart, explicit=explicit is not None)


def parse_worker_arguments(argv: Sequence[str]) -> tuple[SwitchOptions, SwitchOptions, list[str]]:
    """Strip both switches from argv and resolve the effective options.

    Returns (diarization, livekit_worker, remaining-argv). Stripping happens before
    ``parse_command`` so ``-f`` file mode keeps working.
    """
    remaining = list(argv)
    diarization = _strip_pair(
        remaining, DIARIZATION_WITH_FLAG, DIARIZATION_WITHOUT_FLAG, DIARIZATION_AUTOSTART_ENV, remaining
    )
    livekit = _strip_pair(
        remaining, LIVEKIT_WITH_FLAG, LIVEKIT_WITHOUT_FLAG, LIVEKIT_WORKER_AUTOSTART_ENV, remaining
    )
    return diarization, livekit, remaining
