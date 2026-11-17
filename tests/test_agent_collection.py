"""agent 采集 pipeline 实际部署模型/全部参数与 GPU 显存（真源，不编数据）。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from speech_to_speech.agent import pipeline_inspect


@pytest.fixture
def agent_env(tmp_path, monkeypatch):
    declaration = tmp_path / "agent.yaml"
    declaration.write_text(
        "pipeline_port: 8765\nworkloads:\n"
        "  - kind: asr\n    engine: qwen3-asr\n    port: 8011\n    health_path: /health\n"
        "  - kind: llm\n    engine: chat-completions\n    port: 8000\n"
        "  - kind: tts\n    engine: qwen3\n    port: 8010\n",
        encoding="utf-8",
    )
    target = tmp_path / "prod.yaml"
    target.write_text(
        "blocks:\n"
        "  stt:\n    kind: stt\n    backend: qwen3-asr\n    settings:\n"
        "      qwen3_asr_model_name: {env: S2S_ASR_MODEL_DIR}\n      qwen3_asr_device: cuda\n"
        "  llm:\n    kind: llm\n    backend: chat-completions\n    settings:\n"
        "      model_name: qwen3.8-27b\n      responses_api_api_key: {env: LLM_API_KEY}\n"
        "  tts:\n    kind: tts\n    backend: qwen3\n    settings:\n"
        "      qwen3_tts_model_name: {env: S2S_TTS_MODEL_DIR}\n      qwen3_tts_streaming_chunk_size: 4\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("S2S_ASR_MODEL_DIR", "/models/asr-1.7b")
    monkeypatch.setenv("S2S_TTS_MODEL_DIR", "/models/qwen3-tts")
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-should-not-leak")
    return SimpleNamespace(declaration_file=str(declaration), target_yaml=str(target))


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None


def test_pipeline_deployment_reads_models_params_and_redacts_secrets(agent_env, monkeypatch):
    monkeypatch.setattr(
        "speech_to_speech.agent.pipeline_inspect._nvidia_smi_vram", lambda: 4.75
    )
    snapshot = pipeline_inspect.collect_pipeline_deployment(agent_env)
    assert snapshot["models"] == {
        "stt": "/models/asr-1.7b",
        "llm": "qwen3.8-27b",
        "tts": "/models/qwen3-tts",
    }
    params = snapshot["params"]
    assert params["stt.qwen3_asr_device"] == "cuda"
    assert params["tts.qwen3_tts_streaming_chunk_size"] == 4
    assert params["tts.backend"] == "qwen3"
    assert params["llm.responses_api_api_key"] == "***"
    assert "sk-secret-should-not-leak" not in json.dumps(params)
    assert snapshot["vram_gb"] == 4.75


def test_collect_workloads_enriches_declared_services_and_pipeline_row(agent_env, monkeypatch):
    from speech_to_speech.agent import collectors

    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: _Response())
    monkeypatch.setattr(
        "speech_to_speech.agent.pipeline_inspect._nvidia_smi_vram", lambda: 4.75
    )
    rows = {row["kind"]: row for row in collectors.collect_workloads(agent_env)}
    assert rows["asr"]["model"] == "/models/asr-1.7b"
    assert rows["asr"]["params"]["qwen3_asr_model_name"] == "/models/asr-1.7b"
    assert rows["asr"]["params"]["backend"] == "qwen3-asr"
    assert rows["llm"]["model"] == "qwen3.8-27b"
    assert "qwen3_tts_model_name" not in rows["llm"]["params"]  # 只带本 block 参数
    pipeline = rows["pipeline"]
    assert pipeline["vram_gb"] == 4.75
    assert pipeline["params"]["models"] == {
        "stt": "/models/asr-1.7b", "llm": "qwen3.8-27b", "tts": "/models/qwen3-tts"
    }
    assert pipeline["params"]["llm.responses_api_api_key"] == "***"


def test_vram_probe_parses_real_pid_usage(monkeypatch):
    class _Proc:
        stdout = "1234, 2048 MiB\n5678, 512 MiB\n"

    monkeypatch.setattr("speech_to_speech.agent.pipeline_inspect._supervisor_pid", lambda: 1234)
    monkeypatch.setattr(
        "speech_to_speech.agent.pipeline_inspect.subprocess.run", lambda *a, **k: _Proc()
    )
    assert pipeline_inspect._nvidia_smi_vram() == 2.0
