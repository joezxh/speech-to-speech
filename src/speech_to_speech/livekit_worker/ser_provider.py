"""SP-4 声学情感（SER）Provider —— 设计 §4 契约的 worker 侧实现。

与 ``asr_provider.py`` 严格同构：抽象基类 + 纯函数复用 + ``get_ser_provider()``
在未实现时显式 ``raise``，绝不静默降级成假标签。``_to_wav`` 直接从
``asr_provider`` import 复用（全仓唯一允许跨模块引用的一处），不复制第二份。

默认 ``SER_PROVIDER=none`` = 默认不启用；只有服务端开关快照明确 ``ser=true``
且策略块完整时，worker 才会发起外呼。所有业务阈值均由 Java 快照下发，
本模块不持有任何硬编码阈值（DEFAULT_SER_POLICY 仅为快照异常时的 fail-closed 兜底）。

隐私：PCM 只在调用进程内存中转成 WAV 字节，不落盘、不进日志、不进数据库。

移植来源：mediation-deploy/livekit-worker/ser_provider.py 逐行移植；仅 import 路径改为包内绝对导入。
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping

import requests

from speech_to_speech.livekit_worker.asr_provider import _to_wav  # noqa: F401  （复用同一份 WAV 封装）

# 与 SP-2 EMOTION_JSON_SCHEMA 同源五值；平台侧不绑定任何模型名
SER_EMOTIONS = ("calm", "anxious", "agitated", "anger", "threat")
SUPPORTED_LABELS = SER_EMOTIONS  # 向后兼容别名（旧部署脚本与测试引用）

# 官方 9 类 -> 平台 5 类（设计 §8.2.4）。仅用于兼容旧返回体与标签表审计；
# 新契约下服务侧已直接返回平台五值，SerResult.from_response 严格校验。
LABEL_MAP = {
    "neutral": "calm", "happy": "calm",
    "fearful": "anxious", "sad": "anxious", "fear": "anxious",
    "surprised": "agitated", "disgusted": "agitated", "disgust": "agitated",
    "angry": "anger", "anger": "anger",
    "threat": "threat",
    "calm": "calm", "anxious": "anxious", "agitated": "agitated",
}
REJECTED_LABELS = frozenset({"other", "unknown"})  # 模型主动拒分类，不得当 calm

# 平台五值 → 平台五值的显式别名（2026-11-24 实测 137 SenseVoiceSmall 标签集为 6 值，多出 happy）。
# 只映射「同义且都是无需介入」的 happy→calm；其余未知标签一律 raise，不得放宽 fail-closed。
PLATFORM_LABEL_ALIASES = {"happy": "calm"}

# 快照缺失/非法时的兜底；任何一项不合法都不允许放宽门（fail-closed）
DEFAULT_SER_POLICY: dict[str, float] = {
    "minSegSec": 1.0,
    "maxSegSec": 30.0,
    "maxConcurrency": 2,
    "failThreshold": 3,
    "cooldownSec": 60,
}
# §10.1⑭ 定版的 serPolicy 五字段；minConfidence 属顶层配置，可选下发
REQUIRED_POLICY_KEYS = tuple(DEFAULT_SER_POLICY)


def labels_supported() -> list[str]:
    return list(SER_EMOTIONS)


def normalize_label(raw: str) -> str:
    """兼容映射辅助：官方原始标签 → 平台五值；未知/拒分类一律抛错，绝不映射成 calm。"""
    if not raw:
        raise ValueError("SER 返回空标签")
    key = str(raw).strip().lower()
    if key in REJECTED_LABELS:
        raise ValueError(f"SER 模型主动拒分类: {raw}")
    if key in SER_EMOTIONS:
        return key
    if key in LABEL_MAP:
        return LABEL_MAP[key]
    raise ValueError(f"SER 标签集与映射表不一致: {raw}")


class SerRejectedException(RuntimeError):
    """业务拒答（SILENCE / LOW_CONFIDENCE / LOW_MARGIN 等），**不是**服务不可用。

    2026-11-24 实测 137：此类情况服务端返回 HTTP 409 并带结构化 error.code。
    按 §4.3「门未命中不计失败」的精神，拒答不得计入断路器失败计数，
    否则模型对静音段频繁拒答会误触断路、连带停掉整场声学分析。
    """


@dataclass(frozen=True)
class SerResult:
    """§4.1：服务侧自报模型标识，平台只透传不解释。"""

    emotion: str
    confidence: float
    model: str
    latency_ms: int = 0

    @classmethod
    def from_response(cls, body: Any) -> "SerResult":
        """§4.2/§10.2：未知 emotion、confidence 越界、缺字段三种畸形响应一律 raise。

        2026-11-24：137 SenseVoiceSmall 的标签集为 6 值（多 ``happy``），
        经 {@link PLATFORM_LABEL_ALIASES} 归一到平台五值后再校验，其余未知标签仍 raise。
        """
        if not isinstance(body, Mapping):
            raise ValueError("SER 返回体不是 JSON 对象")
        for key in ("emotion", "confidence", "model"):
            if key not in body or body[key] is None:
                raise ValueError(f"SER 返回体缺少字段: {key}")
        emotion = str(body["emotion"]).strip().lower()
        if emotion not in SER_EMOTIONS:
            emotion = PLATFORM_LABEL_ALIASES.get(emotion, emotion)
        if emotion not in SER_EMOTIONS:
            raise ValueError(f"SER 返回未知 emotion: {body['emotion']!r}")
        try:
            confidence = float(body["confidence"])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"SER confidence 非法: {body['confidence']!r}") from exc
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"SER confidence 越界: {confidence}")
        model = str(body["model"]).strip()
        if not model:
            raise ValueError("SER 返回空 model")
        try:
            latency_ms = int(body.get("latencyMs") or body.get("latency_ms") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("SER latencyMs 非法") from exc
        return cls(emotion=emotion, confidence=confidence, model=model, latency_ms=latency_ms)

    def as_dict(self) -> dict:
        return {"emotion": self.emotion, "confidence": self.confidence,
                "model": self.model, "latencyMs": self.latency_ms}

    def __getitem__(self, key: str) -> Any:
        """兼容旧版 dict 取值写法（worker 早期实现），不引入第二份数据结构。"""
        return self.as_dict()[key]


class SerProvider:
    """抽象基类：与 AsrProvider 同构，未实现时显式 NotImplementedError。"""

    def predict(self, pcm16_bytes: bytes, sample_rate: int) -> SerResult:
        raise NotImplementedError


class HttpSerProvider(SerProvider):
    """§4.2：multipart WAV 打到 nginx 前缀之后的 /v1/audio/emotion。"""

    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 timeout_seconds: float | None = None, health_path: str | None = None) -> None:
        base = base_url or os.environ.get("SER_GATEWAY_BASE_URL") \
            or os.environ.get("SER_BASE_URL")
        if not base:
            raise ValueError("MEETING_SER_PROVIDER_UNCONFIGURED: SER_GATEWAY_BASE_URL 未配置")
        self.base = base.rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("SER_API_KEY", "")
        self.timeout = timeout_seconds if timeout_seconds is not None else (
            float(os.environ.get("SER_TIMEOUT_MS", "1500")) / 1000)
        # 探活路径随服务形态而变：自建 emotion2vec 容器是 /health，
        # 137 语音情感识别服务是 /v1/audio/emotion/health（2026-11-24 实测）。
        raw_path = health_path if health_path is not None else os.environ.get("SER_HEALTH_PATH", "/health")
        self.health_path = raw_path if raw_path.startswith("/") else "/" + raw_path

    def predict(self, pcm16_bytes: bytes, sample_rate: int) -> SerResult:
        if not pcm16_bytes:
            raise ValueError("MEETING_SER_AUDIO_EMPTY: 空音频段不得返回 calm")
        wav = _to_wav(pcm16_bytes, sample_rate)
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        resp = requests.post(
            f"{self.base}/v1/audio/emotion",
            files={"file": ("seg.wav", wav, "audio/wav")},
            data={"sample_rate": str(sample_rate), "language": "zh"},
            headers=headers,
            timeout=self.timeout,
        )
        status = getattr(resp, "status_code", None)
        if status is not None and int(status) == 409:
            # 业务拒答（静音/低置信/低余量）：不是故障，不得计入断路
            raise SerRejectedException("MEETING_SER_REJECTED: 服务端拒答（HTTP 409）")
        if status is None or not 200 <= int(status) < 300:
            raise RuntimeError(f"MEETING_SER_PROVIDER_UNAVAILABLE: HTTP {status}")
        try:
            body = resp.json()
        except Exception as exc:
            raise RuntimeError(f"MEETING_SER_LABELS_MISMATCH: 非法 JSON: {exc}") from exc
        try:
            return SerResult.from_response(body)
        except ValueError as exc:
            raise RuntimeError(f"MEETING_SER_LABELS_MISMATCH: {exc}") from exc

    def health(self) -> dict:
        """§4.2 探活：失败由调用方按 fail-closed 处理，不返回默认结论。"""
        headers = {"X-API-Key": self.api_key} if self.api_key else {}
        resp = requests.get(f"{self.base}{self.health_path}", headers=headers, timeout=self.timeout)
        status = getattr(resp, "status_code", None)
        if status is None or not 200 <= int(status) < 300:
            raise RuntimeError(f"MEETING_SER_PROVIDER_UNAVAILABLE: health HTTP {status}")
        return resp.json()


# 旧版命名兼容别名（部署件与历史文档曾引用）
Emotion2VecSerProvider = HttpSerProvider


def get_ser_provider() -> SerProvider:
    """未配置 / 未知 provider 一律显式 raise；宁可 worker 起不来，也不出假标签。

    2026-11-24：新增 ``sensevoice`` 指代 137 语音情感识别服务（内嵌 SenseVoiceSmall），
    与自建 ``emotion2vec`` 容器共用同一 HTTP 契约，差异只在探活路径与标签集归一。
    """
    name = os.environ.get("SER_PROVIDER", "none").lower()
    if name in ("emotion2vec", "sensevoice"):
        return HttpSerProvider()
    raise ValueError(f"MEETING_SER_PROVIDER_UNCONFIGURED: 未实现的 SER_PROVIDER={name!r}")


def fetch_switch_snapshot(base_url: str, room_sid: str, token: str,
                          timeout: float = 5) -> dict:
    """§3.2 步骤 1：401/404/超时/非法 JSON → 返回 {}（fail-closed），并打印一次状态码。

    单独成函数是为了可离线单测：worker 本体依赖 LiveKit 房间，不进纯函数测试。
    """
    try:
        resp = requests.get(
            f"{base_url.rstrip('/')}/admin-api/ai/meeting/internal/analyze/switch",
            params={"roomSid": room_sid},
            headers={"X-Internal-Token": token, "tenant-id": os.environ.get("MEETING_TENANT_ID", "1")},
            timeout=timeout,
        )
        status = getattr(resp, "status_code", None)
        if status is None or not 200 <= int(status) < 300:
            print(f"[worker] switch 快照 HTTP {status} room={room_sid}")
            return {}
        try:
            body = resp.json()
        except Exception as exc:
            print(f"[worker] switch 快照非法 JSON room={room_sid}: {exc}")
            return {}
        if not isinstance(body, Mapping):
            return {}
        return body.get("data") or {}
    except Exception as exc:
        print(f"[worker] switch 快照不可达 room={room_sid}: {exc}")
        return {}


def parse_switch_snapshot(body: Any) -> dict:
    """§3.2 步骤 1 / 评审 C19：把 Java 快照归一化成固定三开关 + 可选策略块。

    HTTP 500 / 超时 / 非法 JSON / `ser` 键缺失 / 策略块不完整 → 一律 ser=false
    （fail-closed）。策略块是**可选扩展**：`serPolicy` 缺任何必需字段即关闭声学能力，
    `facePolicy` 缺失或非映射即关闭画面侧能力，worker 都不自行猜阈值。
    本 worker 当前不实现任何人脸/视频任务，faceEnabled 恒为 False 是显式的 fail-closed 门，
    不等于「G0 已通过」（SP-3 生效版 §9）。
    """
    closed = {"voice": False, "ser": False, "video": False,
              "serPolicy": dict(DEFAULT_SER_POLICY), "policyComplete": False,
              "facePolicy": {}, "facePolicyComplete": False, "faceEnabled": False}
    if not isinstance(body, Mapping):
        return closed
    data = body.get("data", body)  # CommonResult 包装或直接快照
    if not isinstance(data, Mapping):
        return closed
    policy_raw = data.get("serPolicy")
    if not isinstance(policy_raw, Mapping):
        return closed
    policy: dict[str, float] = {}
    for key in REQUIRED_POLICY_KEYS:
        value = policy_raw.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            return closed
        policy[key] = float(value)
    if policy["minSegSec"] > policy["maxSegSec"]:
        return closed
    poll = data.get("switchPollIntervalSeconds", 30)
    poll_seconds = float(poll) if isinstance(poll, (int, float)) and not isinstance(poll, bool) \
        and poll > 0 else 30.0
    face_raw = data.get("facePolicy")
    face_complete = isinstance(face_raw, Mapping) and bool(face_raw)
    return {
        "voice": data.get("voice") is True,
        "ser": data.get("ser") is True,
        "video": data.get("video") is True,
        "serPolicy": policy,
        "policyComplete": True,
        "facePolicy": dict(face_raw) if face_complete else {},
        "facePolicyComplete": face_complete,
        "faceEnabled": data.get("video") is True and face_complete,
        "pollIntervalSec": poll_seconds,
    }


def in_segment_window(pcm_len: int, sample_rate: int, policy: Mapping) -> bool:
    """§4.3 段长门：len(pcm)/(sample_rate*2) 秒须 ∈ [minSegSec, maxSegSec]，闭区间。"""
    if sample_rate <= 0 or pcm_len <= 0:
        return False
    duration = pcm_len / (sample_rate * 2)
    return float(policy["minSegSec"]) <= duration <= float(policy["maxSegSec"])


class SerConcurrencyGate:
    """§4.3 并发门：非阻塞获取，满则放弃本段并计数，绝不等位拖慢字幕。"""

    def __init__(self, limit: int = 2) -> None:
        self.limit = max(1, int(limit))
        self.skipped = 0
        self._inflight = 0
        self._lock = threading.Lock()

    def try_enter(self) -> bool:
        with self._lock:
            if self._inflight >= self.limit:
                self.skipped += 1
                return False
            self._inflight += 1
            return True

    def exit(self) -> None:
        with self._lock:
            self._inflight = max(0, self._inflight - 1)

    @property
    def inflight(self) -> int:
        with self._lock:
            return self._inflight


class SerCircuitBreaker:
    """§4.3 断路器：连续失败达阈 → OPEN 冷却；冷却到期半开，成功即闭合。"""

    def __init__(self, fail_threshold: int = 3, cooldown_sec: float = 60,
                 clock=time.monotonic) -> None:
        self.fail_threshold = max(1, int(fail_threshold))
        self.cooldown_sec = float(cooldown_sec)
        self._clock = clock
        self.failures = 0
        self.opened_at: float | None = None
        self._half_open = False

    @property
    def is_open(self) -> bool:
        return self.opened_at is not None

    def allow(self) -> bool:
        if self.opened_at is None:
            return True
        if self._clock() - self.opened_at < self.cooldown_sec:
            return False
        self._half_open = True  # 半开：只放一次探测
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None
        self._half_open = False

    def record_failure(self) -> None:
        self.failures += 1
        if self._half_open or self.failures >= self.fail_threshold:
            self.opened_at = self._clock()
            self._half_open = False
