# Spec B：S2S 模型适配层（Breeze TTS 2 + MiniCPM 同源组件）设计

> 状态：**设计已批准（2026-11-12），待实施计划**
> 前置：`docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md`（Spec A，已交付并验收）
> 实现规范：`docs/model-integration-guide-CN.md`
> 验收口径：**代码就绪 + 契约测试；不下载权重、不触网、不占 GPU、不加载真实模型**

---

## 1. 意图与为什么

Spec A 交付了统一模型注册框架（`ModelCard` / `ModelRegistry`、`BackendSpec.models`、YAML `models:` 覆盖、`models list`、接入规范），但它只登记**元信息**：9 张 card 中 6 张仍是 `planned`，且 `ResolvedPipeline.model_cards` 没有任何运行时消费点。用户原始需求是「把 Breeze TTS 与 MiniCPM 系列 ASR/TTS/LLM 接入并形成可调用的组件」，本 spec 负责把这件事真正做完。

具体地，本轮要同时解决两件事：

1. **补齐适配层**：让 6 张 `planned` card 对应的模型都能被管线实际加载与调用。
2. **接通配置化**：让 `models:` 段的覆盖值真正影响 Handler 的加载参数，而不是只生成一份没人读的 card 副本。Spec A 的需求第 5 条「模型选择与参数通过配置文件或环境变量管理」目前是**半接通**状态。

**为什么现在做**：Spec A 已把 31 条既有 `BackendSpec` 的派生逻辑（CLI choices、参数类、YAML 校验）自动化，新增后端不会牵动既有配置；BreezeBlue 商业授权已于 2026-11-12 取得（Spec A §12），D7 的「禁止自托管」约束已撤销；GitHub 可达性已验证。

---

## 2. 目标 / 非目标 / 反目标

### 目标

- Breeze TTS 2 以**本地权重进程内加载**方式接入，音频输出与现有语音链路契约一致。
- MiniCPM 同源三段（ASR=Whisper-medium、TTS=CosyVoice2、LLM=Qwen3-8B）各成为可调用组件；MiniCPM-2B / 4B 作为可选 LLM 变体补齐元信息。
- 6 张 card 从 `planned` 翻为 `available`；`models list` 沿用 Spec A 已批准的 10 个字段（名称 / 类型 / 版本 / backend / 状态 / 权重格式 / 显存 / 许可等）；`repo_id`、`default_load_params`、`notes` 由 `ModelRegistry.get()` 与接入规范提供，**本轮不改 `cli.py`**。
- `models:` 段覆盖值注入运行时加载参数，settings 显式值优先，多 pipeline 互不串味。
- 新模型接入只需「Handler + 参数 dataclass + 一条 `BackendSpec` + 一张 card」，接入规范可直接照抄。

### 非目标

- 不下载任何权重、不安装 Breeze / CosyVoice 推理依赖、不做真实推理 PoC、不测 TTFA / RTF。
- 不实现 BreezeBlue 付费托管 API（路径 R）、社区 GGUF 量化版、任何新的远程 backend。
- 不实现 MiniCPM-o 4.5 端到端全双工接入（它是单一 9.4B omni checkpoint，无法拆成三段）。
- 不改 31 条既有 `BackendSpec` 构造、不改 CLI 既有 choices 与默认值、不改 `config/prod.yaml` 与 9 个 `docker-compose*.yml`。
- 不引入模型级选择器（如 `models.active`）、不新增环境变量前缀、不新增 CLI flag。
- 不做显存优化、多卡调度、互斥加载/卸载；这些属于部署阶段。

### 反目标（技术上跑通但算失败）

- **静默回退**：权重缺失或依赖缺失时自动换用其它模型。
- **card 驱动加载**：绕过 `spec.normalize()` 直接把 card 参数塞给 Handler，破坏单一事实来源。
- **破坏延迟导入**：`import backend_registry` 触发任何 STT/TTS/LLM handler 模块加载。
- **虚构元信息**：为未实测的 `min_vram_gb` / 未核实的 `license` 编造数字或许可名。
- **把官方 H100 + fast path 的 TTFA <40 ms 写进本仓验收线**。
- **把 24 kHz 音频直接丢进 16 kHz 管线**，或漏掉 `AUDIO_RESPONSE_DONE`。

---

## 3. 约束与已确认决策

### 3.1 继承自 Spec A

| 编号 | 决策 | 对 Spec B 的约束 |
|---|---|---|
| D1 | 目标模型以**本地权重进程内加载**（HF / transformers / GGUF）接入 | Breeze 用官方 `load_runtime()` / `model.generate()` 进程内库；不走流式 API 服务 |
| D2 | MiniCPM 三段按**同源组件**口径：ASR=Whisper-medium、TTS=CosyVoice2、LLM=Qwen3-8B | card notes 必须标注「非 MiniCPM 品牌独立模型」 |
| D3 | 验收为**代码就绪 + 契约测试** | 真实加载/推理代码要写全，但推理对象可注入，测试用 stub |
| D4 | 拆两层：Spec A 框架层、Spec B 模型适配层 | 本 spec 只做适配层与其必要接线 |
| D5 | `BackendSpec` 加可选 `models` 字段；**card 只作元信息声明，不驱动加载** | card 可以提供默认值，但不得绕过 `config_type` → `normalize()` → `setup_kwargs` |
| D6 | GitHub 可达性已验证（2026-11-10） | 依赖可在**构建期**获取；容器运行时不得依赖 GitHub |
| D7 | ~~商用场景禁止自托管 Breeze~~ | **已由 §12 撤销**，见 3.2 |
| §12 | BreezeBlue 商业授权已取得（2026-11-12） | `breeze-tts-2` 为 `planned`，Spec B **可以**实现本地权重加载；路径 L/R 降级为可选替代 |
| §11 | 本工程定位为**演示开源项目**；商用部署所需许可由应用方/商家自行申请 | 不因许可未核实而阻断代码就绪；但许可事实必须如实写入 card |

### 3.2 本轮新增决策（2026-11-12 用户确认）

