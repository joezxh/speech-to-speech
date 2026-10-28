import { defineStore } from 'pinia'
import { ref } from 'vue'

import i18n from '@/i18n'
import { detectLocale, saveLocale, type Locale } from '@/i18n/locale'

export const useLocaleStore = defineStore('locale', () => {
  const locale = ref<Locale>(detectLocale())
  i18n.global.locale.value = locale.value

  function setLocale(next: Locale): void {
    locale.value = next
    i18n.global.locale.value = next
    saveLocale(next)
  }

  return { locale, setLocale }
})
