export default {
  page: {
    desc: '通话中助理可调用的工具。'
  },
  kpi: {
    total: '工具总数',
    on: '已启用',
    builtin: '内置',
    custom: '自定义',
    sub: '当前账号'
  },
  filter: {
    title: '工具查询',
    kw: '关键字',
    kwPh: '名称 / 描述 / ID',
    scope: '作用域',
    on: '启用状态'
  },
  on: { yes: '已启用', no: '已停用' },
  new: '新建工具',
  edit: '编辑',
  copy: '复制',
  count: '共 {n} 个工具',
  empty: '没有符合条件的工具。',
  col: {
    name: '名称',
    type: '类型',
    desc: '描述',
    params: '参数',
    scope: '作用域',
    on: '启用',
    updated: '更新时间',
    actions: '操作'
  },
  type: {
    web_search: '联网搜索',
    calendar: '日历',
    weather: '天气',
    kb: '知识库',
    http: 'HTTP 工具'
  },
  scope: { global: '全局', session: '会话', tenant: '租户' },
  builtin: '内置',
  customBadge: '自定义',
  toggle: '启用工具 {name}',
  form: { new: '新建工具', edit: '编辑工具 · {name}', save: '保存工具' },
  f: {
    name: '名称',
    nameHint: '工具列表中展示的稳定名称。',
    type: '类型',
    desc: '描述',
    endpoint: '接口地址',
    method: '方法',
    scope: '作用域',
    params: '参数',
    paramsName: '参数名',
    paramsType: '类型',
    paramsReq: '必填',
    paramsRemove: '移除',
    paramsAdd: '添加参数'
  },
  warn: {
    builtinTitle: '正在编辑内置工具',
    builtinBody: '<strong>{name}</strong> 是内置工具。修改后集群内所有会话都会受影响，直到恢复为止。',
    deleteTitle: '正在删除内置工具',
    deleteBody: '<strong>{name}</strong> 是内置工具。删除后集群内所有会话都将失去该能力。'
  },
  deleteTitle: '删除工具',
  deleteBody: '<strong>{name}</strong> 将被删除，助理将无法再调用该工具。',
  err: { name: '请填写工具名称。', dup: '已存在同名工具。', endpoint: 'HTTP 工具必须填写接口地址。' },
  toast: { saved: '工具 {name} 已保存', created: '工具 {name} 已创建', deleted: '工具 {name} 已删除', copied: '工具 {name} 已复制' },
  loadFailed: '工具加载失败',
  saveFailed: '工具保存失败',
  deleteFailed: '工具删除失败'
}
