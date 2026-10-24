import { describe, expect, it } from 'vitest'

import { describeInUse, formatSeconds, precomputeText, statusLabel } from './voice-text'

describe('precomputeText', () => {
  it('keeps the four documented reasons and does not invent a fifth', () => {
    expect(precomputeText('model_not_found')).toBe('未找到 VoiceDesign / 说话人模型')
    expect(precomputeText('audio_too_short')).toBe('参考音频太短（< 3 s）')
    expect(precomputeText('oom_cpu')).toBe('CPU 内存不足')
    expect(precomputeText('timeout')).toBe('预计算超时')
    expect(precomputeText('something_else')).toBe('预计算失败')
    expect(precomputeText(null)).toBe('')
  })
})

describe('describeInUse', () => {
  it('says draft and version counts in one sentence, from detail only', () => {
    expect(
      describeInUse('嘉嘉', [
        { field: 'profiles', value: ['prod'] },
        { field: 'versions', value: 1 }
      ])
    ).toBe('无法删除「嘉嘉」：正被 prod（草稿）与 1 个已发布版本引用，共 2 处。先从这些配置里换成别的音色并发布，再回来删除。')
  })

  it('survives a version-only reference', () => {
    expect(
      describeInUse('嘉嘉', [
        { field: 'profiles', value: [] },
        { field: 'versions', value: 2 }
      ])
    ).toContain('正被 2 个已发布版本引用，共 2 处')
  })
})

describe('statusLabel', () => {
  it('produces the four states which only ready can be picked from', () => {
    expect(statusLabel('ready')).toBe('可用')
    expect(statusLabel('precomputing')).toBe('制作中')
    expect(statusLabel('failed')).toBe('失败')
    expect(statusLabel('draft')).toBe('草稿')
  })
})

describe('formatSeconds', () => {
  it('renders a builtin voice without audio as a dash, not as zero seconds', () => {
    expect(formatSeconds(8)).toBe('8.0 s')
    expect(formatSeconds(0)).toBe('—')
    expect(formatSeconds(null)).toBe('—')
  })
})
