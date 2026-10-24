---
kind: configuration_system
name: YAML + dataclass 类型驱动的离线配置系统
category: configuration_system
scope:
    - '**'
source_files:
    - src/speech_to_speech/config.py
    - src/speech_to_speech/_config_yaml.py
    - src/speech_to_speech/configured_runtime.py
    - src/speech_to_speech/backend_registry.py
    - config/prod.yaml
    - config/prod.env.example
    - docs/configuration.md
    - example_configs/mac.yaml
---

## 1. 采用的方案

项目实现了一套自研的离线 YAML 配置加载与校验系统，核心由 `src/speech_to_speech/config.py`（类型校验、环境值解析、流水线组装）和 `src/speech_to_speech/_config_yaml.py`（受限 YAML 解析器）组成。它不依赖 Pydantic / Hydra / OmegaConf 等外部框架，而是基于 Python `dataclasses` 字段定义 + `typing.get_type_hints` 做运行时类型检查。

- 配置文件格式：单文档 YAML mapping，根键为 `schema_version` / `runtime` / `blocks` / `pipelines`。
- 值来源：文件内字面量、`{env: NAME}` 引用环境变量、dataclass 默认值。
- 后端选择：通过 `backend_registry` 中注册的 STT/LLM/TTS 后端及其 `config_type` 动态决定每个 block 的 settings schema。
- 运行时构建：`resolve_config` 返回 `ResolvedConfig`（含 runtime、pipelines、client、sources），再由 `configured_runtime.py` 构造实际服务。

## 2. 关键文件

- `src/speech_to_speech/config.py` — 配置加载、校验、解析主逻辑；定义 `ConfigurationError`、`ConfigDocument`、`ResolvedStage`、`ResolvedPipeline`、`ResolvedConfig`。
- `src/speech_to_speech/_config_yaml.py` — 基于 `yaml.SafeLoader` 的受限解析器，限制文件大小、嵌套深度、锚点/别名/merge key/tags。
- `src/speech_to_speech/arguments_classes/*.py` — 各组件的 dataclass 参数定义，作为 YAML settings 的 schema 来源。
- `src/speech_to_speech/backend_registry.py` — 后端注册表，提供 `STT_BACKENDS` / `LLM_BACKENDS` / `TTS_BACKENDS` 及 `BackendSelection`。
- `src/speech_to_speech/configured_runtime.py` — 将 `ResolvedConfig` 转换为可运行的 server/runtime。
- `config/prod.yaml` — 生产部署示例（被参数平台渲染）。
- `config/prod.env.example` / `config/prod.env` — 环境变量模板与密钥。
- `docs/configuration.md` — 官方配置文档。
- `example_configs/mac.yaml` — macOS 本地运行示例。

## 3. 架构与设计约定

### 3.1 三阶段处理流程

```text
load_config(path) → ConfigDocument
validate_config(document) → None
resolve_config(document, names, environ, include_client) → ResolvedConfig
```

- `load_config` 仅做文件格式检查和调用 `_config_yaml.read_document`，不导入运行时模块。
- `validate_config` 检查 schema_version、block/pipeline 结构、后端名称合法性、组合约束（如 diarization 需要 STT、bypass STT 需要支持 audio input 的 LLM），但不读取环境变量。
- `resolve_config` 才真正解析 `{env: ...}`、展开路径、实例化后端 `BackendSelection`，并记录每个字段的来源（`file` / `environment` / `default`）到 `ResolvedConfig.sources`。

### 3.2 YAML 解析安全边界

`_config_yaml.py` 显式禁用以下 YAML 特性：
- Anchors / Aliases
- Explicit tags
- Merge keys (`<<`)
- Duplicate mapping keys
- 非有限浮点数（inf/nan）
- 容器嵌套超过 32 层
- 文件大小超过 1 MiB
- 非 UTF-8 编码
- 非 mapping 根节点

所有错误统一抛出 `ConfigurationError`，且诊断信息不包含原始输入值（使用 `safe_path` 过滤敏感内容）。

### 3.3 类型系统与值校验

`_value` 函数根据 dataclass 字段的 type hints 递归校验：
- `str | None`、`bool`、`int`、`float`、`Literal[...]`、`list[T]`、`dict`、`Any`。
- `Union` 按 literal 类型优先匹配，再回退到基类。
- `float` 必须有限（`math.isfinite`）。
- 集合用 YAML 序列表示，字典必须是字符串键映射。
- 未知字段直接报错（白名单来自 dataclass fields）。

### 3.4 环境变量注入机制

