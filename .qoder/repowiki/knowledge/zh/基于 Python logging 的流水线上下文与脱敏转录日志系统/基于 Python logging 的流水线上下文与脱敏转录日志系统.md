---
kind: logging_system
name: 基于 Python logging 的流水线上下文与脱敏转录日志系统
category: logging_system
scope:
    - '**'
source_files:
    - src/speech_to_speech/pipeline/log_context.py
    - src/speech_to_speech/pipeline/transcript_logging.py
    - src/speech_to_speech/s2s_pipeline.py
    - src/speech_to_speech/configured_runtime.py
    - src/speech_to_speech/cli.py
    - tests/test_handler_logging_hygiene.py
---

## 1. 使用的框架与总体方案

项目使用 Python 标准库 `logging`，没有引入第三方日志框架（如 structlog、loguru）。日志在进程启动时通过 `logging.basicConfig` 统一配置格式和级别，并通过自定义 `logging.Filter` 注入每 pipeline 的前缀。敏感对话内容默认不写入应用日志，而是通过一个模块级开关 `transcript_logging.py` 进行脱敏。

## 2. 核心文件

- `src/speech_to_speech/pipeline/log_context.py` — 定义 `pipeline_log_ctx` (`contextvars.ContextVar`) 和 `PipelineLogFilter`，为每个 pipeline 实例注入 `[pipeline N] ` 前缀。
- `src/speech_to_speech/pipeline/transcript_logging.py` — 提供 `set_log_transcripts` / `warn_if_log_transcripts_enabled` / `transcript_for_log` / `log_exception`，作为“是否把完整对话文本写进日志”的统一门控。
- `src/speech_to_speech/s2s_pipeline.py` 中的 `setup_logger(log_level)` — 唯一负责调用 `logging.basicConfig` 并注册 `PipelineLogFilter` 的地方。
- `src/speech_to_speech/configured_runtime.py` 中的 `run_configured_command` — 根据 CLI/YAML 的 `runtime.log_level` 和 `runtime.log_transcripts` 决定实际日志级别与脱敏开关。
- `src/speech_to_speech/cli.py` — 解析 `--log-transcripts` / `--log_transcripts` 参数，并在 `talk` 子命令中直接调用 `set_log_transcripts` + `warn_if_log_transcripts_enabled`。

## 3. 架构与约定

### 3.1 日志初始化

`setup_logger` 是服务侧唯一的入口：

```python
logging.basicConfig(
    level=log_level.upper(),
    format="%(asctime)s - %(pipeline_prefix)s%(name)s - %(levelname)s - %(message)s",
)
pipeline_filter = PipelineLogFilter()
for h in logging.getLogger().handlers:
    h.addFilter(pipeline_filter)
```

- 默认级别来自 YAML `config.runtime.log_level`，缺省值为 `"info"`。
- 当 `log_level == "debug"` 时额外开启 PyTorch compile 日志：`torch._logging.set_logs(graph_breaks=True, recompiles=True, cudagraphs=True)`。
- 客户端模式（`talk`）不走 `setup_logger`，而是在 `configured_runtime.run_configured_command` 中直接调用 `logging.basicConfig(level=...)`。

### 3.2 多 pipeline 上下文标记

`pipeline_log_ctx: contextvars.ContextVar[Optional[int]]` 保存当前 pipeline 索引；`PipelineLogFilter.filter` 读取该变量并把 `record.pipeline_prefix` 设为 `[pipeline N] ` 或空字符串。所有 handler 线程/asyncio task 在进入时设置 `pipeline_log_ctx.set(self.pipeline_index)`（例如 `STT/openai_compatible_handler.py`），从而让同一进程内多个并行 pipeline 的日志可区分。

### 3.3 命名空间约定

- 业务代码普遍使用 `logger = logging.getLogger(__name__)`，形成以包路径命名的 logger 树。
- demo 层使用显式命名空间：`s2s.auth`、`s2s.limiter`、`s2s.params`、`s2s.search`，便于按子系统过滤。

### 3.4 转录内容脱敏

`transcript_logging.py` 维护模块级 `_log_transcripts = False`，并提供：

- `transcript_for_log(text)`：未启用时返回 `chars=N`，启用时返回原文字符串。所有 STT/LLM/TTS 的日志点都通过它包裹原始文本，例如：
  - `STT/transcription_notifier.py`: `logger.info("Transcription completed (language=%s): %s", language_code, transcript_for_log(transcript))`
  - `LLM/base_openai_compatible_language_model.py`: `logger.debug("Clean text: %s", transcript_for_log(state.clean_text))`
  - `TTS/kitten_tts_handler.py`: `logger.debug("KittenTTS synthesizing: %s", transcript_for_log(text))`
- `log_exception(target, message, exc, *, level=logging.ERROR)`：未启用时只记录异常类型名，启用时才附带 `exc_info=(type(exc), exc, exc.__traceback__)`。
- `warn_if_log_transcripts_enabled()`：首次检查到已启用时输出警告，提醒生产环境不要保留完整对话。

### 3.5 开关来源

| 入口 | 设置位置 |
|---|---|
| CLI `speech-to-speech talk --log-transcripts` | `cli.parse_talk_arguments` → `RealtimeAudioClientConfig.log_transcripts` → `cli.main` 调用 `set_log_transcripts` |
| YAML `config.runtime.log_transcripts` | `configured_runtime._adapt` 注入 `ParsedArguments.module_kwargs.log_transcripts`，再由 `run_configured_command` 调用 `set_log_transcripts` |
| 本地模式 (`local`) | 校验 `runtime.log_transcripts` 与 `runtime.client.log_transcripts` 必须一致，否则抛出 `ConfigurationError` |

## 4. 约定与约束

- **library 模块不得调用 `logging.basicConfig`**：测试 `tests/test_handler_logging_hygiene.py` 通过 AST 遍历断言 library 模块（非脚本）不能调用 `logging.basicConfig`，只有 CLI/脚本端负责根配置。
- **handler 模块不得自行初始化日志**：同测试断言 handler 模块也不能调用 `basicConfig`，只能消费已配置的 logger。
- **敏感文本默认脱敏**：`transcript_for_log` 是向日志输出用户/助手文本的唯一通道；未显式启用 `--log-transcripts` 时，任何包含对话内容的日志只会输出字符数而非原文。
- **pipeline 前缀由 Filter 注入**：日志格式固定为 `%(asctime)s - %(pipeline_prefix)s%(name)s - %(levelname)s - %(message)s`，其中 `pipeline_prefix` 由 `PipelineLogFilter` 填充，不是源码硬编码。
- **日志级别统一来自配置**：服务侧通过 `config.runtime.log_level`（默认 `info`），客户端侧通过 `logging.basicConfig(level=config.runtime.get("log_level", "info").upper())`。
- **demo 子系统使用 `s2s.*` 命名空间**：`auth`、`limiter`、`params`、`search` 等 demo 组件全部使用 `logging.getLogger("s2s.xxx")`，与 core 包的 `__name__` 风格区分开。

## 5. 观察到的局限

- 没有结构化 JSON 日志格式；输出是带时间戳和名称的传统文本行。
- 没有集中 sink 抽象（stdout/stderr/file/远程收集器），仅依赖 Python logging 的 root handlers。
- 没有统一的 trace/correlation id；pipeline 上下文只通过 `[pipeline N]` 前缀区分，而不是字段化的 correlation_id。
- 第三方库（如 faster-whisper、openai、torch）的日志通过 root logger 继承，未被单独隔离或降级。