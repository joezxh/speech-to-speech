export default {
  kpi: {
    machines: '机器数',
    pipelineInstances: 'Pipeline 实例',
    online: '在线',
    degraded: '降级',
    offline: '离线',
    draining: '摘除中',
    activeSessions: '活跃会话',
    freeSlots: '空闲槽位',
    totalSlots: '槽位总数',
    pendingGrants: '待领取授权',
    clusterAlerts: '集群告警',
    catalogCommit: '参数目录版本',
    version: '生效版本',
    status: '发布状态',
    allocatorMode: '分配器模式',
    consoleId: '控制台实例',
    dbHealth: '数据库健康',
    pipelineHealth: 'Pipeline 健康',
    instancesRegistered: '已注册实例',
    seedConfigured: '种子配置',
    secretsConsistent: '密钥一致性'
  },
  topology: {
    lbLayer: '负载均衡层',
    pipelineLayer: 'Pipeline 实例层',
    machineLayer: '机器层'
  },
  unimpl: {
    machines: '机器层拓扑由 S2 交付',
    errorRate: '错误率统计由 S3 交付',
    stickiness: '会话粘滞命中率由 S3 交付',
    p95ttft: 'P95 首 token 延迟由 S3 交付',
    training: '训练任务视图未包含在本期范围'
  }
}
