export default {
  page: {
    title: '集群总览',
    desc: '集群范围内的机器、Pipeline 实例与最近变更。'
  },
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
    errorRate: '错误率（5分钟）',
    sub: {
      machinesOnline: '在线机器 {n}',
      activeSessions: '活跃会话: {n}',
      stickyHit: '会话粘滞命中率 · 待 S3 交付',
      topError: '主要错误来源: {source}',
      noSamples: '窗口内无分配样本'
    }
  },
  topology: {
    title: '集群拓扑 —— 负载均衡 → 机器 → Pipeline 实例',
    hint: '点击机器可下钻查看部署与参数',
    clusterLayer: '集群',
    lbLayer: '负载均衡层',
    machineLayer: '机器层',
    instanceLayer: 'Pipeline 实例层',
    empty: '该集群还没有机器 —— 请先在「机器管理」添加机器。',
    poolSessions: '/v1/pool · {n} 会话',
    machineMeta: '{n} 实例 · {m} 在线',
    occupancy: '{inUse}/{size}'
  },
  policy: {
    least: 'least-in-use',
    rr: 'round-robin',
    lat: 'least-latency'
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
    empty: '暂无集群',
    sectionTitle: '集群 —— 每个集群对应一个 LB 注册中心',
    hint: '集群由负载均衡注册中心界定；机器通过它注册并接受调度。'
  },
  status: {
    healthy: '正常',
    unhealthy: '异常',
    ok: '健康',
    warn: '降级',
    draining: '排空中',
    bad: '故障',
    muted: '无数据'
  },
  actions: {
    create: '新增集群',
    switchTo: '进入',
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
    lb: '负载均衡（统一入口）',
    machine: '机器',
    instance: 'Pipeline 实例',
    online: '在线',
    degraded: '降级',
    offline: '离线',
    muted: '暂无数据',
    ok: '健康',
    warn: '降级',
    draining: '排空中',
    bad: '故障',
    flow: '流动连线 = 活跃流量'
  },
  events: {
    title: '最近集群事件',
    hint: '完整历史见操作审计日志',
    at: '时间',
    actor: '操作人',
    role: '角色',
    category: '分类',
    action: '动作',
    target: '对象',
    result: '结果',
    ok: '成功',
    error: '失败',
    empty: '暂无集群操作',
    cat: {
      cluster: '集群',
      param: '参数',
      deploy: '部署',
      release: '发布',
      voice: '音色',
      machine: '机器',
      access: '访问',
      other: '其他'
    }
  },
  toast: {
    created: '集群 {name} 已创建。',
    updated: '集群 {name} 已更新。',
    deleted: '集群 {name} 已移除。',
    switched: '已切换到集群 {name}。',
    last: '至少需要保留一个集群。',
    blocked: '{name} 下仍有 {n} 台机器 —— 请先移除机器。',
    serverError: '操作失败：{message}',
    switchFailed: '切换集群失败：{message}'
  }
}
