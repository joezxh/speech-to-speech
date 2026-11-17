/** traffic 页的纯视图模型（Task 15，可单测；公式不留在模板里）。 */

export interface TrendPoint {
  at: string
  input: number
  output: number
  total: number
}

export function splitBar(input: number, output: number): { aPct: number } {
  const total = input + output
  return { aPct: total > 0 ? Math.round((input / total) * 1000) / 10 : 0 }
}

export function trendPath(points: TrendPoint[], w: number, h: number): { line: string; area: string; peak: { x: number; y: number } } {
  if (!points.length) return { line: '', area: '', peak: { x: 0, y: h } }
  const max = Math.max(...points.map((p) => p.total), 1)
  const step = points.length > 1 ? w / (points.length - 1) : 0
  const coordinates = points.map((p, index) => ({
    x: Math.round(index * step * 10) / 10,
    y: Math.round((h - (p.total / max) * h) * 10) / 10,
  }))
  const line = coordinates.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x},${c.y}`).join(' ')
  const area = `${line} L${coordinates[coordinates.length - 1].x},${h} L${coordinates[0].x},${h} Z`
  const peakIndex = coordinates.reduce((best, c, i) => (c.y < coordinates[best].y ? i : best), 0)
  return { line, area, peak: coordinates[peakIndex] }
}

export function egressRoute(kind: string): 'lb' | 'direct' {
  return kind === 'pipeline' ? 'lb' : 'direct'
}