| 编号 | 决策 | 说明 |
|---|---|---|
| B1 | 沿用 **D3：代码就绪 + 契约测试** | Breeze 官方 `load_runtime()` / `model.generate()` 调用真实写进适配层，但通过可注入 adapter 传入；测试用 stub/mock；权重缺失抛 `ModelWeightsMissingError` 并打印 `repo_id` + 下载命令 |
| B2 | 采用**方案 1：card 默认值注入** | 见 §5；`blocks.*.backend` 选后端，`models:` 覆盖后的 card 提供加载参数默认值；不引入模型级选择器，不打破 D5，旧 YAML 逐字不动 |
| B3 | 6 张 `planned` card **全部纳入**本轮并翻 `available` | 路径 R 与 GGUF 不做 |
| B4 | 分节设计四节全部批准 | 架构与组件 / 配置化与数据流 / 六个模型适配层 / 错误处理与测试验收 |

### 3.3 硬约束

- **音频契约**：STT 输入 16 kHz float32 `VADAudio`；TTS 输出 **16 kHz int16 little-endian PCM / 512 samples 每块**，结尾恰好一个 `AUDIO_RESPONSE_DONE`；`should_listen` 仅在 `EndOfResponse` 后恢复；`CancelScope` / `SpeculativeTurnTracker` 丢弃陈旧轮。
- **显存**：Breeze eager ~7.7 GiB、`--fast-all` ~14.4 GiB（官方单独运行口径）；叠加本仓 4.6 GB 管线底座约 12.3 GB / 19 GB，12 GB 卡无法同卡共存。本轮不实测、不写进验收线，只在 card notes 与接入规范记录预算口径。
- **许可**：Breeze 权重许可证名仍为 `BreezeBlue Research and Non-Commercial License`，商用权来自单独商业授权；MiniCPM 权重受「通用模型许可协议-来源说明-宣传限制-商业授权」约束，商用需单独授权；CosyVoice2 权重为 Apache-2.0。三者均按 §11 定位处理。

---

## 4. 现状核查（2026-11-12，只读）

### 4.1 半接通问题（本 spec 的核心缺口）

`config.py:591` 的 `BackendSelection` 只从 `blocks.*.settings` 构造：

```python
settings = _settings(document, block.get("settings", {}), config_type, ...)
selection = BackendSelection(spec, spec.normalize(config_type(**deepcopy(settings))))
```

`_apply_model_overrides()` 生成的 card 副本仅写入 `ResolvedPipeline.model_cards`（`config.py:593`），**全仓 `src/**/*.py` 未找到任何消费点**。因此当前改 YAML `models:` 段的 `repo_id` 或 `default_load_params` 不会切换权重，只会生成一份没人读的元数据。

### 4.2 `_settings()` 的默认值陷阱

`_settings()`（`config.py:265-319`）遍历 `fields(config_type)`，对未显式提供的字段**填入 dataclass 默认值**后才返回。因此：

> ❌ 不能用 `{**card.default_load_params, **settings}` 合并 —— `settings` 里的 dataclass 默认值会反向覆盖 card 参数，注入静默失效。

正确做法见 §6.2：在 `_settings()` 返回后，按「本次 YAML 中显式出现的键集合」逐键注入，显式键保持不变。

### 4.3 六个目标模型现状矩阵

| 模型 | card | BackendSpec | Handler | 参数 dataclass | 本轮缺口 |
|---|---|---|---|---|---|
| Breeze TTS 2 | `planned`，`backend_name="breeze-tts-2"` 未注册 | 无 | 无（`*breeze*` 文件 0 命中） | 无 | 全套新增 |
| CosyVoice2 | `planned`，`backend_name="cosyvoice2"` 未注册 | 无 | **有但未注册**：`TTS/cosyvoice_handler.py` | **有但未注册**：`arguments_classes/cosyvoice_tts_arguments.py` | 注册 + extra + 修 3 处不一致 |
| Whisper-medium | `planned`，`backend_name="whisper"` 已注册 | 复用 `whisper`（`backend_registry.py:364-374`） | 复用 `STT/whisper_stt_handler.py` | 复用 `WhisperSTTHandlerArguments` | 翻 `available` + 补默认值 |
| MiniCPM 同源 Qwen3-8B | `planned`，`backend_name="transformers"` 已注册 | 复用 `transformers`（517-523） | 复用 `LLM/language_model.py` | 复用 `LanguageModelHandlerArguments` | 翻 `available` + 补默认值 |
| MiniCPM-2B | `planned`，`repo_id=None` | 复用 `transformers` | 复用 | 复用 | 补 repo_id / license / 默认值 |
| MiniCPM-4B | `planned`，`repo_id=None`、`min_vram_gb=None` | 复用 `transformers` | 复用 | 复用 | 补 repo_id / license / 默认值 |

**已核实的省力事实**：
- `language_model.py:835` 的 `load_kwargs` **已硬编码 `trust_remote_code: True`**，而 MiniCPM-2B / MiniCPM3-4B 加载需要它 → 复用 `transformers` 后端**无需改任何 LLM 代码**。
- 重采样依赖（`librosa` / `soxr` / `scipy` / `torchaudio`）已在 `[project].dependencies`，**不需要新增**。
- `TTS/cosyvoice_handler.py` 已实现 24 kHz → 16 kHz `librosa.resample` + 512 samples 切块 + `AUDIO_RESPONSE_DONE` + `CancelScope` / `SpeculativeTurnTracker`，可直接复用。

### 4.4 联网核实结果（2026-11-12）

| 核实项 | 结果 | 影响 |
|---|---|---|
| MiniCPM-2B repo | `openbmb/MiniCPM-2B-dpo-bf16`（另有 `-sft-bf16`）；本轮选 **dpo** 版（对话对齐，更适合 LLM 后端） | card `repo_id` 可补齐 |
| MiniCPM-4B repo | **`openbmb/MiniCPM3-4B`**（官方 4B 名带 `3`，不是 `MiniCPM-4B`） | card id 保持 `minicpm-4b`（稳定标识），notes 标注命名差异 |
| MiniCPM 权重许可 | 代码 Apache-2.0；权重受「通用模型许可协议-来源说明-宣传限制-商业授权」，商用需联系授权 | 与 §11 一致；写入 card `license` + notes |
| CosyVoice2 许可 | HF 模型卡 frontmatter 明确 `license: apache-2.0`；第三方资料提到 README 另有学术用途免责声明 | 修正 card 的 `license=None`；notes 标注免责声明由应用方确认 |
| CosyVoice2 双源 | 参数类默认 ModelScope `iic/CosyVoice2-0.5B`，card 写 HF `FunAudioLLM/CosyVoice2-0.5B`，两者都存在 | card `default_load_params` 用 ModelScope id 与参数类默认值对齐；notes 说明 HF 镜像 |
| Breeze 官方仓库 | `github.com/breezeblue-ai/breeze-tts`：CLI / 进程内库 / 流式 API 三入口；24 kHz mono s16le；eager 7.7 GiB / `--fast-all` 14.4 GiB；单并发忙时 409；checkpoint 自带 `audio_tokenizer`；代码 Apache-2.0 | 见 Spec A §1.4；本 spec 只采用**进程内库**入口 |

