export default {
  status: {
    unknown: 'Not probed',
    online: 'Online',
    degraded: 'Degraded',
    offline: 'Offline',
    draining: 'Draining'
  },
  poll: { every5s: 'Refreshes every 5s', paused: 'Paused', pause: 'Pause', resume: 'Resume' },
  summary: {
    total: 'Total instances',
    statusSplit: 'Online · Degraded · Offline · Draining',
    slots: 'Slots (total/in-use/free)',
    pendingGrants: 'Pending grants'
  },
  columns: {
    instance: 'Instance',
    status: 'Status',
    capacity: 'Capacity',
    slots: 'In use/Free',
    weight: 'Weight',
    probe: 'Probe (ms)',
    actions: 'Actions'
  },
  slotUnit: '{count} slots',
  declaredMismatch: 'Declared capacity differs from actual',
  stuckCount: 'Stuck {count}',
  actions: { trends: 'Trends', drain: 'Drain', undrain: 'Restore', probe: 'Probe' },
  confirm: {
    drainTitle: 'Drain {id}',
    undrainTitle: 'Restore {id}',
    drainContent: 'Once drained, the allocator stops routing new sessions to this machine; already-connected sessions are unaffected.',
    undrainContent: 'Once restored, this machine rejoins allocation (it is still only selected when probed as online/degraded).'
  },
  actionFailed: 'Action failed',
  statusUnreadable: 'Instance status unreadable',
  containerTitle: 'Process',
  fieldStatus: 'Status',
  image: 'Image',
  startedAt: 'Started at',
  detail: 'Detail',
  poolTitle: 'Session pool',
  size: 'Size',
  inUse: 'In use',
  poolUnreachable: 'Session pool unreachable (/v1/pool not responding)',
  columnSession: 'Session',
  trend: {
    selectInstance: 'Select instance',
    refresh: 'Refresh',
    empty: 'No instances to display',
    ariaLabel: 'Instance trend',
    hint: 'Not enough samples yet; the trend line will form shortly',
    legend: { capacity: 'Capacity', free: 'Free', probe: 'Probe time' }
  }
}
