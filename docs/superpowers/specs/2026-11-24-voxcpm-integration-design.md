# VoxCPM 系列 TTS 后端与 MiniCPM-o 2.6 元信息接入设计

- 日期：2026-11-24
- 状态：已确认，待实施
- 关联：`docs/model-integration-guide-CN.md`、`docs/voiceprint-embedding-service-design-CN.md`

## 1. 背景与前提修正

原始需求为“VoxCPM2 2B / 0.8B / 0.5B + MiniCPM-o 2.6”。核实官方信息后修正如下：

| 需求名 | 实际情况 | 采纳 |
|---|---|---|
| VoxCPM2 2B | `openbmb/VoxCPM2`，2B，Apache-2.0，原生 48 kHz | 直接接入 |
| VoxCPM2 0.8B | 不存在；0.8B 属于 `openbmb/VoxCPM1.5` | 以 VoxCPM1.5 接入 |
| VoxCPM2 0.5B | 不存在；0.5B 属于 `openbmb/VoxCPM-0.5B` | 以 VoxCPM-0.5B 接入 |
| MiniCPM-o 2.6 | 8B 全模态（SigLIP-400M + Whisper-medium-300M + ChatTTS-200M + Qwen2.5-7B），非单一 TTS/LLM | 仅登记 `planned` card |

三者共用同一套 `voxcpm` 库 API（`VoxCPM.from_pretrained` / `generate` / `generate_streaming`），因此采用“**单后端 + 多 card**”。

## 2. 范围与非目标

范围内：

1. 新增 TTS 后端 `voxcpm`，通过 `--voxcpm_tts_model_name` 切换三档权重。
2. 新增 3 张 `available` card 和 1 张 `planned` card。
3. 参数校验、错误处理、日志。
4. 离线单测（mock `voxcpm` 与权重）。
5. 文档与模型清单更新。
6. 声纹能力保护：明确部署约束，并在启动期给出可操作告警。
7. 语言能力声明：为 `voxcpm` 增加 `speech_languages` 分支。

非目标：

- 不做真实权重推理验证（`voxcpm` 要求 Python < 3.13，当前开发环境为 3.14；且 12 GB 显存叠加管线会 OOM）。
- 不为 MiniCPM-o 2.6 实现 handler（仅元信息）。
- 不改动任何现有后端行为。

## 3. 架构

```
CLI --tts voxcpm --voxcpm_tts_model_name openbmb/VoxCPM2
        │
        ▼
TTS_BACKENDS["voxcpm"]  BackendSpec(config_prefix="voxcpm_tts", required_extra="voxcpm")
        │  _simple_handler_factory(setup_should_listen=True, context_kwargs=True)
        ▼
VoxCPMTTSHandler(BaseTTSHandler)
        │  from_pretrained → generate(_streaming) → soxr 16 kHz → int16 → 512 分片 → AUDIO_RESPONSE_DONE
        ▼
Realtime 路由器 / 可选 viseme 阶段
```

模型差异只在权重与元信息；handler 通过原生采样率自适应，不按模型名分支。

## 4. 参数层

文件：`src/speech_to_speech/arguments_classes/voxcpm_tts_arguments.py`

类名：`VoxCPMTTSHandlerArguments`，前缀 `voxcpm_tts`。

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `voxcpm_tts_model_name` | str | `openbmb/VoxCPM2` | HF repo id 或本地目录 |
| `voxcpm_tts_device` | str | `auto` | 复用仓库现有设备解析；不可用时回退 CPU |
| `voxcpm_tts_dtype` | str | `auto` | `auto / float16 / bfloat16 / float32`，best-effort |
| `voxcpm_tts_cfg_value` | float | `2.0` | 官方推荐 1.0–3.0 |
| `voxcpm_tts_inference_timesteps` | int | `10` | 1–100 |
| `voxcpm_tts_normalize` | bool | `True` | 文本正则化 |
| `voxcpm_tts_denoise` | bool | `False` | 采样期降噪 |
| `voxcpm_tts_load_denoiser` | bool | `False` | 是否加载降噪器（额外显存） |
| `voxcpm_tts_seed` | int \| None | `None` | 复现用 |
| `voxcpm_tts_ref_audio` | str \| None | `None` | 参考音频路径（克隆/音色设计） |
| `voxcpm_tts_prompt_text` | str \| None | `None` | 参考文本，需同时给 `ref_audio` |
| `voxcpm_tts_streaming` | bool | `True` | 流式合成 |

