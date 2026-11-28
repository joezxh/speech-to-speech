import { ref } from 'vue'
import type { Ref } from 'vue'

import { fetchSessionClipUrl } from '@/api/sessionRecords'

/** 一次片段播放请求：内存 blob URL 直接播；否则按 (recordId, clipId) 拉字节。 */
export interface ClipSource {
  /** 组件内的稳定键（卡片 key + 行序 / 片段 id），broken/playing 状态按它记账。 */
  key: string
  /** live 行的内存 blob URL（voice store 所有，不在这里 revoke）。 */
  audioUrl?: string | null
  recordId?: number
  clipId?: number
}

/**
 * 片段播放的共享状态机（SessionCards 与 SessionRecordDetail 共用）：
 * - 已保存片段：`fetchSessionClipUrl` → 临时 objectURL 播放，播完即 revoke；
 * - 拉取失败（片段缺失 / 404 / 下线）→ 该片段进入 broken 集，pill 转禁用态，
 *   点击不会变成一次播放失败抛错；
 * - `<audio>` 元素由调用方模板提供（`audioRef`），jsdom 等无媒体后端的宿主里
 *   `play()` 的失败一律吞掉——回放失败不是故障。
 */
export function useClipPlayback(): {
  broken: Readonly<Ref<ReadonlySet<string>>>
  playingKey: Readonly<Ref<string>>
  audioRef: Ref<HTMLAudioElement | null>
  play: (source: ClipSource) => Promise<void>
  onEnded: () => void
} {
  const broken = ref<Set<string>>(new Set())
  const playingKey = ref('')
  const audioRef = ref<HTMLAudioElement | null>(null)
  // 播放中的临时 objectURL（fetchSessionClipUrl 产物）；播完/切歌即回收。
  let playbackUrl = ''

  function markBroken(key: string): void {
    const next = new Set(broken.value)
    next.add(key)
    broken.value = next
  }

  function start(key: string, url: string, revokeWhenDone: boolean): void {
    const audio = audioRef.value
    if (!audio) {
      markBroken(key)
      return
    }
    if (playbackUrl) URL.revokeObjectURL(playbackUrl)
    playbackUrl = revokeWhenDone ? url : ''
    audio.src = url
    playingKey.value = key
    try {
      const started = audio.play() as unknown as Promise<void> | undefined
      if (started && typeof started.catch === 'function') started.catch(() => {})
    } catch {
      // 播放失败不是故障：用户可以再点一次。
    }
  }

  async function play(source: ClipSource): Promise<void> {
    // 再点一次播放中的 pill = 停止。
    if (playingKey.value === source.key) {
      playingKey.value = ''
      audioRef.value?.pause()
      return
    }
    if (source.audioUrl) {
      start(source.key, source.audioUrl, false)
      return
    }
    if (source.recordId == null || source.clipId == null || broken.value.has(source.key)) return
    try {
      const url = await fetchSessionClipUrl(source.recordId, source.clipId)
      start(source.key, url, true)
    } catch {
      playingKey.value = ''
      markBroken(source.key)
    }
  }

  function onEnded(): void {
    playingKey.value = ''
    if (playbackUrl) {
      URL.revokeObjectURL(playbackUrl)
      playbackUrl = ''
    }
  }

  return { broken, playingKey, audioRef, play, onEnded }
}