### 4.5 `pyproject.toml` 现状

`[project.optional-dependencies]` 共 15 组，**无 `cosyvoice`、无 `breeze`**。但 `TTS/cosyvoice_handler.py:88` 的 ImportError 提示已写 `Rebuild the image with the 'cosyvoice' extra`，接入规范 §8.1 草稿也填 `required_extra="cosyvoice"` → 本轮必须补上这两个组，否则 `create_backend_handler()` 的安装提示指向不存在的组。

---

## 5. Approaches（候选方案与取舍）

**问题**：`models:` 段的覆盖值如何变成运行时加载参数，同时不推翻 D5「card 不驱动加载」与「31 条构造零改动」的兼容红线？

| | 方案 1：card 默认值注入 ✅ | 方案 2：模型级选择器 | 方案 3：Handler 自读 card | 方案 4：每模型一条 BackendSpec |
|---|---|---|---|---|
| 做法 | `blocks.*.backend` 选后端；`models:` 覆盖后的 card 提供 `default_load_params` 作为该 stage 的**默认值**，合并进 settings，显式值优先 | 新增 `models.active.{stt,llm,tts}: <model_id>`，选中 card 的 `repo_id` 与加载参数注入 settings | 各 Handler 在 `setup()` 里 `resolve_model()` 自己读 card | 给 6 个模型各建一条 spec，`blocks.*.backend` 一字切换 |
| 改动面 | `config.py` 一处接线 + 匹配校验 | `config.py` 白名单 / 校验 / `ResolvedPipeline` + `cli.py` + 修订 D5 | 6 个 Handler 各写一遍，且要改装配层传 `model_cards` | 6 条新 spec + 参数类复制 / normalize |
| 向后兼容 | **最好**：无 `models:` 段时完全空转，旧 YAML 逐字不动 | 旧 YAML 不动，但要显式修订 D5 与兼容红线 | 依赖装配层改动，易漂移 | 旧后端保留，CLI choices 变长、注册表 31 → 37 |
| 主要代价 | 切换模型仍需写 `*_model_name`；`transformers` 下 4 张 card 没有单一「当前选中」声明 | 新增第三套选择语义，把适配层任务变成架构变更 | 逻辑分散、默认值漂移、与 Spec A §3 相悖 | 注册表膨胀，同一 Handler 多条 spec |

**用户选择：方案 1**。理由：它把「半接通」补成真接通，同时不推翻已批准的 D5 和兼容红线；方案 2 更直观但属于一次独立的架构决策，不该在适配层里顺手做掉；方案 3 / 4 的重复与漂移风险高于收益。

**消歧**：`transformers` 后端下挂 4 张 card，按 `backend_name` 匹配会同时命中多张。方案 1 的规则是「只有 `models:` 段中**显式出现**的 card 参与注入」，天然消歧，详见 §6.2。

---

## 6. 详细设计

### 6.1 文件改动清单

| 文件 | 动作 | 职责 |
|---|---|---|
| `src/speech_to_speech/TTS/breeze_tts_runtime.py` | 新增 | `BreezeInferenceAdapter` Protocol + `OfficialBreezeAdapter`（真实 `load_runtime()` / `prepare_inputs()` / `model.generate()`）+ **无第三方依赖的纯函数 `check_breeze_weights()`** + 单推理槽互斥；`load()` 内先查权重再 import |
| `src/speech_to_speech/TTS/breeze_tts_handler.py` | 新增 | `BreezeTTSHandler`：`setup / process / cleanup`，接受 `adapter=None`（默认官方实现，测试注入 stub），产出 16 kHz int16 / 512 samples + `AUDIO_RESPONSE_DONE` |
| `src/speech_to_speech/arguments_classes/breeze_tts_arguments.py` | 新增 | `BreezeTTSHandlerArguments`，前缀 `breeze_tts_` |
| `src/speech_to_speech/audio_utils.py` | 新增 | `resample_pcm_24k_to_16k()` + `iter_pcm_chunks()`；Breeze 与 CosyVoice2 共用 |
| `src/speech_to_speech/TTS/cosyvoice_handler.py` | 修改 | 修 3 处不一致；改用共享 `audio_utils.py` |
| `src/speech_to_speech/arguments_classes/cosyvoice_tts_arguments.py` | 修改 | 统一 `fp16` 默认值、补 `prompt_wav` 字段 |
| `src/speech_to_speech/backend_registry.py` | 追加 2 条 | `breeze-tts-2`、`cosyvoice2` 两条 `BackendSpec`；**31 条既有构造逐字不改，`BackendSpec` 结构也不再加字段** |
| `src/speech_to_speech/models/builtin.py` | 更新 6 张 | `planned → available`；补 `repo_id` / `license` / `default_load_params` / notes；未实测的 `min_vram_gb` 保持 `None` |
| `src/speech_to_speech/model_registry.py` | 新增 1 类 | `ModelWeightsMissingError`（与 `ModelLicenseError` 并列，便于统一导入） |
| `src/speech_to_speech/config.py` | 3 处小改 | ① §6.2 的注入逻辑；② `_apply_model_overrides()` 把 `default_load_params` 从**整体替换改为与 card 内置值合并**（见 §6.2 规则 1，否则部分覆盖会丢掉内置权重名）；③ `_PATH_FIELDS` **只增补纯本地路径字段** `breeze_tts_ref_audio` / `cosyvoice_tts_prompt_wav`；`validate_config()` 白名单不动（已含 `models`）。**`*_model_name` 一律不进 `_PATH_FIELDS`**（见 §6.2） |
| `pyproject.toml` | 新增 2 组 | `breeze`、`cosyvoice` optional extras；**不得声明需运行时编译或联网 GitHub 的依赖** |
| `tests/` 新增 4 个文件 | 新增 | `test_breeze_tts_handler.py` / `test_cosyvoice_registration.py` / `test_model_runtime_wiring.py` / `test_spec_b_cards.py`（见 §6.7） |
| `tests/test_model_registry.py` / `tests/test_model_config_overrides.py` | 更新 6 处断言 | 按 §6.7 表格把状态硬编码值改为新事实；行为断言不放宽 |
| `docs/model-integration-guide-CN.md` | 更新 | §8 草稿改为落地说明、§9 验收清单、§10 决策变更追加本轮结论；**§7.1 一致性测试规则按 card 类型拆分**（见 §6.7）、补入「注入发生在 `_settings()` 之后」「`repo_id` 不改写 settings」「注入值不做路径展开」三条约定 |
| `docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md` | 修 1 处漂移 | §10「Breeze 自托管不在 Spec B 范围内」已被 §12 覆盖，改为指向本 spec |
| `cli.py` / 9 个 `docker-compose*.yml` / `config/prod.yaml` / `example_configs/mac.yaml` | **不动** | `models list` 自动列出新后端与新状态；部署配置不变 |

