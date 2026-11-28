# GPU / 应用部署清单（192.168.1.137 与 192.168.40.30）

> 采集时间：2026-11-26 16:56（`nvidia-smi` 瞬时采样 + GPUStack 计费表近 7 天统计）
> 采集方式：`plink -ssh <user>@<host>` 只读巡检（`nvidia-smi` / `docker ps` / `ss -ltn` / `kubectl get pods` / GPUStack `psql`）
> 覆盖机器：
> - `192.168.1.137`（node-192-168-1-137，Ubuntu 22.04，2×RTX 4090 48G）— GPUStack **Worker** + K8s 控制面 + 语音 S2S + LLaMA-Factory
> - `192.168.40.30`（node-192-168-40-30，Ubuntu 24.04，2×RTX 4090 24G）— GPUStack **Master** + 嵌入/重排模型 + kev + OCR + K8s worker
>
> 两机共享同一个 GPUStack 集群：模型由 40.30 的 master 统一调度，worker 上的 `vllm serve` 子进程实际落在 137。
> 本机（Windows 开发机）8765 上另有一套本地 S2S，**与本文档的 137/8765 不是同一套**，排查时勿混淆。

---

## 一、机器与 GPU 硬件概览

| 机器 | 系统 | CPU / 内存 | GPU | 驱动 / CUDA | 磁盘 | 角色 |
|---|---|---|---|---|---|---|
| 192.168.1.137 | Ubuntu 22.04.4 / kernel 6.8.0-149 | 64 vCPU / 125 GB | 2× RTX 4090（各 49140 MiB ≈ 48G） | 595.99.02 / CUDA 13.2 | `/` 439G(75%)、`/home/jiangwei/nvme` 1.8T(59%)、`/mnt/data` 440G(**93%**，剩 31G) | GPUStack Worker、K8s control-plane+worker、语音 S2S、LLaMA-Factory |
| 192.168.40.30 | Ubuntu 24.04.3 / kernel 7.0.0-43 | 8 vCPU / 62 GB | 2× RTX 4090（各 24564 MiB ≈ 24G） | 595.99.02 / CUDA 13.2 | `/` 439G(61%) | GPUStack Master（内含 Higress/Istio 网关、Postgres、Grafana、Prometheus）、嵌入·重排模型、kev、OCR、K8s worker |

Docker 版本：137 = 25.0.3；40.30 = 28.5.1（Compose v2.40.3）。两机均无外网访问 HF/GitHub 能力，模型一律走本地 `./cache` 或 ModelScope 镜像源。

---

## 二、模型部署明细

### 2.1 192.168.1.137（GPUStack Worker，模型实例实际进程在本机）

| 模型（对外名） | 来源 / 后端 | GPU | 监听端口 | 显存占用 | 关键参数 | 状态 |
|---|---|---|---|---|---|---|
| `qwen3-32b`（Qwen/Qwen3-32B-FP8） | ModelScope / vLLM | GPU 0 | 192.168.1.137:40053 | 46852 MiB（占卡 95.4%） | `--max-model-len=32768`、`--enable-auto-tool-choice`、`--tool-call-parser hermes`、`--reasoning-parser qwen3` | RUNNING 3 天 |
| `qwen3.5-2b`（Qwen/Qwen3.5-2B） | ModelScope / vLLM | GPU 1 | 192.168.1.137:40057 | 9658 MiB（占卡 19.7%） | `--gpu-memory-utilization=0.2`、`--max-model-len 32768`、`--tool-call-parser=qwen3_xml` | RUNNING 3 天 |
| 语音 S2S 栈：Qwen3-ASR-1.7B-hf + Qwen3-TTS + SenseVoiceSmall + qwen3-speaker-encoder + silero-vad | 本地 `./cache`（宿主 `/home/jiangwei/speech-to-speech/cache`） | GPU 1（`device_ids:['1']`） | 8765（pipeline）/ 8010（console） | —（当前 0，容器已停） | STT/TTS/情感/声纹同进程；LLM 走远程 GPUStack `http://192.168.40.30/v1-openai` 的 `Qwen3-8B` | **已停止**（Exited，08:51 优雅关闭，原因见 §7.1） |
| LLaMA-Factory 微调平台（`hiyouga/llamafactory:latest`） | Docker 官方镜像 | 训练时按需 | 7860 / 8000 | 当前 0 | 挂载 `/mnt/data/llamafactory/{cache,data,models,output,saves}` | Up 2 天，当前无训练任务 |

