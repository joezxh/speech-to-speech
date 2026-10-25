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
})
