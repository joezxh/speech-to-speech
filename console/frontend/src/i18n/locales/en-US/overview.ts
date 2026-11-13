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
    status: 'Publish status',
    allocatorMode: 'Allocator mode',
    consoleId: 'Console instance',
    dbHealth: 'Database health',
    pipelineHealth: 'Pipeline health',
    instancesRegistered: 'Registered instances',
    seedConfigured: 'Seed config',
    secretsConsistent: 'Secret consistency',
    errorRate: 'Error rate (5m)'
  },
  topology: {
    title: 'Cluster topology',
    clusterLayer: 'Cluster',
    lbLayer: 'Load balancer',
    machineLayer: 'Machines',
    instanceLayer: 'Pipeline instances'
  },
  policy: {
    least: 'Least sessions',
    rr: 'Round robin',
    lat: 'Lowest latency'
  },
  table: {
    cluster: 'Cluster',
    registry: 'Registry',
    policy: 'Policy',
    machines: 'Machines',
    instances: 'Instances',
    status: 'Status',
    actions: 'Actions',
    current: 'Current',
    empty: 'No clusters yet'
  },
  status: {
    healthy: 'Healthy',
    unhealthy: 'Unhealthy'
  },
  actions: {
    create: 'New cluster',
    switchTo: 'Switch',
    edit: 'Edit',
    delete: 'Delete'
  },
  form: {
    createTitle: 'New cluster',
    editTitle: 'Edit cluster',
    name: 'Name',
    registry: 'Registry',
    policy: 'Policy',
    note: 'Note',
    nameRequired: 'Required · name',
    nameInvalid: 'Name must be 2–40 lowercase letters, digits or hyphens, starting with a letter or digit',
    registryRequired: 'Required · registry',
    registryInvalid: 'Registry must be scheme://host:port or host:port (2–5 digit port)',
    policyInvalid: 'Policy must be one of least / rr / lat',
    noteTooLong: 'Note must be 255 characters or fewer'
  },
  confirm: {
    deleteContent: 'Delete cluster {name}? This action is audited.'
  },
  legend: {
    title: 'Legend',
    cluster: 'Cluster',
    lb: 'Load balancer',
    machine: 'Machine',
    instance: 'Pipeline instance',
    online: 'Online',
    degraded: 'Degraded',
    offline: 'Offline',
    muted: 'No data'
  },
  events: {
    title: 'Recent events',
    at: 'Time',
    actor: 'Actor',
    role: 'Role',
    action: 'Action',
    target: 'Target',
    result: 'Result',
    ok: 'OK',
    error: 'Failed',
    empty: 'No cluster operations yet'
  }
}