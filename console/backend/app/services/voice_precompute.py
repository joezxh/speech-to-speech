"""Voice precompute: a CPU-only child process, never the pipeline's GPU.

Two halves in one module because they share the progress vocabulary:
`run()` is the console side (spawns, reads `stage=` lines, reports), and
`_main()` is the child side (`python -m app.services.voice_precompute`).

The upstream `speech_to_speech` package consumes `ref_spk` / `ref_rvq` but does
not expose a way to produce them, so the child reports `model_not_found` and the
clone stays on its `ref_audio` + `ref_text` fallback, which needs no precompute.
That is a gap in the runtime, not a silent success: the row keeps
`status=failed` + `error_code`, and the picker binds the fallback fields.
"""

from __future__ import annotations

import asyncio
import os
import sys
import wave
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import console

if TYPE_CHECKING:  # pragma: no cover - typing only
    from app.models.voice import Voice

PROGRESS: dict[str, tuple[str, int]] = {}
_SEMAPHORE: asyncio.Semaphore | None = None


def semaphore() -> asyncio.Semaphore:
    """One at a time: `VOICE_PRECOMPUTE_CONCURRENCY=1` is a hard constraint."""
    global _SEMAPHORE
    if _SEMAPHORE is None:
        _SEMAPHORE = asyncio.Semaphore(max(1, console.voice_precompute_concurrency))
    return _SEMAPHORE


def _stage(name: str, percent: int) -> None:
    print(f"stage={name} progress={percent}", flush=True)


def progress(row: Voice) -> tuple[str, int]:
    """What the detail endpoint shows: `queued → loading → spk → rvq → done`."""
    if row.id in PROGRESS:
        return PROGRESS[row.id]
    if row.status == "ready":
        return ("done", 100)
    if row.status == "failed":
        return ("failed", 100)
    if row.status == "precomputing":
        return ("queued", 0)
    return ("draft", 0)


async def run(voice_id: str, ref_wav: Path, out_dir: Path) -> tuple[bool, str | None]:
    """Spawn the child, stream its progress, and return `(ok, errorCode)`."""
    async with semaphore():
        env = {**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "PYTHONUNBUFFERED": "1"}
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "app.services.voice_precompute",
            str(ref_wav),
            str(out_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        PROGRESS[voice_id] = ("loading", 5)
        assert process.stdout is not None
        try:
            async with asyncio.timeout(console.voice_precompute_timeout_s):
                while True:
                    raw = await process.stdout.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("stage="):
                        continue
                    parts = dict(part.split("=", 1) for part in line.split() if "=" in part)
                    stage = parts.get("stage", "")
                    try:
                        percent = int(parts.get("progress", "0"))
                    except ValueError:
                        percent = 0
                    if stage == "failed":
                        PROGRESS[voice_id] = ("failed", 100)
                        return (False, parts.get("error", "model_not_found"))
                    PROGRESS[voice_id] = (stage, percent)
                await process.wait()
        except TimeoutError:
            process.kill()
            await process.wait()
            PROGRESS[voice_id] = ("failed", 100)
            return (False, "timeout")
        if process.returncode != 0:
            PROGRESS[voice_id] = ("failed", 100)
            return (False, "model_not_found")
        PROGRESS[voice_id] = ("done", 100)
        return (True, None)


def _main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m app.services.voice_precompute <ref.wav> <out_dir>", file=sys.stderr)
        return 2
    ref_wav, out_dir = Path(argv[1]), Path(argv[2])  # noqa: F841 - where spk.npy/rvq.npy land once the encoder exists
    _stage("loading", 10)
    try:
        with wave.open(str(ref_wav)) as handle:
            seconds = handle.getnframes() / max(1, handle.getframerate())
    except (OSError, wave.Error):
        _stage("failed", 100)
        print("error=audio_too_short", flush=True)
        return 1
    if seconds < console.voice_min_seconds:
        _stage("failed", 100)
        print("error=audio_too_short", flush=True)
        return 1

    # The speaker/vector encoder lives in the upstream package; until it exposes
    # one, this child cannot produce spk.npy / rvq.npy and says so.
    try:
        import speech_to_speech  # noqa: F401,PLC0415  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - any import failure means "not installed"
        _stage("failed", 100)
        print("error=model_not_found", flush=True)
        return 1
    _stage("spk", 40)
    _stage("rvq", 80)
    _stage("failed", 100)
    print("error=model_not_found", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
