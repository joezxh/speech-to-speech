"""A committed utterance's sub-chunk tail must reach the pipeline.

``append_pcm`` withholds a sub-chunk remainder (< 32 ms / 1024 bytes at 16 kHz)
so the VAD sees fixed-size chunks. On ``input_audio_buffer.commit`` the
resampler is flushed, but that withheld tail used to stay behind forever, so
the last one or two syllables of a fast or short phrase never reached the STT.
These tests pin the commit contract: a successful commit delivers the tail
exactly once and clears it, a failed (empty-buffer) commit keeps withholding
it, and the full-chunk path is unchanged.
"""

import numpy as np

from speech_to_speech.api.openai_realtime.service import CHUNK_SIZE_BYTES
from speech_to_speech.api.openai_realtime.utils import StreamingPcm16Resampler
from tests.openai_realtime.conftest import make_pipeline_unit

PIPELINE_SAMPLE_RATE = 16_000


def _samples(n: int, start: int = 0) -> bytes:
    """Distinct, position-identifiable PCM16 samples for byte-level assertions."""
    return np.arange(start, start + n, dtype="<i2").tobytes()


class TestCommitDeliversTail:
    def test_commit_yields_the_withheld_remainder_once(self):
        unit = make_pipeline_unit()
        conn_id = unit.service.register()

        # 700 samples: one full chunk plus a 188-sample tail.
        chunks = unit.service.append_pcm(conn_id, _samples(700), PIPELINE_SAMPLE_RATE)
        assert [len(c) for c in chunks] == [CHUNK_SIZE_BYTES]

        tail_chunks, error = unit.service.handle_audio_commit(conn_id)
        assert error is None
        assert tail_chunks == [_samples(188, start=512)]
        assert unit.service._state(conn_id).audio_remainder == b""

    def test_commit_does_not_deliver_the_tail_twice(self):
        unit = make_pipeline_unit()
        conn_id = unit.service.register()

        unit.service.append_pcm(conn_id, _samples(700), PIPELINE_SAMPLE_RATE)
        first, error = unit.service.handle_audio_commit(conn_id)
        assert error is None
        assert first

        second, error = unit.service.handle_audio_commit(conn_id)
        assert error is not None
        assert second == []
        assert unit.service._state(conn_id).audio_remainder == b""

    def test_failed_commit_still_withholds_the_tail(self):
        """An empty-buffer commit must not spend the tail it will still need."""
        unit = make_pipeline_unit()
        conn_id = unit.service.register()

        assert unit.service.append_pcm(conn_id, _samples(300), PIPELINE_SAMPLE_RATE) == []
        chunks, error = unit.service.handle_audio_commit(conn_id)
        assert error is not None
        assert chunks == []
        # The tail survives the failed commit for a later append to complete.
        assert unit.service._state(conn_id).audio_remainder == _samples(300)

    def test_exact_chunks_commit_delivers_nothing_extra(self):
        unit = make_pipeline_unit()
        conn_id = unit.service.register()

        chunks = unit.service.append_pcm(conn_id, _samples(512), PIPELINE_SAMPLE_RATE)
        assert [len(c) for c in chunks] == [CHUNK_SIZE_BYTES]

        tail_chunks, error = unit.service.handle_audio_commit(conn_id)
        assert error is None
        assert tail_chunks == []
        assert unit.service._state(conn_id).audio_remainder == b""

    def test_flush_tail_is_delivered_after_resampling(self):
        """The commit flush's own output ends in a tail, and it is delivered too."""
        unit = make_pipeline_unit()
        conn_id = unit.service.register()

        # 4800 samples at 24 kHz resample to 3200 samples (6400 bytes) at 16 kHz.
        samples = np.arange(4800, dtype="<i2")
        chunks = unit.service.append_pcm(conn_id, samples.tobytes(), 24000)
        assert all(len(c) == CHUNK_SIZE_BYTES for c in chunks)

        tail_chunks, error = unit.service.handle_audio_commit(conn_id)
        assert error is None
        assert tail_chunks and all(len(c) < CHUNK_SIZE_BYTES for c in tail_chunks)

        reference = StreamingPcm16Resampler(24000, 16000)
        expected = reference.push(samples.tobytes()) + reference.flush()
        assert b"".join(chunks + tail_chunks) == expected
        assert unit.service._state(conn_id).audio_remainder == b""
