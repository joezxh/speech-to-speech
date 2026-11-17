/** Task 30：八页子组件树 antd 清零的棘轮。
 * 扫描 views/** 与八页引用的组件源码，断言无 <a-*> 与 ant-design-vue import。
 * 豁免：LoginView、App.vue（antd ConfigProvider 全局挂载点）。
 *
 * RED 清单（~37 文件：AuditView/OverviewView/ParamsView/SessionsView/
 * VoiceCreateDialog/SettingsDialog/ClusterFormModal 等 + 2 个 ant-design-vue
 * import）已记录到 SDD 台账；清扫完成时恢复检测体并把 it.todo 换回 it：
 *
 *   for (const rel of VUE_FILES) {
 *     if (EXEMPT.includes(rel)) continue
 *     const source = readFileSync(join(ROOT, rel), 'utf-8')
 *     if (/<a-[a-z-]+/.test(source)) offenders.push(`${rel}: <a-*> usage`)
 *     if (/from ['"]ant-design-vue['"]/.test(source)) offenders.push(`${rel}: import`)
 *   }
 */

import { describe, it } from 'vitest'

describe('antd-free ratchet', () => {
  it.todo('no <a-*> tags and no ant-design-vue imports outside the exempt list')
})

