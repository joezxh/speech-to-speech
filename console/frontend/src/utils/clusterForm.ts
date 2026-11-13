/**
 * 集群表单校验：正则与后端 `cluster_service.NAME_RE/REGISTRY_RE/POLICIES`
 * 逐字一致（spec §4.1），前端只为即时反馈，服务端仍是唯一裁判。
 */
export const NAME_RE = /^[a-z0-9][a-z0-9-]{1,39}$/
export const REGISTRY_RE = /^([a-z][a-z0-9+.-]*:\/\/)?[\w.-]+:\d{2,5}$/i
export const POLICIES = ['least', 'rr', 'lat'] as const

export interface ClusterFormValues {
  name: string
  registry: string
  policy: string
  note: string
}

/** 值 = i18n 键（overview.form.*），由弹窗渲染。 */
export type ClusterFormErrors = Partial<Record<keyof ClusterFormValues, string>>

export function validateClusterForm(values: ClusterFormValues, editing = false): ClusterFormErrors {
  const errors: ClusterFormErrors = {}
  if (!editing) {
    const name = values.name.trim()
    if (!name) errors.name = 'overview.form.nameRequired'
    else if (!NAME_RE.test(name)) errors.name = 'overview.form.nameInvalid'
  }
  const registry = values.registry.trim()
  if (!registry) errors.registry = 'overview.form.registryRequired'
  else if (!REGISTRY_RE.test(registry)) errors.registry = 'overview.form.registryInvalid'
  if (!(POLICIES as readonly string[]).includes(values.policy)) errors.policy = 'overview.form.policyInvalid'
  if (values.note.length > 255) errors.note = 'overview.form.noteTooLong'
  return errors
}