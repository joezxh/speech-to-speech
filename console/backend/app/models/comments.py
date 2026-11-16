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
    "param_proxy_metric": "数据面代理采样：按实例与服务记录成功数与失败原因，成功数为窗口增量",
    "param_version": "配置版本快照，创建后不可变；保存配置全文用于启动自检",
    "turn_latency": "单轮语音延迟索引，可由日志重建，只存原始毫秒值",
    "voices": "音色上传记录，音频与特征路径相对音色数据卷保存",
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
        "raw_offset": "原始日志偏移量，重建时用于定位",
        "ingested_at": "入库时间（UTC）",
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
