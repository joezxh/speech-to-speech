export default {
  tabLog: 'Session log',
  tabRoute: 'Routes',
  backToList: 'Back to list',
  openHistory: 'Open history page',
  noRecords: 'No session records yet',
  noRouteLogs: 'No route logs yet',
  untitled: 'Untitled session',
  turnsBadge: '{n} turns',
  historyDesc: 'One record per finished call, auto-saved. View, edit or delete anytime.',
  deleteRecord: 'Delete record',
  deleteTitle: 'Delete session record',
  deleteBody: 'This cannot be undone. Delete this record and all of its messages?',
  messageSearch: 'Search message content',
  clearMessages: 'Clear messages',
  clearTitle: 'Clear messages',
  clearBody: 'Clear all messages of this record? The record itself is kept.',
  deleteMsgTitle: 'Delete message',
  deleteMsgBody: 'Delete this message?',
  routeCol: {
    time: 'Time',
    instance: 'Instance',
    matched: 'Matched',
    tokens: 'In/Out tokens'
  },
  filterAllStates: 'All states',
  searchPlaceholder: 'Search title / note / session ID',
  batchDeleteTitle: 'Batch delete',
  batchDeleteBody: 'Delete {n} selected session records?',
  batchDelete: 'Delete selected ({n})',
  kpi: {
    total: 'Total sessions',
    done: 'Finished',
    failed: 'Failed',
    turns: 'Turns',
    avgDuration: 'Avg duration'
  },
  col: {
    title: 'Title',
    state: 'State',
    node: 'Instance / node',
    turns: 'Turns',
    duration: 'Duration',
    ttfa: 'TTFA',
    createdAt: 'Created'
  },
  hist: {
    title: 'Session History',
    kpi: {
      total: 'Total sessions',
      done: 'Finished',
      failed: 'Failed',
      avgTtfa: 'Avg TTFT',
      sub: 'on this cluster'
    },
    filter: {
      title: 'Session query',
      kw: 'Keyword',
      kwPh: 'ID / instance / node / transcript',
      state: 'State',
      all: 'All',
      inst: 'Instance',
      range: 'Range'
    },
    range: {
      today: 'Today',
      '24h': 'Last 24h',
      '7d': 'Last 7 days'
    },
    query: 'Query',
    reset: 'Reset',
    count: '{n} sessions',
    sel: { count: '{n} selected' },
    deleteSelected: 'Delete selected',
    col: {
      id: 'Session ID',
      start: 'Started',
      route: 'Instance · node',
      excerpt: 'Transcript',
      turns: 'Turns',
      msgs: 'Messages',
      dur: 'Voice',
      ttft: 'TTFT',
      actions: 'Actions'
    },
    viewMessages: 'Messages',
    empty: 'No session matches the query.',
    prev: 'Previous',
    next: 'Next',
    pageOf: 'Page {n} of {m}',
    msg: {
      title: 'Session messages',
      count: '{n} messages',
      kw: 'Search in the messages',
      clear: 'Clear all messages',
      noMatch: 'No message matches.'
    },
    midCol: 'Message ID',
    roleCol: 'Role',
    typeCol: 'Type',
    contentCol: 'Content',
    atCol: 'At',
    statusCol: 'Status',
    role: { caller: 'Caller', bot: 'Bot' },
    type: { asr: 'ASR', reply: 'Reply' },
    flag: { ok: 'ok', fail: 'fail' }
  }
}
