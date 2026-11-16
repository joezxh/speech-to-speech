// composables/useToast.ts — 原型 `.toast` 的全局状态（单例容器 PToast 渲染）。
import { reactive } from 'vue'

export type ToastKind = 'ok' | 'warn' | 'bad'

export interface ToastState {
  visible: boolean
  msg: string
  kind: ToastKind
}

const state = reactive<ToastState>({ visible: false, msg: '', kind: 'ok' })

let timer: ReturnType<typeof setTimeout> | undefined
// 原型 demo：3.5s 自动消失。
const TOAST_TTL_MS = 3500

export function useToast() {
  function push(msg: string, kind: ToastKind = 'ok'): void {
    state.msg = msg
    state.kind = kind
    state.visible = true
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      state.visible = false
    }, TOAST_TTL_MS)
  }
  return { push, state }
}
