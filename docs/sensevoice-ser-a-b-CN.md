# SenseVoice 内嵌 SER 与 emotion2vec 的 A/B 裁决方案

> 背景：8765 进程内已新增 SenseVoice 情感端点（`POST /recognize`、`POST /v1/audio/emotion`、`GET /v1/audio/emotion/health`），复用已加载的 `SenseVoiceSTTHandler`，零额外模型/端口。本文给出与独立 emotion2vec 服务（8023）做同条件 A/B 的方法与 U5 人检裁决指标。
> 日期：2026-11-18。

## 1. 两个候选

| 候选 | 提供方 | 端点 | 模型 | 切换方式 |
|---|---|---|---|---|
| A：内嵌 SenseVoice | `SER_PROVIDER=local` | 8765 `/recognize` | SenseVoiceSmall（本地 cache，936MB，funasr 1.4.27） | 改 `config/prod.env` 的 `SER_PROVIDER` 后重启 8765 |
| B：emotion2vec 代理 | `SER_PROVIDER=proxy` | 8765 `/v1/audio/emotion` → 8023 | emotion2vec_plus_large（独立 ser-gpu 容器） | 同上 + 填 `SER_API_KEY` |

两者共享 `/v1/audio/emotion` 路径，`mount` 顺序保证只注册一个（local 先注册，proxy 的 `_route_exists` 跳过）。`/recognize` 是 local 专有别名。

## 2. 契约与语义

- 请求：`multipart file=<wav 16k>`，可选 `sample_rate`、`language`。
- 200：`{emotion, confidence, margin, rawLabel, events:{laughter}, model, labels_supported}`。
- 6 类标签：`calm/happy/anxious/agitated/anger/threat`（happy 为本轮新增第 6 类；threat 语义仍归文本侧，声学不单独产出）。
- 错误（结构化 `{"error":{"code","stage":"SER","reason"}}`）：
  - 400 `INVALID_AUDIO`、409 `SILENCE/LOW_CONFIDENCE/LOW_MARGIN/REJECTED_LABEL`、429 `BUSY`、500 `INFER_FAILED`。
- 置信度/margin：hook `ctc.ctc_lo`，在 rich-info 情感位（position 1）取 9 类情感 token 的 softmax，conf=top1、margin=top1−top2；阈值 `SER_MIN_CONFIDENCE=0.55`、`SER_MIN_MARGIN=0.15`。
- 并发：`SER_MAX_INFLIGHT=2`，满时短截止等待 `SER_WAIT_TIMEOUT_S=0.5` 后才 429。

## 3. 脚本与改动清单（均在本项目 scripts/，不碰 mediation-deploy/ser）

| 脚本 | 用途 | 对应参考脚本 |
|---|---|---|
| `scripts/ser_ab_verify.ps1` | 契约验证：health、双端点、静音 409 结构化 reason | `verify.ps1` |
| `scripts/ser_ab_latency.ps1` | 同条件延迟取证：`-Provider local\|proxy -Seconds 10\|30\|60 -Rounds 20` → P50/P95 | `latency_bench*.ps1` |
| `scripts/ser_ab_smoke.ps1` | U5 人检取数：批量 wav → CSV（含 AED 笑声事件与 margin 列） | `e2e-smoke.ps1` |

CSV 列：`file, provider, emotion, confidence, margin, laughter, rawLabel, latencyMs, http_code, human_label`。
新增列（相对参考）：`margin`、`laughter`（AED 笑声事件）、`rawLabel`、`confidence`。

### 部署形态说明
SenseVoice 是**内嵌**服务，不需要独立 Dockerfile/compose：
- CPU/GPU 由 STT handler 的 `stv_device`/`sense_voice_stt_device` 决定，模型随 8765 进程加载。
- emotion2vec 仍走参考目录的 `Dockerfile.gpu` + `docker-compose.gpu.yml`（project `ser-gpu`，端口 8022/8023，torch 2.7.1+cu128 匹配 sm_120）。
- A/B 切换只改 `SER_PROVIDER`，不新建镜像、不改端口。

## 4. A/B 执行步骤

1. 准备同一批真实中文语音 wav（10s/30s/60s，含方言、交叠、情绪样本），放 `state/ser_ab_wavs/`。
2. 切 local：`SER_PROVIDER=local`，重启 8765；跑 `ser_ab_verify.ps1` 确认契约；跑 `ser_ab_latency.ps1 -Provider local` 三段各 20 次；跑 `ser_ab_smoke.ps1 -Provider local -WavDir ... -OutCsv state/ab_local.csv`。
3. 切 proxy：`SER_PROVIDER=proxy` + 填 `SER_API_KEY`（指向 8023），重启 8765；重复 latency/smoke，输出 `state/ab_proxy.csv`。
4. 人工听记：对 `ab_local.csv`、`ab_proxy.csv` 的每条形填 `human_label`（calm/happy/anxious/agitated/anger + 无情绪/拒答）。

## 5. U5 人检裁决指标

| 指标 | 定义 | 裁决阈值（建议） |
|---|---|---|
| 一致率 | 预测 emotion == human_label 的比例（拒答单列） | ≥ 70% 且不低于 emotion2vec |
| 误报率 | 人工无情绪但模型给了非 calm/非拒答 的比例 | ≤ emotion2vec |
| 拒答率 | 409（含 SILENCE/LOW_CONFIDENCE/LOW_MARGIN/REJECTED_LABEL）占比 | 与 emotion2vec 相当；静音必须拒答 |
| happy 可达性 | AED 笑声样本被判 happy 的比例 | > 0（emotion2vec 永不产 happy，一律 calm） |
| agitated/anxious 可达性 | 对应情绪样本命中率 | > 0（emotion2vec 已有，持平即可） |
| 延迟 P95 | `ser_ab_latency.ps1` 各段 P95 | ≤ 1500ms |
| 显存/CPU | 与 ASR+TTS 共存时的增量 | 内嵌 SenseVoice 复用 STT handler，增量应为 0 |

裁决原则：SenseVoice 在**一致率不低于** emotion2vec、happy/agitated/anxious 更可达、延迟达标、增量资源为 0 的情况下，可考虑替换；否则保留 emotion2vec 作主，SenseVoice 仅作 A/B 补充。所有结论须由上述脚本输出与人工听记 CSV 支撑，不以主观印象裁决。

## 6. 已知限制

- 内嵌 SenseVoice 的情感 token 在部分音频（如英文朗读）输出 `<|EMO_UNKNOWN|>` → 409 拒答，属预期行为，不计入一致率分母。
- SenseVoice 情感是句级粗粒度，非帧级；短句/静音段判据依赖 RMS 门与 confidence/margin 门。
- 6 类中 `threat` 为平台占位（声学不单独定性），与参考服务一致。
