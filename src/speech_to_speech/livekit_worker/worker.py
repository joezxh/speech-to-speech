"""LiveKit Agents 会议转录 worker（M10 + SP-4）。

以参会者身份进入 LiveKit 房间，逐个订阅远端音频轨，用 ``silero`` VAD 切段，
每段落静默后调用可插拔 ``AsrProvider``（gateway 默认走 OpenAI 兼容网关，local
复用 pipeline 已解析的 STT handler）转写，并**并行**调用可插拔 ``SerProvider``
（SP-4，仅服务端快照 ser=true 时才发起），再经双路输出（``emit_segments``）：
- 进程内事件总线（``events.get_event_bus``，本地转写/日志 sink）；
- callback 子系统 ``CallbackDispatcher.publish_transcript``（Task 12 前缺失时仅告警）。

版本与验收契约（对齐实施计划 M10 说明）：
- 目标 ``livekit-agents~=0.12``：使用 ``rtc.AudioStream`` 读取帧、``silero.VAD.load()``
  的 ``stream()`` 事件（``SpeechEventType.START_OF_SPEECH`` / ``END_OF_SPEECH``）驱动分段。
- 本 worker 是**集成件、非单元 TDD**：完整链路（进房→逐轨 VAD→ASR/SER→输出）依赖
  真实 LiveKit 房间，由部署/端到端冒烟验收；纯函数（``split_pcm_blocks`` 等）可离线单测。
- 单实例本期串行处理 2–4 轨（M20）；生产并发/多副本再评估。
- SP-4 隐私：PCM 只在产生它的进程内存中存活，不落盘、不进日志、不进数据库。
"""
from __future__ import annotations

import asyncio
import os
import time

from livekit import rtc
from livekit.agents import JobContext, WorkerOptions, cli
from livekit.agents.job import AutoSubscribe
from livekit.agents.vad import VAD, VADEventType
from livekit.plugins import silero

import speech_to_speech.livekit_worker.diarization_provider as dia
from speech_to_speech.livekit_worker.asr_provider import create_asr_provider
from speech_to_speech.livekit_worker.audio_level import compute_audio_level_dbfs
from speech_to_speech.livekit_worker.events import TranscriptEvent, get_event_bus
from speech_to_speech.livekit_worker.segment_dedupe import DuplicateGuard
from speech_to_speech.livekit_worker.ser_provider import (
    DEFAULT_SER_POLICY,
    SerCircuitBreaker,
    SerConcurrencyGate,
    SerRejectedException,
    get_ser_provider,
    in_segment_window,
    parse_switch_snapshot,
)
from speech_to_speech.livekit_worker.ser_provider import (
    fetch_switch_snapshot as fetch_switch_snapshot_raw,
)

# identify_provider 尚未移植进本仓：模块级探测，缺失时声纹标注 fail-closed 停用。
try:
    from speech_to_speech.livekit_worker.identify_provider import get_client as get_identify_client
    from speech_to_speech.livekit_worker.identify_provider import is_fresh
except ImportError:  # pragma: no cover - 移植 identify_provider 前恒走此分支
    get_identify_client = None  # type: ignore[assignment]
    is_fresh = lambda checked_at, ttl_seconds=30.0: False  # noqa: E731 - 兜底：能力快照永不可用

# livekit-agents 0.12.x 健康检查 HTTP 服务在 prod 模式默认绑 8081；本机 8081 已被
# UAA 等 Spring Boot 服务占用，Windows 上会因端口冲突抛 PermissionError[Errno 13] 而非
# Address already in use，导致 worker 启动即失败。默认改绑空闲的 18081，可按需覆盖。
HEALTH_PORT = int(os.environ.get("LIVEKIT_WORKER_HEALTH_PORT", "18081"))
# agent 名：默认「会议秘书」（会议转录 agent）。
# 服务端 CreateDispatch 必须携带同名 agent_name 才能精确派发到本 worker；
# 若把服务端 livekit.agent-name 留空（不限定），则任何空闲 worker 都会接单。
AGENT_NAME = os.environ.get("LIVEKIT_AGENT_NAME", "会议秘书").strip() or "会议秘书"
# 容量阈值：livekit-agents prod 模式默认按 CPU 负载 0.75 判满（超过即标记 unavailable，
# server 不再派发 job）。开发机跑着 IDEA/Java/Docker/浏览器，负载常态就在 0.75 上下，
# 会反复 full capacity → 派发落空；显式放宽到 0.95，可用环境变量覆盖。
LOAD_THRESHOLD = float(os.environ.get("LIVEKIT_LOAD_THRESHOLD", "0.95"))
SAMPLE_RATE = 16000
SWITCH_POLL_SECONDS = 30

