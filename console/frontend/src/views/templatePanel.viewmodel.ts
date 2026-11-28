// views/templatePanel.viewmodel.ts — 部署页模板面板的纯函数（原型 templatePanel）。
import type { TemplateField, TemplateRow } from '@/api/templates'

/** 机器侧校验输入（MachineDetail 的最小切片，便于单测）。 */
export interface TemplateMachineInput {
  machineId: string
  platform: string
  driver: string
  gpuTotalGb: number | null
}

export interface TemplateCheck {
  platformOk: boolean
  vramOk: boolean
  /** 全部硬约束通过（平台一致 + 显存达标）。 */
  ok: boolean
  /** 未通过原因的 i18n key（panel.check.*）。 */
  reasons: string[]
}

/**
 * 硬件校验（原型 checkTemplateHardware）：平台必须一致；模板写了最低显存时，
 * 机器显存未知 → vramOk=false（不能拿未知当通过）；驱动只展示不拦截。
 */
export function checkTemplateHardware(template: TemplateRow, machine: TemplateMachineInput): TemplateCheck {
  const platformOk = template.platform === machine.platform
  const vramOk = template.minVramGb == null || (machine.gpuTotalGb != null && machine.gpuTotalGb >= template.minVramGb)
  const reasons: string[] = []
  if (!platformOk) reasons.push('panel.check.platformMismatch')
  if (!vramOk) reasons.push(machine.gpuTotalGb == null ? 'panel.check.vramUnknown' : 'panel.check.vramShort')
  return { platformOk, vramOk, ok: platformOk && vramOk, reasons }
}

export interface TemplateActualRow {
  field: TemplateField
  actual: string
  /** 模板值与机器实际值一致（字符串化比较，null/'' 视为未知）。 */
  match: boolean | null
}

/** 模板字段 → 机器实际值对照行（原型「机器实际部署参数」列）。 */
export function templateActualRows(
  template: TemplateRow,
  actual: Record<string, string>
): TemplateActualRow[] {
  return template.fields.map((field) => {
    const value = actual[field.key]
    if (value == null || value === '') return { field, actual: '', match: null }
    return { field, actual: value, match: String(field.value) === String(value) }
  })
}

/** 从机器当前草稿/实际值生成「保存为模板」的字段快照。 */
export function snapshotFields(
  keys: string[],
  patch: Record<string, string>,
  actual: Record<string, string>
): Array<{ key: string; value: string }> {
  return keys
    .map((key) => ({ key, value: patch[key] ?? actual[key] ?? '' }))
    .filter((field) => field.value !== '')
}

/** 生效方式推断：全部字段可热更 → runtime；否则 restart。 */
export function inferEffect(fields: Array<{ key: string; value: string }>, hotKeys: Set<string>): 'runtime' | 'restart' {
  if (fields.length === 0) return 'restart'
  return fields.every((field) => hotKeys.has(field.key)) ? 'runtime' : 'restart'
}
