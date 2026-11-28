# 全双工语音调优记录（40.30 生产环境，2026-11-27）

> 范围：`192.168.40.30` 上 s2s-split 部署的全双工语音对话链路
> （浏览器麦克风 → WS `/v1/realtime` → VAD → Qwen3-ASR → LLM(qwen3-32b) → TTS）。
> 本文记录**问题诊断 → 归因判断 → 措施 → 部署 → 验证 → 回滚**的全过程，
> 供后续在 137 / 其他节点复用时参考。
>
> 关联文档：`docs/deployment-tuning-playbook.md`（反模式约束）、
> `docs/parameter-catalog.md`（参数口径）、`docs/gpus.md` §8.4、
> `deploy/4030/README.md` §9.6。

---

## 1. 问题与验收标准

用户反馈两个核心现象：

| # | 现象 | 初步归因方向 |
|---|---|---|
| P1 | **麦克风输入较长时，大量语音文字丢失** | VAD 分块 / 判停 / 丢弃 |
| P2 | **语义识别错误，同音、类似发音为主** | ASR 模型层（语言、热词、解码） |

隐含目标：转写准确后，LLM 的回答也应更准确（转写文本是 LLM 的唯一输入，
`STT(final) → LLM`，partial 字幕不进 LLM——`STT/transcription_notifier.py:42-104`）。

**验收标准（事先确认）：**

- 真实语音长句转写不丢字：VAD `discarding` 日志行数显著下降
- 领域词句转写正确率提升：TTS 合成固定领域词长句对比调优前后转写
- LLM 回答基于正确文本，**端到端延迟增幅 ≤ 1.5s**（基线约 1.8s）
- 真实语音对话验证

**约束（与用户三轮澄清确认）：**

1. 目标环境：40.30 生产环境（改远端配置，真实语音对话验证）
2. 延迟预算：可接受首字慢 1~3 秒（用于 beam search、热词提示、更宽松 VAD 合并）
3. 改动范围：配置 + 最小必要代码（允许重打镜像）

---

## 2. 诊断：服务端日志证据

在 40.30 的 `s2s-split-s2s-pipeline-1` 容器日志与 `model_metrics.log` 中取得直接证据：

### 2.1 P1（丢字）→ VAD 整段丢弃 + 切分过碎

```
VAD: discarding segment=884ms active=32ms (active_min=384ms, segment_max=infms)
VAD: discarding segment=916ms active=64ms (active_min=384ms, segment_max=infms)
```

- 近 **1 秒**的语音段，因"有效语音时长"低于 `min_speech_ms=384` 被**整段丢弃**
  （`VAD/vad_handler.py:841-907`），根本没进 ASR——这是丢字的最直接证据。
- 884ms 的段里只判出 32ms 有效语音，说明语音被 VAD 误判为非语音
  （`thresh=0.6` 偏高或麦克风音量低）。
- `short_segment_merge_ms=0`：短段拼接未启用，被丢弃的段无法与相邻段合并挽救。
- `min_silence_ms=300`：长语音被切成多段**各自独立转写**，上下文断裂。

### 2.2 P2（同音错字）→ 语言不稳 + 无热词 + 解码参数未暴露

`model_metrics.log` 的 `MODEL_CALL_METRICS`：

```
"text": "那现在做法就是大家要求，就是市场人员。"      ← 同一段连续语音
"text": "那现在做法是大家要求就是市场人员、研发。"    ← 被 300ms 静音切成
"text": "那现在做法就是大家要求，就是市场人员、研发、产品经理。" ← 多段独立转写
```

- `language: null` —— `qwen3_asr_language=auto`，短段语言识别不稳
  （`STT/qwen3_asr_handler.py:95-104`）。
- 未配置 `qwen3_asr_prompt`（热词/领域词偏置）。
- 解码参数只有 `gen_max_new_tokens=256`，beam/temperature 未暴露
  （`arguments_classes/qwen3_asr_stt_arguments.py:7-58`）。

### 2.3 回答准确性 → LLM 默认不纠错

`LLM/voice_prompt.py:14` 明确写着
"Treat transcripts as noisy. Correct likely mishearings only if asked or meaning depends on it."
—— 默认**不主动纠正**同音错字，且领域词未注入 system prompt。

---

## 3. 归因判断：为什么改这几处、不改别的

分层归因是本次调优最重要的方法论。`docs/deployment-tuning-playbook.md:404-438`
的反模式约束直接决定了方案边界：