### 2.2 192.168.40.30（GPUStack Master + 推理）

| 模型（对外名） | 来源 / 后端 | GPU | 监听端口 | 显存占用 | 关键参数 | 状态 |
|---|---|---|---|---|---|---|
| `qwen3-vl-embedding-2b`（Qwen/Qwen3-VL-Embedding-2B） | ModelScope / vLLM（`--runner=pooling`） | GPU 0 | 192.168.40.30:40056 | 9890 MiB（占卡 40.3%） | `--gpu-memory-utilization=0.45`、`--max-model-len=4096` | RUNNING 21 小时 |
| `qwen3-vl-reranker-2b`（Qwen/Qwen3-VL-Reranker-2B） | ModelScope / vLLM | GPU 0 | 192.168.40.30:40017 | 6306 MiB（占卡 25.7%） | `--gpu-memory-utilization=0.3`、`--max-model-len 8192`、`hf_overrides` 强制 `Qwen3VLForSequenceClassification` | RUNNING 24 小时 |
| ~~`Qwen3-8B`（Qwen/Qwen3-8B-GGUF，Q8_0）~~ | ModelScope / **llama.cpp-custom** | 已迁至 137 | — | 0 | `/app/llama-server -m .../Qwen3-8B-Q8_0.gguf --alias Qwen3-8B` | **2026-11-26 已迁到 137 worker**，40.30 的 GPU1 整卡让给 S2S 语音栈 |
| `kev-0.8b`（jaredpalmer/kev-0.8b） | HuggingFace / `python -m kev.serve` | GPU 0 | 8008 | 6964 MiB（占卡 28.4%） | 语音情感识别（Kev），配 playground :3000 | Up 3 天 |
| `qwen3-reranker-4b` / `qwen3-embedding-4b` / `qwen3.5-4b` | ModelScope / vLLM | — | — | 0 | — | **replicas=0，未部署**（GPUStack `models` 表有记录，无实例） |

> GPUStack `model_instances` 实录（2026-11-26 迁移后）：`qwen3-vl-reranker-2b`、`qwen3-vl-embedding-2b` → worker `wan-MS-7C22`(=40.30)；`Qwen3-8B`、`qwen3-32b`、`qwen3.5-2b` → worker `NV1`(=137)。

---

## 三、应用 / 服务部署

