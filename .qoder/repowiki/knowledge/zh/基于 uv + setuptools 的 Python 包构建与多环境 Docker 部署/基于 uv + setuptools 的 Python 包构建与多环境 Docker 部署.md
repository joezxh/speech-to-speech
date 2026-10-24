---
kind: build_system
name: 基于 uv + setuptools 的 Python 包构建与多环境 Docker 部署
category: build_system
scope:
    - '**'
source_files:
    - pyproject.toml
    - .github/workflows/ci.yml
    - .github/workflows/publish.yml
    - .github/workflows/omnivoice.yml
    - Dockerfile.cu130
    - Dockerfile.baked
    - Dockerfile.arm64
    - Dockerfile.local
    - docker-compose.yml
    - demo/Dockerfile
    - tests/install_smoke.py
---

## 1. 构建系统概览

本项目采用 **PEP 517/518** 现代 Python 打包方案：
- 构建后端为 `setuptools.build_meta`（`pyproject.toml` 中声明）。
- 依赖解析、虚拟环境管理、CI 工具链统一使用 **uv**（astral-sh/setup-uv@v10），而非 pip/poetry。
- 包元数据、依赖、可选 extras、脚本入口全部集中在 `pyproject.toml`，无独立 `setup.py`。
- 源码位于 `src/speech_to_speech`，通过 `[tool.setuptools.packages.find] where = ["src"]` 发现。

## 2. 关键文件

- `pyproject.toml`：包名 `speech-to-speech`、版本 `1.0.0`、Python ≥3.11；定义核心依赖、可选 extras（`chattts`、`faster-whisper`、`kokoro`、`omnivoice`、`paraformer`、`sensevoice`、`pocket`、`supertonic`、`webrtc`、`whisper-mlx` 等）、`[project.scripts] speech-to-speech` 入口点、`[dependency-groups.dev]`、`[tool.ruff]`、`[tool.mypy]`、`[tool.pytest.ini_options]`。
- `.github/workflows/ci.yml`：PR/merge 到 main 触发，包含 ruff lint/format、mypy、pytest（Python 3.11–3.14 矩阵）、Node 24 Playwright 测试（demo 前端）、`uv build` + `twine check --strict`、跨平台 wheel 安装冒烟（Linux + macOS-arm64）。
- `.github/workflows/publish.yml`：仅对 `v*` tag 触发，`uv build` → `twine check --strict` → `pypa/gh-action-pypi-publish`（启用 OIDC `id-token: write`，发布到 PyPI `https://pypi.org/project/speech-to-speech/`）。
- `.github/workflows/omnivoice.yml`：针对 `omnivoice` extra 的兼容性检查，按路径触发（`pyproject.toml`、`uv.lock`、相关 handler/tests），含 `uv pip compile` 多平台解析和额外 smoke 测试。
- `Dockerfile.cu130` / `Dockerfile.baked` / `Dockerfile.arm64` / `Dockerfile.local` / `Dockerfile.torch-base` / `Dockerfile.sox`：多种 GPU/CPU/ARM 变体镜像。
- `docker-compose.yml`：编排 `llama`（ggml-org/llama.cpp server）+ `pipeline`（本项目的 `speech-to-speech serve -f /app/config/prod.yaml --name prod`）两个服务，挂载 `./cache` 与 `./config`。
- `demo/Dockerfile`：Node 24 预构建 OpenAI Agents SDK bundle，再基于 `python:3.11-slim` 构建演示服务，暴露 7860 端口。
- `tests/install_smoke.py`：验证已安装包 CLI (`serve`/`talk`/`local`)、默认参数、handler import、macOS 依赖 pin 版本。

## 3. 架构与约定

### 依赖与平台差异
- 核心依赖在 `pyproject.toml` 中以 `platform_system == 'Darwin'` 条件分支区分 macOS 与非 macOS 依赖（如 `torch==2.11.0` vs `>=2.4.0`、`sounddevice==0.5.3` vs `>=0.5.0`、`transformers==5.18.0` vs `<6`、`miniaudio==1.61`、`mlx-*` 系列仅在 Darwin 生效）。
- Windows 下 `faster-qwen3-tts` 使用不带 `[ggml]` 的版本，非 Windows 使用 `[ggml]` 版。
- 可选 extras 通过 `[project.optional-dependencies]` 暴露，CI 通过 `uv sync --group dev` 安装开发依赖。

