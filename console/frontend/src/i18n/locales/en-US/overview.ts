export default {
  page: {
    title: 'Cluster Overview',
    desc: 'Machines, pipeline instances and recent changes across the cluster.'
  },
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
    errorRate: 'Error rate (5m)',
    sub: {
      machinesOnline: 'Machines online {n}',
      activeSessions: 'Active sessions: {n}',
      stickyHit: 'Sticky hit rate · coming in S3',
      topError: 'Top error source: {source}',
      noSamples: 'No allocation samples in window'
    }
  },
  topology: {
    title: 'Cluster topology — LB → machines → pipeline instances',
    hint: 'click a machine to inspect its deployments and parameters',
    clusterLayer: 'Cluster',
    lbLayer: 'Load balancer',
    machineLayer: 'Machines',
    instanceLayer: 'Pipeline instances',
    empty: 'No machines in this cluster yet — add machines on the Machines page first.',
    poolSessions: '/v1/pool · {n} sessions',
    machineMeta: '{n} instances · {m} online',
    occupancy: '{inUse}/{size}'
  },
  policy: {
    least: 'least-in-use',
    rr: 'round-robin',
    lat: 'least-latency'
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
    empty: 'No clusters yet',
    sectionTitle: 'Clusters — one LB registry per cluster',
    hint: 'A cluster is scoped by its load-balancing registry; machines register and get scheduled through it.'
  },
  status: {
    healthy: 'Healthy',
    unhealthy: 'Unhealthy',
    ok: 'Healthy',
    warn: 'Degraded',
    draining: 'Draining',
    bad: 'Fault',
    muted: 'Pending'
  },
  actions: {
    create: 'Add cluster',
    switchTo: 'Enter',
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
    lb: 'Load balancer (unified entry)',
    machine: 'Machine',
    instance: 'Pipeline instance',
    online: 'Online',
    degraded: 'Degraded',
    offline: 'Offline',
    muted: 'No data',
    ok: 'Healthy',
    warn: 'Degraded',
    draining: 'Draining',
    bad: 'Fault',
    flow: 'Animated edge = active traffic'
  },
  events: {
    title: 'Recent cluster events',
    hint: 'full history in Audit Log',
    at: 'Time',
    actor: 'Actor',
    role: 'Role',
    category: 'Category',
    action: 'Action',
    target: 'Target',
    result: 'Result',
    ok: 'OK',
    error: 'Failed',
    empty: 'No cluster operations yet',
    cat: {
      cluster: 'Cluster',
      param: 'Params',
      deploy: 'Deploy',
      release: 'Release',
      voice: 'Voice',
      machine: 'Machine',
      access: 'Access',
      other: 'Other'
    }
  },
  toast: {
    created: 'Cluster {name} created.',
    updated: 'Cluster {name} updated.',
    deleted: 'Cluster {name} removed.',
    switched: 'Switched to cluster {name}.',
    last: 'At least one cluster must remain.',
    blocked: '{name} still hosts {n} machine(s) — remove them first.',
    serverError: 'Operation failed: {message}',
    switchFailed: 'Switching cluster failed: {message}'
  }
}
