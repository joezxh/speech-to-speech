export default {
  title: 'Turn latency',
  statusAll: 'All statuses',
  refresh: 'Refresh',
  unreadable: 'Turn latency is unreadable',
  unavailable: 'Unavailable',
  turnsCount: '{count} row(s)',
  indexLagNote: '{lag}; aggregate values should not be read as current state',
  empty: 'No turn rows in this time window',
  rowsTruncated: 'Details truncated — narrow the time range and look again',
  columns: { loggedAt: 'Logged at', response: 'Response', status: 'Status', vadDecision: 'VAD decision' },
  metric: {
    turns: 'Turns',
    states: 'States',
    failureRate: 'Failure rate',
    vadDecision: 'VAD decision p50 · p95',
    holdUnavailable: 'hold unavailable'
  },
  format: { notIndexed: 'Index not built yet', lag: 'Index lagging by {lag} s' }
}