| 机器 | 应用 | 编排 / 载体 | 对外端口 | 占 GPU | 备注 |
|---|---|---|---|---|---|
| 137 | GPUStack Worker | docker `gpustack-worker` v2.2.3（`--server-url http://192.168.40.30`） | 40053 / 40057 | GPU0 + GPU1 | 模型实例由 master 下发到本机 |
| 137 | LLaMA-Factory | docker `llamafactory` | 7860、8000 | 按需 | 数据在 `/mnt/data/llamafactory`（该盘已 93%） |
| 137 | s2s-split 语音栈 | `docker-compose.split.yml`（project `s2s-split`，目录 `/home/jiangwei/speech-to-speech`） | 8765 / 8010 | GPU1 | 容器 `s2s-split-s2s-pipeline-1`、`s2s-split-s2s-console-1`（2026-11-26 复查时均 Up，console healthy；agent 心跳因缺注册码报 warning，不影响语音链路） |
| 137 | Portainer Agent | docker `portainer/agent:2.39.0` | 9001 | 无 | |
| 137 | Redis | docker `redis:7.2-alpine` | 6379 | 无 | 供 fastgpt compose 使用 |
| 137 | K8s 控制面 + Argo + Kubeflow + Rainbond | kubeadm/containerd 1.6.28 | 6443、10250、10256/7/9、9253/9353 | 节点声明 1 张 GPU 配额 | 当前**无 GPU Pod**、无在跑 Workflow |
| 137 | FastGPT（`tqdeploy/fastgpt`） | docker-compose | — | 无 | 仅 redis 在跑（`running(1)`），FastGPT 主服务未起 |
| 40.30 | GPUStack Master | docker `gpustack` v2.2.3 | 80（网关）、9099 | 控制面 | 内含 Higress/Istio、Postgres 17、Grafana、Prometheus(:19090) |
| 40.30 | GPUStack Worker | docker `gpustack-worker` | — | GPU0 + GPU1 | |
| 40.30 | kev-server / kev-playground | docker `kev-0.8b-server` / `kev-0.8b-playground` | 8008 / 3000 | GPU0 | 情感模型对外 API |
| 40.30 | PP-OCRv6 + paddle-nginx | docker，目录 `/home/wan/ocr-services` | 127.0.0.1:8011 / 8080 | 无（CPU 推理） | 需 `X-API-Key`（在服务器 `.env`，不落文档） |
| 40.30 | Portainer Agent | docker | 9001 | 无 | |
| 40.30 | **s2s-split 语音栈（2026-11-26 新增）** | `docker-compose.split.yml`（project `s2s-split`，目录 `/home/wan/speech-to-speech`） | 8765 / 8010 | **GPU1（11114 MiB）** | 镜像 `s2s-agent:4030-1` / `s2s-console:4030-1`；使用已有共享库 `s2s_db`（2026-11-27 决策变更，不再建 `s2s_db_4030`）；LLM 走 GPUStack `qwen3-32b`（实例在 137）；配置见 `deploy/4030/` |

---

## 四、GPU 实时用量（采样 2026-11-26 16:56）

| 机器 | GPU | 显存占用 | 利用率 | 温度 | 功耗 | 占用进程 |
|---|---|---|---|---|---|---|
| 137 | GPU 0 | 46875 / 49140 MiB（95.4%） | 0% | 41℃ | 7.8 W / 450 W | `VLLM::EngineCore`（Qwen3-32B-FP8）46852 MiB |
| 137 | GPU 1 | 9681 / 49140 MiB（19.7%） | 7% | 57℃ | 270 W / 450 W | `VLLM::EngineCore`（Qwen3.5-2B）9658 MiB |
| 40.30 | GPU 0 | 23218 / 24564 MiB（94.5%） | 0% | 37℃ | 57 W / 450 W | `VLLM::EngineCore` ×2（reranker 6306 + embedding 9890）+ kev 6964 |
| 40.30 | GPU 1 | 11137 / 24564 MiB（45.3%，S2S 语音栈） | 0% | 22℃ | 5.8 W / 450 W | `s2s-split-s2s-pipeline-1`（SenseVoice STT + Qwen3-TTS + 声纹 encoder）11114 MiB |

> 每卡另有 Xorg 桌面进程占 4–10 MiB。40.30 GPU1 原由 `llama-server`（Qwen3-8B GGUF）占用 14.2 GB 且利用率 96%，2026-11-26 该实例迁至 137 后整卡交给 S2S 语音栈。
> GPU0 三个业务实例（kev 6968 / reranker 6306 / embedding 9890 = 23222 MiB，94.5%）未受影响。

---

## 五、近 7 天推理用量（GPUStack `model_usage_details`）

| 模型 | 所在机 | 请求数 | Prompt tokens | Completion tokens | 缓存命中 | 今日请求 |
|---|---|---|---|---|---|---|
| `qwen3.5-2b` | 137 | 121,840 | 172.7 M | 30.5 M | 0 | 3,095 |
| `qwen3-32b` | 137 | 14,582 | 29.6 M | 3.56 M | 8.58 M | 429 |
| `qwen3-vl-embedding-2b` | 40.30 | 4,008 | 14.5 M | 0 | 0 | 4 |
| `Qwen3-8B` | 40.30 | 1,994 | 3.08 M | 0.59 M | 0 | 23 |
| `qwen3-vl-reranker-2b` | 40.30 | 0（7 天内无调用） | — | — | — | 0 |

