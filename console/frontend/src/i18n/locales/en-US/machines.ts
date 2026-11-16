export default {
  status: {
    unknown: 'unprobed',
    online: 'online',
    degraded: 'degraded',
    offline: 'offline',
    draining: 'draining',
    ok: 'online',
    pending_register: 'pending',
    unreachable: 'unreachable'
  },
  poll: { every5s: 'refresh every 5s', paused: 'paused', pause: 'Pause', resume: 'Resume' },
  summary: {
    total: 'Instances',
    statusSplit: 'online · degraded · offline · draining',
    slots: 'Slots (total/used/free)',
    pendingGrants: 'Pending grants'
  },
  slotUnit: '{count} slots',
  declaredMismatch: 'declared capacity mismatch',
  stuckCount: '{count} stuck',
  hostFilter: 'Showing instances on machine {host} only',
  trend: {
    selectInstance: 'Select instance',
    refresh: 'Refresh',
    empty: 'No instance to display',
    ariaLabel: 'instance trends',
    hint: 'not enough samples yet, the trend line will build up',
    legend: { capacity: 'capacity', free: 'free', probe: 'probe time' }
  },
  // Task 12 (prototype alignment): machine management page (§4.5)
  admin: {
    alertStale: 'Heartbeat stale (>60s): {ids}',
    searchPlaceholder: 'Search machine ID / address',
    newMachine: 'New machine',
    autoRegister: 'Auto register',
    columns: {
      machine: 'Machine',
      role: 'Role',
      gpu: 'GPU',
      state: 'State',
      registry: 'Registry',
      agentVersion: 'Agent version',
      lastSeen: 'Last heartbeat',
      workloads: 'Workloads',
      vram: 'VRAM',
      cluster: 'Cluster',
      addr: 'Address',
      actions: 'Actions'
    },
    registry: { manual: 'manual', auto: 'auto' },
    workloadSum: '{n} workloads · VRAM {used}/{total} GB',
    workloadCols: {
      kind: 'Kind',
      model: 'Model',
      listen: 'Listen',
      publicAddr: 'Public address',
      vramGb: 'VRAM'
    },
    empty: 'No machines yet. Create one, or let the machine-side agent auto register.',
    confirmDelete: 'Delete machine {id}? Its workload list and instance binding go with it.',
    deleteFailed: 'Delete failed'
  },
  test: {
    title: 'Register test (3 steps)',
    simulate: 'Simulate failure (agent never comes)',
    start: 'Test',
    stepOk: 'pass',
    stepRunning: 'waiting',
    stepFail: 'fail',
    registerCode: 'Register code',
    ok: 'All three steps passed, the machine is enrolled'
  },
  form: {
    createTitle: 'New machine',
    editTitle: 'Edit machine',
    machineId: 'Machine ID',
    addr: 'Address',
    role: 'Role',
    gpu: 'GPU model',
    gpuTotalGb: 'VRAM total (GB)',
    clusterId: 'Cluster',
    workloadsTitle: 'Workload declaration',
    pipelineLocked: 'The pipeline workload is auto-discovered by the agent; no manual entry needed.',
    autoDiscovered: 'agent-discovered',
    kind: 'Kind',
    model: 'Model',
    addWorkload: 'Add workload',
    created: 'Created. Register code:',
    codeOnce: 'The register code is shown once — copy it now.',
    submit: 'Create',
    save: 'Save',
    cancel: 'Cancel',
    edit: 'Edit',
    delete: 'Delete'
  }
}
