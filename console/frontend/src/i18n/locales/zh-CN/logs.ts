export default {
  title: '日志',
  levelsAll: '全部级别',
  rangeFrom: '起始时间',
  rangeTo: '结束时间',
  searchPlaceholder: '关键字（大小写不敏感）',
  followTail: '尾部跟随',
  refresh: '刷新',
  analyze: '分析',
  rotated: '日志已轮转，已从头重读',
  loading: '读取中…',
  empty: '该时间窗没有日志行',
  scanned: '{files} 个文件 / {bytes} 字节',
  truncated: '已截断，缩小时间范围再看',
  confidence: { high: '高', medium: '中', low: '低' },
  sent: {
    lines: '已送入 {n} 行',
    approxTokens: '约 {n}k tokens（估算）',
    dropped: '已截断 {n} 行',
    turns: '附带 {n} 条轮次'
  },
  analysis: {
    title: '日志归纳',
    retry: '重试',
    errorsBlock: '错误签名',
    criticalBlock: '关键影响',
    criticalEmpty: '模型未指出关键影响',
    rootCausesBlock: '根因假设',
    rootCausesEmpty: '模型未给出根因',
    actionsBlock: '建议动作',
    actionsEmpty: '模型未给出动作',
    confidence: '置信度 {value}',
    expectedEffect: '预期效果：{value}',
    analyzing: '归纳中…',
    notAnalyzed: '尚未分析：点「分析」把当前日志窗口交给回环模型',
    columns: { signature: '签名', count: '次数', firstSeen: '首次出现', lastSeen: '最后出现', level: '级别' }
  }
}