# ---- 转录准确率调参（V3.70）----
# VAD 切段：默认 min_silence=0.55s 在会议里停顿即切句，产出大量 1~3 字碎段
# （"嗯。""基金。"），ASR 拿不到上下文导致错误率高；放宽静默与最短语音门，
# 让段落贴近自然句长。均可用环境变量覆盖。
VAD_MIN_SILENCE_SEC = float(os.environ.get("VAD_MIN_SILENCE_SEC", "0.8"))
VAD_MIN_SPEECH_SEC = float(os.environ.get("VAD_MIN_SPEECH_SEC", "0.2"))
VAD_PREFIX_PADDING_SEC = float(os.environ.get("VAD_PREFIX_PADDING_SEC", "0.5"))
# 超长段分块：网关 ASR 请求超时 30s，连续长发言整段送转写会超时 → 整段内容丢失；
# 超过阈值按块切分逐块转写再拼接（块间不做拼接修复，保持逐块原文）。
ASR_MAX_SEGMENT_SEC = float(os.environ.get("ASR_MAX_SEGMENT_SEC", "25"))
# 单段 ASR 请求失败重试次数（网络抖动兜底；重试失败才丢弃该块）
ASR_MAX_ATTEMPTS = int(os.environ.get("ASR_MAX_ATTEMPTS", "2"))
# V3.71：说话中强制切段阈值——持续不断的长时间声音（连续发言/噪声/电视声）会让 VAD
# 永远不触发 END_OF_SPEECH，段无限缓冲导致「转写一直没有结果」。超过该秒数即把已
# 积累的缓冲强制送转写（VAD 仍继续，不打断监听），后续声音进入下一段。
MAX_SPEECH_SEC = float(os.environ.get("MAX_SPEECH_SEC", "20"))


# ---- Java 回调凭据（惰性读取：导入期不再强制要求环境变量，serve 内嵌线程按需取用）----
def _env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if value is None and required:
        raise ValueError(f"--with-livekitworker 需要 {name}")
    return value


def java_base() -> str:
    return (_env("JAVA_CALLBACK_BASE", required=True) or "").rstrip("/")


def internal_token() -> str:
    return _env("MEETING_INTERNAL_TOKEN", required=True) or ""


def tenant_id() -> str:
    return _env("MEETING_TENANT_ID", "1") or "1"


_provider = None
_shared_state: dict[str, object] = {}
_ser_provider = None
_switch_caches: dict[str, "AnalyzeSwitchCache"] = {}
_identify_client = None
_vad_instance = None
_diarization_client = None
# room_sid -> (是否可标注, 检查时间)；30s 复用，避免每段都打 capability
_identify_caps: dict[str, tuple[bool, float]] = {}
_dup_guard = DuplicateGuard()
# identity -> 当前音轨转写任务；同一人重发音轨时取消旧任务，避免双轨重复转写
_track_tasks: dict[str, asyncio.Task] = {}
# identify_provider 缺失的哨兵：缓存「不可用」结论，避免每段都重试导入并刷日志
_IDENTIFY_UNAVAILABLE = object()


def set_shared_state(**kwargs: object) -> None:
    """LiveKitWorkerRuntime 启动时注入共享状态（STT handler、共享 stop_event）。"""
    _shared_state.update(kwargs)


def _stt_handler_instance():
    """local ASR 模式的 STT handler 注入点：由 LiveKitWorkerRuntime 在启动时设置。"""
    return _shared_state.get("stt_handler")


def asr_provider():
    """ASR provider 惰性解析（gateway | local），导入期不读环境、不建连接。"""
    global _provider
    if _provider is None:
        _provider = create_asr_provider(
            os.environ.get("LIVEKIT_WORKER_ASR_MODE", "gateway").strip().lower(),
            stt_handler=_stt_handler_instance(),
        )
    return _provider