**不新增**：`cli.py` 子命令、模型级选择 flag、`BackendSpec` 字段、远程 backend、Docker 运行时 GitHub 依赖。

### 6.2 配置化与数据流（方案 1 的精确落地）

**注入点**：`config.py` 的 `resolve_config()` 循环内，`_settings()` 返回**之后**、`BackendSelection(...)` 构造**之前**（当前 `config.py:578-591`）。注入只对 `stt` / `llm` / `tts` 三个 stage 生效，`vad` 分支保持原样。

> **不能改成 `{**card_params, **settings}`**：`_settings()`（`config.py:283-298`）已把未显式提供的字段填成 dataclass 默认值，反向合并会让默认值覆盖 card 参数、注入静默失效。也不能把 card 参数塞进 `supplied` 交给 `_settings()`：`_mapping()` 的白名单与 `{env:}` 展开路径会改变既有行为。

**伪代码**（表达语义，非最终实现）：

```python
# 在每个 pipeline 的 stage 循环之前计算一次，供注入与 ResolvedPipeline 共用
model_cards = _apply_model_overrides(document, environment)  # 仅含 models: 段显式出现的 card 副本

for kind, block_id in pipeline["stages"].items():
    ...
    raw_settings = block.get("settings", {})
    settings = _settings(document, raw_settings, config_type, path, environment, sources, ...)
    if kind != "vad":
        explicit_keys = set(_mapping(document, raw_settings, path, set(fields(config_type))))
        matched = [c for c in model_cards.values() if c.backend_name == block["backend"]]
        if len(matched) > 1:
            _error(document, path, "Only one model card may target a backend per stage.")
        if matched:
            for key, value in matched[0].default_load_params.items():
                if key not in explicit_keys:
                    settings[key] = value   # sources 已由 _settings 标为 default，不改动
    ...
# resolved[name] = ResolvedPipeline(count, stages, options, model_cards)  ← 复用同一份，勿重复调用
```

**四条规则**：

1. **card 必须被 `models:` 段显式激活**：来源是 `_apply_model_overrides()` 返回的 per-pipeline 副本（仅含 `models:` 段中出现的 `model_id`）。未在 `models:` 段出现的 card 完全不参与运行时 —— 这正是 D5「card 只作元信息声明」的体现。只要 `models:` 段写出该 `model_id`（哪怕写空 mapping `{}`，`_validate_models_section()` 的白名单允许），其 `default_load_params` 就会注入。
   - **必须修正 `_apply_model_overrides()` 的合并语义**：现有实现（`config.py:416-422`）是 `updates["default_load_params"] = {…overrides…}` 后 `replace(card, **updates)`，即**整体替换**。6 张 card 本轮首次带上内置 `default_load_params`，若用户写部分覆盖（如 `minicpm-2b: {default_load_params: {llm_device: "cpu"}}`，该键能通过 `load_param_types()` 校验），内置的 `model_name` 会被丢弃，**权重切换静默失效**。改为 `updates["default_load_params"] = {**card.default_load_params, **resolved_overrides}`（card 内置值为底、YAML 覆盖值优先），再 `replace()`。既有 3 张 `available` card 内置值为空 dict，行为不变；`test_model_config_overrides.py` 中「覆盖后等于 `{"qwen3_tts_device": "cpu"}`」的断言依然成立。
2. **消歧**：筛出 `card.backend_name == block["backend"]` 的 card。**0 张 → 不注入；1 张 → 注入；≥2 张 → 抛 `ConfigurationError`**，消息要求该 stage 只保留一张 card 覆盖。这解决 `transformers` 后端下挂 4 张 card 的歧义。
3. **settings 显式值优先**：注入按「`_mapping()` 展开后的显式键集合」逐键判断；`blocks.*.settings` 里写了的键一律不动。显式值已由 `_settings()` 完成类型校验、`choices` 校验、`{env:}` 展开与 `_PATH_FIELDS` 路径解析；注入值来自 `_apply_model_overrides()`，已通过 `_validate_models_section()` 的键名与类型校验（但该校验**不做 `choices` 与路径展开**，见下方限制）。
4. **`default_load_params` 键名**：必须是 **`config_type` 的真实 dataclass 字段名**，即 `get_type_hints(config_type)` / `fields(config_type)` 的键 —— 这正是 `ModelRegistry.load_param_types()` 与 `_settings()` 使用的口径。字段名**是否带 `config_prefix` 前缀由参数类自身决定**，不可一律加前缀：`WhisperSTTHandlerArguments` 是 `stt_model_name`，`CosyVoiceTTSHandlerArguments` 是 `cosyvoice_tts_model_name`，而 `LanguageModelHandlerArguments` 继承的基类字段是 **`model_name`（无前缀）**。`spec.normalize()` 负责把带前缀的键剥成 handler 的 `model_name`。

**注入值的三条限制**（必须写进接入规范与测试）：

