"""`TURN_LATENCY` machine line: the same measurements, one parseable line (§3.9.4).

The indexer's only input is this line, so the two things it can silently get
wrong are pinned here: a missing measurement becoming 0 (which reads as "instant"
instead of "not measured"), and a newline splitting one record across two lines.
"""

from __future__ import annotations

import json

from speech_to_speech.pipeline.turn_latency import MACHINE_KEYS, encode_machine_line

PREFIX = "TURN_LATENCY "


def test_machine_line_starts_with_the_prefix_and_parses():
    line = encode_machine_line({"version": 2, "response_key": "k1", "e2e_s": 6.26})
    assert line.startswith(PREFIX)
    assert json.loads(line[len(PREFIX) :])["e2e_s"] == 6.26


def test_missing_measurements_stay_null_and_every_key_is_present():
    payload = json.loads(encode_machine_line({"version": 2, "response_key": "k1"})[len(PREFIX) :])
    assert list(payload) == list(MACHINE_KEYS)
    assert payload["hold_s"] is None
    assert payload["hold_s"] != 0


def test_machine_line_never_contains_a_newline():
    assert "\n" not in encode_machine_line({"response_key": "k\n1"})
