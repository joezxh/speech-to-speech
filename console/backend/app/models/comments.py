"""数据库表/字段中文注释的单一事实源。

同时供两处消费，避免漂移：
  1. `app/models/__init__.py` 调用 `apply_comments(Base.metadata)`，把注释挂到
     SQLAlchemy 的 Table/Column 上（`create_all` 与 autogenerate 都会带上）。
  2. `alembic/versions/0007_comments.py` 调用 `comment_statements()`，给**存量库**
     补 `COMMENT ON`（PostgreSQL）。SQLite 不支持 COMMENT ON，返回空列表。

约束：文案主体为中文；不出现单引号（虽会转义）；不出现大写字面量
TIMESTAMP（离线 SQLite 文件的静态闸禁止该子串）。
"""

from __future__ import annotations

from sqlalchemy import MetaData

#: 表级注释。键必须与 Base.metadata 中的表名一一对应。
TABLE_COMMENTS: dict[str, str] = {
    "param_user": "控制台操作员账号与角色，用于登录鉴权",
    "param_audit": "操作审计日志，仅追加；fields 只存字段名不存值",
    "param_cluster": "集群登记表：一个负载均衡注册中心界定一个集群",
    "param_draft": "配置草稿：每个配置档一份增量补丁，不是整份配置",
    "param_instance": "Pipeline 实例注册表，运维开关与集群归属落库",
    "param_instance_metric": "实例状态与分配计数采样；计数为窗口增量而非累计值，空值表示不可得",
    "param_instance_runtime": "实例运行时状态：健康五态、槽位占用、能力指纹与占位数，跨控制台副本共享",
    "param_allocator_lease": "选台占位租约明细：预留待连接的租约与已建立会话的占用都占槽位",
    "param_proxy_metric": "数据面代理采样：按实例与服务记录成功数与失败原因，成功数为窗口增量",
    "param_config": "控制台配置项登记表：库中的值优先于环境变量，改完数秒内生效",
    "param_machine": "机器实体：agent 注册与心跳的落点，实例挂载与机器状态的单一来源",
    "param_machine_command": "机器命令队列：用户下发、机器端 agent 拉取并回执，不主动连接机器",
    "param_machine_workload": "机器负载声明：心跳清单全量覆盖，按机器与负载类型对齐",
    "param_machine_config": "机器实际生效配置，与配置档期望值比对得出漂移数",
    "param_machine_draft": "机器级待下发草稿：配置档渲染后按本表覆盖对应键",
    "param_agent_config_version": "agent 目标配置下发快照，按机器保留最近若干版",
    "param_token_metric": "机器与负载的 token 增量时序，计数为窗口增量而非累计值",
    "param_lb_rule": "负载均衡路由规则，按优先级升序首条命中生效",
    "param_lb_affinity": "会话亲和记录：命中粘性键则跳过规则评估直接选台",
    "param_lb_route_log": "路由决策记账，只追加，用于命中率与规则命中统计",
    "param_release": "发布流水线台账：外部 CI 执行构建与验证，控制台只记录过程",
    "param_version": "配置版本快照，创建后不可变；保存配置全文用于启动自检",
    "turn_latency": "单轮语音延迟索引，可由日志重建，只存原始毫秒值",
    "voices": "音色上传记录，音频与特征路径相对音色数据卷保存",
    "callback_target": "回调目标配置：java 与 python 两类协议的地址、鉴权、超时与重试",
    "callback_delivery_log": "回调投递日志：每次尝试一行，目标删除后日志按软关联保留",
}