特点：137 上的 `qwen3.5-2b` 是绝对主力（约 89% 请求量，典型的轻量分类/改写/路由类负载）；32B 主要承担带工具调用与推理的长任务；40.30 的两个 VL 模型偏「嵌入 + 重排」检索链路，重排模型目前实际未被调用。

---

## 六、K8s 集群分布（控制面在 137）

| 项目 | 值 |
|---|---|
| 集群 | k8s v1.28.8，control-plane 节点 = 137 / 110.165 / 110.167（110.165 当前 NotReady） |
| 节点（10） | 1.137、40.30、100.80、100.83、100.84、110.60、110.61、110.165、110.167、110.169 |
| GPU 配额 | 仅 `node-192-168-1-137` 声明 `nvidia.com/gpu=1`，其余节点为 `<none>` |
| 当前 GPU Pod | 无（`kubectl get pods -A` 中无任何 `nvidia.com/gpu` limits） |
| 训练编排 | `argo-server`、`workflow-controller`（infra ns）、`kubeflow-dashboard*`、`minio` 均在 137 运行；`kubectl get workflows -A` = No resources found；无 `notebooks` CRD |
| 平台组件 | `rbd-plugins`（Rainbond）、`rbd-system`（大量 hosts-job Pending/Failed，属噪声） |

结论：GPU 实际由 **GPUStack（Docker）** 管理，**不经 K8s**；K8s 侧只有 gpu-observer DaemonSet 之类监控件。

---

## 七、风险与待办

1. **137 的语音 S2S 服务当前是停的**：日志末段为 `agent tick failed: 401 Unauthorized`（agent 向 console 心跳鉴权失败）→ `agent: stopped` → Uvicorn 优雅关闭，8765 / 8010 当前无监听。恢复前先修 console 令牌（`S2S_AGENT_TOKEN_FILE` 落在挂载卷 `./data/agent/token`），再 `docker compose -f docker-compose.split.yml up -d`。注意 compose 只读 `.env`，`JWT_SECRET_KEY` 必须先在 shell 里 `export`（或写入 `.env`），否则 console 会因缺密钥循环重启。
2. **两张卡显存均已顶格**：137 GPU0 = 95.4%、40.30 GPU0 = 94.5%，再新建 GPU 容器会直接 OOM；新增模型必须先停用现有实例或扩卡。
3. **137 `/mnt/data` 已 93%（剩 31G）**：LLaMA-Factory 的 models/data/cache/output 全在该盘，模型下载或训练产物会撑爆。
4. **端口 40053 在两机语义不同**：137 上是 vLLM 的 `qwen3-32b`，40.30 上是 llama.cpp 的 `Qwen3-8B`。跨机调用务必写全 `192.168.x.x:port`，不要用同一端口号做映射推断。
5. **GPUStack 控制面单点**：master 在 40.30（容器 `gpustack`），且 40.30 只有 8 核 / 62 GB 内存，同时兼作 worker 与 GPU 推理节点（GPU0 三进程共存）。
6. **模型清单与实际实例不一致**：GPUStack `models` 表登记 8 个模型，其中 3 个 `replicas=0` 未部署；排障时以 `model_instances` 为准。
7. `qwen3-vl-reranker-2b` 7 天零调用但常驻占 6.3 GB 显存，若无检索重排需求可考虑缩容。

---

## 八、复测命令速查

