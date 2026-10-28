export default {
  title: '轮次延迟',
  statusAll: '全部状态',
  refresh: '刷新',
  unreadable: '轮次延迟不可读',
  unavailable: '不可用',
  turnsCount: '{count} 条',
  indexLagNote: '{lag}，聚合值不可当现状看',
  empty: '该时间窗没有轮次记录',
  rowsTruncated: '明细已截断，缩小时间范围再看',
  columns: { loggedAt: '记录时间', response: '响应', status: '状态', vadDecision: 'VAD 决策' },
  metric: {
    turns: '轮次',
    states: '四态',
    failureRate: '失败率',
    vadDecision: 'VAD 决策 p50 · p95',
    holdUnavailable: 'hold 不可用'
  },
  format: { notIndexed: '索引尚未建立', lag: '索引落后 {lag} s' }
}
