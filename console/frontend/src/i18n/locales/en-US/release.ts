export default {
  loadFailed: 'Failed to load version list',
  rollbackFailed: 'Rollback failed',
  rollbackConfirmTitle: 'Roll back to v{version}',
  rollbackConfirmContent: 'Rollback writes a new version and restarts the pipeline; in-progress voice sessions will be interrupted.',
  columns: {
    version: 'Version',
    status: 'Status',
    author: 'Author',
    time: 'Time',
    duration: 'Duration',
    note: 'Note',
    actions: 'Actions'
  },
  rolledBackFrom: 'Rolled back from v{version}',
  rollbackToThis: 'Roll back to this version',
  publish: {
    title: 'Publish',
    alertMessage: 'Publishing restarts the pipeline process',
    alertDescription: 'In-progress voice sessions will be interrupted and use the new config after reconnecting.',
    notePlaceholder: 'Change note (written into the version record and audit)',
    publishedMessage: 'v{version} is now live',
    publishedDescription: 'Took {duration}s · pool size {poolSize} · audit {auditId}',
    failed: 'Publish failed',
    close: 'Close',
    cancel: 'Cancel',
    confirm: 'Confirm publish'
  }
}
