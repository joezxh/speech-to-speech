# 移除 SenseVoiceLarge 与内嵌 SenseVoiceSmall 情感服务（Embedded SER）设计

- 日期：2026-11-26
- 状态：已确认（用户逐节认可），待实施
- 关联：`docs/superpowers/specs/2026-11-25-livekit-worker-migration-design.md`（worker SER 契约来源）

## 1. 背景与目标

1. **SenseVoiceLarge 完全清除**：模型卡片、测试断言、配置注释、prod 主配置的 STT 指向全部移除，全仓 grep 零残留。
2. **STT 与情感能力解耦**：引入模型卡片级 `native_emotion` 能力声明；serve 启动时按所选 STT 是否原生支持情感识别，自动决定是否加载 SenseVoiceSmall 作为内嵌情感服务。
3. **自动部署形态 = serve 进程内嵌**（用户选定）：与 `--with-console`/voiceprint/`LiveKitWorkerRuntime` 同模式（线程 + 就绪标志 + 崩溃隔离），零外部依赖、情感首包零延迟。
4. **管线 + worker 共用**：内嵌端点同时服务实时管线（emotion→LLM 注入）与 livekit_worker 的 `HttpSerProvider`，一份模型显存服务全链路。
5. **加载时机 = 启动即加载 + 可关**：默认自动启用；`--no-embedded-ser` / `EMBEDDED_SER_AUTOSTART=false` 显式关闭。

已确认决策（2026-11-26 用户逐项选定）：

| 决策点 | 结论 |
|---|---|
| 部署形态 | serve 进程内嵌（方案 A） |
| 能力判定 | 静态能力声明（`ModelCard.native_emotion`），不做运行时探测 |
| 服务范围 | 实时管线 + livekit_worker 共用 |
| 加载时机 | serve 启动即加载 + `--no-embedded-ser`/env 可关 |
| prod 主配置 STT | 换 qwen3-asr（与 config.split 已用 qwen3-asr-0.6b 对齐） |

## 2. 范围与非目标

范围内：

- 删除 `sensevoice-large` 卡片及全部引用；prod STT 切换 qwen3-asr。
- `ModelCard.native_emotion` 能力字段 + `stt_has_native_emotion()` 查询。
- 内嵌 SER 运行时（模型装载、本地端点、崩溃隔离、开关）。
- `emotion_local_service` 回落改造；worker `get_ser_provider` 回落改造。
- 离线单测、文档同步。

非目标：

- 不实现独立容器编排（方案 C 已否决）。
- 不改动 worker 的 SER 快照门（serPolicy/断路器/并发门）与 409 拒答契约。
- 不迁移/修改 mediation 侧独立 emotion2vec SER 服务（`SER_BASE_URL` proxy 模式保持不变）。
- 不做运行时情感能力探测。

## 3. SenseVoiceLarge 清除清单

| 位置 | 处理 |
|---|---|
| `src/speech_to_speech/models/builtin.py` | 删除 `sensevoice-large` 整张卡片（约 L43-61） |
| `tests/test_model_registry.py` | 卡片全集断言更新（含 `native_emotion` 字段断言） |
| `config/prod.yaml` | STT 块改写：`backend: qwen3-asr` + `qwen3_asr_model_name/device/language`；删除 SenseVoiceLarge 相关注释（含 llm 段 `enable_lang_prompt` 对 sense-voice language_code 的依赖注释需同步改写——qwen3-asr 是否产出 language_code 以 handler 实际行为为准，不假设） |
| `config/prod.env` | `S2S_ASR_MODEL_DIR` 改指 qwen3-asr 权重目录；新增 `S2S_SENSEVOICE_MODEL_DIR` |
| config.container / config.split | 复查确认无 Large 引用（现仅 Small 语义，保留） |
| README 双语 / docs | 复查 "SenseVoiceLarge" 字样清零 |

验证：`grep -ri sensevoicelarge` 全仓零命中（保留的 `sense-voice`/`SenseVoiceSmall` 引用不受影响）。

## 4. 模型卡片能力声明

- `ModelCard` 新增字段 `native_emotion: bool = False`（默认 False，既有卡片不动）。
- `sensevoice-small` 卡置 `native_emotion=True`（SenseVoice 原生情感/事件标签输出）。
- `qwen3-asr-1.7b-hf`、`whisper-medium` 保持 `False`。
- `model_registry.py` 新增 `stt_has_native_emotion(backend_name) -> bool`：按 backend 名查卡片；无卡片映射的后端返回 False（fail-closed → 走内嵌 SER）。
- 启动期校验日志：serve 启动打印一行判定（所选 STT → 原生情感 / 内嵌 SER 补齐 / 情感禁用），供 doctor 与排障。

