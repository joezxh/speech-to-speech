// @vitest-environment jsdom
// Task 11（2026-11-17 原型对齐计划）——proto 组件渲染出对应原型 class 的根节点。
// class 名与 design/console-refactor-demo.html 逐字一致；组件只是消重复的薄封装。
import { createApp, defineComponent, h, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import PBadge from './PBadge.vue'
import PBar from './PBar.vue'
import PChip from './PChip.vue'
import PDot from './PDot.vue'
import PKpi from './PKpi.vue'
import PPipe from './PPipe.vue'
import PSplit from './PSplit.vue'
import PSwitch from './PSwitch.vue'
import PTable from './PTable.vue'
import PWave from './PWave.vue'
import PModal from './PModal.vue'
import PDrawer from './PDrawer.vue'
import { useToast } from '../../composables/useToast'
import PToast from './PToast.vue'

let roots: HTMLDivElement[] = []

function mount(Component: unknown, props: Record<string, unknown> = {}): HTMLElement {
  const root = document.createElement('div')
  document.body.appendChild(root)
  roots.push(root)
  const app = createApp(defineComponent({ render: () => h(Component as never, props) }))
  app.mount(root)
  return root
}

afterEach(() => {
  for (const root of roots) {
    try {
      ;(root as never as { __vue_app__: { unmount: () => void } }).__vue_app__.unmount()
    } catch {
      /* already gone */
    }
    root.remove()
  }
  roots = []
})

describe('proto components carry the prototype class names verbatim', () => {
  it('PTable renders table.tbl with th per column', () => {
    const root = mount(PTable, {
      columns: [
        { key: 'machine_id', label: '机器' },
        { key: 'state', label: '状态' }
      ],
      rows: [{ machine_id: 'node-a01', state: 'ok' }]
    })
    expect(root.querySelector('table.tbl')).toBeTruthy()
    expect(root.querySelectorAll('thead th').length).toBe(2)
    expect(root.textContent).toContain('node-a01')
  })

  it('PKpi renders .kpi with label/value/sub', () => {
    const root = mount(PKpi, { label: '在线机器', value: '3/4', sub: '过去 5 分钟', tone: 'ok' })
    expect(root.querySelector('.kpi')).toBeTruthy()
    expect(root.querySelector('.kpi .label')?.textContent).toBe('在线机器')
    expect(root.querySelector('.kpi .value')?.textContent).toBe('3/4')
    expect(root.querySelector('.kpi .sub')?.textContent).toBe('过去 5 分钟')
  })

  it('PChip toggles active chip and emits update', async () => {
    const received: string[] = []
    const root = document.createElement('div')
    document.body.appendChild(root)
    roots.push(root)
    const app = createApp(
      defineComponent({
        data: () => ({ picked: 'a' }),
        render() {
          return h(PChip, {
            items: [
              { key: 'a', label: '全部' },
              { key: 'b', label: '漂移' }
            ],
            modelValue: (this as never as { picked: string }).picked,
            'onUpdate:modelValue': (v: string) => {
              ;(this as never as { picked: string }).picked = v
              received.push(v)
            }
          })
        }
      })
    )
    app.mount(root)
    const chips = root.querySelectorAll('button.chip')
    expect(chips.length).toBe(2)
    expect(chips[0].classList.contains('active')).toBe(true)
    ;(chips[1] as HTMLButtonElement).click()
    await Promise.resolve()
    expect(received).toEqual(['b'])
  })

  it('PBadge/PDot carry kind/state classes', () => {
    expect(mount(PBadge, { kind: 'ok', text: '在线' }).querySelector('span.badge.ok')?.textContent).toBe('在线')
    expect(mount(PDot, { state: 'draining' }).querySelector('span.dot.draining')).toBeTruthy()
  })

  it('PBar clamps pct above 100 and renders fill width', () => {
    const root = mount(PBar, { pct: 180 })
    const fill = root.querySelector('.bar > i') as HTMLElement
    expect(fill.style.width).toBe('100%')
    const half = mount(PBar, { pct: 42.5 }).querySelector('.bar > i') as HTMLElement
    expect(half.style.width).toBe('42.5%')
  })

  it('PSplit renders two segments sized by aPct', () => {
    const root = mount(PSplit, { aPct: 60 })
    const segments = root.querySelectorAll('.split > i')
    expect(segments.length).toBe(2)
    expect((segments[0] as HTMLElement).style.width).toBe('60%')
    expect((segments[1] as HTMLElement).style.width).toBe('40%')
  })

  it('PPipe maps done/active/todo onto stage done/current/pending', () => {
    const root = mount(PPipe, {
      steps: [
        { key: 'b', label: '构建', state: 'done' },
        { key: 's', label: 'staging', state: 'active' },
        { key: 'r', label: '运行', state: 'todo' }
      ]
    })
    const stages = root.querySelectorAll('.pipe .stage')
    expect(stages.length).toBe(3)
    expect(stages[0].classList.contains('done')).toBe(true)
    expect(stages[1].classList.contains('current')).toBe(true)
    expect(stages[2].classList.contains('pending')).toBe(true)
  })

  it('PWave renders one rect per bar', () => {
    const root = mount(PWave, { bars: [3, 7, 2, 9] })
    expect(root.querySelectorAll('svg.wave rect').length).toBe(4)
  })

  it('PSwitch renders .switch and toggles .on', async () => {
    const root = document.createElement('div')
    document.body.appendChild(root)
    roots.push(root)
    const app = createApp(
      defineComponent({
        data: () => ({ value: false }),
        render() {
          return h(PSwitch, {
            modelValue: (this as never as { value: boolean }).value,
            'onUpdate:modelValue': (v: boolean) => {
              ;(this as never as { value: boolean }).value = v
            }
          })
        }
      })
    )
    app.mount(root)
    const sw = root.querySelector('.switch') as HTMLElement
    expect(sw.classList.contains('on')).toBe(false)
    sw.click()
    await nextTick()
    expect(sw.classList.contains('on')).toBe(true)
    sw.click()
    await nextTick()
    expect(sw.classList.contains('on')).toBe(false)
  })

  it('PModal/PDrawer render .modal/.drawer with .open when open', () => {
    const closedModal = mount(PModal, { open: false, title: '新建机器' })
    expect(closedModal.querySelector('.modal.open')).toBeNull()
    const modal = mount(PModal, { open: true, title: '新建机器' })
    expect(modal.querySelector('.modal.open .modal-head h3')?.textContent).toBe('新建机器')

    const drawer = mount(PDrawer, { open: true, title: '机器详情' })
    expect(drawer.querySelector('.drawer.open .drawer-head h3')?.textContent).toBe('机器详情')
  })
})

describe('useToast', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('push shows a toast that disappears after 3.5s', async () => {
    const toast = useToast()
    const root = document.createElement('div')
    document.body.appendChild(root)
    roots.push(root)
    const app = createApp(defineComponent({ render: () => h(PToast) }))
    app.mount(root)

    expect(root.querySelector('.toast.show')).toBeNull()
    toast.push('已保存', 'ok')
    await vi.advanceTimersByTimeAsync(0)
    const shown = root.querySelector('.toast.show')
    expect(shown).toBeTruthy()
    expect(shown?.textContent).toContain('已保存')

    await vi.advanceTimersByTimeAsync(3500)
    expect(root.querySelector('.toast.show')).toBeNull()
  })
})
