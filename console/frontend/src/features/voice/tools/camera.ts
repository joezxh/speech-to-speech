const MAX_EDGE = 768
const FIRST_QUALITY = 0.7
/** SCTP messages above 64 KiB fail on the aiortc peer; leave JSON headroom. */
const DC_BUDGET_CHARS = 60_000
const LADDER: [number, number][] = [
  [MAX_EDGE, FIRST_QUALITY],
  [MAX_EDGE, 0.5],
  [640, 0.45],
  [512, 0.4],
  [448, 0.35],
  [384, 0.3]
]

export async function openCamera(): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 1280 } }, audio: false })
}

/** @returns a data URL, or `''` when the camera has no frame yet. */
export function snapshot(video: HTMLVideoElement): string {
  if (!video.videoWidth || video.videoHeight === 0) return ''
  for (const [edge, quality] of LADDER) {
    const scale = Math.min(1, edge / Math.max(video.videoWidth, video.videoHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(video.videoWidth * scale))
    canvas.height = Math.max(1, Math.round(video.videoHeight * scale))
    const ctx = canvas.getContext('2d')
    if (!ctx) return ''
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
    const dataUrl = canvas.toDataURL('image/jpeg', quality)
    if (dataUrl.length <= DC_BUDGET_CHARS) return dataUrl
  }
  // Last rung still over budget (never seen in practice): send nothing rather
  // than a frame the data channel will refuse.
  return ''
}