## 5. 内嵌 SER 子系统

```
serve 启动
  ├─ 解析 STT → stt_has_native_emotion(backend)?
  │     ├─ True  → 沿用现状（emotion_local_service 复用 pipeline handler，零改动）
  │     └─ False → 且未禁用且 SER_ENABLED=true
  │            → EmbeddedSerRuntime 线程：funasr AutoModel 加载
  │              SenseVoiceSmall（S2S_SENSEVOICE_MODEL_DIR，device cuda）
  │            → realtime API 挂载 /recognize + /v1/audio/emotion
  │              + /v1/audio/emotion/health（复用 sense_voice_emotion 标签归一/
  │              置信度门/409 拒答语义；数据源为独立 handler，非 pipeline 复用）
  └─ livekit_worker（--with-livekitworker 时）：
        get_ser_provider() 回落——SER_PROVIDER=none 且本进程 EmbeddedSerRuntime
        已就绪 → HttpSerProvider(base=http://127.0.0.1:<realtime端口>,
        health_path=/v1/audio/emotion/health)
        SER_PROVIDER 显式配置时优先显式值；两套 env 值域不混用
        （realtime: local|proxy；worker: none|emotion2vec|sensevoice）
```

- 新模块 `src/speech_to_speech/embedded_ser.py`：单文件含 `EmbeddedSerRuntime`（线程生命周期 + `ready` 标志 + handler 访问器）+ FastAPI 挂载函数；崩溃只记日志不拖垮 pipeline。
- `emotion_local_service.py` 最小改造：`local` 模式下 `find_ser_handler(pool)` 找不到 pipeline handler 时回落到 `EmbeddedSerRuntime` 的 handler；均无 → 维持现状 `ready=false`。
- 开关双通道（沿用 worker_integration 剥离模式）：`--with-embedded-ser`/`--no-embedded-ser`（serve/local 接受、talk 拒绝）与 `EMBEDDED_SER_AUTOSTART`（布尔，非法值启动期报错）；显式 flag > env > 默认自动。
- 禁用且 STT 无原生能力且 SER_ENABLED=true 时：启动 warning（情感功能不可用），不阻塞转写链路。
- 显存预算：qwen3-asr（0.6B≈1.8GB / 1.7B≈4GB）+ SenseVoiceSmall≈0.4GB + 管线其余组件；文档标注预算说明。

## 6. 错误处理

- funasr/sensevoice extra 未安装 → EmbeddedSerRuntime 记 ImportError 警告、不加载、health 返回 `ready=false`（崩溃隔离，不拖垮 serve）。
- `S2S_SENSEVOICE_MODEL_DIR` 缺失 → 同上 warning + `ready=false`（与 STV soft-fail 先例一致）。
- 模型装载失败（权重损坏/OOM）→ 记日志退出线程；情感请求按既有 409/503 语义返回，转写不受影响。
- 模型未就绪时收到情感请求 → 503 + 结构化 error（与 emotion_routes 下游不可达语义一致）。
- worker 回落路径：内嵌未就绪且无显式 SER_PROVIDER → 维持 `MEETING_SER_PROVIDER_UNCONFIGURED` 显式 raise（fail-closed，不产假标签）。

## 7. 测试与验收

1. `tests/test_model_registry.py`：卡片全集断言更新（无 sensevoice-large）、`native_emotion` 字段断言、`stt_has_native_emotion` 映射（sense-voice→True、qwen3-asr→False、未知→False）。
2. 新增 `tests/test_embedded_ser.py`（全部离线 mock，不装 funasr）：
   - 开关解析：默认 auto / `--no-embedded-ser` / env 覆盖 / 显式 flag 优先 / talk 拒绝 / env 非法值报错。
   - 绑定三分支：原生能力→不加载内嵌；非原生→加载并挂端点；禁用→warning。
   - 端点契约：200 正常、静音/低置信 409、未就绪 503、health ready 字段。
   - worker 回落：显式 SER_PROVIDER 优先 / 内嵌就绪回落成功 / 未就绪显式 raise。
3. 残留验证：`grep -ri sensevoicelarge` 全仓零命中。
4. `ruff check` 新增文件零告警；pytest 全量回归由用户手动执行。
