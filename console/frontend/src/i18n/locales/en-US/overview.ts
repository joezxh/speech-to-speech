export default {
  kpi: {
    machines: 'Machines',
    pipelineInstances: 'Pipeline instances',
    online: 'Online',
    degraded: 'Degraded',
    offline: 'Offline',
    draining: 'Draining',
    activeSessions: 'Active sessions',
    freeSlots: 'Free slots',
    totalSlots: 'Total slots',
    pendingGrants: 'Pending grants',
    clusterAlerts: 'Cluster alerts',
    catalogCommit: 'Catalog commit',
    version: 'Live version',
    status: 'Release status',
    allocatorMode: 'Allocator mode',
    consoleId: 'Console id',
    dbHealth: 'Database health',
    pipelineHealth: 'Pipeline health',
    instancesRegistered: 'Registered instances',
    seedConfigured: 'Seed configured',
    secretsConsistent: 'Secrets consistent'
  },
  topology: {
    lbLayer: 'Load balancer layer',
    pipelineLayer: 'Pipeline instance layer',
    machineLayer: 'Machine layer'
  },
  unimpl: {
    machines: 'Machine-level topology ships in S2',
    errorRate: 'Error-rate tracking ships in S3',
    stickiness: 'Session stickiness hit rate ships in S3',
    p95ttft: 'P95 time-to-first-token ships in S3',
    training: 'Training job view is out of scope for this phase'
  }
}
