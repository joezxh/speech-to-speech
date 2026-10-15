FROM nvidia/cuda:12.8.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PATH="/usr/src/app/.venv/bin:${PATH}"

WORKDIR /usr/src/app

# Install packages
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        git \
        libportaudio2 \
        libsndfile1 \
        python3 \
        python3-pip \
        python3-venv \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m pip install --no-cache-dir --break-system-packages uv

COPY pyproject.toml README.md LICENSE MANIFEST.in ./
RUN uv sync --python /usr/bin/python3 --no-install-project --no-dev

COPY . .
RUN uv sync --python /usr/bin/python3 --no-dev

# CosyVoice2 is NOT pip-installable as a normal package (the PyPI "cosyvoice"
# name is an unrelated project). Copy the official Alibaba source
# (cosyvoice/ + third_party/ + asset/) into the image and expose it via PYTHONPATH.
COPY cosyvoice-src /opt/cosyvoice-src
# CosyVoice2's flow/vocoder reuses the Matcha-TTS package (a git submodule shipped
# under third_party/). It is NOT auto-added to sys.path by the inference entry
# point, so both the cosyvoice root and third_party/Matcha-TTS must be on PYTHONPATH.
ENV PYTHONPATH=/opt/cosyvoice-src:/opt/cosyvoice-src/third_party/Matcha-TTS

# python3-dev (Python.h) required to compile pyworld/torchdiffeq C extensions; espeak-ng for phonemizer
RUN apt-get update && apt-get install -y --no-install-recommends python3-dev espeak-ng && rm -rf /var/lib/apt/lists/*

RUN uv pip install --no-cache-dir "funasr==1.1.6" "modelscope>=1.17.1" onnxruntime torchaudio \
    hyperpyyaml conformer wetext librosa openai-whisper sentencepiece diffusers

# CosyVoice2 inference-time Python dependencies (subset of its requirements.txt,
# excluding the training/serving-heavy packages: torch/torchaudio re-pins,
# tensorrt, deepspeed, vllm, gradio, fastapi, lightning, grpcio...). Versions
# match cosyvoice's requirements.txt where given. build-essential (above) is
# required so pyworld / torchdiffeq can compile their C extensions.
RUN uv pip install --no-cache-dir \
    "inflect==7.3.1" \
    "omegaconf==2.3.0" \
    "einops" \
    "pyworld==0.3.4" \
    "scipy" \
    "tiktoken==0.14.0" \
    "x_transformers==2.11.24" \
    "torchdiffeq" \
    "hydra-core==1.3.2" \
    "phonemizer" \
    "unidecode" \
    "rootutils" \
    "cython" \
    "packaging" "pyarrow" "regex" "tqdm" "rich" "networkx" "pydantic" "protobuf"
# nltk data download is best-effort only. The build environment often cannot
# reach nltk.org (blocked / slow), and the pipeline already has a regex fallback
# for sentence tokenization, so a missing punkt_tab must NOT fail the build.
RUN timeout 90 python -c "import nltk; nltk.download('punkt_tab', quiet=True); nltk.download('averaged_perceptron_tagger_eng', quiet=True)" \
    || echo "nltk data download skipped (non-fatal; regex fallback will be used)"
