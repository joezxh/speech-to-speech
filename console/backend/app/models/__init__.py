from app.db.base import Base

from .comments import apply_comments
from .lb import ParamLbAffinity, ParamLbRouteLog, ParamLbRule
from .machine import ParamMachine, ParamMachineWorkload
from .machine_command import ParamMachineCommand
from .machine_config import ParamAgentConfigVersion, ParamMachineConfig, ParamMachineDraft
from .param_allocator_lease import ParamAllocatorLease
from .param_audit import ParamAudit
from .param_cluster import ParamCluster
from .param_config import ParamConfig
from .param_draft import ParamDraft
from .param_instance import ParamInstance
from .param_instance_metric import ParamInstanceMetric
from .param_instance_runtime import ParamInstanceRuntime
from .param_proxy_metric import ParamProxyMetric
from .release import ParamRelease
from .param_user import ParamUser
from .param_version import ParamVersion
from .token_metric import ParamTokenMetric
from .turn_latency import TurnLatencyRow
from .voice import Voice

__all__ = [
    "ParamAgentConfigVersion",
    "ParamAllocatorLease",
    "ParamAudit",
    "ParamCluster",
    "ParamConfig",
    "ParamDraft",
    "ParamInstance",
    "ParamInstanceMetric",
    "ParamInstanceRuntime",
    "ParamLbAffinity",
    "ParamLbRouteLog",
    "ParamLbRule",
    "ParamMachine",
    "ParamMachineCommand",
    "ParamMachineConfig",
    "ParamMachineDraft",
    "ParamMachineWorkload",
    "ParamProxyMetric",
    "ParamRelease",
    "ParamTokenMetric",
    "ParamUser",
    "ParamVersion",
    "TurnLatencyRow",
    "Voice",
]

# 所有模型类注册完成后，把中文注释挂到 Table/Column.comment：
# create_all（测试/新库）与 Alembic autogenerate 都会带上，且与 0007 迁移同源。
apply_comments(Base.metadata)
