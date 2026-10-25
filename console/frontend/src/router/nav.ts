export type ShellFace = 'console' | 'voice'

/** 对话页侧栏里四个「打开浮层」的项——它们不是路由，旧页也从来没给它们路由。 */
export type VoiceOverlay = 'history' | 'tools' | 'settings' | 'about'

/**
 * 侧栏图标：值是 `index.html` 里 `<symbol>` 的 id 去掉 `i-` 前缀。
 * 侧栏折叠成 56px 后只剩这枚图标，所以每一项都必须有。
 */
export type NavIcon = 'sliders' | 'wave' | 'chat' | 'history' | 'server' | 'check' | 'target' | 'wrench' | 'gear' | 'info'

export interface NavItem {
  /** 路由名（自 Task 12/13 注册）；`action` 项没有路由。 */
  name?: string
  /** 只在 voice 面出现：由 `ConsoleLayout` 写进 `stores/shell` 的 `voiceOverlay`。 */
  action?: VoiceOverlay
  label: string
  icon: NavIcon
}

export interface NavGroup {
  face: ShellFace
  /** 分组标题，画在侧栏第一项之上；折叠态隐藏。 */
  label: string
  items: NavItem[]
}

/**
 * 侧栏两组，按 `route.meta.face` 只渲染其中一组（§3.2.4）。
 * `ConsoleLayout` 用 `router.hasRoute(item.name)` 过滤尚未注册的路由，所以这张表
 * 可以在视图建齐之前就写完整。
 */
export const NAV_GROUPS: NavGroup[] = [
  {
    face: 'console',
    label: '运维台 · console 面',
    items: [
      { name: 'params', label: '参数', icon: 'sliders' },
      { name: 'voices', label: '音色库', icon: 'wave' },
      { name: 'sessions', label: '活跃会话', icon: 'chat' },
      { name: 'versions', label: '版本', icon: 'history' },
      { name: 'instances', label: '实例', icon: 'server' },
      { name: 'audit', label: '审计', icon: 'check' }
    ]
  },
  {
    face: 'voice',
    label: '语音对话 · voice 面',
    items: [
      { name: 'voice', label: '对话', icon: 'target' },
      { action: 'history', label: '会话历史', icon: 'chat' },
      { action: 'tools', label: '工具', icon: 'wrench' },
      { action: 'settings', label: '设置', icon: 'gear' },
      { action: 'about', label: '关于', icon: 'info' }
    ]
  }
]

export function navGroupFor(face: ShellFace): NavGroup | undefined {
  return NAV_GROUPS.find((group) => group.face === face)
}

export function navItemsFor(face: ShellFace): NavItem[] {
  return navGroupFor(face)?.items ?? []
}
