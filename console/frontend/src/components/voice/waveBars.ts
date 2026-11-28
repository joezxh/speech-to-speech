/**
 * 片段条波形高度（原型 `waveBars` 同算法移植，console-refactor-demo.html:3793）：
 * FNV-1a 哈希 seed → LCG 逐根推进，高度 3-11px。同 seed 恒等，换 seed 即换波形。
 * LCG 保持原型写法（float64 乘法后 >>>0），保证与原型视觉逐字节一致。
 */
export function waveBars(seed: string, n = 12): number[] {
  const text = String(seed)
  let h = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    h ^= text.charCodeAt(i)
    h = Math.imul(h, 16777619) >>> 0
  }
  const bars: number[] = []
  for (let i = 0; i < n; i += 1) {
    h = (h * 1103515245 + 12345) >>> 0
    bars.push(3 + (h % 9))
  }
  return bars
}