def emit_segments(room_sid: str, segments: list[dict]) -> None:
    """转写分段双路输出：进程内事件总线（本地转写/日志）+ CallbackDispatcher 回调。

    任何一路失败仅告警，不阻断另一路与其它轨。
    """
    for seg in segments:
        try:
            get_event_bus().publish(TranscriptEvent(
                event_type="transcript",
                room_sid=room_sid,
                identity=str(seg.get("speakerIdentity", "")),
                text=str(seg.get("text", "")),
                start_ts=int(seg.get("startTs", 0)),
                end_ts=int(seg.get("endTs", 0)),
                audio_level=seg.get("audioLevel"),
                extra={k: v for k, v in seg.items()
                       if k not in ("speakerIdentity", "text", "startTs", "endTs", "audioLevel")},
                timestamp_ms=int(time.time() * 1000),
            ))
        except Exception as exc:  # noqa: BLE001 单段事件失败不拖垮其余分段
            print(f"[worker] local transcript sink 失败 room={room_sid}: {exc}", flush=True)
    try:
        from speech_to_speech.callback.dispatcher import get_dispatcher

        get_dispatcher().publish_transcript(room_sid, segments)
    except Exception as exc:  # noqa: BLE001 回调子系统故障不影响转写（Task 12 之前 dispatcher 不存在，走此分支）
        print(f"[worker] callback dispatch 失败 room={room_sid}: {exc}", flush=True)


def _emit_session_end(room_sid: str) -> None:
    """房间断开时产出 session_end 事件（本地归档等下游消费）；回调路失败仅告警。"""
    event = TranscriptEvent(
        event_type="session_end", room_sid=room_sid, identity="", text="",
        start_ts=0, end_ts=int(time.time() * 1000), audio_level=None,
        extra={}, timestamp_ms=int(time.time() * 1000),
    )
    get_event_bus().publish(event)
    try:
        from speech_to_speech.callback.dispatcher import get_dispatcher

        get_dispatcher().dispatch(event)
    except Exception as exc:  # noqa: BLE001
        print(f"[worker] session_end 回调失败 room={room_sid}: {exc}", flush=True)


def fetch_switch_snapshot(room_sid: str) -> dict:
    """拉取服务端权威开关快照；任何失败一律 fail-closed（返回空 dict）。"""
    return fetch_switch_snapshot_raw(java_base(), room_sid, internal_token())


class AnalyzeSwitchCache:
    """spec §3.2 步骤 1：每 30s 拉一次；首次/任一次失败即 ser=false，零外呼。"""

    def __init__(self, room_sid: str) -> None:
        self.room_sid = room_sid
        self.snapshot = parse_switch_snapshot({})

    def refresh(self) -> dict:
        self.snapshot = parse_switch_snapshot(fetch_switch_snapshot(self.room_sid))
        return self.snapshot

    @property
    def ser_enabled(self) -> bool:
        return bool(self.snapshot["ser"]) and bool(self.snapshot["policyComplete"])

    @property
    def policy(self) -> dict:
        return self.snapshot["serPolicy"]

    @property
    def face_enabled(self) -> bool:
        """C19：facePolicy 是可选策略块；缺失时画面侧能力 fail-closed。

        本 worker 不实现人脸/视频任务，该门只用于锁死契约，不得据此推断 G0 已通过。
        """
        return bool(self.snapshot.get("faceEnabled")) and bool(self.snapshot.get("facePolicyComplete"))

    @property
    def poll_seconds(self) -> float:
        return float(self.snapshot.get("pollIntervalSec", SWITCH_POLL_SECONDS))


def switch_cache(room_sid: str) -> AnalyzeSwitchCache:
    cache = _switch_caches.get(room_sid)
    if cache is None:
        cache = AnalyzeSwitchCache(room_sid)
        _switch_caches[room_sid] = cache
    return cache


async def switch_poll_loop(room_sid: str) -> None:
    cache = switch_cache(room_sid)
    while True:
        await asyncio.to_thread(cache.refresh)
        await asyncio.sleep(cache.poll_seconds)