#: 列级注释。键必须与 Base.metadata 中对应表的列名一一对应。
COLUMN_COMMENTS: dict[str, dict[str, str]] = {
    "param_user": {
        "id": "主键标识",
        "username": "登录用户名，全局唯一",
        "password_hash": "口令哈希，不存明文",
        "role": "角色：admin 或 operator",
        "disabled": "是否禁用，禁用后不可登录",
        "created_at": "创建时间（UTC）",
        "last_login_at": "最近一次成功登录时间（UTC）",
    },
    "param_audit": {
        "id": "主键标识",
        "at": "事件发生时间（UTC）",
        "actor": "操作人用户名",
        "role": "操作发生时的角色",
        "action": "动作代码，点分前缀表示分类",
        "profile": "关联的配置档名或对象标识",
        "version": "关联的配置版本号",
        "fields": "变更字段名列表，只存字段名不存值",
        "result": "结果：ok 或 error",
        "error_code": "失败时的机器可读错误码",
        "duration_s": "操作耗时（秒）",
        "request_id": "请求追踪标识",
    },
    "param_cluster": {
        "id": "主键标识",
        "name": "集群名称，全局唯一",
        "registry": "负载均衡注册中心地址；空串表示存量 default 集群",
        "policy": "调度策略：least、rr 或 lat",
        "note": "备注说明",
        "created_at": "创建时间（UTC）",
        "updated_at": "最近修改时间（UTC）",
        "updated_by": "最近修改人",
        "baseline_profile": "集群期望值基线绑定的配置档名，机器未指定 profile 时回落",
    },
    "param_draft": {
        "id": "主键标识",
        "profile": "配置档名，每档仅一份草稿",
        "base_version": "草稿所基于的配置版本号",
        "patch": "增量补丁（JSON），不是整份配置",
        "updated_by": "最近修改人",
        "updated_at": "最近修改时间（UTC）",
    },
    "param_instance": {
        "id": "主键标识",
        "instance_id": "实例标识，注册 seed 的幂等键",
        "base_url": "实例端点地址",
        "weight": "调度权重",
        "max_sessions_hint": "声明容量，仅用于展示与偏差告警，不参与分配",
        "labels_json": "实例标签（JSON）",
        "enabled": "是否参与调度",
        "drain_requested": "是否请求排空，控制台重启后仍保持",
        "created_at": "创建时间（UTC）",
        "updated_at": "最近修改时间（UTC）",
        "updated_by": "最近修改人",
        "cluster_id": "所属集群名，软关联 param_cluster.name",
        "machine_id": "所属机器标识，软关联 param_machine.machine_id，空表示未绑定",
    },
    "param_instance_metric": {
        "id": "主键标识",
        "instance_id": "实例标识，软关联 param_instance.instance_id",
        "observed_at": "采样时间（UTC）",
        "observed_by": "采集方标识，未配置时取主机名",
        "kind": "采样类型：sample 或状态跳变",
        "size": "实例池容量",
        "in_use": "占用中的会话槽位数",
        "free": "空闲槽位数",
        "stuck": "卡住的槽位数",
        "status": "实例状态",
        "probe_ms": "探活耗时（毫秒）",
        "alloc_ok": "本采样窗口内分配成功次数",
        "alloc_fail_no_instance": "本窗口内无可用实例的分配失败次数",
        "alloc_fail_instance_503": "本窗口内实例返回 503 的分配失败次数",
        "evict_count": "本窗口内实例摘除次数",
        "recover_count": "本窗口内实例恢复次数",
    },
    "param_proxy_metric": {
        "id": "主键标识",
        "instance_id": "实例标识，软关联 param_instance.instance_id",
        "service": "服务名，例如 asr、tts、voiceprint、emotion、realtime",
        "observed_at": "采样时间（UTC）",
        "observed_by": "采集方标识，未配置时取主机名",
        "ok": "本采样窗口内代理成功次数",
        "fail_count": "本采样窗口内代理失败次数",
        "fail_reason": "失败原因，空表示本窗口无失败",
        "duration_ms": "本窗口内平均耗时（毫秒）",
    },
    "param_instance_runtime": {
        "id": "主键标识",
        "instance_id": "实例标识，软关联 param_instance.instance_id",
        "status": "机器级健康状态：unknown、online、degraded、offline、draining",
        "pool_size": "实例池容量，不可得时为空",
        "in_use": "占用中的会话槽位数，不可得时为空",
        "stuck": "卡住的槽位数，不可得时为空",
        "probe_ms": "探活耗时（毫秒），不可得时为空",
        "capabilities": "能力指纹（JSON 数组），派生状态不落指标表",
        "capability_issues": "能力探测异常原因（JSON 对象），键为能力名",
        "consecutive_failures": "连续探测失败次数，达到阈值判定摘除",
        "consecutive_successes": "连续探测成功次数，达到阈值判定恢复",
        "last_error": "最近一次探测错误摘要",
        "probe_history": "最近若干次探活耗时（JSON 数组），用于分位数",
        "reserved": "本实例上的占位数，预留与会话占用之和，选台时按它原子判定",
        "observed_at": "状态采集时间（UTC）",
        "observed_by": "采集方标识，未配置时取主机名",
    },
    "param_allocator_lease": {
        "lease_key": "租约标识，主键；控制台自生成的预留键",
        "instance_id": "实例标识，软关联 param_instance.instance_id",
        "state": "租约状态：pending 表示已预留待连接，held 表示会话已建立",
        "expires_at": "预留的回收时刻（UTC），会话占用为空",
        "console_id": "占住该槽位的控制台副本标识",
        "created_at": "创建时间（UTC）",
        "updated_at": "最近修改时间（UTC）",
    },
    "param_config": {
        "id": "主键标识",
        "config_key": "配置项键，全局唯一；只允许登记在册的键",
        "value": "配置项值，按字符串存，配合 value_type 解释",
        "value_type": "值类型：str、int、float 或 bool",
        "section": "配置分区：app、console、allocator、demo 或 bootstrap",
        "description": "配置项说明",
        "restart_required": "是否需要重启控制台才生效",
        "version": "写入版本号，单调递增",
        "updated_by": "最近修改人",
        "created_at": "创建时间（UTC）",
        "updated_at": "最近修改时间（UTC）",
    },
    "param_machine": {
        "id": "主键标识",
        "machine_id": "机器标识，全局唯一，注册 seed 的幂等键",
        "cluster_id": "所属集群名，软关联 param_cluster.name",
        "profile": "机器专用配置档名，空表示回落集群基线档",
        "addr": "机器地址，用于面板展示与连通性提示",
        "role": "机器角色：agent、gateway 或 canary",
        "gpu": "显卡型号描述",
        "gpu_total_gb": "显存总量（GB），不可得时为空",
        "version": "部署版本描述，来自 agent 读取的已安装包元数据",
        "gpu_util_pct": "GPU 利用率（%），按 pipeline 进程所在卡采样",
        "cpu_pct": "节点 CPU 使用率（%）",
        "load_avg": "节点 1/5/15 分钟负载均值（JSON 数组）",
        "mem_total_gb": "节点内存总量（GB）",
        "mem_used_gb": "节点已用内存（GB）",
        "mem_pct": "节点内存使用率（%）",
        "gpu_mem_used_gb": "pipeline 所在卡已用显存（GB）",
        "gpu_mem_total_gb": "pipeline 所在卡显存总量（GB）",
        "pipeline_vram_gb": "pipeline 进程实际占用显存（GB）",
        "collected_at": "节点资源采集时间（UTC）",
        "deployment_json": "部署参数快照：运行时生效参数与仓库声明参数分栏（密钥已掩码）",
        "state": "机器状态：pending_register、ok、warn、draining 或 bad",
        "registry_mode": "注册方式：auto 表示自动注册，manual 表示手工建档",
        "agent_version": "agent 程序版本，来自最近一次心跳",
        "protocol_version": "心跳协议版本号",
        "agent_caps": "agent 能力清单（JSON 数组）",
        "token_hash": "机器令牌哈希，明文只下发一次",
        "register_code_hash": "一次性注册码哈希，注册成功后失效",
        "last_seen_at": "最近一次心跳时间（UTC），空表示从未注册成功",
        "created_by": "创建人",
        "updated_by": "最近修改人",
        "created_at": "创建时间（UTC）",
        "updated_at": "最近修改时间（UTC）",
    },
    "param_machine_command": {
        "id": "主键标识",
        "command_id": "命令全局标识，供 agent 回执关联",
        "machine_id": "目标机器标识，软关联 param_machine.machine_id",
        "kind": "命令类型白名单：排空、恢复、重启、拉起、健康检查",
        "payload": "命令参数，健康检查带服务标识",
        "status": "命令状态：待领取、已下发、成功、失败、已超时",
        "result": "agent 回执的真实执行或探测结果，无结果时为空",
        "error": "回执错误信息，成功时为空",
        "expires_at": "命令超时时间（UTC），到期后不再被领取",
        "dispatched_at": "agent 领取时间（UTC）",
        "finished_at": "命令终态时间（UTC）",
        "created_at": "创建时间（UTC）",
        "updated_at": "最近修改时间（UTC）",
    },
    "param_machine_workload": {
        "id": "主键标识",
        "machine_id": "所属机器标识，软关联 param_machine.machine_id",
        "kind": "负载类型：pipeline、llm、video、jepa 或 embed",
        "engine": "推理引擎描述",
        "model": "负载使用的模型名",
        "port": "监听端口，不可得时为空",
        "listen_addr": "容器内实际监听地址，不用于实例匹配",
        "public_addr": "对外可达地址，控制台用它反查实例归属",
        "vram_gb": "显存占用（GB），pipeline 行取 nvidia-smi 实测，其余为声明值",
        "health_path": "健康检查路径",
        "health_interval_s": "健康检查间隔（秒）",
        "note": "备注说明",
        "params_json": "agent 采集的 pipeline 模型与全部参数（密钥已掩码）",
        "state": "负载状态描述，空表示未探测",
        "updated_at": "最近修改时间（UTC）",
    },
    "param_machine_config": {
        "id": "主键标识",
        "machine_id": "所属机器标识，软关联 param_machine.machine_id",
        "param_key": "配置项键，与机器组成唯一键",
        "actual_value": "机器上报的实际值，按字符串存",
        "config_version": "上报时机器持有的配置版本号",
        "observed_at": "观测时间（UTC）",
        "reported_by": "上报方标识，通常为 agent",
    },
    "param_machine_draft": {
        "id": "主键标识",
        "machine_id": "所属机器标识，软关联 param_machine.machine_id",
        "param_key": "配置项键，与机器组成唯一键",
        "value": "待下发的覆盖值，按字符串存",
        "updated_by": "最近修改人",
        "updated_at": "最近修改时间（UTC）",
    },
    "param_agent_config_version": {
        "machine_id": "机器标识，联合主键之一",
        "config_version": "配置版本号，联合主键之一，按机器递增",
        "yaml_hash": "下发全文的摘要，agent 用于比对",
        "yaml_text": "下发全文快照，用于排障与回溯",
        "rendered_at": "渲染时间（UTC）",
    },
    "param_token_metric": {
        "id": "主键标识",
        "machine_id": "所属机器标识，软关联 param_machine.machine_id",
        "workload_id": "所属负载标识，软关联 param_machine_workload.id",
        "observed_at": "窗口起点时间（UTC）",
        "input_tokens": "本窗口输入 token 增量",
        "output_tokens": "本窗口输出 token 增量",
        "responses": "本窗口响应次数增量",
        "audio_duration_s": "本窗口音频时长（秒），不可得时为空",
        "window_s": "统计窗口长度（秒）",
        "reported_by": "上报方标识，通常为 agent",
    },
    "param_lb_rule": {
        "id": "主键标识",
        "name": "规则名，全局唯一",
        "priority": "优先级，数值小者先评估",
        "match_type": "匹配类型：user_signed、tenant_tag、header 或 default",
        "match_value": "匹配值，default 类型为空",
        "target_kind": "目标类型：instance、machine 或 strategy",
        "target_value": "目标值，按目标类型解释",
        "share_pct": "分流百分比，非分流规则为空",
        "sticky_ttl_s": "粘性保持时长（秒），非粘性规则为空",
        "enabled": "是否启用，停用后不参与评估",
        "updated_by": "最近修改人",
        "created_at": "创建时间（UTC）",
        "updated_at": "最近修改时间（UTC）",
    },
    "param_lb_affinity": {
        "affinity_key": "会话派生键，主键",
        "machine_id": "粘住的机器标识，软关联 param_machine.machine_id",
        "instance_id": "粘住的实例标识，软关联 param_instance.instance_id",
        "rule_id": "产生该亲和的规则标识",
        "created_at": "创建时间（UTC）",
        "expires_at": "过期时间（UTC），过期后不再粘住",
    },
    "param_lb_route_log": {
        "id": "主键标识",
        "at": "决策时间（UTC）",
        "session_key": "会话派生键",
        "rule_id": "命中的规则标识，未命中为空",
        "matched": "是否命中规则",
        "instance_id": "最终选中的实例标识",
        "sticky_hit": "是否由粘性亲和直接命中",
        "is_canary": "是否命中灰度目标",
        "input_tokens": "本轮输入 token 数",
        "output_tokens": "本轮输出 token 数",
    },
    "param_release": {
        "id": "主键标识",
        "version": "发布版本名",
        "profile_version": "关联的配置版本号，软关联 param_version.version，未产出时为空",
        "cluster_id": "目标集群名，软关联 param_cluster.name",
        "status": "发布状态：draft、building、staging、canary、rolling、current 或 rolled_back",
        "stage": "当前阶段说明",
        "rollout_pct": "灰度百分比",
        "nodes": "涉及节点清单（JSON 数组）",
        "changes": "变更清单（JSON 数组）",
        "created_by": "创建人",
        "created_at": "创建时间（UTC）",
    },
    "param_version": {
        "id": "主键标识",
        "profile": "配置档名",
        "version": "版本号，与配置档名组成唯一键",
        "status": "发布状态，例如 publishing",
        "note": "版本说明",
        "author": "发布人",
        "yaml_text": "配置全文快照，用于启动自检",
        "yaml_sha256": "配置全文的摘要",
        "env_sha256": "环境变量摘要",
        "duration_s": "发布耗时（秒）",
        "rolled_back_to": "回滚指向的版本号",
        "error_code": "发布失败时的错误码",
        "created_at": "创建时间（UTC）",
    },
    "turn_latency": {
        "response_key": "响应标识，联合主键之一",
        "turn_revision": "轮次修订号，联合主键之一",
        "turn_id": "对话轮次标识",
        "source": "日志来源",
        "status": "本轮状态",
        "smart_status": "Smart Turn 判定状态",
        "e2e_ms": "端到端延迟（毫秒）",
        "stt_ms": "语音识别耗时（毫秒）",
        "llm_ms": "语言模型耗时（毫秒）",
        "tts_ttfa_ms": "语音合成首包耗时（毫秒）",
        "vad_decision_ms": "VAD 判停耗时（毫秒）",
        "hold_ms": "保持等待耗时（毫秒）",
        "logged_at": "日志写入时间（UTC）",
        "raw_offset": "原始日志偏移量，重建时用于定位；agent 上报行恒为 0",
        "ingested_at": "入库时间（UTC）",
        "machine_id": "采集机器标识，软关联 param_machine.machine_id，空表示控制台本机",
        "instance_id": "采集实例标识，软关联 param_instance.instance_id",
        "audio_duration_s": "本轮音频时长（秒），合成实时率的分子，缺键时为空",
    },
    "voices": {
        "id": "音色标识",
        "name": "音色名称，唯一",
        "source": "音色来源",
        "backend": "合成后端",
        "language": "语种",
        "status": "音色状态，例如 draft",
        "audio_relpath": "参考音频相对路径",
        "audio_bytes": "音频字节数",
        "audio_seconds": "音频时长（秒）",
        "trim_start_ms": "裁剪起点（毫秒）",
        "trim_end_ms": "裁剪终点（毫秒）",
        "ref_text": "参考音频对应的文本",
        "instruct": "音色描述指令",
        "spk_relpath": "说话人特征相对路径",
        "rvq_relpath": "RVQ 特征相对路径",
        "error_code": "处理失败时的错误码",
        "created_at": "创建时间（UTC）",
        "created_by": "上传人",
        "consent_ack_at": "授权确认时间（UTC）",
        "retention_days": "保留天数",
    },
    "callback_target": {
        "id": "主键标识",
        "name": "目标名称，全局唯一",
        "target_type": "协议类型：java 或 python",
        "base_url": "目标地址；java 取服务根地址，python 取完整回调地址",
        "auth_type": "鉴权方式：none、bearer 或 header_token",
        "auth_header_name": "header_token 鉴权的请求头名，bearer 与 none 时为空",
        "auth_token": "鉴权凭据，接口返回时脱敏",
        "extra_headers": "附加请求头（JSON 对象）",
        "timeout_ms": "单次请求超时（毫秒）",
        "retry_max_attempts": "最大尝试次数",
        "retry_backoff_ms": "首次重试退避（毫秒），按指数递增",
        "events": "订阅的事件类型清单（JSON 数组）",
        "filters": "可选过滤器：说话人与最小文本长度（JSON 对象）",
        "enabled": "是否启用，停用后不投递",
        "updated_by": "最近修改人",
        "created_at": "创建时间（UTC）",
        "updated_at": "最近修改时间（UTC）",
    },
    "callback_delivery_log": {
        "id": "主键标识",
        "target_id": "目标标识，软关联 callback_target.id，目标删除后为空",
        "event_type": "投递的事件类型",
        "triggered_at": "投递触发时间（UTC）",
        "request_url": "实际请求地址",
        "request_payload": "请求体快照，截断存储且凭据已脱敏",
        "attempt": "第几次尝试，从 1 起",
        "http_status": "响应状态码，网络异常时为空",
        "response_snippet": "响应体摘要，截断存储",
        "duration_ms": "本次尝试耗时（毫秒）",
        "status": "尝试结果：success、retrying 或 failed",
        "error": "失败原因摘要，成功时为空",
    },
}


