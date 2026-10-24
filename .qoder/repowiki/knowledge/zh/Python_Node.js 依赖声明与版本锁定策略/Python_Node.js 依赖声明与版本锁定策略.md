---
kind: dependency_management
name: Python/Node.js 依赖声明与版本锁定策略
category: dependency_management
scope:
    - '**'
source_files:
    - pyproject.toml
    - demo/package.json
    - demo/package-lock.json
    - demo/requirements.txt
    - .github/dependabot.yml
    - demo/.npmrc
---

## 1. 使用的工具与系统

- **Python 包管理**：`pyproject.toml`（PEP 621）+ `setuptools.build_meta` 构建后端；同时启用 `tool.uv` 配置，表明项目也支持通过 `uv` 解析依赖。
- **演示应用前端**：`demo/package.json` + `demo/package-lock.json` 使用 npm 管理 Node.js 依赖。
- **CI 依赖更新**：`.github/dependabot.yml` 仅对 GitHub Actions 进行每周更新。
- **私有仓库/代理**：`demo/.npmrc` 显式指定 `registry=https://registry.npmjs.org/` 并启用 `replace-registry-host=always`，强制所有 npm 请求走该 registry。

## 2. 关键文件

- `pyproject.toml` — Python 包元数据、运行时依赖、可选 extras、dev dependency-groups、构建与 lint 配置。
- `demo/package.json` — 演示应用的 Node.js 依赖与脚本。
- `demo/package-lock.json` — npm 依赖树锁文件。
- `demo/requirements.txt` — 演示服务单独的最小依赖清单（与主包解耦）。
- `.github/dependabot.yml` — Dependabot 规则。
- `demo/.npmrc` — npm registry 与发布年龄策略。

## 3. 架构与约定

### 3.1 Python 依赖声明（`pyproject.toml`）

- **运行时依赖**集中在 `[project].dependencies`，采用“宽松下限 + 平台条件”的写法：
  - 使用 `>=X.Y` 允许上游升级，但部分核心库用精确版本锁定（如 `openai==2.28.0`、`nltk==3.10.3`、`librosa==0.11.0`、`sounddevice==0.5.3`、`torch==2.11.0`、`torchaudio==2.11.0`、`transformers==5.18.0`、`miniaudio==1.61`、`mlx==0.32.3`、`mlx-audio==0.4.7`、`mlx-lm==0.31.3`、`mlx-metal==0.32.3`），以规避 ML 生态不兼容。
  - 针对 macOS（`platform_system == 'Darwin'`）提供独立分支（如 `numpy`、`sounddevice`、`soundfile`、`torch`、`torchaudio`、`transformers`、`miniaudio`、`mlx-*`、`kokoro` 相关依赖），因为 Apple Silicon 上的 ML 栈与 Linux/Windows 不同。
  - Windows 上 `faster-qwen3-tts` 使用不带 `[ggml]` 的版本，非 Windows 使用带 `[ggml]` 的版本。
- **可选功能组**通过 `[project.optional-dependencies]` 暴露为 extras（`chattts`、`faster-whisper`、`fireredvad`、`kokoro`、`kitten`、`mlx-lm`、`nemo`、`omnivoice`、`paraformer`、`sensevoice`、`pocket`、`supertonic`、`webrtc`、`whisper-mlx`），用户按需安装。
- **开发依赖**放在 `[dependency-groups].dev`（ruff、mypy、pytest、pytest-asyncio、aiortc），由 uv 管理。
- **构建系统**固定 `setuptools>=77.0.3` + `wheel`，包目录位于 `src/speech_to_speech`，并通过 `package-data` 打包 `TTS/*.wav` 和 `STV/*.json`。
- **Python 版本约束**：`requires-python = ">=3.11"`，classifiers 覆盖 3.11–3.14。

### 3.2 演示应用依赖（`demo/`）

- `demo/package.json` 中 `@openai/agents` 与 `zod` 使用精确版本号（`0.14.3`、`4.4.3`），测试依赖 `@playwright/test: 1.62.1`。
- `demo/requirements.txt` 是演示服务的独立依赖清单，全部使用精确版本（`fastapi==0.115.6`、`uvicorn[standard]==0.34.0`、`httpx==0.28.1`、`pyyaml==6.0.2`），并注释说明 PyYAML 用于读取 YAML 参数目录，且该平台不导入 torch。
- `demo/.npmrc` 将 npm registry 固定为官方源，并设置 `min-release-age=7`（新发布需等待 7 天）。`replace-registry-host=always` 确保即使依赖间接引用其他 host，也会被替换回官方 registry。

### 3.3 第三方子模块

- `silero-vad/` 是一个独立的第三方包（含自己的 `pyproject.toml`、`hubconf.py`、多语言示例），作为 git subtree/submodule 形式纳入本仓库，其依赖由其自身 `pyproject.toml` 管理，不在主包 `pyproject.toml` 中声明。

## 4. 约定与约束

- **版本锁定粒度**：ML 相关核心库（openai、nltk、librosa、torch/torchaudio、transformers、mlx-*、miniaudio）在主包中使用 `==` 精确锁定；Web 框架类依赖使用 `>=` 放宽范围。这是代码中实际观察到的模式，而非文档化规则。
- **平台分派**：macOS 与非 macOS 的依赖在 `pyproject.toml` 中以 `platform_system == 'Darwin'` 条件分支表达，Windows 也有特例（`faster-qwen3-tts`、`sounddevice`、`soundfile`、`torch`、`torchaudio`、`transformers`、`miniaudio`、`kokoro` 相关依赖）。
- **可选功能按能力拆分**：每个 STT/TTS/LLM/VAD 后端对应一个 extras group，避免默认安装重型依赖。
- **演示服务与主包解耦**：`demo/requirements.txt` 与 `pyproject.toml` 中的依赖列表不完全一致（例如 demo 固定 `fastapi==0.115.6`，主包写 `fastapi>=0.115.0`），二者各自维护。
- **Dependabot 仅覆盖 GitHub Actions**：`.github/dependabot.yml` 只声明了 `github-actions` ecosystem，未包含 `pip` 或 `npm`，因此 Python/Node 依赖不会自动收到 PR。
- **npm registry 强制**：`demo/.npmrc` 的 `replace-registry-host=always` 强制所有 npm 包解析都走 `https://registry.npmjs.org/`，禁止从其他镜像源拉取。
- **构建后端固定**：`[build-system].requires` 固定 setuptools 最低版本，保证可重现构建。

## 5. 缺失项

- 没有 `requirements.txt` 形式的 Python 主包依赖清单（依赖仅在 `pyproject.toml` 中声明）。
- 没有 `setup.py` / `setup.cfg`。
- 没有 `poetry.lock` / `uv.lock` 等 Python 锁文件（依赖版本由 `pyproject.toml` 直接声明）。
- 没有 pip 私有 index / `--extra-index-url` / `PIP_INDEX_URL` 配置。
- Dependabot 未配置 Python 与 npm 生态的自动更新。