def _ser_provider_instance():
    """只在 ser 真正开启后才解析 provider；未配置显式抛错，绝不返回假标签。"""
    global _ser_provider
    if _ser_provider is None:
        _ser_provider = get_ser_provider()
    return _ser_provider


def maybe_ser(cache: AnalyzeSwitchCache, pcm_bytes: bytes,
              gate: SerConcurrencyGate, breaker: SerCircuitBreaker) -> dict:
    """同步执行（由 to_thread offload）：四道门 + 失败计断路；不产告警、不重试。"""
    if not cache.ser_enabled:
        return {}
    policy = cache.policy
    if not in_segment_window(len(pcm_bytes), SAMPLE_RATE, policy):
        return {}                      # 段长门：不发起、不计失败
    if not breaker.allow():
        return {}                      # 断路器 OPEN：不发起、不计失败
    if not gate.try_enter():
        return {}                      # 并发门：放弃本段，绝不等位
    try:
        result = _ser_provider_instance().predict(pcm_bytes, SAMPLE_RATE)
        breaker.record_success()
        return {
            "serEmotion": result.emotion,
            "serConfidence": result.confidence,
            "serModel": result.model,
        }
    except SerRejectedException:
        # 业务拒答（静音/低置信）：不是故障，不计断路失败（§4.3 门未命中不计失败）
        return {}
    except Exception:
        breaker.record_failure()
        raise
    finally:
        gate.exit()


def _identify_provider_instance():
    """声纹 provider 惰性解析；identify_provider 未移植时返回 None（fail-closed 停用）。"""
    global _identify_client
    if _identify_client is None:
        if get_identify_client is None:
            print("[worker] identify_provider 未部署，声纹标注停用（fail-closed）", flush=True)
            _identify_client = _IDENTIFY_UNAVAILABLE
        else:
            _identify_client = get_identify_client()
    return None if _identify_client is _IDENTIFY_UNAVAILABLE else _identify_client


def diarization_client():
    """说话人分离客户端（惰性）；DIARIZATION_BASE_URL 未配置返回 None = 功能关闭。"""
    global _diarization_client
    if _diarization_client is None:
        _diarization_client = dia.get_client()
    return _diarization_client


async def identify_available(room_sid: str) -> bool:
    """30s 复用服务端门禁快照；任何异常 fail-closed（不上传音频）。"""
    provider = _identify_provider_instance()
    if provider is None:
        return False
    cached = _identify_caps.get(room_sid)
    if cached is not None and is_fresh(cached[1]):
        return cached[0]
    try:
        enabled = await asyncio.to_thread(provider.capability, room_sid)
    except Exception as exc:
        print(f"[worker] identify capability 失败 room={room_sid}: {type(exc).__name__}")
        enabled = False
    _identify_caps[room_sid] = (enabled, time.time())
    return enabled


async def maybe_identify(room_sid: str, pcm_bytes: bytes) -> dict:
    """被动声纹标注：只回传可空扩展字段；失败一律 {}，不影响字幕链路。"""
    if not await identify_available(room_sid):
        return {}
    try:
        return await asyncio.to_thread(
            _identify_provider_instance().identify, room_sid, pcm_bytes, SAMPLE_RATE)
    except Exception as exc:
        # 只打异常类型，不打印音频/向量/回包
        print(f"[worker] identify 失败 room={room_sid}: {type(exc).__name__}")
        return {}


def _shared_vad() -> VAD:
    """ONNX 模型较大（每实例约 50MB），全进程只加载一份，每人各开一个 stream。

    切段参数取转录调优值（V3.70）：更长的静默门 + 最短语音门，减少碎段，
    让 ASR 每段拿到完整句上下文（详见模块头 VAD_MIN_SILENCE_SEC 注释）。
    """
    global _vad_instance
    if _vad_instance is None:
        _vad_instance = silero.VAD.load(
            sample_rate=SAMPLE_RATE,
            min_silence_duration=VAD_MIN_SILENCE_SEC,
            min_speech_duration=VAD_MIN_SPEECH_SEC,
            prefix_padding_duration=VAD_PREFIX_PADDING_SEC,
        )
    return _vad_instance


