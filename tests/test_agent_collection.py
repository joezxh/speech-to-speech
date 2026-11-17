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


def test_package_version_uses_installed_metadata(monkeypatch):
    monkeypatch.setattr(pipeline_inspect.metadata, "version", lambda name: "1.1.0")
    assert pipeline_inspect.package_version() == "1.1.0"


def test_node_metrics_reads_cpu_mem_gpu_model_and_utilization(monkeypatch):
    class _Proc:
        def __init__(self, stdout):
            self.stdout = stdout

    def _fake_run(args, **kwargs):
        joined = " ".join(args)
        if "compute-apps" in joined:
            return _Proc("1234, 2048 MiB\n")
        return _Proc("0, NVIDIA L40S, 64, 49152, 20480\n")

    monkeypatch.setattr(pipeline_inspect, "_supervisor_pid", lambda: 1234)
    monkeypatch.setattr(pipeline_inspect.subprocess, "run", _fake_run)
    monkeypatch.setattr(
        pipeline_inspect,
        "_cpu_mem",
        lambda: {
            "cpu_pct": 12.5,
            "load_avg": [1.0, 0.5, 0.25],
            "mem_total_gb": 64.0,
            "mem_used_gb": 20.0,
            "mem_pct": 31.2,
        },
    )
    metrics = pipeline_inspect.collect_node_metrics()
    assert metrics["cpu_pct"] == 12.5
    assert metrics["mem_total_gb"] == 64.0
    assert metrics["gpu_name"] == "NVIDIA L40S"
    assert metrics["gpu_util_pct"] == 64
    assert metrics["gpu_mem_total_gb"] == 48.0
    assert metrics["pipeline_vram_gb"] == 2.0


def test_deployment_params_split_runtime_and_declared_manifest(agent_env, tmp_path):
    manifest = tmp_path / "deployment-manifest.json"
    manifest.write_text(
        json.dumps({
            "generatedBy": "scripts/generate_deployment_manifest.py",
            "services": {
                "pipeline": {
                    "compose": "docker-compose.voiceprint.yml",
                    "image": "speech-to-speech-local:cu130-1.3-voiceprint",
                    "command": ["--tts", "qwen3", "--min_silence_ms", "700"],
                    "env": {"LLM_API_KEY": "sk-secret-must-not-leak", "MIN_SILENCE_MS": "700"},
                    "deviceIds": ["0"],
                }
            },
        }),
        encoding="utf-8",
    )
    settings = SimpleNamespace(
        target_yaml=agent_env.target_yaml,
        deployment_manifest=str(manifest),
    )
    payload = pipeline_inspect.collect_deployment_params(settings)
    assert payload["runtime"]["stt.qwen3_asr_model_name"] == "/models/asr-1.7b"
    assert payload["declared"]["pipeline.compose"] == "docker-compose.voiceprint.yml"
    assert payload["declared"]["pipeline.env.LLM_API_KEY"] == "***"
    assert "sk-secret-must-not-leak" not in json.dumps(payload)


def test_container_log_tail_is_bounded_and_redacted(tmp_path):
    log = tmp_path / "pipeline-stdout.log"
    log.write_text(
        "INFO ok\nERROR api_key=sk-secret-abcdef payload=abc\nWARN done\n", encoding="utf-8"
    )
    settings = SimpleNamespace(pipeline_log=str(log), container_log_max_lines=100)
    rows = pipeline_inspect.collect_container_logs(settings)
    assert [row["source"] for row in rows] == ["stdout"]
    assert "sk-secret-abcdef" not in " ".join(rows[0]["lines"])
    assert "api_key=***" in " ".join(rows[0]["lines"])
    assert len(rows[0]["lines"]) == 3
