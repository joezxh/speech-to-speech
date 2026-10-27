import { describe, expect, it } from 'vitest'

import { TranscriptReducer } from './events'

describe('TranscriptReducer', () => {
  it('merges one user turn from delta → snapshot → completed into a single entry', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'hel' })
    r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'lo' })
    r.apply({ type: 'speech_to_speech.input_audio_transcription.snapshot', item_id: 'i1', transcript: 'hello there' })
    r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hello there.' })

    expect(r.entries).toHaveLength(1)
    expect(r.entries[0]).toMatchObject({ role: 'user', text: 'hello there.', partial: false })
  })

  it('keeps the snapshot text while the deltas are still catching up', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'speech_to_speech.input_audio_transcription.snapshot', item_id: 'i1', transcript: 'snap' })
    r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'sn' })

    expect(r.entries[0]).toMatchObject({ text: 'snap', partial: true })
  })

  it('drops a turn whose final transcript is empty, so no blank bubble is left behind', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'hmm' })
    r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: '' })

    expect(r.entries).toHaveLength(0)
  })

  it('appends assistant segments per response id instead of creating one bubble each', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'response.audio_transcript.delta', response_id: 'r1', delta: 'Hi' })
    r.apply({ type: 'response.output_audio_transcript.done', response_id: 'r1', transcript: 'Hi.' })
    r.apply({ type: 'response.audio_transcript.delta', response_id: 'r1', delta: 'More' })
    r.apply({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'More.' })

    expect(r.entries).toHaveLength(1)
    expect(r.entries[0]).toMatchObject({ role: 'assistant', text: 'Hi. More.', partial: false })
  })

  it('keeps user and assistant turns in arrival order and ignores unknown events', () => {
    const r = new TranscriptReducer()
    r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'q' })
    r.apply({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'a' })
    r.apply({ type: 'response.output_audio.delta', delta: 'AAAA' })
    r.apply({ type: 'speech_to_speech.output_audio.visemes', samples: [] })

    expect(r.entries.map((e) => `${e.role}:${e.text}`)).toEqual(['user:q', 'assistant:a'])
  })

  // 原音回放：demo 的 `onUserAudio` + `_ensureUserHist`（chat.js:538-540）。
  // 两个关键点：1) 转写还没到也要先有一行（STT 关掉时音频是这一轮唯一的痕迹）；
  // 2) 后来的转写只改文本，不能把已经挂上的播放器关掉。
  describe('user audio', () => {
    const recording = {
      itemId: 'i1',
      url: 'blob:wav-1',
      durationMs: 1200,
      truncated: false
    }

    it('creates an audio-only row when no transcript has arrived yet', () => {
      const r = new TranscriptReducer()
      r.userAudio(recording)

      expect(r.entries).toHaveLength(1)
      expect(r.entries[0]).toMatchObject({ key: 'u:i1', role: 'user', text: '', audio: { url: 'blob:wav-1', durationMs: 1200 } })
    })

    it('keeps the player when the transcript lands afterwards', () => {
      const r = new TranscriptReducer()
      r.userAudio(recording)
      r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'hello' })
      r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hello.' })

      expect(r.entries).toHaveLength(1)
      expect(r.entries[0]).toMatchObject({ text: 'hello.', partial: false, audio: { url: 'blob:wav-1' } })
    })

    it('replaces the url on a speculative continuation instead of adding a second row', () => {
      const r = new TranscriptReducer()
      r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'one' })
      r.userAudio(recording)
      // 同一个 `item_id` 的续接会把拼接后的整段 WAV 重新交出来（播放器逐次变长）。
      r.userAudio({ ...recording, url: 'blob:wav-2', durationMs: 2400, truncated: true })

      expect(r.entries).toHaveLength(1)
      expect(r.entries[0].audio).toMatchObject({ url: 'blob:wav-2', durationMs: 2400, truncated: true })
    })

    it('keeps a row whose final transcript is empty as long as it carries audio', () => {
      const r = new TranscriptReducer()
      r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'hmm' })
      r.userAudio(recording)
      r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: '' })

      // 没有音频时这一行会被丢掉（见上面的用例）；有音频时 demo 保留空文本行 + 播放器。
      expect(r.entries).toHaveLength(1)
      expect(r.entries[0]).toMatchObject({ text: '', audio: { url: 'blob:wav-1' } })
    })

    it('clears the audio with the rest of the transcript', () => {
      const r = new TranscriptReducer()
      r.userAudio(recording)
      r.reset()

      expect(r.entries).toHaveLength(0)
    })
  })

  // 气泡层要的是「每一次转写变化」，不是最终列表：demo 客户端为此专门发
  // `transcript` 事件（s2s-realtime-client.js:619-635）。reducer 是这里唯一的累加器，
  // 所以它必须把同一个信号广播出去，而不是让调用方再算一遍增量。
  describe('onTranscript', () => {
    it('reports every user and assistant update with its own identity', () => {
      const r = new TranscriptReducer()
      const seen: unknown[] = []
      r.onTranscript = (detail) => seen.push(detail)

      r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i1', delta: 'hel' })
      r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'hello.' })
      r.apply({ type: 'response.audio_transcript.delta', response_id: 'r1', delta: 'Hi' })

      expect(seen).toEqual([
        { role: 'user', text: 'hel', partial: true, itemId: 'i1', responseId: '' },
        { role: 'user', text: 'hello.', partial: false, itemId: 'i1', responseId: '' },
        { role: 'assistant', text: 'Hi', partial: true, itemId: '', responseId: 'r1' }
      ])
    })

    it('stays silent for tool rows and for turns deleted without a final text', () => {
      const r = new TranscriptReducer()
      const seen: unknown[] = []
      r.onTranscript = (detail) => seen.push(detail)

      r.toolCall({ name: 'web_search', arguments: '{"query":"x"}', callId: 'c1' })
      r.apply({ type: 'conversation.item.input_audio_transcription.delta', item_id: 'i2', delta: 'hmm' })
      r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i2', transcript: '' })

      expect(seen).toEqual([{ role: 'user', text: 'hmm', partial: true, itemId: 'i2', responseId: '' }])
    })
  })

  // 被插话的回复（demo chat.js:615-627 + `_markHistInterrupted` chat.js:391-398）：
  // `response.done` 的 `status === 'cancelled'`。已收到多少字就留多少，只打标记，
  // 绝不因为「被打断了」就当没说过的历史消失。
  describe('interrupt', () => {
    it('keeps the received text and flags the assistant row as interrupted', () => {
      const r = new TranscriptReducer()
      r.apply({ type: 'response.audio_transcript.delta', response_id: 'r1', delta: 'It looks like' })

      expect(r.interrupt('r1', 'It looks like')).toBe(true)

      expect(r.entries).toHaveLength(1)
      expect(r.entries[0]).toMatchObject({ role: 'assistant', text: 'It looks like', partial: false, interrupted: true })
    })

    it('builds the row from the transcript carried by response.done when the events never landed', () => {
      const r = new TranscriptReducer()

      expect(r.interrupt('r1', 'Half a sentence')).toBe(true)

      expect(r.entries).toHaveLength(1)
      expect(r.entries[0]).toMatchObject({ key: 'a:r1', role: 'assistant', text: 'Half a sentence', interrupted: true })
    })

    it('only flags the row when response.done carries no transcript', () => {
      const r = new TranscriptReducer()
      r.apply({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'Full reply.' })

      expect(r.interrupt('r1', '')).toBe(true)

      expect(r.entries).toHaveLength(1)
      expect(r.entries[0]).toMatchObject({ text: 'Full reply.', interrupted: true })
    })

    it('is idempotent — a second cancel does not duplicate the row', () => {
      const r = new TranscriptReducer()
      r.interrupt('r1', 'Same text')
      r.interrupt('r1', 'Same text')

      expect(r.entries).toHaveLength(1)
      expect(r.entries[0]).toMatchObject({ text: 'Same text', interrupted: true })
    })

    it('does nothing without a response id, so two id-less replies never collapse', () => {
      const r = new TranscriptReducer()
      r.apply({ type: 'response.audio_transcript.done', response_id: '', transcript: 'loose' })

      expect(r.interrupt('', 'loose')).toBe(false)
      expect(r.entries[0]?.interrupted).toBeUndefined()
    })

    it('leaves the audio and timings of the row alone', () => {
      const r = new TranscriptReducer()
      r.apply({ type: 'conversation.item.input_audio_transcription.completed', item_id: 'i1', transcript: 'question' })
      r.userAudio({ itemId: 'i1', url: 'blob:wav-1', durationMs: 800, truncated: false })
      r.apply({ type: 'response.audio_transcript.done', response_id: 'r1', transcript: 'answer' })
      r.interrupt('r1', 'answer')

      expect(r.entries.map((entry) => entry.key)).toEqual(['u:i1', 'a:r1'])
      expect(r.entries[0].audio?.url).toBe('blob:wav-1')
      expect(r.entries[1].interrupted).toBe(true)
    })
  })
})
