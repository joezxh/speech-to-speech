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
    secretsConsistent: '密钥一致性',
    errorRate: '错误率 (5m)'
  },
  topology: {
    title: '集群拓扑',
    clusterLayer: '集群',
    lbLayer: '负载均衡层',
    machineLayer: '机器层',
    instanceLayer: 'Pipeline 实例层'
  },
  policy: {
    least: '最少会话',
    rr: '轮询',
    lat: '最低延迟'
  },
  table: {
    cluster: '集群',
    registry: 'Registry',
    policy: '策略',
    machines: '机器',
    instances: '实例',
    status: '状态',
    actions: '操作',
    current: '当前',
    empty: '暂无集群'
  },
  status: {
    healthy: '正常',
    unhealthy: '异常'
  },
  actions: {
    create: '新增集群',
    switchTo: '切换',
    edit: '编辑',
    delete: '删除'
  },
  form: {
    createTitle: '新增集群',
    editTitle: '编辑集群',
    name: '名称',
    registry: 'Registry',
    policy: '策略',
    note: '备注',
    nameRequired: '必填 · 名称',
    nameInvalid: '名称需为 2–40 位小写字母/数字/连字符，且以字母或数字开头',
    registryRequired: '必填 · registry',
    registryInvalid: 'registry 需为 scheme://host:port 或 host:port（端口 2–5 位）',
    policyInvalid: '策略仅支持 least / rr / lat',
    noteTooLong: '备注不超过 255 字'
  },
  confirm: {
    deleteContent: '删除集群 {name}？该操作会写入审计。'
  },
  legend: {
    title: '图例',
    cluster: '集群',
    lb: '负载均衡',
    machine: '机器',
    instance: 'Pipeline 实例',
    online: '在线',
    degraded: '降级',
    offline: '离线',
    muted: '暂无数据'
  },
  events: {
    title: '最近事件',
    at: '时间',
    actor: '操作人',
    role: '角色',
    action: '动作',
    target: '对象',
    result: '结果',
    ok: '成功',
    error: '失败',
    empty: '暂无集群操作'
  }
}