- 注入值**不经过 `_settings()` 的 `choices` 校验与 `_PATH_FIELDS` 路径展开**。因此 card 的 `default_load_params` 只放 HF repo id 或**绝对路径**；需要 `~` / 相对路径时请写绝对路径。模型名字段本身无 `choices` 约束，其余字段不放进 `default_load_params`。
- **`*_model_name` 一律不加入 `config.py:_PATH_FIELDS`**：`_settings()`（`config.py:309-317`）会把 `_PATH_FIELDS` 中的**任何非空字符串**转成 `document.path.parent / value` 的绝对路径，把 HF repo id `Qwen/Qwen3-8B`、`BreezeBlue/Breeze-TTS-2` 误当成相对路径。既有 `qwen3_asr_model_name` / `qwen3_tts_model_name` / `model_name` 均不在该集合中，新字段沿用同一口径；本轮只把纯文件路径的 `breeze_tts_ref_audio` / `cosyvoice_tts_prompt_wav` 加进去。
- 注入值**不改写 `sources`**：被注入的键必然不在 `explicit_keys` 中，`_settings()` 已将其标为 `"default"`，保持不变即可。既有 `test_config.py` 的 `sources` 断言不得因注入而改变。

**`repo_id` 覆盖语义**（不制造第二套机制）：只更新 card 元信息，供 `models list`、权重缺失报错与下载命令使用，**不自动改写 settings**。要真正切换权重，在 `models:` 段写 `default_load_params` 的对应 `*_model_name` 字段。此语义与 Spec A 接入规范 §7 的既有建议一致，必须写进接入规范避免使用者误解。

**兼容性**：无 `models:` 段时注入逻辑完全空转、行为逐字一致；不新增 CLI flag、不新增环境变量前缀、不新增模型级选择器；`{env: NAME}` 继续可用。

### 6.3 Breeze TTS 2 适配层

**adapter 接口**（`breeze_tts_runtime.py`）：

```python
class BreezeInferenceAdapter(Protocol):
    def load(self, *, repo_id: str, revision: str | None, device: str, fast_all: bool) -> None: ...
    def synthesize(
        self, *,
        text: str,
        ref_audio: str | None,
        ref_text: str | None,
        instruction: str | None,
        cfg_scale: float,
        seed: int | None,
    ) -> np.ndarray: ...          # 24 kHz mono PCM
    @property
    def sample_rate(self) -> int: ...   # 24000
    def close(self) -> None: ...
```

`OfficialBreezeAdapter` 在 `load()` 里延迟导入官方 `breeze_infer`，调用 `load_runtime()` 取得 `audio_tokenizer`，在 `synthesize()` 里调用 `prepare_inputs()` + `model.generate(output_audio=True, audio_tokenizer=..., repetition_penalty=1.1, no_repeat_ngram_size=0, encoder_no_repeat_ngram_size=0)`。导入失败按既有 `required_extra` 机制提示；权重目录缺失或缺少 checkpoint 组件（含 `audio_tokenizer`）抛 `ModelWeightsMissingError`。单推理槽用互斥锁保护（官方 API 单并发；进程内库是否流式官方 README 未说明，本轮按「整段生成 + 分块产出」实现，**不宣称 TTFA**）。

**权重检查必须可独立单测**（builder check 发现的实现陷阱）：`BaseHandler.__init__()`（`baseHandler.py:57-64`）在构造时就调用 `setup()`，而 `create_backend_handler()` 只把 `ImportError` 包装成 `required_extra` 安装提示。若 `load()` 先 `import breeze_infer`，CI（不装官方依赖）里永远只得到 `ImportError`，真实权重检查代码跑不到，验收项「权重缺失 + 禁止静默回退」就变成只测 stub。因此：

- 在 `breeze_tts_runtime.py` 顶层定义**无第三方依赖的纯函数** `check_breeze_weights(repo_id, revision=None, *, cache_dir=None) -> None`，只做本地文件/目录检查（含 `audio_tokenizer` 组件），失败抛 `ModelWeightsMissingError`；消息含 `repo_id`、必备子目录、下载/安装命令。
- `OfficialBreezeAdapter.load()` 的**顺序固定为：先 `check_breeze_weights()`，再 `import breeze_infer`**。这样权重缺失的报错优先级高于依赖缺失，且两者互斥、不会互相遮蔽。
- **`breeze_tts_runtime.py` 顶层不得 import 官方 `breeze_infer`**（只允许标准库 + `numpy`）：否则无依赖环境下模块本身无法导入，权重检查与 stub 注入都无从谈起。官方包只在 `OfficialBreezeAdapter.load()` / `synthesize()` 方法体内延迟导入。
- 契约测试分两层：`test_breeze_tts_handler.py` 用 `tmp_path` 造缺失/完整目录，**直接调用真实的 `check_breeze_weights()`** 断言异常类型、消息内容与「无回退」；再用 stub adapter 驱动 `BreezeTTSHandler` 断言异常透传与音频契约。CosyVoice2 的权重检查沿用同一模式（其 `cosyvoice_handler.py:84-89` 已有 ImportError 提示，只需把权重目录检查前置）。
- **错误包装链路**：`_simple_handler_factory` 构造 handler 时会触发 `BaseHandler.__init__() → setup()`，故 `load()` 内的 `ImportError` 会冒泡到 `create_backend_handler()`（`backend_registry.py:200-209`），被 `_optional_dependency_error()` 包装成 `pip install "speech-to-speech[breeze]"` 提示；而 `ModelWeightsMissingError` 是 `ModelRegistryError(ValueError)` 子类，**不会被包装**，原样冒泡（这正是期望行为：权重缺失优先、依赖缺失次之）。两层报错互不遮蔽，测试需分别断言。

**Handler**：`BreezeTTSHandler(BaseHandler[TTSIn, TTSOut])`，构造函数接受 `adapter=None` → 默认 `OfficialBreezeAdapter()`；测试注入 stub adapter。`setup()` 读取 `BreezeTTSHandlerArguments` 参数并调用 `adapter.load()`；`process()` 调 `adapter.synthesize()`，经 `audio_utils.resample_pcm_24k_to_16k()` 与 `iter_pcm_chunks()` 转成 16 kHz int16 / 512 samples 块，尾部不足一块补零，结尾 yield 恰好一个 `AUDIO_RESPONSE_DONE`；`cleanup()` 调 `adapter.close()`。打断与陈旧轮沿用 `CancelScope` / `SpeculativeTurnTracker`，与 `CosyVoiceTTSHandler` 同构。

