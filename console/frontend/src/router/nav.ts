export type ShellFace = 'console' | 'voice'

/** 语音对话组里的「打开浮层」项——它们不是路由。 */
export type VoiceOverlay = 'history' | 'tools' | 'settings'

/** 侧栏图标：对应 index.html 里 `<symbol>` 去 `i-` 前缀。 */
export type NavIcon =
  | 'sliders' | 'wave' | 'history' | 'server' | 'check' | 'target' | 'wrench' | 'gear'
  | 'layers' | 'signal' | 'cpu'

export interface NavMeta {
  navGroup: 'lb' | 'front' | 'ops'
  navKey: string
  navIcon: NavIcon
  navOrder: number
}

/** demo 前台三个 overlay 不是路由，无法从路由表派生，单独保留常量表。 */
export const frontOverlays: Array<{ overlay: VoiceOverlay; navKey: string; navIcon: NavIcon; navOrder: number }> = [
  { overlay: 'history', navKey: 'nav.history', navIcon: 'history', navOrder: 20 },
  { overlay: 'tools', navKey: 'nav.tools', navIcon: 'wrench', navOrder: 30 },
  { overlay: 'settings', navKey: 'nav.settings', navIcon: 'gear', navOrder: 40 }
]
