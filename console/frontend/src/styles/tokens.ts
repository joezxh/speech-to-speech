// styles/tokens.ts — 设计 token 唯一事实来源（spec §9）。
// 值允许是 `var(--…)` 字符串，因为 voice 的别名本来就这么写。
export const shellTokens = {
  colorBg: '#0b1020',
  colorSurface: '#141a2e',
  colorSurface2: '#1a2138',
  colorSurface3: '#212a45',
  colorBorder: '#232b45',
  colorBorderStrong: '#2e3856',
  colorText: '#e6e8f0',
  colorMuted: '#8b93a7',
  colorFaint: '#5b6478',
  colorAccent: '#5b8cff',
  colorAccentSoft: 'rgba(91, 140, 255, 0.16)',
  colorSuccess: '#35c48a',
  colorWarning: '#e8b339',
  colorDanger: '#f0655c',
  colorPurple: '#a78bfa',
  colorOrange: '#f0a05c',
  colorCyan: '#22d3ee',
  radiusSm: '6px',
  radiusMd: '10px',
  radiusLg: '14px',
  font: "-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', system-ui, sans-serif",
  fontMono: "'Geist Mono', ui-monospace, Consolas, 'Courier New', monospace"
} as const

export const voiceTokens = {
  voiceBg: '#0a0b10',
  voiceSurface: '#13151c',
  voiceSurface2: '#1b1e29',
  voiceSurfaceMix: '#2a2e3c',
  voiceBorder: 'rgba(255, 255, 255, 0.08)',
  voiceBorderStrong: 'rgba(255, 255, 255, 0.16)',
  voiceText: '#f5f6fa',
  voiceDim: 'rgba(245, 246, 250, 0.65)',
  voiceFaint: 'rgba(245, 246, 250, 0.42)',
  voiceAccent: '#8b7dff',
  voiceListening: '#22d3ee',
  voiceProcessing: '#f59e0b',
  voiceError: '#ff6a75',
  voiceReady: '#34d399',
  voiceQueued: '#94a3b8',
  voiceConnecting: '#facd15',
  voiceUser: 'var(--voice-listening)',
  voiceAssistant: 'var(--voice-accent)',
  voiceTool: 'var(--voice-processing)',
  voiceRadius: '14px'
} as const

/** hex 禁令的作用域。每完成一个子项目就把该页文件加进来，只增不减。 */
export const TOKEN_ENFORCED_GLOBS: readonly string[] = [
  'src/styles/**',
  'src/layouts/ConsoleLayout.vue',
  'src/views/LoginView.vue',
  'src/views/OverviewView.vue',
  'src/views/TrafficView.vue',
  'src/components/NotImplemented.vue'
]