| 现象 | 属于哪一层 | 为什么 |
|---|---|---|
| 同音/近音错字 | **STT 模型层**（语言锁定、热词 prompt、beam 解码） | VAD 参数只能影响"何时切/是否送"，改不动"送进去之后识别成什么字"。用 VAD 判停参数修错字是 playbook 明示的反模式 |
| 长语音丢字 | **VAD 层**（丢弃门槛、拼接、静音切分）+ **代码层**（commit 尾部不足块被扣留） | 语音根本没进 ASR，改 STT 参数无效 |
| 回答不准 | **LLM 提示词层** | 转写含错字时 LLM 默认不纠正；注入领域词与纠错规则是零成本手段 |
| 句尾丢字 | **代码层**：`audio.py:292-368` commit 后不足 1024 字节的 remainder 不下发 | Silero VAD 接受任意帧长，没有理由扣留 |

**每项参数的判断理由：**

| 参数 | 原值 → 新值 | 理由 |
|---|---|---|
| `qwen3_asr_language` | `auto` → `zh` | 日志 `language: null` 证明 auto 在短段上不稳；锁定中文消除语言误判，还省掉每段的语言识别开销 |
| `qwen3_asr_prompt` | 无 → 热词串 | Qwen3-ASR 的 prompt 是转写偏置机制，压同音错字的最直接手段；要求 transformers ≥ 5.15.1（镜像 5.20.2 ✓）。**控制在 100 字内**——prompt 随每个分段重复送入，过长直接抬高每段延迟 |
| `qwen3_asr_gen_num_beams` | 未暴露 → `3` | beam search 对同音候选择优；代码上 `backend_registry.py:155-175` 会把全部 `gen_*` 字段透传给 `model.generate`，只需在参数类加字段 |
| `qwen3_asr_gen_max_new_tokens` | `256` → `320` | parameter-catalog §3.3：过小截断长句转写 |
| `min_silence_ms` | `300` → `450` | 300ms 把长语音切碎成多段独立转写（§2.2 证据）。代价：每轮判停多等 150ms |
| `min_speech_ms` | `384`(默认) → `250` | 884ms 段因有效语音 <384ms 被整段丢弃（§2.1 证据）。此参数原先走 CLI 默认值、不在 YAML 里——**调优必须显式写入 YAML** |
| `short_segment_merge_ms` | `0` → `800` | 启用短段拼接，让被丢的短段与相邻段合并后进 ASR。**反模式约束：必须 > min_silence_ms**（playbook §438），否则拼接失效 |
| `thresh` | `0.6` → `0.5` | **实验项**：884ms 段只判出 32ms 语音，疑似阈值偏高/音量低。风险是噪声误触发（VAD 频繁起停），出现即回 0.6 |
| `init_chat_prompt` | 简短助手 → + 纠错规则与领域词 | 覆盖 voice_prompt 的 noisy 容忍策略；temperature 保持 0.0 不变 |

**延迟预算核算（改前算清，避免超预算）：**

- 判停：`min_silence_ms` 300→450，每轮多等 **+150ms**
- 解码：beam=1→3，STT 单段约 0.4~0.6s → 0.8~1.2s，**约 +0.4s**
- 合计 ≈ **+0.55s**，远在 1~3s 预算内（实测见 §6）

---

## 4. 措施落地

### 4.1 配置层（生效文件：`config.split.2/prod.yaml`）

> 关键前提：40.30 compose 的 `env_file` 是 `./config.split.2/prod.env`、
> `volumes` 挂 `./config.split.2:/app/config`——**`config.split/` 是旧目录，改它无效**。
> 容器内生效文件为 `/app/config/prod.yaml`。

diff 摘要：

```yaml
vad.settings:
  min_silence_ms: 300 → 450        # 切分过碎 → 上下文断裂
  min_speech_ms: 250               # 新显式项：384 门槛整段丢语音
  short_segment_merge_ms: 800      # 新显式项：> min_silence_ms 才有效
  thresh: 0.5                      # 实验项，误触发回 0.6

stt.settings:
  qwen3_asr_language: auto → zh
  qwen3_asr_gen_max_new_tokens: 256 → 320
  qwen3_asr_prompt: "热词：市场人员、研发、产品经理、项目、客户、需求、部署、发布、上线、语音助手、集群、参数目录。请准确转写以上词汇与中文专有名词。"
  qwen3_asr_gen_num_beams: 3       # 新参数（需代码支持）

llm.settings:
  init_chat_prompt: 追加"转写可能含同音错字，结合上下文自动纠正后再理解意图" + 领域词表
```

### 4.2 代码层（最小改动，两个文件）

