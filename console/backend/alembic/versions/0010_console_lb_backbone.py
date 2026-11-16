"""Console load-balancing backbone: machines, workloads, config, LB, releases.

Revision ID: 0010_console_lb_backbone
Revises: 0009_db_registry_and_config

spec 2026-11-17 §7.1 的 9 张新表 + 3 处扩列，另并入一张实现载体表：

- `param_machine` / `param_machine_workload`：机器一等公民与负载声明。
- `param_machine_config` / `param_machine_draft`：漂移源与机器级待下发草稿。
- `param_agent_config_version`：agent 配置下发快照（Task 5/6 的载体，按机保留最近若干版）。
- `param_token_metric`：token 增量时序。
- `param_lb_rule` / `param_lb_affinity` / `param_lb_route_log`：路由规则、会话亲和、决策记账。
- `param_release`：发布流水线台账（build/staging 由外部 CI 执行，console 只记账）。

扩列：turn_latency +3（机器维度与音频时长）、param_instance +machine_id、
param_cluster +baseline_profile。都不建 FK（软关联，与既有做法一致）；
实例删除/机器删除后历史仍可读。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_console_lb_backbone"
down_revision = "0009_db_registry_and_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_machine",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("cluster_id", sa.String(64), server_default="", nullable=False),
        sa.Column("profile", sa.String(64), nullable=True),
        sa.Column("addr", sa.String(255), server_default="", nullable=False),
        sa.Column("role", sa.String(16), server_default="agent", nullable=False),
        sa.Column("gpu", sa.String(64), server_default="", nullable=False),
        sa.Column("gpu_total_gb", sa.Float(), nullable=True),
        sa.Column("version", sa.String(64), server_default="", nullable=False),
        sa.Column("state", sa.String(16), server_default="pending_register", nullable=False),
        sa.Column("registry_mode", sa.String(16), server_default="manual", nullable=False),
        sa.Column("agent_version", sa.String(64), server_default="", nullable=False),
        sa.Column("protocol_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("agent_caps", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=True),
        sa.Column("register_code_hash", sa.String(64), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(64), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("machine_id", name="uq_param_machine_machine_id"),
        sa.UniqueConstraint("token_hash", name="uq_param_machine_token_hash"),
        sa.UniqueConstraint("register_code_hash", name="uq_param_machine_register_code_hash"),
    )
    op.create_index("ix_param_machine_cluster_id", "param_machine", ["cluster_id"])

    op.create_table(
        "param_machine_workload",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), server_default="pipeline", nullable=False),
        sa.Column("engine", sa.String(64), server_default="", nullable=False),
        sa.Column("model", sa.String(128), server_default="", nullable=False),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("listen_addr", sa.String(64), server_default="", nullable=False),
        sa.Column("public_addr", sa.String(64), server_default="", nullable=False),
        sa.Column("vram_gb", sa.Float(), nullable=True),
        sa.Column("health_path", sa.String(255), server_default="", nullable=False),
        sa.Column("health_interval_s", sa.Integer(), server_default="30", nullable=False),
        sa.Column("note", sa.String(255), server_default="", nullable=False),
        sa.Column("state", sa.String(16), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_param_machine_workload_machine_id", "param_machine_workload", ["machine_id"])

    op.create_table(
        "param_machine_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("param_key", sa.String(128), nullable=False),
        sa.Column("actual_value", sa.String(1024), server_default="", nullable=False),
        sa.Column("config_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reported_by", sa.String(64), server_default="agent", nullable=False),
        sa.UniqueConstraint("machine_id", "param_key", name="uq_param_machine_config_key"),
    )
    op.create_index("ix_param_machine_config_machine_id", "param_machine_config", ["machine_id"])

    op.create_table(
        "param_machine_draft",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("param_key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(1024), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("machine_id", "param_key", name="uq_param_machine_draft_key"),
    )
    op.create_index("ix_param_machine_draft_machine_id", "param_machine_draft", ["machine_id"])

    op.create_table(
        "param_agent_config_version",
        sa.Column("machine_id", sa.String(64), primary_key=True),
        sa.Column("config_version", sa.Integer(), primary_key=True),
        sa.Column("yaml_hash", sa.String(64), server_default="", nullable=False),
        sa.Column("yaml_text", sa.Text(), nullable=False),
        sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "param_token_metric",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("workload_id", sa.Integer(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("responses", sa.Integer(), server_default="0", nullable=False),
        sa.Column("audio_duration_s", sa.Float(), nullable=True),
        sa.Column("window_s", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reported_by", sa.String(64), server_default="agent", nullable=False),
    )
    op.create_index("ix_param_token_metric_machine_id", "param_token_metric", ["machine_id"])

    op.create_table(
        "param_lb_rule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="100", nullable=False),
        sa.Column("match_type", sa.String(16), server_default="default", nullable=False),
        sa.Column("match_value", sa.String(255), server_default="", nullable=False),
        sa.Column("target_kind", sa.String(16), server_default="instance", nullable=False),
        sa.Column("target_value", sa.String(255), server_default="", nullable=False),
        sa.Column("share_pct", sa.Integer(), nullable=True),
        sa.Column("sticky_ttl_s", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_param_lb_rule_name"),
    )

    op.create_table(
        "param_lb_affinity",
        sa.Column("affinity_key", sa.String(128), primary_key=True),
        sa.Column("machine_id", sa.String(64), nullable=True),
        sa.Column("instance_id", sa.String(64), nullable=True),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_param_lb_affinity_machine_id", "param_lb_affinity", ["machine_id"])
    op.create_index("ix_param_lb_affinity_expires_at", "param_lb_affinity", ["expires_at"])

    op.create_table(
        "param_lb_route_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("session_key", sa.String(128), server_default="", nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("matched", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("instance_id", sa.String(64), nullable=True),
        sa.Column("sticky_hit", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("is_canary", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
    )
    op.create_index("ix_param_lb_route_log_at", "param_lb_route_log", ["at"])

    op.create_table(
        "param_release",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("profile_version", sa.String(64), nullable=True),
        sa.Column("cluster_id", sa.String(64), server_default="", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("stage", sa.String(32), server_default="", nullable=False),
        sa.Column("rollout_pct", sa.Integer(), server_default="0", nullable=False),
        sa.Column("nodes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("changes", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("created_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 扩列（均可空或带默认，存量行零回填）。
    op.add_column("turn_latency", sa.Column("machine_id", sa.String(64), nullable=True))
    op.add_column("turn_latency", sa.Column("instance_id", sa.String(64), nullable=True))
    op.add_column("turn_latency", sa.Column("audio_duration_s", sa.Float(), nullable=True))
    op.add_column("param_instance", sa.Column("machine_id", sa.String(64), nullable=True))
    op.add_column(
        "param_cluster",
        sa.Column("baseline_profile", sa.String(64), server_default="prod", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("param_cluster", "baseline_profile")
    op.drop_column("param_instance", "machine_id")
    op.drop_column("turn_latency", "audio_duration_s")
    op.drop_column("turn_latency", "instance_id")
    op.drop_column("turn_latency", "machine_id")
    op.drop_table("param_release")
    op.drop_index("ix_param_lb_route_log_at", table_name="param_lb_route_log")
    op.drop_table("param_lb_route_log")
    op.drop_index("ix_param_lb_affinity_expires_at", table_name="param_lb_affinity")
    op.drop_index("ix_param_lb_affinity_machine_id", table_name="param_lb_affinity")
    op.drop_table("param_lb_affinity")
    op.drop_table("param_lb_rule")
    op.drop_index("ix_param_token_metric_machine_id", table_name="param_token_metric")
    op.drop_table("param_token_metric")
    op.drop_table("param_agent_config_version")
    op.drop_index("ix_param_machine_draft_machine_id", table_name="param_machine_draft")
    op.drop_table("param_machine_draft")
    op.drop_index("ix_param_machine_config_machine_id", table_name="param_machine_config")
    op.drop_table("param_machine_config")
    op.drop_index("ix_param_machine_workload_machine_id", table_name="param_machine_workload")
    op.drop_table("param_machine_workload")
    op.drop_index("ix_param_machine_cluster_id", table_name="param_machine")
    op.drop_table("param_machine")
