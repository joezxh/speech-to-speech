import { ref } from 'vue'

export interface ConfirmRequest {
  title: string
  content: string
}

/** 一个 Promise 化的确认框：丢弃草稿是破坏性动作，必须先问。 */
export function useConfirm() {
  const open = ref(false)
  const title = ref('')
  const content = ref('')
  let resolver: ((confirmed: boolean) => void) | null = null

  function ask(request: ConfirmRequest): Promise<boolean> {
    title.value = request.title
    content.value = request.content
    open.value = true
    return new Promise((resolve) => {
      resolver = resolve
    })
  }

  function answer(confirmed: boolean): void {
    open.value = false
    resolver?.(confirmed)
    resolver = null
  }

  return { open, title, content, ask, answer }
}