**参数类**（`BreezeTTSHandlerArguments`，`config_prefix="breeze_tts_"`）：

| 字段 | 默认 | 说明 |
|---|---|---|
| `breeze_tts_model_name` | `BreezeBlue/Breeze-TTS-2` | HF repo id 或本地权重目录 |
| `breeze_tts_revision` | `None` | 固定权重版本 |
| `breeze_tts_device` | `cuda` | |
| `breeze_tts_fast_all` | `False` | 官方快路径，14.4 GiB |
| `breeze_tts_ref_audio` / `breeze_tts_ref_text` / `breeze_tts_instruction` | `None` / `None` / `""` | 三模式映射 |
| `breeze_tts_cfg_scale` | `4.0` | |
| `breeze_tts_seed` | `None` | |
| `breeze_tts_chunk_size` | `512` | |
| `breeze_tts_gen_*` | — | 由 `normalize_dataclass_config()` 合并进 `gen_kwargs` |

**BackendSpec**：`BackendSpec("breeze-tts-2", "tts", BreezeTTSHandlerArguments, _simple_handler_factory(..., setup_should_listen=True, context_kwargs=True), config_prefix="breeze_tts", required_extra="breeze")`。**不内联 `ModelCard`**（builtin 已有同 id card，双写会触发 `ModelRegistryError`）。

**共享音频工具**（`audio_utils.py`）：

```python
def resample_pcm_24k_to_16k(pcm: np.ndarray, *, input_dtype: str) -> np.ndarray: ...
def iter_pcm_chunks(pcm_i16: np.ndarray, chunk_size: int = 512) -> Iterator[bytes]: ...
```

- Breeze 输入是 int16 s16le：重采样时先转 float32 归一，重采样后乘 32767 并 `clip`，避免削波与越界；输出 `<i2`。
- CosyVoice2 输入是 float32 tensor：沿用现有归一化路径，输出 `<i2`。
- 采样数按 2/3 收敛；尾部不足 `chunk_size` 时补零到整块。
- 两者共用 `iter_pcm_chunks()`，避免两份切块逻辑。

### 6.4 其余五个模型

| 模型 | 交付 | 关键约定 |
|---|---|---|
| **CosyVoice2** | 注册 + 修 3 处不一致 | `BackendSpec("cosyvoice2", "tts", CosyVoiceTTSHandlerArguments, _simple_handler_factory("speech_to_speech.TTS.cosyvoice_handler", "CosyVoiceTTSHandler", setup_should_listen=True, context_kwargs=True), config_prefix="cosyvoice_tts", required_extra="cosyvoice")`；统一 `fp16` 默认值（参数类 `True` / handler `False` 二选一，以参数类为准）、补 `cosyvoice_tts_prompt_wav` 字段、card HF 与参数类 ModelScope 双源写进 notes；改用共享 `audio_utils.py` |
| **Whisper-medium** | 不新建后端 | card 翻 `available`，`default_load_params={"stt_model_name": "openai/whisper-medium"}`；`min_vram_gb` / `license` 未实测保持 `None` + notes |
| **MiniCPM 同源 Qwen3-8B** | 不新建后端 | card `default_load_params={"model_name": "Qwen/Qwen3-8B"}`；复用 `transformers`，`trust_remote_code` 已覆盖 |
| **MiniCPM-2B** | 不新建后端 | `repo_id=openbmb/MiniCPM-2B-dpo-bf16`；`default_load_params={"model_name": "openbmb/MiniCPM-2B-dpo-bf16"}`；`min_vram_gb=1.2`（估值，notes 标注来源 `docs/models.md:72`） |
| **MiniCPM-4B** | 不新建后端 | `repo_id=openbmb/MiniCPM3-4B`；`default_load_params={"model_name": "openbmb/MiniCPM3-4B"}`；card id 不变，notes 说明官方命名与 `min_vram_gb=None` 待实测 |

**CosyVoice2 的 3 处不一致**（`docs/upstream-diff-and-deployment-config.md:227` 提到目前无测试）：
1. 参数类 `cosyvoice_tts_fp16=True`（`cosyvoice_tts_arguments.py:37-39`），handler `fp16=False`（`cosyvoice_handler.py:58`）→ 统一为 `False`（与 handler 现有行为一致，避免改变已写好的推理路径），并同步参数类 help 文案。
2. 参数类缺 `prompt_wav`，handler `setup()` 有 `prompt_wav`（54）→ 补 `cosyvoice_tts_prompt_wav: str | None = None`，并加入 `config.py:_PATH_FIELDS`。
3. card `repo_id=FunAudioLLM/CosyVoice2-0.5B`（HF）与参数类默认 `iic/CosyVoice2-0.5B`（ModelScope）不同 → `default_load_params` 用 ModelScope id 与参数类默认值对齐，notes 说明 HF 为镜像源。

### 6.5 card 元信息变更表（`models/builtin.py`）

| id | status | repo_id | default_load_params | license | min_vram_gb |
|---|---|---|---|---|---|
| `breeze-tts-2` | `planned → available` | 不变 | `{"breeze_tts_model_name": "BreezeBlue/Breeze-TTS-2"}` | 不变（官方权重许可证名） | 7.7 |
| `whisper-medium` | `planned → available` | 不变 | `{"stt_model_name": "openai/whisper-medium"}` | `None` | `None` |
| `cosyvoice2` | `planned → available` | 不变（HF） | `{"cosyvoice_tts_model_name": "iic/CosyVoice2-0.5B"}` | `apache-2.0` | `None` |
| `minicpm-homologous-qwen3-8b` | `planned → available` | 不变 | `{"model_name": "Qwen/Qwen3-8B"}` | `None` | 16.0 |
| `minicpm-2b` | `planned → available` | `openbmb/MiniCPM-2B-dpo-bf16` | `{"model_name": "openbmb/MiniCPM-2B-dpo-bf16"}` | 「通用模型许可协议-来源说明-宣传限制-商业授权」（代码 Apache-2.0） | 1.2 |
| `minicpm-4b` | `planned → available` | `openbmb/MiniCPM3-4B` | `{"model_name": "openbmb/MiniCPM3-4B"}` | 同上 | `None` |