```bash
# 1) GPU 概览（两机通用）
nvidia-smi
nvidia-smi --query-gpu=index,name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,power.draw,power.limit --format=csv

# 2) 容器与编排
docker ps --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'
docker compose ls

# 3) 端口占用
ss -ltn | awk '{print $4}' | sort -u

# 4) 找出占用 GPU 的推理进程及其模型（关键：定位到 vllm serve 参数）
ps -eo pid,cmd | grep 'vllm serve' | grep -v grep
ps -eo pid,cmd | grep -E 'llama-server|llama.cpp' | grep -v grep

# 5) GPUStack 模型与实例（master 在 40.30:80）
docker exec gpustack psql -U root -h 127.0.0.1 -d gpustack -c \
  'select id,model_name,source,state,worker_name from model_instances'
docker exec gpustack psql -U root -h 127.0.0.1 -d gpustack -c \
  'select name,replicas,ready_replicas,backend,source from models'
# 近 7 天用量（注意 psql 里用 current_date - 7，避免 interval 引号被本地 shell 吃掉）
docker exec gpustack psql -U root -h 127.0.0.1 -d gpustack -c \
  'select model_name,count(*) as reqs,sum(prompt_token_count) as ptok,sum(completion_token_count) as ctok from model_usage_details where created_at > current_date - 7 group by model_name order by reqs desc'

# 6) K8s（控制面在 137）
kubectl get nodes -o wide
kubectl get pods -A -o wide
kubectl get nodes -o custom-columns=NAME:.metadata.name,GPU:.status.allocatable.nvidia\\.com/gpu --no-headers

# 7) 语音 S2S 恢复（137）
cd /home/jiangwei/speech-to-speech
export JWT_SECRET_KEY=$(sed -n 's/^JWT_SECRET_KEY=//p' .env.agentconsole | head -1)
docker compose -f docker-compose.split.yml up -d
docker logs --tail 50 s2s-split-s2s-pipeline-1
```

远程登录（只读巡检用）：

```bash
d:\tools\plink.exe -ssh jiangwei@192.168.1.137 -pw <pwd>
d:\tools\plink.exe -ssh wan@192.168.40.30 -pw <pwd>
```

---

## 八、语音服务（speech-to-speech）部署实录（2026-11-26）

### 8.1 部署形态

| 项 | 值 |
|---|---|
| 目标机 | 192.168.40.30（Ubuntu 24.04，2×RTX 4090 24G） |
| 目录 | /home/wan/speech-to-speech（project `s2s-split`） |
| 容器 | `s2s-split-s2s-pipeline-1`（8765，GPU1）、`s2s-split-s2s-console-1`（8010→8000） |
| 镜像 | `s2s-agent:4030-1`（sha256:3a6ff284ef487）、`s2s-console:4030-1`（9fcb12a45f1d，本地构建后 load） |
| GPU | 仅 GPU1：`device_ids: ["1"]`；实测占用 11114 MiB（SenseVoice STT + Qwen3-TTS + 声纹 encoder） |
| LLM | GPUStack `http://192.168.40.30/v1-openai` 的 `qwen3-32b`（实例跑在 137 worker，不占本机显存） |
| 参数库 | **已有共享库** `192.168.100.80:5432/s2s_db`（2026-11-27 决策变更，见 8.4；不再建 `s2s_db_4030`） |
| 模型 | 全部离线拷贝：sensevoice-small 897M、qwen3-tts-model 4.3G、qwen3-asr-0.6b-hf 1.5G、qwen3-speaker-encoder 23M、wav2vec2-ljspeech-gruut 361M、smart-turn onnx 8.3M、silero-vad 171M |

### 8.2 验证结果（L0–L7 全绿）

| 层 | 结果 |
|---|---|
| L1 容器 | console `healthy`、pipeline `Up` |
| L2 GPU | GPU1 11137/24564 MiB；GPU0 保持 23222 MiB 不变 |
| L3 空闲池 | `GET /v1/pool` → `{"size":2,"in_use":0,"units":[idle,idle]}` |
| L4 agent | 未注册：`no machine token on disk and no usable register code`（**不影响语音链路**，agent 异常被吞并退避重试） |
| L5 端点 | ASR `今天天气怎么样？` ✅；TTS 53804B wav ✅；SER `/v1/audio/emotion/health` ready=true ✅；声纹 `/v1/audio/embeddings/capability` dim=2048 ready=true ✅，embeddings 返回 2048 维向量 ✅ |
| L6 实时 | e2e：转写 `今天天气怎么样？` → 回复 `让我查一下今天的天气。` → 音频 1.63s/52224B；STT 出字 1.34s、TTFA 1.49s、端到端 1.88s |
| L7 控制台 | `http://192.168.40.30:8010/` → 200，`/api/v1/health` → ok；`param_instance` 已播种 `pipeline-3030 → http://s2s-pipeline:8765` |

### 8.3 镜像交付路径（三次调整的最终结论）

