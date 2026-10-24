import { describe, expect, it } from 'vitest'

import { describeAlert } from './error'

describe('describeAlert', () => {
  it('translates the four codes the instances endpoint emits', () => {
    expect(describeAlert('pool_unreachable')).toBe('无法连接 pipeline 池')
    expect(describeAlert('pool_stuck')).toBe('有 unit 卡在 stuck，需要重启 pipeline')
    expect(describeAlert('pipeline_stopped')).toBe('pipeline 进程未运行')
    expect(describeAlert('usage_unavailable')).toBe('用量数据不可读')
  })

  it('shows an unknown code instead of hiding it', () => {
    // A new alert must be visible in the ops tool the day it is added, even if
    // this table has not caught up; hiding it would turn a signal into silence.
    expect(describeAlert('disk_filling_up')).toBe('disk_filling_up')
  })
})