def _literal(text: str) -> str:
    """PostgreSQL 字符串字面量；中文文案里不用单引号，这里仍做转义兜底。"""
    return "'" + text.replace("'", "''") + "'"


def apply_comments(metadata: MetaData) -> None:
    """把中文注释挂到 SQLAlchemy 的 Table/Column 上（新库 create_all 也带上）。"""
    for table_name, comment in TABLE_COMMENTS.items():
        table = metadata.tables.get(table_name)
        if table is not None:
            table.comment = comment
    for table_name, columns in COLUMN_COMMENTS.items():
        table = metadata.tables.get(table_name)
        if table is None:
            continue
        for column_name, comment in columns.items():
            column = table.columns.get(column_name)
            if column is not None:
                column.comment = comment


def comment_statements(dialect_name: str) -> list[str]:
    """给存量库补注释的 SQL；SQLite 不支持 COMMENT ON，返回空列表。"""
    return _statements(dialect_name, drop=False)


def drop_comment_statements(dialect_name: str) -> list[str]:
    """回滚：清除注释（IS NULL）。"""
    return _statements(dialect_name, drop=True)


def _statements(dialect_name: str, *, drop: bool) -> list[str]:
    if dialect_name != "postgresql":
        return []
    statements: list[str] = []
    # 不带尾部分号：Alembic 离线渲染（upgrade head --sql）会自行补 `;`，
    # 带了会生成 `;;`；在线执行时 sa.text 无分号同样合法。
    for table_name, comment in TABLE_COMMENTS.items():
        value = "NULL" if drop else _literal(comment)
        statements.append(f'COMMENT ON TABLE "{table_name}" IS {value}')
    for table_name, columns in COLUMN_COMMENTS.items():
        for column_name, comment in columns.items():
            value = "NULL" if drop else _literal(comment)
            statements.append(
                f'COMMENT ON COLUMN "{table_name}"."{column_name}" IS {value}'
            )
    return statements