1. 本地 `docker save` 导出 16.7GB 镜像**两次卡死**（0 字节、CPU 不增长）→ Docker Desktop 导出超大镜像不可靠。
2. 40.30 端完整重建（`Dockerfile.agent`）**卡在 `uv sync`**（8 核机器上 uv 无响应）→ 不可靠。
3. **最终方案**：40.30 直接 `docker pull ccr.ccs.tencentyun.com/llm-basic/s2s-agent:1.0`（137 现役同款基底，ID `1ae2ea87f55e`），再用**增量 Dockerfile** 只替换 `src` 层（3 秒完成）：
   ```dockerfile
   FROM ccr.ccs.tencentyun.com/llm-basic/s2s-agent:1.0
   COPY src /usr/src/app/src
   WORKDIR /usr/src/app
   ```
   依赖已核验齐备（`httpx2`/`pywebrtc_audio`/`funasr`/`qwen_tts`/`soundfile` 均可 import），最新代码模块 `irodori_tts_handler.py` 确认在镜像内。

### 8.4 参数库决策变更（2026-11-27：改用已有 `s2s_db`）

> **当前决策**：40.30 的 s2s-console 使用**已有的 `192.168.100.80:5432/s2s_db`**，
> **不再新建、也不使用 `s2s_db_4030`**。部署入口 `deploy/4030/.env.agentconsole`
> 本就已经指向 `s2s_db`；本次同步修正了 `config.split.2/prod.env`、
> `prod.env.example` 及本文档，消除"另建独立库"的旧指引。
>
> **前置条件**：历史 `s2s_db.param_config` 里存有本地 Windows 开发机路径，
> 改用共享库前须修正为容器内路径，否则 console 启动报
> `static dir ../frontend/dist is missing`。逐键目标值见
> `deploy/4030/README.md` §9.6。同时 `S2S_AGENT_MACHINE_ID` 必须与 137 的
> `pipeline-137` 不同（40.30 用 `pipeline-3030`），避免同 machine 行令牌互相覆盖。
>
> 下面保留 2026-11-26 的**历史决策**作为背景，该决策已被上述变更取代。

#### 历史决策（已撤销）：独立参数库 `s2s_db_4030`

共享库 `s2s_db` 的 `param_config` 表里存的是**本地 Windows 开发机播种的路径**（`console.static_dir=../frontend/dist`、`console.data_dir=D:/work/...`），而 console 的配置读取是**库优先于 env**（`config/_store.py`），导致 40.30 的 console 直接启动失败：
`RuntimeError: static dir ../frontend/dist is missing; the image was built without the frontend`。
因此当时改用同实例上的独立库 `s2s_db_4030`：console 播种自己的容器路径（`static_dir=/app/console/static`、`data_dir=/app/console/data`、`param_config_dir=/app/config`），与本地开发机、137 互不污染。

### 8.5 遗留事项

- **agent 注册**：需在控制台"机器"页为 `pipeline-3030` 建档，取一次性注册码填入 `.env.agentconsole` 的 `S2S_AGENT_REGISTER_CODE` 并重启 pipeline（注册码用后即焚，复用返回 401）。
- `console.pipeline_container` 仍是播种默认值 `speech-to-speech-local-pipeline-1`（仅显示用标签），如需可在 `s2s_db` 中改为 `s2s-split-s2s-pipeline-1`。
- 40.30 的 ccr / 个人仓库登录凭据已写入该机 `~/.docker/config.json`，如需收敛权限可删除对应条目。

## 九、config.split.2 切换与本地部署（2026-11-26 晚）

### 9.1 两处部署形态（同一套配置档、两种编排）

