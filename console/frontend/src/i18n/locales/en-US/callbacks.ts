export default {
  targetsTab: 'Callback Targets',
  logsTab: 'Delivery Logs',
  liveTab: 'Live Subtitles',
  create: 'New Target',
  createTitle: 'New Callback Target',
  editTitle: 'Edit Callback Target',
  batchEnable: 'Enable Selected',
  batchDisable: 'Disable Selected',
  batchDelete: 'Delete Selected',
  batchDeleteConfirm: 'Delete the selected callback targets?',
  deleteConfirm: 'Delete this callback target?',
  test: 'Test',
  testOk: 'Test delivery succeeded',
  testFail: 'Test delivery failed',
  viewDetail: 'Detail',
  logDetail: 'Delivery Detail',
  logStatusFilter: 'Filter by status',
  loadFailed: 'Failed to load callback list',
  edit: 'Edit',
  delete: 'Delete',
  save: 'Save',
  saved: 'Saved',
  saveFailed: 'Failed to save',
  deleted: 'Deleted',
  actions: 'Actions',
  field: {
    name: 'Name',
    type: 'Target Type',
    baseUrl: 'Base URL',
    authType: 'Auth Type',
    authHeaderName: 'Auth Header',
    authToken: 'Credential Token',
    timeoutMs: 'Timeout (ms)',
    retry: 'Retry',
    events: 'Subscribed Events',
    enabled: 'Enabled',
    filters: 'Filters',
    filterSpeakers: 'Only these speakers (optional)',
    filterMinLen: 'Min text length',
    payload: 'Request Payload',
    response: 'Response Snippet',
    error: 'Error'
  },
  hint: {
    javaUrl:
      'Java targets only need the service base URL; the callback path is fixed to /admin-api/ai/meeting/internal/transcript',
    pythonUrl: 'Python targets take the full webhook URL and receive a unified event JSON',
    javaEvents: 'Java targets only support the transcript event'
  },
  log: {
    target: 'Target',
    event: 'Event',
    duration: 'Duration (ms)'
  },
  live: {
    connected: 'Connected to live transcript stream',
    disconnected: 'Not connected (worker not running in this process or disconnected)',
    pause: 'Pause',
    resume: 'Resume',
    clear: 'Clear',
    empty:
      'No transcript events yet; start serve --with-livekitworker and join a room to see subtitles'
  }
}
