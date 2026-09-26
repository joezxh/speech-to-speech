FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PATH="/usr/src/app/.venv/bin:${PATH}"

WORKDIR /usr/src/app

# Install packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        libportaudio2 \
        libsndfile1 \
        python3 \
        python3-pip \
        python3-venv \
        cargo \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir --break-system-packages uv

COPY pyproject.toml README.md LICENSE MANIFEST.in ./
RUN UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple UV_EXTRA_INDEX_URL=https://pypi.org/simple uv sync --python /usr/bin/python3 --no-install-project --no-dev --extra paraformer

COPY . .
RUN UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple UV_EXTRA_INDEX_URL=https://pypi.org/simple uv sync --python /usr/bin/python3 --no-dev --extra paraformer
# Pin torch/torchaudio to the cu128 wheel so they match the host NVIDIA driver
# (12.8). The default PyPI wheel is cu130 and fails CUDA init on this driver,
# which silently falls TTS/STT back to CPU (RTF ~3.7x realtime).
RUN uv pip install --python /usr/src/app/.venv/bin/python --no-cache-dir \
    --reinstall-package torch --reinstall-package torchaudio \
    --index-url https://download.pytorch.org/whl/cu128 \
    "torch==2.11.0" "torchaudio==2.11.0"
# nltk.sent_tokenize needs the legacy 'punkt' tokenizer resource (not just
# 'punkt_tab'); without it the LLM text stage raises LookupError and the
# pipeline emits the "I'm having trouble responding right now" fallback.
# Download is best-effort: container egress may block it (SSRF guard), in which
# case the code falls back to a regex sentence splitter.
RUN python -c "import nltk; [nltk.download(p, quiet=True) for p in ('punkt','punkt_tab','averaged_perceptron_tagger_eng')]" || true
# faster-qwen3-tts' transformers-5.x compat shim assumes every config has
# `rope_theta`; transformers 5.15+ MimiConfig (Qwen3-TTS's codec) does not, which
# crashes the torch TTS backend on load (AttributeError). Fall back to a default
# base — Mimi is a convolutional codec and never uses RoPE, so the value is moot.
RUN sed -i 's/^    base = config\.rope_theta$/    base = getattr(config, "rope_theta", 10000.0)/' \
    /usr/src/app/.venv/lib/python3.12/site-packages/qwen_tts/_transformers_compat.py

# Paraformer (Chinese ASR) support. The runtime container egress has SSL EOF for
# modelscope, so we pre-download the model at build time (host network) into a
# path that is NOT shadowed by the /root/.cache volume mount, then point
# MODELSCOPE_CACHE there at runtime so funasr uses the local copy offline.
ENV MODELSCOPE_CACHE=/opt/modelscope
RUN python -c "from funasr import AutoModel; AutoModel(model='paraformer-zh', device='cpu'); print('paraformer-zh cached OK')"