| 项 | 本地（Windows + Docker Desktop） | 192.168.40.30（Ubuntu 24.04，2×RTX 4090 24G） |
|---|---|---|
| 编排 | `docker-compose.local.yml`（project `s2s-local`） | `docker-compose.split.yml`（project `s2s-split`） |
| pipeline | 8765，GPU0 | 8765，GPU1（`device_ids: ["1"]`） |
| console | 8010→8000 | 8010→8000 |
| 镜像 | `s2s-agent:local2` + `s2s-console:local`（本地构建） | `s2s-agent:4030-2` + `s2s-console:4030-1` |
| 配置档 | `config.split.2/`（prod.env.local 口径） | `config.split.2/`（prod.env 口径） |
| 权重 | 宿主 `./cache` 绑定挂载到 `/root/.cache/` | 同左（宿主 `/home/wan/speech-to-speech/cache`） |
| LLM | 百炼公网 `qwen-plus`（本地部署要求"只跑本地"，故不依赖内网 GPUStack） | GPUStack `http://192.168.40.30/v1-openai` 的 `qwen3-32b` |
| 参数库 | 本机 postgres 容器 `s2s_db_local`（独立库） | `192.168.100.80:5432/s2s_db`（已有共享库） |
| 机器号 | `local-split2` | `pipeline-3030` |

模型与参数**逐项一致**，差异只在"把内网依赖换成等价可达项"：LLM、参数库、实例 seed（`instances.local.yaml`，id `pipeline-local`）。

### 9.2 配置档 `config.split.2/`（第三套）

模型与参数继承仓库 `config/`（本地 Windows 直跑版），仅两处形态改写：
权重路径 → `/root/.cache/...`（容器 WORKDIR 是 `/usr/src/app`，仓库相对路径不可达）；
agent 三路径 → `/app/config/*`、令牌 → `/app/data/agent/token`（挂载卷，重建不丢）。

启用项：STT `qwen3-asr` / TTS `voxcpm` / `diarization: true`（nemotron3-diarization，bfloat16）/
`enable_visemes: true`（wav2vec2-ljspeech-gruut，cpu）/ `runtime.livekit_worker.enabled: true` / `num_pipelines: 1`。

### 9.3 依赖固化路径（两端都"构建期固化，不在容器里临时 pip"）

| 位置 | 镜像 | 增量层 | 耗时 |
|---|---|---|---|
| 40.30 | `s2s-agent:4030-1` → `4030-2`（sha256:0cf86ae01755） | `COPY src` + `pip install voxcpm livekit-agents~=0.12 livekit-plugins-silero~=0.7 av~=12.3 requests~=2.31` | 33.5s（aliyun 源 32MB/s） |
| 本地 | `s2s-agent:local` → `local2` | `COPY src`（依赖已在 local 里：voxcpm 2.0.3 / livekit-agents 0.12.21 / silero 插件 0.7.6 / funasr 1.4.29 / torchcodec 0.17.0 / torch 2.15.0 + triton 3.9.0 + nvidia-cu13 13.4.1.3） | 数十秒 |

`Dockerfile.agent`（全量构建）本轮修正了三处构建链路缺陷，供后续重建使用：
① apt 换阿里云源 + 组件只留 `main restricted` + 关 DEP-11 + 20s 超时（tuna 的 universe 19.3MB 索引在本机会卡死 7 分钟）；
② `uv sync` 目标从系统 python3 改为 base 预置 `.venv`（否则 uv 判定 torch 缺失，要重下 ~2GB CUDA 栈）；
③ constraints 精准剔除 `torchaudio`/`accelerate`（前者与 torch 2.14.1+cu130 错配、后者与 qwen-tts-hf 要求的 accelerate==1.12.0 冲突），保留 `torch==2.14.1+cu130` 钉版。

### 9.4 切换到 config.split.2 时修掉的四个真缺陷

| 缺陷 | 根因 | 修复位置 |
|---|---|---|
| 独立 TTS 端点恒 503 `TTS handler unavailable` | `audio_services.find_handlers()` 硬编码 TTS 类名为 `Qwen3TTSHandler` | 改为 `name.endswith("TTSHandler")` |
| 内嵌 LiveKit worker 连 localhost:7880 | livekit-agents 0.12.x `WorkerOptions.ws_url` 默认值非空，SDK 因此跳过 `LIVEKIT_URL` 回落 | `Worker(...)` 显式传 `ws_url`/`api_key`/`api_secret` |
| 换 qwen3-asr 后情感端点整体失效 | STT 不再是 SenseVoice，进程内无情感 handler | 新增 `src/speech_to_speech/embedded_ser.py`（独立线程 + 崩溃隔离 + 路由回落） |
| 本地全量重建镜像卡死 | apt 大文件索引 + uv 解析/目标解释器错位 | 见 9.3 |