- 语法：`{env: VAR_NAME}`，VAR_NAME 必须符合正则 `[A-Za-z_][A-Za-z0-9_]*`。
- 仅标量字段允许 env 引用（`str`/`bool`/`int`/`float`/`Literal`）；集合必须写 YAML。
- 缺失的环境变量是硬错误（无 fallback）。
- `num_pipelines` 也支持 env 引用。
- 已解析的 secrets 不会在日志中暴露（`ConfigurationError` 只输出字段名）。

### 3.5 路径展开规则

以下字段会被视为文件系统路径，自动展开 `~` 并将相对路径相对于 YAML 文件所在目录解析：
`vad_firered_model_dir`、`smart_turn_model_path`、`omnivoice_ref_audio`、`omnivoice_voice_clone_prompt`、`omnivoice_ref_voices_dir`、`qwen3_tts_gguf_talker_path`、`qwen3_tts_gguf_codec_path`、`qwen3_tts_ref_cache_dir`、`qwen3_tts_ref_audio`、`qwen3_tts_ref_spk`、`qwen3_tts_ref_rvq`。
其他字段（模型 ID、URL、tool module name）保持字面量。

### 3.6 Pipeline 与 Block 模型

- `blocks`：声明 VAD/STT/LLM/TTS 组件实例，包含 `kind`、`backend`、`settings`。
- `pipelines`：将 blocks 串联成 `stages: {vad, stt, llm, tts}`，每个 stage 必须引用同 kind 的 block。
- `num_pipelines`：该 pipeline 的独立实例数，默认 1，必须为正整数。
- `options`：pipeline 级选项（device、diarization、enable_visemes 等），受 `_MODULE_PIPELINE` 白名单约束。
- `runtime`：进程级设置（log_level、log_transcripts、torch_num_threads）、server（host/port）、client（url、voice、input/output device、playback_buffer_ms、tool_module）。

### 3.7 组合约束（`_check_composition`）

- bypass STT（`backend: none`）要求 LLM backend 支持音频输入。
- 启用说话人分离（diarization）必须有 STT backend。
- diarization threshold 必须在 (0, 1)。
- LLM proxy 仅在 backend 能力支持时可用。

## 4. 约定与约束

**观察到的约定：**
- 配置文件放在 `config/` 或 `example_configs/`，CLI 通过 `-f/--file` 指定。
- 生产配置由“参数平台”渲染生成（`prod.yaml` 注释说明），`.env` 文件由 docker-compose 的 `env_file:` 注入。
- 敏感凭据（如 `GPUSTACK_API_KEY`、`S2S_ADMIN_TOKEN`）通过 `{env: ...}` 注入，不在 YAML 中明文出现。
- 每个后端 handler 对应一个 `*_arguments.py` dataclass，新增后端需同时注册到 `backend_registry` 并提供参数类。
- 配置文档与代码同步维护于 `docs/configuration.md`。

**明确强制的规则（有源码/文档依据）：**
- `schema_version` 必须为整数且等于 1（`config.py:375`）。
- YAML 文件后缀必须为 `.yaml` 或 `.yml`（`config.py:116`）。
- 文件最大 1 MiB、嵌套深度不超过 32 层（`_config_yaml.py:13-14`）。
- 禁止 YAML anchors、aliases、merge keys、explicit tags、重复键（`_config_yaml.py:60-87`）。
- 布尔值仅接受小写 `true`/`false`，null 为小写 `null`（`_config_yaml.py:41-43`，`configuration.md:127`）。
- 数值必须为有限十进制数，拒绝 inf/nan（`_config_yaml.py:49-54`，`config.py:243-253`）。
- 环境变量引用必须使用 `{env: NAME}` 语法，且 VAR_NAME 符合标识符正则（`config.py:19`、`config.py:190`）。
- 缺失的环境变量是硬错误，不提供 fallback（`config.py:197-198`，`configuration.md:112`）。
- blocks 和 pipelines 映射都必须非空（`config.py:391-392`）。
- pipeline 的 stages 必须恰好包含 vad/stt/llm/tts 四个键（`config.py:420-421`）。
- block id 和 pipeline name 必须以字母开头，长度 1–64，仅含字母、数字、下划线、连字符（`config.py:18`、`config.py:395-399`、`config.py:416-417`）。
- 未记录的字段会报错（`config.py:153-154`，`configuration.md:68`）。
- 返回值中的 secrets 不得直接序列化或日志输出（`configuration.md:165`）。

**遗留兼容：**
- CLI 的扁平 JSON 输入仍在工作区外保留（`config.py:117-122` 提示），但新配置应使用 YAML 文件模式。
- 旧版 Docker Compose 中的 40+ CLI 标志已迁移到 `config/prod.yaml`（文件头注释）。