export default {
  banner: {
    off: 'Load balancing is currently disabled. The values below are configuration, not live behavior.'
  },
  title: {
    settings: 'Allocator settings',
    policy: 'Scheduling policy',
    routing: 'Routing capabilities',
    trends: 'Instance trends'
  },
  field: {
    probeIntervalS: 'Probe interval (s)',
    probeTimeoutS: 'Probe timeout (s)',
    failThreshold: 'Fail threshold',
    recoverThreshold: 'Recover threshold',
    grantTtlS: 'Grant TTL (s)',
    usageIntervalS: 'Usage report interval (s)',
    metricRetentionDays: 'Metric retention (days)',
    queueEnabled: 'Queuing',
    webrtcHangupEnabled: 'WebRTC hangup',
    consoleId: 'Console id',
    seedConfigured: 'Seed configured',
    allocatorMode: 'Allocator mode'
  },
  policy: {
    readOnlyNote: 'The scheduling policy is hard-coded and not configurable yet.',
    policy: 'Policy',
    tieBreaker: 'Tie breaker'
  },
  unimpl: {
    stickiness: 'Session stickiness ships in S3',
    canary: 'Canary traffic ratio ships in S3',
    routing: 'Custom routing rules ship in S3'
  },
  cards: {
    title: 'Traffic & Routing',
    total: 'Total tokens',
    perMinute: 'Per minute',
    cost: 'Cost (USD)',
    sticky: 'Sticky hit',
    tokenCard: 'Token usage',
    tokenNotice: 'Scope: tokens from registered machines, summed from heartbeat window deltas.',
    policy: 'Policy',
    rules: 'Routing rules',
    trend: 'Token trend',
    distribution: 'Machine distribution',
    egress: 'Workload egress',
    instances: 'Instances'
  }
}
