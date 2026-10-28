export interface TrafficSettings {
  allocatorMode: 'off' | 'local'
  consoleId: string
  seedConfigured: boolean
  probeIntervalS: number
  probeTimeoutS: number
  failThreshold: number
  recoverThreshold: number
  grantTtlS: number
  usageIntervalS: number
  metricRetentionDays: number
  queueEnabled: boolean
  webrtcHangupEnabled: boolean
  scheduling: { policy: string; configurable: boolean; tieBreaker: string }
  unimplemented: string[]
}