def split_pcm_blocks(pcm16_bytes: bytes, sample_rate: int,
                     max_block_sec: float = ASR_MAX_SEGMENT_SEC) -> list[bytes]:
    """把一段 PCM16 按秒数切成若干块（末块可短）。

    纯函数，可离线单测。用于超长发言分块送 ASR，避免网关 30s 请求超时整段丢失。
    """
    if max_block_sec <= 0:
        return [pcm16_bytes] if pcm16_bytes else []
    block_bytes = int(sample_rate * 2 * max_block_sec)  # 16bit mono = 2 bytes/frame
    if len(pcm16_bytes) <= block_bytes:
        return [pcm16_bytes] if pcm16_bytes else []
    return [bytes(pcm16_bytes[i:i + block_bytes])
            for i in range(0, len(pcm16_bytes), block_bytes)]


def transcribe_with_retry(pcm16_bytes: bytes, sample_rate: int) -> str:
    """分块转写 + 单块有限重试；任一块彻底失败即抛异常（调用方按段丢弃并告警）。

    同步函数，由 to_thread offload。块文本直接拼接：VAD 静默门已保证块边界
    大概率落在停顿处，拼接语义接近原文。
    """
    blocks = split_pcm_blocks(pcm16_bytes, sample_rate)
    parts: list[str] = []
    for block in blocks:
        last_exc: Exception | None = None
        for _ in range(max(1, ASR_MAX_ATTEMPTS)):
            try:
                text = asr_provider().transcribe(block, sample_rate)
                last_exc = None
                break
            except Exception as exc:  # noqa: BLE001 网关抖动兜底
                last_exc = exc
        if last_exc is not None:
            raise last_exc
        if text and text.strip():
            parts.append(text.strip())
    return "".join(parts)


async def _speaker_pipeline(room_sid: str, identity: str, speaker: int,
                            subs: list[tuple[bytes, float, float]],
                            started_ms: int, cache: "AnalyzeSwitchCache",
                            gate: SerConcurrencyGate, breaker: SerCircuitBreaker
                            ) -> list[dict]:
    """单个 diarization speaker 的完整流水线：代表子段声纹/SER → 逐子段 ASR → 分段列表。

    子段文本天然按人拆分（diarization 时间段切片）；任一子段 ASR 失败只丢该子段。
    声纹/SER 标注作用于该 speaker 全部子段（同一人）。
    """
    rep_pcm, _rep_start, _rep_end = dia.pick_representative(subs)

    # 声纹归属：代表子段（最纯的该说话人声音）打 1:N 识别
    identify_fields: dict = {}
    if await identify_available(room_sid):
        try:
            identify_fields = await asyncio.to_thread(
                _identify_provider_instance().identify, room_sid, rep_pcm, SAMPLE_RATE)
        except Exception as exc:
            print(f"[worker] identify 失败 room={room_sid}: {type(exc).__name__}")

    # SER：只跑代表子段（多为单人语音，符合段长门）；结果挂该 speaker 全部子段
    ser_fields: dict = {}
    policy = cache.policy
    gate.limit = max(1, int(policy["maxConcurrency"]))
    breaker.fail_threshold = max(1, int(policy["failThreshold"]))
    breaker.cooldown_sec = float(policy["cooldownSec"])
    if (cache.ser_enabled and in_segment_window(len(rep_pcm), SAMPLE_RATE, policy)
            and breaker.allow() and gate.inflight < gate.limit):
        try:
            ser_fields = await asyncio.to_thread(maybe_ser, cache, rep_pcm, gate, breaker)
        except Exception as exc:
            print(f"[worker] ser 失败(代表子段) room={room_sid}: {type(exc).__name__}")

    segments: list[dict] = []
    for sub_pcm, sub_start, sub_end in subs:
        try:
            text = await asyncio.to_thread(transcribe_with_retry, sub_pcm, SAMPLE_RATE)
        except Exception as exc:
            print(f"[worker] ASR 失败(子段) room={room_sid}: {exc}")
            continue
        if not text or not text.strip():
            continue
        start_ts, end_ts = dia.to_epoch_ms(started_ms, sub_start, sub_end)
        if _dup_guard.should_skip(identity, text, start_ts):
            print(f"[worker] 近重复分段已跳过 identity={identity} text={text[:20]}", flush=True)
            continue
        segment = {
            "speakerIdentity": identity,
            "text": text,
            "startTs": start_ts,
            "endTs": end_ts,
            "audioLevel": compute_audio_level_dbfs(sub_pcm),
        }
        segment.update(ser_fields)
        segment.update(identify_fields)
        segments.append(segment)
    if segments:
        tag = identify_fields.get("speakerName") or identify_fields.get("speakerCode") or "未标注"
        print(f"[worker] diarization speaker={speaker} → 转录标注 {tag}，"
              f"子段 {len(segments)}/{len(subs)} 已转写", flush=True)
    return segments


