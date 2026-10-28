export default {
  title: 'Logs',
  levelsAll: 'All levels',
  rangeFrom: 'Start time',
  rangeTo: 'End time',
  searchPlaceholder: 'Keyword (case-insensitive)',
  followTail: 'Follow tail',
  refresh: 'Refresh',
  analyze: 'Analyze',
  rotated: 'Logs rotated; re-read from the beginning',
  loading: 'Loading…',
  empty: 'No log lines in this time window',
  scanned: '{files} file(s) / {bytes} bytes',
  truncated: 'Truncated — narrow the time range and look again',
  confidence: { high: 'High', medium: 'Medium', low: 'Low' },
  sent: {
    lines: '{n} line(s) fed in',
    approxTokens: '~{n}k tokens (estimated)',
    dropped: 'truncated {n} line(s)',
    turns: 'with {n} turn row(s)'
  },
  analysis: {
    title: 'Log summary',
    retry: 'Retry',
    errorsBlock: 'Error signatures',
    criticalBlock: 'Key impacts',
    criticalEmpty: 'The model flagged no key impacts',
    rootCausesBlock: 'Root-cause hypotheses',
    rootCausesEmpty: 'The model gave no root causes',
    actionsBlock: 'Suggested actions',
    actionsEmpty: 'The model gave no actions',
    confidence: 'Confidence {value}',
    expectedEffect: 'Expected effect: {value}',
    analyzing: 'Summarizing…',
    notAnalyzed: 'Not analyzed yet: click “Analyze” to hand the current log window to the loopback model',
    columns: { signature: 'Signature', count: 'Count', firstSeen: 'First seen', lastSeen: 'Last seen', level: 'Level' }
  }
}