### 构建产物
- `uv build` 生成 sdist 与 wheel，产出目录 `dist/`。
- CI 通过 `actions/upload-artifact` 上传 `dist/*`，后续 job 下载后以 `pip install <wheel>` 进行冒烟测试。
- publish workflow 使用 GitHub Actions OIDC 直接推送到 PyPI，无需存储 token。

### Docker 策略
- 根级提供多套 Dockerfile 对应不同硬件/驱动组合（cu128、cu130、arm64、baked、local、sox、torch-base），由 `docker-compose.yml` 中的 `${DOCKERFILE:-Dockerfile}` 变量选择。
- Compose 将配置目录以只读方式挂载 (`./config:/app/config:ro`)，运行时环境变量来自 `config/prod.env`，强调“配置只有一个写入方”。
- demo 子项目独立 Dockerfile，基于 Node 24 + Python 3.11 slim，静态托管前端并代理 API。

### 测试与质量门禁
- Ruff：`select = ["E", "F", "I", "W"]`，忽略 E501，line-length 120。
- mypy：`python_version = "3.11"`，`ignore_missing_imports = true`，`check_untyped_defs = false`。
- pytest：`asyncio_mode = "auto"`，CI 在 4 个 Python 版本上并行执行。
- 冒烟测试覆盖 CLI help 契约、默认 handler 可导入、macOS 依赖版本 pin 校验、可选 extra (omnivoice) 安装。

## 4. 约定与约束

- **包元数据单一来源**：所有依赖、extras、脚本入口、lint/test 配置均位于 `pyproject.toml`，不存在独立的 `setup.py`。
- **Python 版本矩阵**：`requires-python = ">=3.11"`，CI 固定对 3.11/3.12/3.13/3.14 运行 pytest。
- **uv 作为唯一依赖解析器**：CI 中所有步骤通过 `astral-sh/setup-uv` 安装 uv，再用 `uv sync --group dev` 或 `uv build`，不直接使用 `pip install -e .`。
- **发布触发条件**：仅当 push tag 匹配 `v*` 时触发 publish workflow；普通 PR 不会发布。
- **PyPI 发布使用 OIDC**：publish job 开启 `id-token: write`，通过 `pypa/gh-action-pypi-publish` 的 OIDC 认证，仓库 secret 中不存放 PyPI token。
- **macOS 依赖严格 pin**：`tests/install_smoke.py::_validate_darwin_dependency_pins()` 断言 `miniaudio==1.61`、`mlx==0.32.3`、`mlx-audio==0.4.7`、`mlx-lm==0.31.3`、`mlx-metal==0.32.3`、`sounddevice==0.5.3`、`transformers==5.18.0`，且 numpy < 2.4.4；任何偏离都会导致冒烟失败。
- **CLI 契约由测试维护**：`tests/install_smoke.py` 断言 `speech-to-speech` 命令存在 `serve`/`talk`/`local` 子命令，`serve --help` 必须包含 `--host`/`--port`/`--stt`/`--llm_backend`/`--tts`，旧 `--mode realtime/local/socket` 行为有明确的弃用提示。
- **可选功能通过 extras 隔离**：新增 handler 需在 `pyproject.toml` 的 `[project.optional-dependencies]` 中添加 entry，并在 CI 的 `omnivoice.yml` 类似流程中增加路径触发与冒烟用例。
- **Docker 镜像选择**：Compose 通过环境变量 `DOCKERFILE` 指定具体 Dockerfile，默认 `Dockerfile`；GPU 相关 compose 文件（`docker-compose.cu130.yml`、`docker-compose.gpustack.yml`、`docker-compose.llm-bundled.yml` 等）分别对应不同部署场景。