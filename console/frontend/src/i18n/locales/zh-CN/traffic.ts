export default {
  banner: {
    off: '负载均衡当前未启用，下方展示的是配置值而非生效行为。'
  },
  title: {
    settings: '分配器配置',
    policy: '调度策略',
    routing: '路由能力',
    trends: '实例趋势'
  },
  field: {
    probeIntervalS: '探测间隔(秒)',
    probeTimeoutS: '探测超时(秒)',
    failThreshold: '失败阈值',
    recoverThreshold: '恢复阈值',
    grantTtlS: '授权有效期(秒)',
    usageIntervalS: '用量上报间隔(秒)',
    metricRetentionDays: '指标保留(天)',
    queueEnabled: '排队',
    webrtcHangupEnabled: 'WebRTC 挂断',
    consoleId: '控制台实例',
    seedConfigured: '种子配置',
    allocatorMode: '分配器模式'
  },
  policy: {
    readOnlyNote: '调度策略当前为硬编码，暂不可配置。',
    policy: '策略',
    tieBreaker: '平票规则'
  },
  unimpl: {
    stickiness: '会话粘滞路由由 S3 交付',
    canary: '金丝雀流量比例由 S3 交付',
    routing: '自定义路由规则由 S3 交付'
  },
  cards: {
    title: '流量与路由',
    total: 'Token 总量',
    perMinute: '每分钟',
    cost: '成本(USD)',
    sticky: '粘性命中',
    tokenCard: 'Token 用量',
    tokenNotice: '口径：token 只计本控制台登记的机器，按心跳窗口增量汇总。',
    policy: '调度与会话策略',
    rules: '路由规则',
    trend: 'Token 趋势',
    distribution: 'Token 机器分布',
    egress: '负载出口',
    instances: '实例',
    backends: '模型接口调用统计'
  },
  kpi: {
    p95ttft: 'P95 TTFT',
    p95ttftSub: '最快机器 {machine}',
    activeSessions: '活跃会话',
    instancesSub: '实例数: {n}',
    routeHit: '路由命中率',
    stickySub: '粘性 TTL {ttl}s',
    errRate: '错误率',
    topErrSub: '最高错误实例: {instance}'
  },
  token: {
    windowTotal: '{win} Token 总量',
    prompt: '输入（prompt）',
    completion: '输出（completion）',
    rate: '每分钟速率',
    quotaSub: '水位 {pct}% · 配额 {quota}/min',
    splitRatio: '输入/输出占比',
    promptLabel: '输入',
    completionLabel: '输出',
    costLine: '成本（{win}）≈ ${cost}',
    priceNote: '单价：输入 ${in}/Mtok · 输出 ${out}/Mtok（env 配置）',
    perSession: '每会话 token',
    perSessionSub: '{n} token · 约 {turns} 轮/会话'
  },
  policyCard: {
    scheduling: '调度策略',
    stickyTtl: '会话粘性保持',
    healthInterval: '健康检查间隔',
    evict: '摘除阈值',
    canary: '金丝雀流量比例',
    seconds: '秒',
    failures: '{n} 次失败'
  },
  rules: {
    colRule: '规则',
    colDest: '目标',
    colTokens: '窗口 Token',
    colRate: '每分钟',
    colShare: '份额',
    noMatched: '窗口内无路由记录'
  },
  distribution: {
    colMachine: '机器',
    colTokens: 'Token',
    colShare: '份额'
  },
  egress: {
    colKind: '类型',
    colEngine: '引擎',
    colHosts: '主机',
    colLoad: '负载',
    colTokens: 'Token',
    colVram: '显存',
    colRoute: '路由方式',
    routeLb: '负载均衡 · 会话粘性',
    routeDirect: '直连'
  },
  backends: {
    byKind: '按类型汇总',
    byModel: '按引擎/模型明细',
    byMachine: '按机器分布',
    trend: '调用次数趋势',
    colKind: '类型',
    colCalls: '调用次数',
    colErrors: '错误数',
    colAvgMs: '平均时延',
    colEngine: '引擎',
    colModel: '模型',
    colMachine: '机器',
    colShare: '占比',
    noData: '窗口内无调用记录（需 pipeline 升级到带 backends 上报的 agent）'
  },
  instances: {
    colInstance: '实例',
    colMachine: '机器',
    colLoad: '负载',
    colRpm: 'rpm',
    colTtft: 'TTFT',
    colRtf: 'RTF',
    colErr: '错误率',
    colStatus: '状态'
  },
  chart: {
    peak: '峰值',
    now: '当前'
  },
  common: {
    effective: '生效',
    default: '默认',
    empty: '暂无数据'
  }
}