现有 3 张 `available` card（`qwen3-asr-1.7b-hf` / `qwen3-tts-1.7b-customvoice` / `qwen3.5-4b-transformers`）**逐字不改**。

notes 必须补充：Breeze 商业授权来源与进程内库路径；CosyVoice2 README 学术用途免责声明由应用方确认；MiniCPM 同源组件「非 MiniCPM 品牌独立模型」与商用需单独授权；`minicpm-4b` 官方命名差异；所有 `None` 字段标注「未实测/未核实」而非占位符。

### 6.6 错误处理

| 场景 | 行为 |
|---|---|
| 权重缺失 | 抛 `ModelWeightsMissingError`（在 `model_registry.py` 定义，`ModelRegistryError` 子类）；消息含 `repo_id`、必备组件（Breeze 的 `audio_tokenizer`）、下载/安装命令；**禁止静默回退** |
| 可选依赖缺失 | 沿用 `create_backend_handler()` 的 `required_extra` → `pip install "speech-to-speech[<extra>]"`；`breeze` / `cosyvoice` 的完整构建期安装步骤写入接入规范，容器运行时不依赖 GitHub |
| 同 stage 多张 card 覆盖 | `ConfigurationError`，消息要求只保留一张；错误路径精确到 `("models", model_id)` |
| `models:` 段非法值 | 沿用 `_validate_models_section()`：未知 id、非法键、类型不符、`{env:}` 缺失均报错且路径精确 |
| 单推理槽 | Breeze adapter 内互斥锁；**不把官方流式 API 的 409 语义搬进进程内路径** |
| `deprecated` card | 通用闸门与 `models list` 告警保留；本轮目录 0 张 `deprecated`，不触发 |
| `resolve_model()` 对 `planned` | 保持 Spec A 行为（抛 `ModelNotAvailableError`）；本轮 6 张翻 `available` 后不再对这 6 张触发 |

### 6.7 测试与验收

**新增测试**（全部 stub/mock；不下载权重、不触网、不占 GPU）：

| 文件 | 覆盖 |
|---|---|
| `tests/test_breeze_tts_handler.py` | adapter 注入（stub 返回 24 kHz 正弦/方波）、24→16 kHz 重采样正确性（采样数按 2/3 收敛、无削波、无越界）、512 samples 块、尾部补块、恰好一个 `AUDIO_RESPONSE_DONE`、`int16` little-endian、权重缺失抛 `ModelWeightsMissingError` 且不回退、打断与陈旧轮丢弃、三模式参数透传 |
| `tests/test_cosyvoice_registration.py` | 新 spec 已注册且 kind/prefix/extra 正确、`card ↔ 参数类默认值`一致、3 处不一致已修、共享 `audio_utils.py` 输出契约、不内联重复 card |
| `tests/test_model_runtime_wiring.py` | 显式覆盖注入生效、`settings` 显式值优先、同 stage 多 card 报错、无 `models:` 段零回归、两个 pipeline 注入互不污染、`sources` 语义不变、`repo_id` 覆盖不改写 settings、注入值使用 `config_type` 真实字段名（含无前缀的 `model_name`）、**注入不会绕过 `choices` 校验与路径展开的边界有测试锁定** |
| `tests/test_spec_b_cards.py` | 6 张 card 为 `available`、`backend_name` 已注册、`default_load_params` 键通过 `validate()`、repo_id / license / notes 事实、**`models list --json` 沿用 Spec A 的 10 字段且不含 `repo_id` 键**（repo 由 `ModelRegistry.get()` 提供）、延迟导入不被破坏（`sys.modules` 无 handler 模块） |

**一致性测试规则的修订**（必须同步写入接入规范 §7.1）：Spec A 模板第 1 条要求「`card.default_load_params` 的值与 dataclass 默认值一致」，该规则只对**后端默认模型 card** 成立；Spec B 引入了复用同一后端、但指向不同权重的**模型变体 card**，其值必须与默认值不同，否则配置化切换无意义。规则改为按 card 角色二分：

| card 角色 | 判定 | 一致性断言 |
|---|---|---|
| 后端默认模型 card | `default_load_params` 为空，或值等于 `config_type` 默认值（如 `qwen3-asr-1.7b-hf`、`qwen3-tts-1.7b-customvoice`、`qwen3.5-4b-transformers`、`breeze-tts-2`、`cosyvoice2`） | 值等于 dataclass 默认值；键名通过 `validate()` |
| 模型变体 card | 值指向不同于默认值的权重（`whisper-medium`、`minicpm-homologous-qwen3-8b`、`minicpm-2b`、`minicpm-4b`） | 值**不等于**默认值；值等于 `card.repo_id`（CosyVoice2 的双源例外在 notes 声明）；键名通过 `validate()`；且 `models:` 段激活该 id 后 `ResolvedStage.selection.config` 确实取到该值 |

两类 card 共同要求：键名属于 `load_param_types(card.id)`；无 card 的后端不虚构元信息。既有 `test_model_registry.py` 对 3 张默认模型 card 的断言保持不变。

**既有测试断言的更新**（builder check 发现，必须纳入实施计划）：Spec A 的测试把旧状态硬编码了，6 张 card 翻 `available` + 新增 2 条 `BackendSpec` 后这些断言必然失败。本 spec 对「既有测试零回归」的准确定义是：**行为与断言全部通过，但允许按新事实更新描述状态的硬编码断言**；不得改动断言所验证的行为语义。需更新的具体位置：

