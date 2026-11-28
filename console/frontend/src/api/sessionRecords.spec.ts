import { beforeEach, describe, expect, it, vi } from 'vitest'

// 只 mock axios 层：上传/回放的字段名与响应解包是这里要钉死的契约。
vi.mock('./client', () => ({
  api: {
    post: vi.fn(),
    get: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn()
  },
  // 字节端点走原始 axios（blob 无 envelope）。
  client: {
    get: vi.fn()
  }
}))

import { api, client } from './client'
import { fetchSessionClipUrl, uploadSessionClip } from './sessionRecords'

const mockedApi = vi.mocked(api, true)

beforeEach(() => {
  vi.clearAllMocks()
})

describe('uploadSessionClip', () => {
  it('sends multipart with snake_case fields and unwraps the clip summary', async () => {
    // api.post 内部已解包 envelope，mock 直接给解包后的 clip 概要。
    mockedApi.post.mockResolvedValueOnce({
      id: 7,
      role: 'user',
      itemRef: 'u:1',
      messageOrdinal: 0,
      durationMs: 1800,
      sizeBytes: 44
    })
    const blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'audio/wav' })
    const clip = await uploadSessionClip(12, {
      role: 'user',
      itemRef: 'u:1',
      messageOrdinal: 0,
      sampleRate: 24000,
      durationMs: 1800,
      blob
    })
    expect(clip.id).toBe(7)
    expect(mockedApi.post).toHaveBeenCalledTimes(1)
    const [path, body] = mockedApi.post.mock.calls[0]
    expect(path).toBe('/session-records/12/clips')
    expect(body).toBeInstanceOf(FormData)
    const form = body as FormData
    expect(form.get('file')).toBeInstanceOf(File)
    expect(form.get('file')).toBeTruthy()
    expect(form.get('message_ordinal')).toBe('0')
    expect(form.get('role')).toBe('user')
    expect(form.get('item_ref')).toBe('u:1')
    expect(form.get('sample_rate')).toBe('24000')
    expect(form.get('duration_ms')).toBe('1800')
  })
})

describe('fetchSessionClipUrl', () => {
  it('fetches the clip bytes and returns an object URL', async () => {
    const wav = new Blob([new Uint8Array([9, 8, 7])], { type: 'audio/wav' })
    const mockedClient = vi.mocked(client, true)
    mockedClient.get.mockResolvedValueOnce({ data: wav })
    const url = await fetchSessionClipUrl(12, 7)
    expect(mockedClient.get).toHaveBeenCalledWith('/api/v1/session-records/12/clips/7', {
      responseType: 'blob'
    })
    expect(url.startsWith('blob:')).toBe(true)
    URL.revokeObjectURL(url)
  })
})
