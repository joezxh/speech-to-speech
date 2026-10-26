export type ShellFace = 'console' | 'voice'

/** 语音对话组里的「打开浮层」项——它们不是路由，旧页也从来没给它们路由。 */
export type VoiceOverlay = 'history' | 'tools' | 'settings'

/**
 * 侧栏图标：值是 `index.html` 里 `<symbol>` 的 id 去掉 `i-` 前缀。
 * 侧栏折叠成 56px 后只剩这枚图标，所以每一项都必须有。
 */
export type NavIcon = 'sliders' | 'wave' | 'chat' | 'history' | 'server' | 'check' | 'target' | 'trend' | 'wrench' | 'gear'

export interface NavItem {
  /** 路由名（自 Task 12/13 注册）；`action` 项没有路由。 */
  name?: string
  /** 语音对话组的浮层动作：点击时跳到对话页并打开对应浮层。 */
  action?: VoiceOverlay
  label: string
  icon: NavIcon
}

export interface NavGroup {
  /** 稳定标识，用作 v-for key。 */
  key: string
  /** 分组标题，画在该组第一项之上；折叠态隐藏。 */
  label: string
  items: NavItem[]
}

/**
 * 对齐 `console/design/console-preview.html`：同一个侧栏里纵向呈现多个菜单组，
 * 各自带分组标题，模块归到对应组下。`对话`（路由）与它的三个浮层动作在语音组，
 * 运维台各页在运维组，实例管理与趋势在负载均衡组。各组始终同时显示，不再按
 * `route.meta.face` 二选一。
 * `ConsoleLayout` 用 `router.hasRoute(item.name)` 过滤尚未注册的路由，所以这张表
 * 可以在视图建齐之前就写完整。
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    key: 'voice',
    label: '语音对话',
    items: [
      { name: 'voice', label: '对话', icon: 'target' },
      { action: 'history', label: '会话历史', icon: 'chat' },
      { action: 'tools', label: '工具', icon: 'wrench' },
      { action: 'settings', label: '设置', icon: 'gear' }
    ]
  },
  {
    key: 'console',
    label: '运维台',
    items: [
      { name: 'params', label: '参数', icon: 'sliders' },
      { name: 'voices', label: '音色库', icon: 'wave' },
      { name: 'sessions', label: '会话', icon: 'chat' },
      { name: 'versions', label: '版本', icon: 'history' },
      { name: 'audit', label: '审计', icon: 'check' }
    ]
  },
  {
    key: 'lb',
    label: '负载均衡',
    items: [
      { name: 'instances', label: '实例管理', icon: 'server' },
      { name: 'instance-trends', label: '趋势', icon: 'trend' }
    ]
  }
]

export function navGroups(): NavGroup[] {
  return NAV_GROUPS
}
