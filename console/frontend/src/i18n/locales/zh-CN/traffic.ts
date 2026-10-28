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
  }
}
