import { describe, expect, it } from 'vitest'

import { REGISTRY_RE, NAME_RE, validateClusterForm } from './clusterForm'

const base = { name: 'gray-01', registry: 'consul://10.0.0.1:8500', policy: 'rr', note: '' }

describe('validateClusterForm', () => {
  it('accepts a well-formed create payload', () => {
    expect(validateClusterForm(base)).toEqual({})
  })

  it('requires a name and enforces the shared regex', () => {
    expect(validateClusterForm({ ...base, name: '' })).toEqual({ name: 'overview.form.nameRequired' })
    expect(validateClusterForm({ ...base, name: 'Bad_Name!' })).toEqual({ name: 'overview.form.nameInvalid' })
    expect(NAME_RE.test('a'.repeat(40))).toBe(true)
    expect(NAME_RE.test('a'.repeat(41))).toBe(false)
  })

  it('skips the name in edit mode (the field is disabled)', () => {
    expect(validateClusterForm({ ...base, name: 'IGNORED' }, true)).toEqual({})
  })

  it('requires a registry with host:port, scheme optional and case-insensitive', () => {
    expect(validateClusterForm({ ...base, registry: '' })).toEqual({ registry: 'overview.form.registryRequired' })
    expect(validateClusterForm({ ...base, registry: 'consul://host' })).toEqual({
      registry: 'overview.form.registryInvalid'
    })
    expect(REGISTRY_RE.test('CONSUL://Host:8500')).toBe(true)
    expect(REGISTRY_RE.test('10.0.0.1:8500')).toBe(true)
  })

  it('pins the policy enum and the note length', () => {
    expect(validateClusterForm({ ...base, policy: 'fifo' })).toEqual({ policy: 'overview.form.policyInvalid' })
    expect(validateClusterForm({ ...base, note: 'x'.repeat(256) })).toEqual({ note: 'overview.form.noteTooLong' })
  })
})