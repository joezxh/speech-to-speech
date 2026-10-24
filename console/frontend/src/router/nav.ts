export type ShellFace = 'console' | 'voice'

/** 对话页侧栏里四个「打开浮层」的项——它们不是路由，旧页也从来没给它们路由。 */
export type VoiceOverlay = 'history' | 'tools' | 'settings' | 'about'

export interface NavItem {
  /** 路由名（自 Task 12/13 注册）；`action` 项没有路由。 */
  name?: string
  /** 只在 voice 面出现：由 `ConsoleLayout` 写进 `stores/shell` 的 `voiceOverlay`。 */
  action?: VoiceOverlay
  label: string
}

export interface NavGroup {
  face: ShellFace
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
    label: '部署',
    items: [
      { name: 'params', label: '参数' },
      { name: 'voices', label: '音色库' },
      { name: 'sessions', label: '活跃会话' },
      { name: 'versions', label: '版本' },
      { name: 'instances', label: '实例' },
      { name: 'audit', label: '审计' }
    ]
  },
  {
    face: 'voice',
    label: '对话',
    items: [
      { name: 'voice', label: 'Voice' },
      { action: 'history', label: 'History' },
      { action: 'tools', label: 'Tools' },
      { action: 'settings', label: 'Settings' },
      { action: 'about', label: 'About' }
    ]
  }
]

export function navItemsFor(face: ShellFace): NavItem[] {
  return NAV_GROUPS.find((group) => group.face === face)?.items ?? []
}
