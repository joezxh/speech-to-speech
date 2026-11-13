"""声纹嵌入服务的单元测试（不加载真实模型）。

覆盖设计文档 §9.4 的用例，重点是三条硬约束：
  1. 鉴权 fail-closed：无凭据/错凭据一律拒绝，未配置时端点关闭
  2. **440Hz 纯音不拒收**（F11：g0-probe 的探测音频就是它，拒收则 G0 永远不可取证）
  3. 失败不得回 200 + 空向量；响应不得出现 verdict/confidence 等结论字段
"""

from __future__ import annotations

import io
import json
import math
import struct
import wave

import numpy as np
import pytest

from speech_to_speech.voiceprint.errors import VoiceprintErrorCode
from speech_to_speech.voiceprint.service import (
    VoiceprintRequestError,
    VoiceprintService,
)

API_KEY = "unit-test-key"
DIM = 2048


class FakeEmbedder:
    """替身 embedder：不做真实推理，只返回固定维度向量。"""

    def __init__(self, dim: int = DIM, ready: bool = True) -> None:
        self.dim_value = dim if ready else None
        self._ready = ready
        self.calls = 0

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def dim(self) -> int | None:
        return self.dim_value

    @property
    def model_id(self) -> str:
        return "fake-tts-base-speaker@test"

    def ensure_ready(self) -> None:
        if not self._ready:
            from speech_to_speech.voiceprint.embedder import SpeakerEncoderUnavailable

            raise SpeakerEncoderUnavailable("fake: no encoder")

    def embed(self, audio: np.ndarray) -> list[float]:
        self.calls += 1
        return [0.0] * self.dim_value


def _wav_bytes(
    *,
    seconds: float = 2.0,
    sr: int = 16000,
    freq: float = 440.0,
    amplitude: float = 6000.0,
) -> bytes:
    """生成单声道 16-bit WAV（默认 440Hz 正弦波，与 g0-probe 的探测音频同型）。"""
    frames = int(sr * seconds)
    data = b"".join(
        struct.pack("<h", int(math.sin(2 * math.pi * freq * i / sr) * amplitude)) for i in range(frames)
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data)
    return buf.getvalue()


def _service(**kwargs) -> tuple[VoiceprintService, FakeEmbedder]:
    service = VoiceprintService(api_key=API_KEY, **kwargs)
    fake = FakeEmbedder()
    service._embedder = fake  # noqa: SLF001 - 单元测试注入替身
    return service, fake


class TestAuthorization:
    def test_missing_api_key_is_fail_closed(self) -> None:
        service = VoiceprintService(api_key=None)
        with pytest.raises(VoiceprintRequestError) as exc:
            service.authorize("Bearer whatever")
        assert exc.value.code is VoiceprintErrorCode.AUTH_NOT_CONFIGURED
        assert exc.value.status_code == 503

    def test_missing_bearer_header_is_unauthorized(self) -> None:
        service, _ = _service()
        with pytest.raises(VoiceprintRequestError) as exc:
            service.authorize(None)
        assert exc.value.code is VoiceprintErrorCode.UNAUTHORIZED
        assert exc.value.status_code == 401

    def test_wrong_key_is_forbidden(self) -> None:
        service, _ = _service()
        with pytest.raises(VoiceprintRequestError) as exc:
            service.authorize("Bearer wrong-key")
        assert exc.value.code is VoiceprintErrorCode.FORBIDDEN
        assert exc.value.status_code == 403

    def test_correct_key_passes(self) -> None:
        service, _ = _service()
        service.authorize(f"Bearer {API_KEY}")


class TestRejections:
    def test_oversized_payload_rejected(self) -> None:
        service, _ = _service(max_bytes=1024)
        with pytest.raises(VoiceprintRequestError) as exc:
            service.embed(_wav_bytes(seconds=1.0))
        assert exc.value.code is VoiceprintErrorCode.AUDIO_TOO_LARGE
        assert exc.value.status_code == 413

    def test_undecodable_audio_rejected(self) -> None:
        service, _ = _service()
        with pytest.raises(VoiceprintRequestError) as exc:
            service.embed(b"this is definitely not a wav file")
        assert exc.value.code is VoiceprintErrorCode.AUDIO_UNDECODABLE
        assert exc.value.status_code == 422

    def test_too_long_audio_rejected(self) -> None:
        service, _ = _service(max_audio_ms=500)
        with pytest.raises(VoiceprintRequestError) as exc:
            service.embed(_wav_bytes(seconds=3.0))
        assert exc.value.code is VoiceprintErrorCode.AUDIO_TOO_LONG
        assert exc.value.status_code == 422

    def test_silent_audio_rejected(self) -> None:
        service, _ = _service()
        with pytest.raises(VoiceprintRequestError) as exc:
            service.embed(_wav_bytes(seconds=1.0, amplitude=0.0))
        assert exc.value.code is VoiceprintErrorCode.AUDIO_SILENT
        assert exc.value.status_code == 409

    def test_model_mismatch_rejected(self) -> None:
        service, _ = _service(model_name="expected-model")
        with pytest.raises(VoiceprintRequestError) as exc:
            service.embed(_wav_bytes(), model="other-model")
        assert exc.value.code is VoiceprintErrorCode.MODEL_MISMATCH
        assert exc.value.status_code == 400


