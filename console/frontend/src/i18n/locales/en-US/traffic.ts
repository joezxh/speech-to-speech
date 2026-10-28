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
  }
}
