from app.db.base import Base

from .comments import apply_comments
from .param_audit import ParamAudit
from .param_cluster import ParamCluster
from .param_draft import ParamDraft
from .param_instance import ParamInstance
from .param_instance_metric import ParamInstanceMetric
from .param_proxy_metric import ParamProxyMetric
from .param_user import ParamUser
from .param_version import ParamVersion
from .turn_latency import TurnLatencyRow
from .voice import Voice

__all__ = [
    "ParamAudit",
    "ParamCluster",
    "ParamDraft",
    "ParamInstance",
    "ParamInstanceMetric",
    "ParamProxyMetric",
    "ParamUser",
    "ParamVersion",
    "TurnLatencyRow",
    "Voice",
]

# 所有模型类注册完成后，把中文注释挂到 Table/Column.comment：
# create_all（测试/新库）与 Alembic autogenerate 都会带上，且与 0007 迁移同源。
apply_comments(Base.metadata)
