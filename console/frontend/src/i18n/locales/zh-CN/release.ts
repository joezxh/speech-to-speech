export default {
  loadFailed: '版本列表加载失败',
  rollbackFailed: '回滚失败',
  rollbackConfirmTitle: '回滚到 v{version}',
  rollbackConfirmContent: '回滚会写入一个新版本并重启 pipeline，正在进行的语音会话会中断。',
  columns: {
    version: '版本',
    status: '状态',
    author: '作者',
    time: '时间',
    duration: '耗时',
    note: '说明',
    actions: '操作'
  },
  rolledBackFrom: '回滚自 v{version}',
  rollbackToThis: '回滚到此版本',
  publish: {
    title: '发布',
    alertMessage: '发布会重启 pipeline 进程',
    alertDescription: '正在进行的语音会话会中断，并在重连后使用新配置。',
    notePlaceholder: '变更说明（会写进版本记录与审计）',
    publishedMessage: 'v{version} 已生效',
    publishedDescription: '耗时 {duration}s · 池大小 {poolSize} · 审计 {auditId}',
    failed: '发布失败',
    close: '关闭',
    cancel: '取消',
    confirm: '确认发布'
  }
}
