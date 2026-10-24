import { describe, expect, it } from 'vitest'

import { fallbackCode, translate } from './error'

describe('translate', () => {
  it('maps the codes the backend is allowed to send', () => {
    expect(translate('unauthorized')).toBe('登录已过期，请重新登录')
    expect(translate('vram_budget_exceeded')).toBe('显存预算不足，请减少 pipeline 数量或换更小的模型')
    expect(translate('publish_in_progress')).toBe('已有一次发布正在进行')
    expect(translate('version_not_rollbackable')).toBe('该版本不可回滚')
  })

  it('never falls back to the server message', () => {
    // A.0: the UI translates `code` and must not parse `message` — the message is
    // English and may quote an input value (B7). A code we do not know yet gets a
    // neutral sentence, not the raw text.
    expect(translate('brand_new_code')).toBe('操作失败，请查看审计记录')
  })
})

describe('fallbackCode', () => {
  it('gives every status the UI can receive a code of our own', () => {
    expect(fallbackCode(503)).toBe('db_unavailable')
    expect(fallbackCode(403)).toBe('forbidden')
    expect(fallbackCode(undefined)).toBe('network_error')
  })
})
