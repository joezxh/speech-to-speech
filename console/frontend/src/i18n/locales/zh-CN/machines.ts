export default {
  status: {
    unknown: '未探测',
    online: '在线',
    degraded: '降级',
    offline: '离线',
    draining: '摘除中',
    ok: '在线',
    pending_register: '待接入',
    unreachable: '不可达'
  },
  poll: { every5s: '每 5s 刷新', paused: '已暂停', pause: '暂停', resume: '继续' },
  summary: {
    total: '实例总数',
    statusSplit: '在线 · 降级 · 离线 · 摘除',
    slots: '槽位（总/占/闲）',
    pendingGrants: '待领取授权'
  },
  slotUnit: '{count} 槽',
  declaredMismatch: '声明容量与实际不符',
  stuckCount: '卡 {count}',
  hostFilter: '仅显示机器 {host} 上的实例',
  trend: {
    selectInstance: '选择实例',
    refresh: '刷新',
    empty: '没有可展示的实例',
    ariaLabel: '实例趋势',
    hint: '采样点不足，趋势线稍后成形',
    legend: { capacity: '容量', free: '空闲', probe: '探测耗时' }
  },
  // Task 12（原型对齐）：机器管理页（§4.5）
  admin: {
    alertStale: '心跳超时（>60s）：{ids}',
    searchPlaceholder: '搜索机器 ID / 地址',
    newMachine: '新增机器',
    autoRegister: '自动注册',
    columns: {
      machine: '机器',
      role: '角色',
      gpu: 'GPU',
      state: '状态',
      registry: '注册',
      agentVersion: 'Agent 版本',
      lastSeen: '最后心跳',
      workloads: '负载',
      vram: '显存水位',
      cluster: '集群',
      addr: '地址',
      actions: '操作'
    },
    registry: { manual: '手动', auto: '自动' },
    workloadSum: '{n} 个负载 · 显存 {used}/{total} GB',
    workloadCols: {
      kind: '类型',
      model: '模型',
      listen: '监听地址',
      publicAddr: '对外地址',
      vramGb: '显存'
    },
    empty: '还没有机器。点「新增机器」建档，或让机器端 agent 自动注册。',
    confirmDelete: '删除机器 {id}？负载清单与实例绑定一并清除。',
    deleteFailed: '删除失败'
  },
  test: {
    title: '注册测试（三步）',
    simulate: '模拟失败（agent 不来）',
    start: '测试',
    stepOk: '通过',
    stepRunning: '等待',
    stepFail: '失败',
    registerCode: '注册码',
    ok: '三步全部通过，机器已接入'
  },
  form: {
    createTitle: '新增机器',
    editTitle: '编辑机器',
    machineId: '机器 ID',
    addr: '地址',
    role: '角色',
    gpu: 'GPU 型号',
    gpuTotalGb: '显存总量 (GB)',
    clusterId: '集群',
    workloadsTitle: '负载声明',
    pipelineLocked: 'pipeline 负载由 agent 探测自动补全，无需手工声明。',
    autoDiscovered: 'agent 探测补全',
    kind: '类型',
    model: '模型',
    addWorkload: '加负载',
    created: '建档成功，注册码：',
    codeOnce: '注册码明文只显示这一次，请立即复制。',
    submit: '建档',
    save: '保存',
    cancel: '取消',
    edit: '编辑',
    delete: '删除'
  }
}