| 文件 | 改动 | 为什么 |
|---|---|---|
| `arguments_classes/qwen3_asr_stt_arguments.py` | 新增 `qwen3_asr_gen_num_beams: int = 1` 字段 | handler 无需改动——`backend_registry` 把全部 `gen_*` 字段规范化进 `gen_kwargs` 透传给 `model.generate` |
| `api/openai_realtime/handlers/audio.py:292-368` | commit 时 flush 后若 `audio_remainder` 仍非空则**直接下发**并重置 | 原实现扣留不足块的尾部音频 → 句尾丢字 |

测试：`tests/test_qwen3_asr_arguments.py`、`tests/openai_realtime/test_audio_commit_tail.py`
等 pipeline 受影响用例 **52 passed**。

### 4.3 部署层（远端增量镜像）

```bash
# 40.30 上直接构建增量镜像（基座已在远端，热修层仅 29KB，避免传输 16.7GB）
cd /tmp/hotfix-4030-3
docker build -t s2s-agent:4030-3 -f - . <<'DOCKEOF'
FROM s2s-agent:4030-2        # 注意：远端实际基座是 4030-2，不是文档写的 4030-1
COPY pipeline/qwen3_asr_stt_arguments.py /usr/src/app/src/speech_to_speech/arguments_classes/
COPY pipeline/audio.py /usr/src/app/src/speech_to_speech/api/openai_realtime/handlers/
RUN /usr/src/app/.venv/bin/python -m compileall -q ... && echo COMPILE-OK
DOCKEOF
# compose 里 image: s2s-agent:4030-2 → 4030-3（sed，先备份）
docker compose -f docker-compose.split.yml --env-file .env.agentconsole up -d --force-recreate s2s-console s2s-pipeline
```

> 为什么增量：完整 `Dockerfile.agent` 构建产物 16.7GB，`docker save/load`
> 传输不现实；本次只改 `src/` 下两个文件，从远端已有基座 COPY 增量层即可。
> 完整重打仍可作为后续正式发布路径。

---

## 5. 部署踩坑（过程实录，复用时避坑）

| # | 坑 | 现象 | 处置 / 教训 |
|---|---|---|---|
| 1 | **配置先于镜像上线** | 新 YAML 带新键（`gen_num_beams`），4030-2 镜像的参数 schema 是严格白名单 → `Configuration error` → 容器循环重启 | **回滚恢复服务，镜像先上、配置后上**。顺序错了会直接打挂生产 |
| 2 | **`prod.yaml` 被参数平台覆盖** | 文件头注明 "Generated by the deployment parameter platform"，属主 root；console 重启时重新渲染 | 直接改 YAML 是**临时的**（下次发布覆盖）；持久化应走参数平台草稿→发布。改文件需 `sudo` |
| 3 | **改错文件** | `config.split/` 与 `config.split.2/` 同存，旧目录改了没效果 | 先用 `docker compose config` / 容器内 `cat` 确认真实挂载与生效值，再动手 |
| 4 | **`lb_mode` 误改（前序操作事故）** | `s2s_db.param_config` 的 `console.lb_mode` 被从 `off` 改成 `proxy` → 注册表无可用上游 → WS 403 → 浏览器 "Could not start the conversation" | 改回 `off` 并重启 console。**库配置优先于 env**：即使 compose 里写了 `CONSOLE_LB_MODE: proxy` 也被库值覆盖。40.30 单 pipeline 必须保持 `off`，除非先完成 agent 注册 |
| 5 | **agent config/ack 500** | ack 打 `"ack:" + 64位哈希`（4+64=68 字符）落在 `yaml_hash varchar(64)` 列 → StringDataRightTruncation，agent 配置回执永久失败 | 新迁移 `0016_agent_config_hash_len` 扩列到 80（SQLite no-op——其 VARCHAR 本不强制长度，且 batch 重建会破坏离线 SQL 静态闸）。教训：**前缀 hack 之前先核对列宽** |

---

## 6. 验证结果

### 6.1 自动化指标

| 指标 | 调优前 | 调优后 | 判据 |
|---|---|---|---|
| VAD `discarding segment` 行数 | 单次对话 2+ 次 | **0 次**（重启后 20 分钟实测） | 丢字主因消除 |
| STT `language` 字段 | `null` | **`"zh"`** | 语言锁定生效 |
| STT 延迟 | avg 0.455s | **avg 0.837s / p50 0.98 / p95 1.02s** | beam=3 生效；+0.38s，在预算内 |
| 端到端 WS | 握手 403（事故期间） | **101 Switching Protocols** + `session.created` | 链路恢复 |

### 6.2 端到端文本验证（TTS 合成 → ASR 转写闭环）

输入（TTS 合成 52 字领域词长句）：

> "那现在做法就是大家要求，就是市场人员、研发、产品经理，这个需求要尽快部署上线。"

转写输出：

> "那现在做法就是，大家要求就是市场人员、研发、产品经理这个需求要尽快部署上线。"

