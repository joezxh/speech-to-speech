export default {
  status: {
    unknown: '未探测',
    online: '在线',
    degraded: '降级',
    offline: '离线',
    draining: '摘除中'
  },
  poll: { every5s: '每 5s 刷新', paused: '已暂停', pause: '暂停', resume: '继续' },
  summary: {
    total: '实例总数',
    statusSplit: '在线 · 降级 · 离线 · 摘除',
    slots: '槽位（总/占/闲）',
    pendingGrants: '待领取授权'
  },
  columns: {
    instance: '实例',
    status: '状态',
    capacity: '容量',
    slots: '占用/空闲',
    weight: '权重',
    probe: '探测(ms)',
    actions: '操作'
  },
  slotUnit: '{count} 槽',
  declaredMismatch: '声明容量与实际不符',
  stuckCount: '卡 {count}',
  actions: { trends: '趋势', drain: '摘除', undrain: '恢复', probe: '探测' },
  confirm: {
    drainTitle: '摘除 {id}',
    undrainTitle: '恢复 {id}',
    drainContent: '摘除后分配器不再把新会话派给这台，已连接的会话不受影响。',
    undrainContent: '恢复后这台重新参与分配（仍需探测为在线/降级才会被选中）。'
  },
  actionFailed: '操作失败',
  statusUnreadable: '实例状态不可读',
  containerTitle: '进程',
  fieldStatus: '状态',
  image: '镜像',
  startedAt: '启动时间',
  detail: '详情',
  poolTitle: '会话池',
  size: '大小',
  inUse: '占用',
  poolUnreachable: '会话池不可达（/v1/pool 无响应）',
  columnSession: '会话'
}
