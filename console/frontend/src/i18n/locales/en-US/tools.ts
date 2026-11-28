export default {
  page: {
    desc: 'Tools the assistant may call during a conversation.'
  },
  kpi: {
    total: 'Tools',
    on: 'Enabled',
    builtin: 'Built-in',
    custom: 'Custom',
    sub: 'for this account'
  },
  filter: {
    title: 'Tool query',
    kw: 'Keyword',
    kwPh: 'Name / description / id',
    scope: 'Scope',
    on: 'Enabled'
  },
  on: { yes: 'Enabled', no: 'Disabled' },
  new: 'New tool',
  edit: 'Edit',
  copy: 'Copy',
  count: '{n} tools',
  empty: 'No tool matches the query.',
  col: {
    name: 'Name',
    type: 'Type',
    desc: 'Description',
    params: 'Parameters',
    scope: 'Scope',
    on: 'Enabled',
    updated: 'Updated',
    actions: 'Actions'
  },
  type: {
    web_search: 'Web search',
    calendar: 'Calendar',
    weather: 'Weather',
    kb: 'Knowledge base',
    http: 'HTTP'
  },
  scope: { global: 'Global', session: 'Session', tenant: 'Tenant' },
  builtin: 'Built-in',
  customBadge: 'Custom',
  toggle: 'Enable tool {name}',
  form: { new: 'New tool', edit: 'Edit tool · {name}', save: 'Save tool' },
  f: {
    name: 'Name',
    nameHint: 'A stable name shown in the tool list.',
    type: 'Type',
    desc: 'Description',
    endpoint: 'Endpoint',
    method: 'Method',
    scope: 'Scope',
    params: 'Parameters',
    paramsName: 'Parameter',
    paramsType: 'Type',
    paramsReq: 'Required',
    paramsRemove: 'Remove',
    paramsAdd: 'Add parameter'
  },
  warn: {
    builtinTitle: 'Editing a built-in tool',
    builtinBody: '<strong>{name}</strong> is built in. Changes affect the whole cluster until restored.',
    deleteTitle: 'Deleting a built-in tool',
    deleteBody: '<strong>{name}</strong> is built in. All conversations will lose this capability.'
  },
  deleteTitle: 'Delete tool',
  deleteBody: '<strong>{name}</strong> will be deleted and the assistant can no longer call it.',
  err: { name: 'Please enter a tool name.', dup: 'A tool with this name already exists.', endpoint: 'HTTP tools require an endpoint.' },
  toast: { saved: 'Tool {name} saved', created: 'Tool {name} created', deleted: 'Tool {name} deleted', copied: 'Tool {name} copied' },
  loadFailed: 'Failed to load tools',
  saveFailed: 'Failed to save tool',
  deleteFailed: 'Failed to delete tool'
}