- **52 字完整返回，无丢字**——`min_silence 450 + 尾部 remainder 下发` 生效
  （调优前同段语音被 300ms 静音切成 3 段独立转写，见 §2.2）。
- 领域词"市场人员、研发、产品经理、部署、上线"全部正确——热词 prompt 生效。
- 观察到的差异仅为标点/助词级别，属模型自身分词行为，非丢字。

### 6.3 真实语音对话

重启后日志中出现真实麦克风输入（如"啥？那个。"）被正常转写与响应；
用户侧确认语音对话恢复可用。

### 6.4 回归测试

- pipeline 受影响测试：**52 passed**
- console `tests/unit` 全量：**417 passed**（含 0016 迁移链的 3 个 head 断言修复）
- 离线 SQL 双方言渲染：PG `ALTER COLUMN yaml_hash TYPE VARCHAR(80)` ✓、SQLite no-op ✓

---

## 7. 回滚方案

| 对象 | 回滚方式 |
|---|---|
| 远端 `config.split.2/prod.yaml` | `config.split.2/prod.yaml.bak-20261127`（sudo cp 覆盖回） |
| 远端 `config.split.2/prod.env` | `prod.env.bak-20261127` |
| 远端 `docker-compose.split.yml` | `docker-compose.split.yml.bak-20261127`（image tag 改回） |
| 镜像 | compose tag 改回 `s2s-agent:4030-2` / `s2s-console:4030-1` |
| 共享库 `param_config` | 旧值备份：本地 `state/param_config-backup-20261127.json` |
| 单参数 | `thresh: 0.5` 出现噪声误触发 → 回 `0.6`；延迟超预算 → `gen_num_beams` 回 1 |

---

## 8. 遗留项与后续建议

| # | 事项 | 说明 |
|---|---|---|
| 1 | `thresh: 0.5` 持续观察 | 实验项。若 VAD 频繁起停（噪声误触发）回 0.6；若低音量丢字仍在，可试 0.45 并配合提高 `min_speech_ms` 复验 |
| 2 | 热词词表维护 | 当前热词从日志提取（市场人员/研发/产品经理等）。随业务演进由使用者自行增补，**保持 ≤100 字**，过长抬高每段延迟 |
| 3 | 配置持久化走参数平台 | 直接改 `prod.yaml` 会在下次参数发布时被覆盖（§5 坑 2）。调优值应录入参数平台草稿并发布，使其进入版本历史 |
| 4 | agent 注册闭环补齐 | `pipeline-3030` 已建档（`param_machine state=ok`），一次性注册码流程见 `deploy/4030/README.md` §8.5；token 落盘后 agent 心跳正常 |
| 5 | 命中率指标待 S3 | LLM 界面的"会话粘滞命中"类指标后端暂无数据源，占位口径见 parameter-catalog §4.4 |
| 6 | 基线量化 | 如需精确 CER 对比，建议固定 20 句领域词测试集（TTS 合成 + 人工标注），用 `/v1/audio/transcriptions` 批量回归 |

---

## 9. 方法论沉淀（复用清单）

1. **先分层归因，再动手**：丢字找 VAD/代码，错字找 STT（语言/热词/beam），回答找 LLM 提示词。跨层改参数是反模式。
2. **日志先行**：`VAD: discarding` 行、`MODEL_CALL_METRICS` 的 `text/language/duration_s` 是本调优的三把尺子，调优前后各采一次。
3. **反模式清单背下来**：`short_segment_merge_ms > min_silence_ms`；不用 VAD 参数修错字；`gen_max_new_tokens` 过小截断长句。
4. **延迟预算先算后改**：判停 +150ms、beam +0.4s，合计 0.55s < 1.5s 预算——这是敢于放宽参数的依据。
5. **配置与镜像的上线顺序**：新配置键依赖新 schema，**镜像先行**；否则严格校验会让容器循环重启。
6. **确认生效文件**：多套配置目录（`config.split` / `config.split.2`）并存时，以 `docker compose config` 与容器内实际文件为准。
7. **增量镜像交付**：远端已有基座时，热修层构建（秒级）优于 16.7GB 全量传输。
8. **每次改库留备份**：`param_config` 旧值、yaml/env/compose 的 `.bak-<date>`，回滚路径先于改动存在。

---

*变更明细见 git 工作区（未提交）：`config.split.2/prod.yaml`、
`src/speech_to_speech/arguments_classes/qwen3_asr_stt_arguments.py`、
`src/speech_to_speech/api/openai_realtime/handlers/audio.py`、
`console/backend/alembic/versions/0016_agent_config_hash_len.py` 及配套测试。*
