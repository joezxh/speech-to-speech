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
| `Qwen3-8B`（Qwen/Qwen3-8B-GGUF，Q8_0） | ModelScope / **llama.cpp-custom** | GPU 1 | 192.168.40.30:40053 | 14226 MiB（占卡 57.9%） | `/app/llama-server -m .../Qwen3-8B-Q8_0.gguf --alias Qwen3-8B` | RUNNING 3 天 |
| `kev-0.8b`（jaredpalmer/kev-0.8b） | HuggingFace / `python -m kev.serve` | GPU 0 | 8008 | 6964 MiB（占卡 28.4%） | 语音情感识别（Kev），配 playground :3000 | Up 3 天 |
| `qwen3-reranker-4b` / `qwen3-embedding-4b` / `qwen3.5-4b` | ModelScope / vLLM | — | — | 0 | — | **replicas=0，未部署**（GPUStack `models` 表有记录，无实例） |

> GPUStack `model_instances` 实录（5 条 RUNNING）：`Qwen3-8B`→worker `wan-MS-7C22`(=40.30)、`qwen3-vl-reranker-2b`→40.30、`qwen3-vl-embedding-2b`→40.30、`qwen3-32b`→worker `NV1`(=137)、`qwen3.5-2b`→137。

---

## 三、应用 / 服务部署

| 机器 | 应用 | 编排 / 载体 | 对外端口 | 占 GPU | 备注 |
|---|---|---|---|---|---|
| 137 | GPUStack Worker | docker `gpustack-worker` v2.2.3（`--server-url http://192.168.40.30`） | 40053 / 40057 | GPU0 + GPU1 | 模型实例由 master 下发到本机 |
| 137 | LLaMA-Factory | docker `llamafactory` | 7860、8000 | 按需 | 数据在 `/mnt/data/llamafactory`（该盘已 93%） |
| 137 | s2s-split 语音栈 | `docker-compose.split.yml`（project `s2s-split`，目录 `/home/jiangwei/speech-to-speech`） | 8765 / 8010 | GPU1 | 容器 `s2s-split-s2s-pipeline-1`、`s2s-split-s2s-console-1`（**均已停止**） |
| 137 | Portainer Agent | docker `portainer/agent:2.39.0` | 9001 | 无 | |
| 137 | Redis | docker `redis:7.2-alpine` | 6379 | 无 | 供 fastgpt compose 使用 |
| 137 | K8s 控制面 + Argo + Kubeflow + Rainbond | kubeadm/containerd 1.6.28 | 6443、10250、10256/7/9、9253/9353 | 节点声明 1 张 GPU 配额 | 当前**无 GPU Pod**、无在跑 Workflow |
| 137 | FastGPT（`tqdeploy/fastgpt`） | docker-compose | — | 无 | 仅 redis 在跑（`running(1)`），FastGPT 主服务未起 |
| 40.30 | GPUStack Master | docker `gpustack` v2.2.3 | 80（网关）、9099 | 控制面 | 内含 Higress/Istio、Postgres 17、Grafana、Prometheus(:19090) |
| 40.30 | GPUStack Worker | docker `gpustack-worker` | — | GPU0 + GPU1 | |
| 40.30 | kev-server / kev-playground | docker `kev-0.8b-server` / `kev-0.8b-playground` | 8008 / 3000 | GPU0 | 情感模型对外 API |
| 40.30 | PP-OCRv6 + paddle-nginx | docker，目录 `/home/wan/ocr-services` | 127.0.0.1:8011 / 8080 | 无（CPU 推理） | 需 `X-API-Key`（在服务器 `.env`，不落文档） |
| 40.30 | Portainer Agent | docker | 9001 | 无 | |

---

## 四、GPU 实时用量（采样 2026-11-26 16:56）

| 机器 | GPU | 显存占用 | 利用率 | 温度 | 功耗 | 占用进程 |
|---|---|---|---|---|---|---|
| 137 | GPU 0 | 46875 / 49140 MiB（95.4%） | 0% | 41℃ | 7.8 W / 450 W | `VLLM::EngineCore`（Qwen3-32B-FP8）46852 MiB |
| 137 | GPU 1 | 9681 / 49140 MiB（19.7%） | 7% | 57℃ | 270 W / 450 W | `VLLM::EngineCore`（Qwen3.5-2B）9658 MiB |
| 40.30 | GPU 0 | 23218 / 24564 MiB（94.5%） | 0% | 37℃ | 57 W / 450 W | `VLLM::EngineCore` ×2（reranker 6306 + embedding 9890）+ kev 6964 |
| 40.30 | GPU 1 | 14289 / 24564 MiB（58.2%） | **96%** | 54℃ | 338 W / 450 W | `llama-server`（Qwen3-8B GGUF）14226 MiB |

> 每卡另有 Xorg 桌面进程占 4–10 MiB。40.30 GPU1 利用率 96%、功耗 338W，是当前唯一满载卡。

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