async def process_diarized(room_sid: str, identity: str, pcm_bytes: bytes,
                           started_ms: int, cache: "AnalyzeSwitchCache",
                           gate: SerConcurrencyGate, breaker: SerCircuitBreaker
                           ) -> bool:
    """diarization 主路径：整段 → 按说话人切子段 → 子段 ASR/声纹 → 逐子段输出。

    返回 True 表示已按子段处理；False 表示应回退整段路径（未启用/服务失败/无有效子段）。
    本函数绝不抛异常：任何失败都降级为 False。
    """
    client = diarization_client()
    if client is None:
        return False
    try:
        segments = await asyncio.to_thread(client.diarize, pcm_bytes, SAMPLE_RATE)
        subs_by_speaker = client.slice(pcm_bytes, SAMPLE_RATE, segments)
    except Exception as exc:
        print(f"[worker] diarization 不可用，回退整段 room={room_sid}: {type(exc).__name__}")
        return False
    if not subs_by_speaker:
        print(f"[worker] diarization 无有效说话人，回退整段 room={room_sid}", flush=True)
        return False
    try:
        results = await asyncio.gather(
            *(_speaker_pipeline(room_sid, identity, spk, subs, started_ms, cache, gate, breaker)
              for spk, subs in subs_by_speaker.items()),
            return_exceptions=True,
        )
    except Exception as exc:  # noqa: BLE001 gather 收集阶段兜底
        print(f"[worker] diarization 流水线异常，回退整段 room={room_sid}: {type(exc).__name__}")
        return False
    merged: list[dict] = []
    for res in results:
        if isinstance(res, BaseException):
            print(f"[worker] speaker 流水线失败 room={room_sid}: {res}")
            continue
        merged.extend(res)
    if merged:
        merged.sort(key=lambda s: s["startTs"])
        emit_segments(room_sid, merged)
        return True
    # 所有子段均无有效文本：视为已处理（整段也大概率无文本），避免重复转写
    return True