**本地降级档（`prod.local.yaml` / `prod.env.local`）踩到的两个配置坑**：

| 坑 | 现象 | 根因 | 处置 |
|---|---|---|---|
| 配置文件名后缀 | 启动报 `Configuration error: check the YAML file, selected names, and required environment settings.`（CLI 掩盖真实原因） | `config.load_config` 强制要求文件名以 `.yaml`/`.yml` 结尾，`prod.yaml.local` 不合规 | 改名 `prod.local.yaml`；诊断用容器/宿主内 `load_config()` 取真实 traceback |
| 关闭说话人分离无效 | 日志仍打 `Diarization ready: device=cuda` | `config.py` 的 active 判定是 `(model 非 env 且非空) or diarization is True` —— 只置 `diarization: false` 而保留 `diarization_model_name` 仍判 active | 降级档**同时删掉** `diarization_model_name` 行 |

### 9.5 验证结果

**40.30（config.split.2 + s2s-agent:4030-2）**：L1 console healthy / pipeline Up；L2 GPU1 **12667/24564 MiB**（基线 11137，+1530）、GPU0 **23222 MiB 未变**；
L3 `{"size":1,"in_use":0,"units":[{"index":0,"state":"idle"}]}`；L4 agent 未注册（已知状态）；
L5 ASR「今天天气怎么样？」/ TTS 200（276524B、48 kHz）/ SER ready=true / visemes ready=true / 声纹 dim=2048 + embeddings 2048 维；
L6 e2e：STT **1.62s**、TTFA **2.00s**、端到端 **2.59s**（现役 1.34/1.49/1.88s）；
L7 控制台 200 + health 200；
专项 diarization `device=cuda`、visemes `ready=true`、livekit worker **`registered worker`**、情感**未下线**；137 回归无影响。

**本机（12GB 笔记本卡）**：因单卡要同时承载 ASR-1.7B(3.9G) + VoxCPM2-2B(5.0G) + diarization(0.4G)，
VoxCPM 扩散式预热峰值把显存打满（实测 10521/12227 MiB 后预热长时间不推进；40.30 的 24GB 卡同组合 12667 MiB 正常），
故本机用**降级档** `config.split.2/prod.local.yaml`：diarization 关闭 + ASR 换 `qwen3-asr-0.6b-hf`
（`config.split.2/prod.env.local`），其余（voxcpm TTS / visemes / 声纹 / 内嵌 SER / livekit worker）不变。
**交付口径仍以 `prod.yaml` 为准**（40.30 与仓库基准都用它）。

本机降级档实测（2026-11-26）：L1 console healthy / pipeline Up；L2 显存 **7937/12227 MiB**（降级前 10521）；
L3 `{"size":1,...,"state":"idle"}`；L5 ASR 转写正确、TTS 200/261164B、声纹 capability **dim=2048 ready=true**
+ embeddings 200（2048 维）、SER **ready=true**、visemes **ready=true**；
L6 e2e：转写「今天天气怎么样？」→ 回复「我来帮你查一下今天的天气。」→ 音频 1.92s/61440B，
**STT 3.42s / TTFA 4.45s / 端到端 5.48s**（比 40.30 慢：12GB 卡推理 + LLM 走公网百炼往返 + 0.6B 自回归 ASR）；
L7 console 200 + health 200、`param_instance` 一行（`http://s2s-pipeline:8765`）；
专项：livekit worker **registered**、visemes/SER/声纹均 ready、diarization 按降级关闭。
已知状态：agent 未建档（`no machine token on disk`），不影响语音链路。

### 9.6 已知状态

- **agent 未注册**：两端都报 `agent tick failed: no machine token on disk and no usable register code`，
  需在控制台"机器"页建档并填一次性注册码；**不影响语音链路**（异常被吞并退避重试）。
- **LiveKit 媒体口**：`192.168.110.169:7881` 是 UDP，TCP 探测被拒属正常；worker 以 WS 信令 7880 建连。