帧长固定为模块常量 `BLOCKSIZE = 512`，不暴露为参数，避免用户配置出违反管线契约的输出。

环境变量由 `config_prefix` 自动派生（`VOXCPM_TTS_*`）。

## 5. Handler 设计

文件：`src/speech_to_speech/TTS/voxcpm_tts_handler.py`，类 `VoxCPMTTSHandler(BaseTTSHandler)`。

### 5.1 setup

1. 校验参数（见 §6），失败抛 `ValueError`，启动期失败。
2. 惰性 `import voxcpm`（保持 CLI `models` 子命令不加载重依赖）。
3. `VoxCPM.from_pretrained(model_name, load_denoiser=...)`。
4. 设备/精度 best-effort：`hasattr(model, "to")` 时 `model.to(device)`；失败仅 warning，不阻断。
5. 原生采样率：依次尝试 `model.sample_rate`、`model.tts_model.sample_rate`、`model.output_sample_rate`，缺省 48000。
6. 日志：模型名、解析设备、原生采样率、流式开关、是否加载降噪器。

### 5.2 process

1. 沿用 `BaseTTSHandler` 的 `EndOfResponse` 门控与取消语义，结构对齐 `supertonic_tts_handler.py`。
2. 空文本直接跳过，不发音频。
3. 组装生成参数：`text` + 可选 `prompt_wav_path`（= `ref_audio`）、`prompt_text`、`cfg_value`、`inference_timesteps`、`normalize`、`denoise`、`seed`；`None` 值不传。
4. 流式：`generate_streaming(...)` 逐块产出；非流式：`generate(...)` 一次产出。两者输出统一走同一后处理。
5. 重采样：`soxr.ResampleStream(native_sr, 16000, 1, dtype="float32", quality="HQ")`，流式跨块保持状态，结束时 flush，避免分块爆音。
6. 转 int16：mono、`np.clip(-1, 1) * 32767`、C-contiguous。
7. 切片：累积缓冲，按 512 采样输出；结束时尾部补零到 512。
8. 每片之间检查取消作用域，已失效则立即停止。
9. 收到 `EndOfResponse` 时输出 `AUDIO_RESPONSE_DONE`。
10. 兼容性兜底：`generate*` 因未知关键字抛 `TypeError` 时，降级为只传 `text` 重试一次，并 warning 一次（记录库版本差异）。

`voice` 字段按仓库约定只回显、不改变合成；音色控制统一走 `voxcpm_tts_ref_audio`。

## 6. 校验、错误与日志

### 6.1 启动期 `ValueError`

- `cfg_value` 非有限或 ≤ 0。
- `inference_timesteps` 不在 1–100。
- `ref_audio` 非空但路径不存在。
- `prompt_text` 非空但 `ref_audio` 为空。
- `dtype` 不在枚举内；`device` 无法解析。

### 6.2 运行期错误

| 场景 | 行为 |
|---|---|
| 未安装 `voxcpm` | `ImportError`，消息含 `pip install "speech-to-speech[voxcpm]"` 与“需要 Python 3.10–3.12” |
| 本地路径不存在 | `ModelWeightsMissingError`，含路径、repo_id、下载命令 |
| 远程权重下载失败 | 包装为 `RuntimeError`，含 repo_id 与网络/缓存提示，不静默降级 |
| 推理异常 | 记录模型名、文本长度、耗时后原样抛出；禁止吞错返回静音 |
| 设备/精度设置失败 | warning，继续用库默认 |

## 7. 与既有声纹 / 情感 / 口型能力的相互影响

### 7.1 结论

- **情感识别：不受影响**。管线 SER、`/v1/audio/emotion` 本地模式、emotion2vec 代理都在输入侧或 STT 侧，与 TTS 后端无关。
- **口型 visemes：接口不变**。`Wav2Vec2STVHandler` 要求 16 kHz / 512 / 哨兵；本 handler 严格满足，且该阶段失败本身是 soft-skip。
- **声纹：接口不变，但能力依赖需显式解除**。`VoiceprintService.attach_pool()` 只在池内查找 `Qwen3TTSHandler`；改用 `voxcpm` 后若未配置 `VOICEPRINT_ENCODER_DIR`，`capability.ready=false`，`/v1/audio/embeddings` 返回 503 `MODEL_UNAVAILABLE`。配置独立的 speaker encoder（方案 C，生产形态）即完全不受影响。

### 7.2 声纹保护措施（纳入实施）