| 文件 | 断言 | 新值 |
|---|---|---|
| `tests/test_model_registry.py:153-166` | `available` 列表、`planned==6`、`breeze.status=="planned"` | 9 张全 `available`、`planned==0`、`breeze.status=="available"`；`min_vram_gb==7.7` 与许可/notes 断言保留 |
| `tests/test_model_registry.py:172-185` | `reg.bind()` 用只含 4 个后端的假注册表 | 假注册表补 `breeze-tts-2` / `cosyvoice2` 两个 `FakeSpec("tts")`，否则 6 张 `available` card 会触发 `available card references unregistered backend` |
| `tests/test_model_registry.py:194` | `len(STT)+len(LLM)+len(TTS)==31` | `==33`（新增 2 条；`spec.models == ()` 的断言保持不变，因为新 spec 不内联 card） |
| `tests/test_model_registry.py:201-202` | 全局 9 张、`get_model("breeze-tts-2").status == "planned"` | 9 张不变、`status == "available"` |
| `tests/test_model_config_overrides.py:129-136` | `--json` 断言 `available==3 / planned==6 / unregistered==27`、`breeze.status=="planned"` | `available==9 / planned==0 / unregistered==27`（27 不变）、`breeze.status=="available"`；许可断言保留 |
| `docs/model-integration-guide-CN.md:182`（§7 第 4 条） | 「`planned` 的 `breeze-tts-2` 可被正常配置」 | 改为「`available` 的 `breeze-tts-2` 可被正常配置；`deprecated` 闸门用临时注册 card 验证」 |
| `docs/superpowers/specs/2026-11-10-s2s-model-registry-design.md` §8.1/§8.3 | 记录 Spec A 当时验收值（3/6/27） | **保留为历史验收记录不改**；另加一行指向本 spec 的新值，避免把历史记录当成当前约束 |

`test_backend_registry.py` 中与 31 条构造、延迟导入、choices 派生的断言**不改**；`test_config.py` 与 `test_configured_runtime.py` 的 `sources` / 行为断言**不改**。

**验收命令**（CI 同款，全绿）：

```
ruff check src/ tests/
ruff format --check src/ tests/
mypy src/
pytest tests/ -x -q
```

**验收结果**：

1. `speech-to-speech models list` 输出 **9 张 `available`**（原 3 + 新 6）、**0 张 `planned`**、**27 行 `unregistered`**（新增 2 个后端同时新增 2 张 card 指向它们，计数不变）；`--json` 可解析。
2. `models:` 段写一张 card 的 `default_load_params` 后，`ResolvedStage.selection.config` 中对应字段确实改变；`blocks.*.settings` 显式值仍优先。
3. Breeze Handler 在 stub adapter 下产出符合音频契约的块，且不触发任何真实模型加载。
4. Spec A 全部既有测试通过（含上表 6 处按新事实更新的断言）；`test_backend_registry.py` / `test_config.py` / `test_configured_runtime.py` 的行为断言逐字不改。
5. 全程**未下载权重、未加载真实模型、未占用 GPU、未发起网络调用**。

**兼容性红线**：31 条 `BackendSpec` 构造逐字不改（只追加 2 条新 spec）；三个 CLI choices 的既有取值与默认值不变；`cli.py`、`config/prod.yaml`、9 个 `docker-compose*.yml`、`example_configs/mac.yaml` 不变；无 `models:` 段时行为逐字不变；既有测试**只按新事实更新状态类硬编码断言**，不放宽任何行为断言。

---

## 7. 留给 builder 自行决定的事项

以下不改变「构建什么」，实施者可按现场情况定，无需回到用户：

- `OfficialBreezeAdapter` 内部对官方 `breeze_infer` 模块的具体导入路径与 `prepare_inputs()` 参数组装细节（以官方 README 为准）。
- `breeze` / `cosyvoice` 两个 optional extra 组的**具体包清单**（只放纯 PyPI 可安装包；flash-attn 等需编译依赖的构建期步骤写进接入规范）。
- `audio_utils.py` 的重采样后端选 `librosa` / `soxr` / `scipy.signal.resample_poly` 中哪一个（三者在 dependencies 中均可用）。
- Breeze handler 的参数类字段最终命名微调（须保持 `breeze_tts_` 前缀）。
- 新增测试文件的内部组织与 fixture 复用方式。
- `cosyvoice_tts_fp16` 统一为 `False` 后 help 文案的措辞。

---

## 8. 风险与未核实项

| 风险 | 处置 |
|---|---|
| Breeze 官方进程内 `model.generate()` **是否流式，README 未说明** | 本轮按「整段生成 + 分块产出」实现；TTFA 不进验收线；真实流式性留待后续 PoC |
| Breeze 官方依赖含 flash-attn，Docker 默认 sm90、A100 需 `FLASH_ATTN_CUDA_ARCHS=80` | 运行时不装；构建期步骤写进接入规范；目标卡若非 Hopper 需实施者验证构建架构 |
| Breeze 显存 7.7 / 14.4 GiB 叠加 4.6 GB 管线 → 12.3 GB / 19 GB，12 GB 卡无法共存 | 只记录预算口径，不做互斥加载/多卡调度（非目标） |
| Breeze 权重许可名含「非商业」字样，商用权来自单独商业授权；MiniCPM 权重商用需单独授权 | 按 §11「演示开源项目、商用授权由应用方申请」处理；card notes 如实标注，代码不阻断 |
| CosyVoice2 README 学术用途免责声明与 frontmatter Apache-2.0 可能并存 | card `license=apache-2.0`，notes 标注由应用方确认；不自行下法律结论 |
| `minicpm-2b` / `minicpm-4b` 的 `min_vram_gb` 未实测 | 2B 保留 `docs/models.md:72` 的 1.2 估值并标注；4B 保持 `None` |
| `FunAudioLLM/CosyVoice2-0.5B` 与 `iic/CosyVoice2-0.5B` 双源 | `default_load_params` 用 ModelScope id 对齐参数类默认值；notes 说明 HF 镜像 |
| Spec A §10 仍写「Breeze 自托管不在 Spec B 范围内」，与 §12 冲突 | 本轮修 1 处措辞，明确以 §12 与本 spec 为准 |
| 工具侧 GitHub 可达 ≠ 容器网络命名空间可达 | 容器运行时不依赖 GitHub；接入规范写明需在目标容器内复核 |

---

## 9. 与 Spec A / 后续流程的关系

- Spec A 提供注册框架、card 校验、`models:` 段语法与接入规范；本 spec **只消费它们，不改结构**。
- 接入规范 `docs/model-integration-guide-CN.md` §7 一致性测试模板与 §8 示例草稿在本轮转为落地说明，并补入「`repo_id` 覆盖不改写 settings」与「注入发生在 `_settings()` 之后」两条易踩坑约定。
- 四节设计已于 2026-11-12 批准；本文件已写完并通过独立 builder check，待用户审阅后转入 `writing-plans` 生成实施计划，再进入实现。
- **本轮到此为止未写任何工程代码**：工作区只新增了这份设计文档，没有改动任何 `src/` 或 `tests/` 文件。
