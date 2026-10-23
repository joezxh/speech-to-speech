# ============================================================================
# speech-to-speech（s2s）镜像 A —— 运行时卷挂载版（与本地部署一致）
#
# 基于团队公共基础镜像 llm-basic/python-dl-*（CUDA runtime + Python3.12 + uv +
# torch/torchaudio/transformers/numpy 等共享深度学习依赖已固化在基础镜像内）。
#
# 本镜像只含代码 + Python 环境，不内置任何模型权重：
#   - STT : qwen3-asr    （transformers，基础镜像已带）
#   - TTS : qwen3        （faster-qwen3-tts，default 依赖已带）
#   - VAD : silero-vad   （运行时由 ./silero-vad 卷挂载到 /opt/silero-vad）
#   - 模型权重 qwen3-asr-model-hf / qwen3-tts-model 由 ./cache 卷挂载到 /root/.cache
# 因此本镜像体积小，换模型/模型更新无需重 build。
#
# qwen3-asr 与 qwen3-tts 都在 pyproject 的 default 依赖内，不依赖任何 extra。
# uv sync 的通用解析会把所有 extra（含 darwin-only 的 kokoro/mlx）纳入而导致
# tqdm 版本不可解，故构建期删除全部 optional-dependencies，仅解析 default 依赖。
#
# 变体：
#   Dockerfile        → cu128 基础镜像（宿主驱动 CUDA < 13.0，本机 572.84 适用）
#   Dockerfile.cu130  → cu130 基础镜像（宿主驱动需 >= 580）
#
# 构建（上下文为本目录）：
#   docker build -f Dockerfile -t ccr.ccs.tencentyun.com/llm-basic/speech-to-speech:cu128-1.0 .
# ============================================================================
ARG BASE_IMAGE=ccr.ccs.tencentyun.com/llm-basic/python-torch:cu128
FROM ${BASE_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# 基础镜像已把 PATH 指向 /usr/src/app/.venv，uv sync 直接复用该虚拟环境。
# 索引：官方 PyTorch cu128 通道（torch/torchaudio 的 +cu128 本地构建，受 constraints.txt 锁死）
# → 清华 tuna PyPI 镜像（绝大多数非 torch 依赖走这里，可靠）→ 阿里云 PyPI 镜像（tuna 未镜像的
# 小众包如 qwentts-cpp-python 兜底，国内可靠）。刻意不用 pypi.org（构建容器内连接抖动/超时）。
# 用 first-index（PyTorch 索引优先）：torch(cu128) 依赖 nvidia-*-cu12 包名，first-index 会按该名
# 从 PyTorch 索引取 cu12 轮子，绝不会误装 cu13 变体；其余依赖回退到 tuna/阿里云 PyPI，并由
# constraints.txt 锁死 cu12 版本（torch 已由基座预装 2.11.0+cu128，uv sync --inexact 保留）。
ENV UV_INDEX="https://download.pytorch.org/whl/cu128 https://pypi.tuna.tsinghua.edu.cn/simple https://mirrors.aliyun.com/pypi/simple"
ENV UV_INDEX_STRATEGY=first-index
# 关闭构建隔离：项目以 setuptools>=77 构建时需要 packaging>=24.2，而 first-index 下
# PyTorch 索引只提供旧版 packaging；隔离环境会再从中取旧版导致 ImportError。
# 关掉隔离后直接用本 venv（已锁定 packaging>=24.2 / setuptools>=77）构建，规避该问题。
ENV UV_BUILD_ISOLATION=false

WORKDIR /usr/src/app

# 先把 pyproject.toml 复制进来（uv sync 需要它），再装依赖，最后再 COPY 全部源码。
# 这样“只改源码、不动依赖”时第一步的装包层可命中缓存，不必重复解析/下载。
# --inexact：保留基础镜像里的共享包（accelerate/peft 等），避免被 sync 裁掉。
COPY pyproject.toml ./
# uv sync 会做全平台通用解析并生成通用锁，会纳入所有 extra（含 darwin-only 的
# kokoro/mlx 等），导致 mlx-audio(tqdm>=4.67.1) 与 kokoro 的 spacy(tqdm<=4.66.5)
# 在 darwin 上无解、整图不可解。本部署只用 qwen3-asr/qwen3-tts（均在 default 依赖内，
# 无需任何 extra），故删除全部 optional-dependencies，仅保留 default 依赖解析。
# 仅修改镜像内 pyproject，不动仓库源文件。
RUN /usr/bin/python3 - <<'PY'
import re, pathlib
p = pathlib.Path("pyproject.toml")
t = p.read_text()
# 1) 删除全部 optional-dependencies，仅解析 default 依赖（见上文说明）。
t = re.sub(r"\[project\.optional-dependencies\][\s\S]*?(?=\n\[)", "", t, count=1)
# 2) 删除 darwin-only 的主依赖（mlx / mlx-audio / mlx-lm / mlx-metal / miniaudio /
#    sounddevice·soundfile·numpy 的 Darwin 变体）。这些是 macOS 专用，Linux 镜像用不到；
# 且 mlx-audio(darwin) 依赖 tqdm>=4.67.1，而 PyTorch 索引只收 tqdm<=4.66.5，正是当初
# 需要 unsafe-best-match 的根源。删掉它们后可用默认 first-index，避免误拉 cu13 nvidia。
t = re.sub(r".*platform_system == 'Darwin'.*\n", "", t)
# 3) 基座固定 Python 3.12：把 requires-python 收窄到 3.12，避免 uv 对 3.13/3.14/3.15
# 做跨版本通用解析。faster-qwen3-tts 的传递依赖 qwentts-cpp-python 在 3.15+ 无可用
# 轮子，会导致 "No solution found"（原构建卡 14 分钟最终失败）。锁到 3.12 后单版本解析。
t = re.sub(r'(requires-python\s*=\s*)"[^"]*"', r'\1">=3.12,<3.13"', t)
p.write_text(t)
PY

# torch/torchaudio 与 nvidia-cu12 交给 uv 从 PyTorch(cu128) 索引统一解析，保证 torch 与 nvidia
# 版本互相匹配：cu128 通道 torch 最高即 2.11.0，与基座预装版本一致，故重解析后直接复用，
# 不会重装 torch/nvidia/torchaudio。剥掉三者约束是为了让 uv 按依赖图自洽推导（而非死锁旧值）。
# cu12 变体由 first-index + PyTorch 索引（仅 cu12）天然保证，不会误装 cu13。其余依赖约束保留。
RUN grep -vE '^(torch|torchaudio|nvidia-)' /opt/base-image/constraints.txt > /tmp/c.txt && mv /tmp/c.txt /opt/base-image/constraints.txt

# 解析并装好全部依赖（保留基础镜像的 torch/nvidia）。把 UV_INDEX_STRATEGY 写进命令以打破
# 上层缓存（否则会复用旧 unsafe-best-match 的解析结果，把 torch 错装成 cu130）。
RUN --mount=type=cache,target=/root/.cache/uv \
    UV_INDEX_STRATEGY=first-index UV_TIMEOUT=180 UV_CONNECT_TIMEOUT=60 UV_RETRIES=8 \
    uv sync --python /usr/bin/python3 --no-install-project --no-dev --inexact

# 仅复制源码（不 COPY . .，避免把宿主 ./cache 模型塞进镜像——权重由运行时卷挂载提供）。
COPY src ./src

# 装上项目本体。
# 先显式把构建所需的 packaging/setuptools 升到满足 setuptools>=77 的版本：这里临时用
# --index-strategy unsafe-best-match，让 first-index 下也能回退到 tuna/pypi 取到 packaging>=24.2
# （否则 PyTorch 索引只提供 <=24.1，会触发 ImportError: Cannot import packaging.licenses）。
# 再用 --no-build-isolation 直接以 venv 内已升级的打包工具安装项目本体，避免 uv 构建隔离
# 环境从 PyTorch 索引取旧版 packaging。
RUN --mount=type=cache,target=/root/.cache/uv echo "[build] upgrading packaging/setuptools/wheel" && \
    UV_TIMEOUT=120 uv pip install --index-strategy unsafe-best-match --python /usr/src/app/.venv/bin/python --upgrade "packaging>=24.2" "setuptools>=77.0.3" "wheel"
RUN --mount=type=cache,target=/root/.cache/uv echo "[build] installing project (editable, no-deps, no-build-isolation)" && \
    uv pip install -e . --python /usr/src/app/.venv/bin/python --no-deps --no-build-isolation

# nltk.sent_tokenize 需要旧版 'punkt' 分词资源（不只是 'punkt_tab'）；
# 缺失会抛 LookupError，pipeline 退化成兜底文案。下载 best-effort；
# 容器内 nltk 数据 CDN 可能连接挂起（SSRF 代理不快速失败），故用 timeout 硬上限兜底，失败不致命。
RUN echo "[build] downloading nltk data (best-effort, timeout-guarded)" && \
    timeout 90 python -c "import nltk; [nltk.download(p, quiet=True) for p in ('punkt','punkt_tab','averaged_perceptron_tagger_eng')]" || true

# faster-qwen3-tts 的 transformers-5.x 兼容补丁：MimiConfig 无 rope_theta，
# torch TTS 后端加载时会 AttributeError。Mimi 是卷积 codec、不用 RoPE，兜底默认无副作用。
RUN sed -i 's/^    base = config\.rope_theta$/    base = getattr(config, "rope_theta", 10000.0)/' \
    /usr/src/app/.venv/lib/python3.12/site-packages/qwen_tts/_transformers_compat.py

# 收尾清理：删除 uv 下载缓存与 __pycache__，避免被烤进镜像层（cache mount 已阻止入层，这里兜底）
RUN rm -rf /root/.cache/uv && \
    find /usr/src/app/.venv -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null; \
    true