1. **启动期可操作告警**：修改 `voiceprint/service.py` 中“找不到 Qwen3TTSHandler”的 warning，明确说明“当前 TTS 不是 qwen3 时不提供 encoder；请设置 `VOICEPRINT_ENCODER_DIR` 使用方案 C，否则嵌入接口返回 503 `MODEL_UNAVAILABLE`”。只改日志文案，不改行为。
2. **文档约束**：在 `docs/voiceprint-embedding-service-design-CN.md` 增加一行部署约束：切换 TTS 后端（含 `voxcpm`）必须保留 `VOICEPRINT_ENCODER_DIR`。
3. **回归保护**：新增测试断言告警文案包含 `VOICEPRINT_ENCODER_DIR`，确保后续不被删掉。

### 7.3 语言能力声明（纳入实施）

`speech_languages.py` 的 `kind == "tts"` 分支增加：

```python
elif name == "voxcpm":
    languages, auto = getattr(module, "VOXCPM_LANGUAGE_CODES", None), True
```

handler 模块内定义 `VOXCPM_LANGUAGE_CODES` 为官方 30 语言（Whisper 风格代码）：

```
ar my zh da nl en fi fr de el he hi id it ja km ko lo ms no pl pt ru es sw sv tl th tr vi
```

- `supports_auto=True`：VoxCPM 无需语言标签自动识别。
- `supports_language_selection` 保持默认 `True`：避免把 STT 的语言选择能力一并关闭；TTS 侧语言字段只影响校验、不实际生效，与 `voice` 字段行为一致。此取舍写入文档。
- 9 种中文方言仅在 `notes` 中说明，不进代码集合。

## 8. 注册表与模型卡片

### 8.1 BackendSpec

`src/speech_to_speech/backend_registry.py`，追加到 `TTS_BACKENDS`（与 `supertonic` 同形）：

```python
BackendSpec(
    "voxcpm",
    "tts",
    VoxCPMTTSHandlerArguments,
    _simple_handler_factory(
        "speech_to_speech.TTS.voxcpm_tts_handler",
        "VoxCPMTTSHandler",
        setup_should_listen=True,
        context_kwargs=True,
    ),
    config_prefix="voxcpm_tts",
    required_extra="voxcpm",
)
```

`models=()`，卡片统一放 `builtin.py`，保持 `spec.models == ()` 断言成立。

### 8.2 Card（`src/speech_to_speech/models/builtin.py`）

| id | kind | backend | repo_id | min_vram_gb | status | 备注 |
|---|---|---|---|---|---|---|
| `voxcpm2-2b` | tts | `voxcpm` | `openbmb/VoxCPM2` | 8.0（官方） | available | 48 kHz，30 语言 + 9 方言，Apache-2.0 |
| `voxcpm1.5-0.8b` | tts | `voxcpm` | `openbmb/VoxCPM1.5` | None | available | 约 0.8B，44.1 kHz；显存官方未给出 |
| `voxcpm-0.5b` | tts | `voxcpm` | `openbmb/VoxCPM-0.5B` | None | available | 约 0.5B，16 kHz；显存官方未给出 |
| `minicpm-o-2-6` | llm | `minicpm-o` | `openbmb/MiniCPM-o-2_6` | None | planned | 8B 全模态，非流水线后端，需 `trust_remote_code` |

- 三张 voxcpm card 的 `default_load_params` 均为 `{"model_name": "<repo_id>"}`。
- `license`：VoxCPM 系列 `Apache-2.0`；MiniCPM-o 2.6 为 `MiniCPM Model License`。
- `minicpm-o-2-6` 的 `backend_name="minicpm-o"` 未注册，`planned` 状态允许（`validate()` 仅对 available 报错）。
- `notes` 必须写明：48/44.1/16 kHz 原生输出经 handler 重采样到 16 kHz；`voxcpm` 需 Python < 3.13；MiniCPM-o 2.6 不是独立 TTS/STT/LLM、本仓不提供运行适配。

## 9. 配置与依赖

- `src/speech_to_speech/config.py`：`_PATH_FIELDS` 增加 `voxcpm_tts_ref_audio`，使 YAML/env 中的相对路径按配置文件目录解析。
- `pyproject.toml`：optional-dependencies 增加 `voxcpm = ["voxcpm"]`（不锁版本）。无法在 Python 3.14 安装，属预期行为；文档说明。

## 10. 测试计划

新增 `tests/test_voxcpm_tts_handler.py`（全部离线，注入假 `voxcpm` 模块）：