async def _handle_chunk(room_sid: str, identity: str, pcm_bytes: bytes,
                        chunk_started_ms: int, cache: "AnalyzeSwitchCache",
                        gate: SerConcurrencyGate, breaker: SerCircuitBreaker) -> None:
    """一个语音段的完整处理：diarization 主路径 → 失败回退整段 ASR/SER/identify → 输出。"""
    if len(pcm_bytes) < int(SAMPLE_RATE * 2 * 0.4):  # <0.4s 的碎片段直接丢弃
        return
    # V3.71 主路径：diarization 场景区分（未启用/失败 → 返回 False 走下方整段回退）
    try:
        if await process_diarized(room_sid, identity, pcm_bytes, chunk_started_ms,
                                  cache, gate, breaker):
            return
    except Exception as exc:  # noqa: BLE001 流水线兜底，绝不因异常丢整段
        print(f"[worker] diarization 流水线异常，回退整段 room={room_sid}: {type(exc).__name__}")

    # 整段回退（V3.70）：SER/声纹标注与 ASR 重叠而非串联；ASR 走分块转写避免网关超时
    tasks: dict[str, asyncio.Task] = {
        "asr": asyncio.to_thread(transcribe_with_retry, pcm_bytes, SAMPLE_RATE)
    }
    policy = cache.policy
    gate.limit = max(1, int(policy["maxConcurrency"]))
    breaker.fail_threshold = max(1, int(policy["failThreshold"]))
    breaker.cooldown_sec = float(policy["cooldownSec"])
    ser_allowed = (cache.ser_enabled
                   and in_segment_window(len(pcm_bytes), SAMPLE_RATE, policy)
                   and breaker.allow() and gate.inflight < gate.limit)
    if ser_allowed:
        tasks["ser"] = asyncio.to_thread(maybe_ser, cache, pcm_bytes, gate, breaker)
    if await identify_available(room_sid):
        tasks["identify"] = maybe_identify(room_sid, pcm_bytes)

    names = list(tasks)
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    resolved = dict(zip(names, results))
    asr_result = resolved["asr"]
    if isinstance(asr_result, BaseException):
        print(f"[worker] ASR 失败 room={room_sid}: {asr_result}")
        return
    text = asr_result
    ser_fields: dict = {}
    ser_result = resolved.get("ser")
    if isinstance(ser_result, BaseException):
        # §5.5：不产告警、不重试、不影响文本链路与字幕链路
        print(f"[worker] ser 不可用 room={room_sid}: {ser_result}")
    elif isinstance(ser_result, dict):
        ser_fields = ser_result
    identify_fields: dict = {}
    identify_result = resolved.get("identify")
    if isinstance(identify_result, BaseException):
        print(f"[worker] identify 不可用 room={room_sid}: {type(identify_result).__name__}")
    elif isinstance(identify_result, dict):
        identify_fields = identify_result

    if text and text.strip():
        segment = {
            "speakerIdentity": identity,
            "text": text,
            "startTs": chunk_started_ms,
            "endTs": chunk_started_ms + len(pcm_bytes) // (SAMPLE_RATE * 2) * 1000,
            # audioLevel 为 SP-2 一级门输入；下游可空，旧端不消费亦不报错
            "audioLevel": compute_audio_level_dbfs(pcm_bytes),
        }
        segment.update(ser_fields)
        segment.update(identify_fields)
        if _dup_guard.should_skip(identity, text, chunk_started_ms):
            print(f"[worker] 近重复分段已跳过 identity={identity} text={text[:20]}", flush=True)
            return
        emit_segments(room_sid, [segment])


async def transcribe_track(room_sid: str, identity: str, track: rtc.AudioTrack) -> None:
    """订阅单条音频轨：VAD 起止 + 自管理缓冲 → 段处理（diarization/整段）→ 输出。

    V3.71：PCM 缓冲由本协程自管理（VAD 只提供起止信号）——持续不断的长时间声音
    不再无限缓冲：说话中每 MAX_SPEECH_SEC 秒强制把已积累缓冲送转写（VAD 监听不中断），
    之后的声音进入下一段。段处理以任务并发执行，不阻塞帧消费。
    """
    stream = rtc.AudioStream(track, sample_rate=SAMPLE_RATE, num_channels=1)
    # livekit-agents 0.12.21：VAD.stream() + push_frame（旧版 from_stream 已移除）
    # AudioStream 迭代产出的是 AudioFrameEvent，必须取 .frame 才能被 VAD 接受
    vad: VAD = _shared_vad()
    detector = vad.stream()
    cache = switch_cache(room_sid)
    gate = SerConcurrencyGate(int(DEFAULT_SER_POLICY["maxConcurrency"]))
    breaker = SerCircuitBreaker(int(DEFAULT_SER_POLICY["failThreshold"]),
                                float(DEFAULT_SER_POLICY["cooldownSec"]))

    speaking = False
    started_ms = 0            # 本轮说话起点（epoch ms）
    chunk_offset_ms = 0       # 本轮说话内已冲刷的时长（强制切段偏移）
    live = bytearray()        # 当前未转写的语音缓冲（feed 持续追加）
    flush_evt = asyncio.Event()
    max_live_bytes = int(SAMPLE_RATE * 2 * MAX_SPEECH_SEC)
    inflight: set[asyncio.Task] = set()

    async def feed() -> None:
        try:
            async for audio_ev in stream:
                detector.push_frame(audio_ev.frame)
                if speaking:
                    live.extend(bytes(audio_ev.frame.data))
                    if len(live) >= max_live_bytes:
                        flush_evt.set()
            detector.end_input()
        except Exception as e:
            # VADStream 对非 AudioFrame 是静默丢弃，这里显式暴露喂帧异常
            print(f"[worker] VAD feed 失败 room={room_sid} identity={identity}: {type(e).__name__}: {e}")

    def spawn_chunk(chunk: bytes, chunk_start_ms: int) -> None:
        """把一段缓冲交给后台处理（不阻塞帧消费；完成即从在飞集合移除）。"""
        task = asyncio.create_task(_handle_chunk(room_sid, identity, chunk,
                                                 chunk_start_ms, cache, gate, breaker))
        inflight.add(task)
        task.add_done_callback(inflight.discard)

    feed_task = asyncio.create_task(feed())
    try:
        async for ev in detector:
            if ev.type == VADEventType.START_OF_SPEECH:
                speaking = True
                started_ms = int(time.time() * 1000)
                chunk_offset_ms = 0
                live.clear()
            elif ev.type == VADEventType.END_OF_SPEECH:
                # END 时不再用 ev.frames（强制切段已分流部分内容），用自管理缓冲收尾
                speaking = False
                chunk = bytes(live)
                live.clear()
                if chunk:
                    spawn_chunk(chunk, started_ms)
                started_ms = 0
                chunk_offset_ms = 0
            elif flush_evt.is_set() and speaking:
                # 说话中强制切段：转写本段已积累部分，本轮说话继续累积
                flush_evt.clear()
                chunk = bytes(live)
                live.clear()
                if chunk:
                    chunk_start = started_ms + chunk_offset_ms
                    chunk_offset_ms += len(chunk) // (SAMPLE_RATE * 2) * 1000
                    spawn_chunk(chunk, chunk_start)
    finally:
        # 会话结束（轨移除）：结束标记 + 等待在飞任务落库，避免丢最后的转录
        feed_task.cancel()
        speaking = False
        if live:
            spawn_chunk(bytes(live), started_ms + chunk_offset_ms)
            live.clear()
        if inflight:
            await asyncio.gather(*list(inflight), return_exceptions=True)
        await stream.aclose()
        await detector.aclose()


