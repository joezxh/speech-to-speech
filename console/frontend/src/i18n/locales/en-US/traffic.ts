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
    policy: 'Scheduling & session policy',
    rules: 'Routing rules',
    trend: 'Token trend',
    distribution: 'Token by machine',
    egress: 'Workload egress',
    instances: 'Instances',
    backends: 'Model API call stats'
  },
  kpi: {
    p95ttft: 'P95 TTFT',
    p95ttftSub: 'fastest machine {machine}',
    activeSessions: 'Active sessions',
    instancesSub: 'instances: {n}',
    routeHit: 'Route hit rate',
    stickySub: 'sticky TTL {ttl}s',
    errRate: 'Error rate',
    topErrSub: 'top error instance: {instance}'
  },
  token: {
    windowTotal: '{win} total tokens',
    prompt: 'Input (prompt)',
    completion: 'Output (completion)',
    rate: 'Rate / min',
    quotaSub: 'water {pct}% · quota {quota}/min',
    splitRatio: 'Input/output split',
    promptLabel: 'input',
    completionLabel: 'output',
    costLine: 'Cost ({win}) ≈ ${cost}',
    priceNote: 'Prices: in ${in}/Mtok · out ${out}/Mtok (env configured)',
    perSession: 'Tokens per session',
    perSessionSub: '{n} tokens · ~{turns} turns/session'
  },
  policyCard: {
    scheduling: 'Scheduling policy',
    stickyTtl: 'Session stickiness TTL',
    healthInterval: 'Health check interval',
    evict: 'Eviction threshold',
    canary: 'Canary ratio',
    seconds: 's',
    failures: '{n} failures'
  },
  rules: {
    colRule: 'Rule',
    colDest: 'Destination',
    colTokens: 'Window tokens',
    colRate: 'Rate / min',
    colShare: 'Share',
    noMatched: 'No routing decisions in this window'
  },
  distribution: {
    colMachine: 'Machine',
    colTokens: 'Tokens',
    colShare: 'Share'
  },
  egress: {
    colKind: 'Kind',
    colEngine: 'Engine',
    colHosts: 'Hosts',
    colLoad: 'Load',
    colTokens: 'Tokens',
    colVram: 'VRAM',
    colRoute: 'Routing',
    routeLb: 'Load balancer · sticky sessions',
    routeDirect: 'Direct'
  },
  backends: {
    byKind: 'By kind',
    byModel: 'By engine / model',
    byMachine: 'By machine',
    trend: 'Calls trend',
    colKind: 'Kind',
    colCalls: 'Calls',
    colErrors: 'Errors',
    colAvgMs: 'Avg latency',
    colEngine: 'Engine',
    colModel: 'Model',
    colMachine: 'Machine',
    colShare: 'Share',
    noData: 'No calls in this window (requires an agent that reports the backends{} section)'
  },
  instances: {
    colInstance: 'Instance',
    colMachine: 'Machine',
    colLoad: 'Load',
    colRpm: 'rpm',
    colTtft: 'TTFT',
    colRtf: 'RTF',
    colErr: 'Error rate',
    colStatus: 'Status'
  },
  chart: {
    peak: 'peak',
    now: 'now'
  },
  common: {
    effective: 'effective',
    default: 'default',
    empty: 'No data'
  }
}