1. `setup` 正常加载、采样率三种来源回退、日志字段。
2. 全部参数校验分支（cfg、timesteps、dtype、ref_audio 不存在、prompt_text 缺参考音频）。
3. `voxcpm` 缺失 → `ImportError` 文案含 extra 与 Python 版本提示。
4. 本地路径缺失 → `ModelWeightsMissingError`。
5. 流式与非流式输出等价：16 kHz、int16、每片 512、尾部补零。
6. 48 kHz→16 kHz、44.1 kHz→16 kHz 的长度与比例正确。
7. 取消后提前停止且不再产出。
8. 推理异常原样抛出、不被吞。
9. `generate*` 关键字不兼容时降级重试一次。

更新既有断言：

- `tests/test_model_registry.py`：card 9→13，planned 6→10，available 列表增加 3 个 voxcpm id，后端总数 31→32。
- `tests/test_model_config_overrides.py`：available 3→6，planned 6→10，unregistered 保持 27（新增后端与新增卡片相互抵消）。
- 如存在 TTS 后端清单断言（`tests/test_backend_registry.py` 等），同步补充 `voxcpm`。
- 新增 `speech_languages` 用例：`voxcpm` 返回 30 语言、`supports_auto=True`；并断言 `VOXCPM_LANGUAGE_CODES` 全为 2 字母码。
- 声纹告警用例：断言文案包含 `VOICEPRINT_ENCODER_DIR`。

验收命令：

```bash
python -m speech_to_speech.cli models list
pytest tests/test_voxcpm_tts_handler.py tests/test_model_registry.py tests/test_model_config_overrides.py
pytest
ruff check .
```

## 11. 文档更新

- `README.md` / `README-CN.md`：可选依赖安装行；TTS 表格新增 3 行。
- `docs/model-integration-guide-CN.md`：模型清单与计数（9→13、31→32）；“路径 R”补 VoxCPM2 示例；注明 Python 约束。
- `docs/model-combination-matrix-CN.md`：TTS 表新增 3 行与显存/硬件档位建议；LLM 侧注明 MiniCPM-o 2.6 为 planned、非流水线后端。
- `docs/parameter-catalog.md`：§1 计数更新；§5.3 增加 `voxcpm_*` 字段表。
- `docs/voiceprint-embedding-service-design-CN.md`：补“切换 TTS 后端必须保留 `VOICEPRINT_ENCODER_DIR`”。

## 12. 风险

| 风险 | 影响 | 处置 |
|---|---|---|
| `voxcpm` 仅支持 Python < 3.13 | 当前 3.14 环境无法真实运行 | 文档 + 错误消息明确；单测 mock |
| 12 GB 显存跑 2B + 4.6 GB 管线 OOM | 本机不能端到端验证 | card `notes` 与矩阵文档标注；建议 ≥ 16 GB |
| `voxcpm` 库 API 版本差异 | 生成参数可能不兼容 | TypeError 降级重试 + warning，不阻断 |
| 声纹方案 A 失效 | 未配 encoder 的部署返回 503 | 启动告警 + 文档约束 |
| 44.1 kHz 重采样非整数比 | 重采样质量/延迟 | 统一走 `soxr` 流式高质量重采样 |

## 13. 实施清单（顺序）

1. 新增参数 dataclass。
2. 新增 handler（setup / process / 重采样 / 分片 / 错误处理 / 语言码常量）。
3. `backend_registry.py` 注册 `voxcpm`。
4. `models/builtin.py` 增加 4 张 card。
5. `config.py` 增加 `voxcpm_tts_ref_audio` 路径字段。
6. `speech_languages.py` 增加 `voxcpm` 分支。
7. `voiceprint/service.py` 告警文案。
8. `pyproject.toml` 增加 extra。
9. 新增 handler 测试；更新注册表/配置/语言/声纹相关测试。
10. 更新 README 与 4 份 docs。
11. 运行验收命令，修复回归。

## 14. 验收标准

- `models list` 显示 13 张 card：6 available、10 planned、0 deprecated；`voxcpm2-2b`、`voxcpm1.5-0.8b`、`voxcpm-0.5b` 为 available，`minicpm-o-2-6` 为 planned。
- `--tts voxcpm` 在缺失依赖时给出可操作 ImportError；在 mock 环境下完成初始化、流式/非流式合成与哨兵输出。
- 既有模型（qwen3 / supertonic / kitten 等）行为不变，全部测试与 `ruff` 通过。
- 声纹在方案 C 下不受影响；未配置 encoder 时启动日志给出明确指引。