async def _handle_track(ctx: JobContext, participant: rtc.Participant, track: rtc.Track) -> None:
    # SP-3 G0 取证专用观测日志：只打印轨元信息，不打印帧内容、不改判断分支
    print(f"[track-observe] room={ctx.room.name} identity={participant.identity} "
          f"kind={track.kind} sid={track.sid}", flush=True)
    if track.kind != rtc.TrackKind.KIND_AUDIO:
        return
    room_sid = ctx.room.name
    # 同一 identity 重发音频轨（浏览器刷新/重连）时，旧轨任务必须取消，
    # 否则两条轨同时 VAD 会产生内容相同的重复字幕
    old = _track_tasks.get(participant.identity)
    if old is not None and not old.done():
        old.cancel()
    task = asyncio.create_task(transcribe_track(room_sid, participant.identity, track))
    _track_tasks[participant.identity] = task


async def entrypoint(ctx: JobContext) -> None:
    # 1.1.10 的 AUDIO_ONLY 实际映射为 auto_subscribe=false（需手动订阅），
    # 先用 SUBSCRIBE_ALL 保证音频轨自动到达，再在 _handle_track 只处理 KIND_AUDIO
    await ctx.connect(auto_subscribe=AutoSubscribe.SUBSCRIBE_ALL)
    room = ctx.room
    # 开关快照轮询：首次拉取失败即整场 ser=false（fail-closed）
    asyncio.create_task(switch_poll_loop(room.name))
    # 已在房内的远端轨
    for p in room.remote_participants.values():
        for pub in p.track_publications.values():
            if pub.kind == rtc.TrackKind.KIND_AUDIO and pub.track is not None:
                await _handle_track(ctx, p, pub.track)
    # 后续加入/新发音频
    room.on("track_subscribed", lambda track, pub, participant: asyncio.ensure_future(
        _handle_track(ctx, participant, track)))
    # 会话结束：向事件总线/回调子系统产出 session_end（本地归档等下游消费）
    room.on("disconnected", lambda *_: _emit_session_end(room.name))
    print(f"[worker] connected room={room.name}")


if __name__ == "__main__":
    cli.run_app(WorkerOptions(
        entrypoint_fnc=entrypoint,
        port=HEALTH_PORT,
        agent_name=AGENT_NAME,
        load_threshold=LOAD_THRESHOLD,
    ))