class TestNonSpeechIsAccepted:
    """F11 约束：440Hz 纯音必须能出向量，否则 G0-a/G0-c 恒失败。"""

    def test_tone_is_not_rejected(self) -> None:
        service, fake = _service()
        result = service.embed(_wav_bytes(seconds=3.0, freq=440.0))
        assert len(result["embedding"]) == DIM
        assert result["dim"] == DIM
        assert fake.calls == 1

    def test_short_speech_is_not_rejected_by_default(self) -> None:
        service, _ = _service(min_speech_ms=800)
        result = service.embed(_wav_bytes(seconds=0.2, freq=440.0))
        assert result["dim"] == DIM

    def test_strict_mode_rejects_without_speech(self) -> None:
        service, _ = _service(strict_reject=True)
        with pytest.raises(VoiceprintRequestError) as exc:
            service.embed(_wav_bytes(seconds=0.2, freq=440.0))
        assert exc.value.code in (
            VoiceprintErrorCode.SPEECH_NOT_DETECTED,
            VoiceprintErrorCode.AUDIO_TOO_SHORT,
        )


class TestResponseShape:
    def test_response_has_required_fields_only(self) -> None:
        service, _ = _service()
        result = service.embed(_wav_bytes())
        assert set(result) == {"embedding", "dim", "model", "quality", "speechDurationMs"}
        assert result["model"]
        assert result["quality"] is not None
        assert isinstance(result["speechDurationMs"], int)

    def test_response_has_no_verdict_fields(self) -> None:
        service, _ = _service()
        result = service.embed(_wav_bytes())
        for forbidden in ("verdict", "confidence", "matched", "speaker_id"):
            assert forbidden not in result

    def test_embedding_length_equals_dim(self) -> None:
        service, _ = _service()
        result = service.embed(_wav_bytes())
        assert len(result["embedding"]) == result["dim"]


class TestCapability:
    def test_ready_capability_reports_dim(self) -> None:
        service, _ = _service()
        cap = service.capability()
        assert cap["ready"] is True
        assert cap["dim"] == DIM
        assert cap["embedding_dim"] == DIM

    def test_not_ready_capability_is_still_http_200_shape(self) -> None:
        service = VoiceprintService(api_key=API_KEY)
        service._embedder = FakeEmbedder(ready=False)  # noqa: SLF001
        cap = service.capability()
        assert cap["ready"] is False
        assert cap["dim"] == 0


class TestStandaloneEmbedderReadiness:
    """回归：方案 C（独立加载 speaker encoder）下的就绪判定与启动期定维。

    历史缺陷：`SpeakerEmbedder.ready` 只判 `_extractor`（方案 A 的官方封装），
    而方案 C 绑定时显式置 `_extractor=None` → capability 恒报 `ready=false`，
    而推理其实完全正常；调用端若以 `ready` 做门禁，会在服务可用时全量拒绝。
    同时 `dim` 原本只在首次推理后确定，冷启动首个 capability 请求返回 `dim=0`。
    """

    @staticmethod
    def _embedder():
        from speech_to_speech.voiceprint.embedder import SpeakerEmbedder

        return SpeakerEmbedder()

    def test_standalone_binding_marks_ready(self) -> None:
        embedder = self._embedder()
        assert embedder.ready is False
        embedder.bind_standalone_encoder(object(), model_id="standalone-test")
        assert embedder.ready is True

    def test_standalone_binding_sets_startup_dim(self) -> None:
        embedder = self._embedder()
        embedder.bind_standalone_encoder(object(), model_id="standalone-test", dim=2048)
        assert embedder.dim == 2048

    def test_capability_reports_ready_and_dim_for_standalone(self) -> None:
        service = VoiceprintService(api_key=API_KEY)
        embedder = self._embedder()
        embedder.bind_standalone_encoder(object(), model_id="standalone-test", dim=2048)
        service._embedder = embedder  # noqa: SLF001
        cap = service.capability()
        assert cap["ready"] is True
        assert cap["dim"] == 2048
        assert cap["embedding_dim"] == 2048

    def test_read_encoder_dim_from_config_json(self, tmp_path) -> None:
        from speech_to_speech.voiceprint.standalone import read_encoder_dim

        (tmp_path / "config.json").write_text(
            json.dumps({"enc_dim": 2048, "sample_rate": 24000}), encoding="utf-8"
        )
        assert read_encoder_dim(tmp_path) == 2048

    def test_read_encoder_dim_missing_config_returns_none(self, tmp_path) -> None:
        from speech_to_speech.voiceprint.standalone import read_encoder_dim

        assert read_encoder_dim(tmp_path) is None

    def test_read_encoder_dim_invalid_json_returns_none(self, tmp_path) -> None:
        from speech_to_speech.voiceprint.standalone import read_encoder_dim

        (tmp_path / "config.json").write_text("{not json", encoding="utf-8")
        assert read_encoder_dim(tmp_path) is None


class TestWarmup:
    """预热：把首请求的惰性成本（librosa/numba JIT）前置到启动期。

    实测冷启动后首个请求 26.4s、第二次起 <2s；3s 推理超时覆盖不到预处理段，
    因此预热必须由服务自己在启动期完成。
    """

    def test_warmup_succeeds(self) -> None:
        pytest.importorskip("librosa")  # 宿主可能缺依赖（容器内齐备）
        service, fake = _service()
        assert service.warmup() is True
        assert fake.calls == 1

    def test_warmup_failure_does_not_raise(self) -> None:
        pytest.importorskip("librosa")
        service = VoiceprintService(api_key=API_KEY)
        service._embedder = FakeEmbedder(ready=False)  # noqa: SLF001
        assert service.warmup() is False
