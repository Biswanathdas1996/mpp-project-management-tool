import { createI18n } from 'vue-i18n'
import en from './en'
import ar from './ar'

export type Locale = 'en' | 'ar'

function initialLocale(): Locale {
  try {
    const saved = localStorage.getItem('pma.locale')
    if (saved === 'en' || saved === 'ar') return saved
  } catch {
    /* ignore */
  }
  return navigator.language?.startsWith('ar') ? 'ar' : 'en'
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: 'en',
  messages: { en, ar },
  missingWarn: false,
  fallbackWarn: false,
})

export function applyLocale(locale: Locale) {
  i18n.global.locale.value = locale
  document.documentElement.lang = locale
  document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr'
  try {
    localStorage.setItem('pma.locale', locale)
  } catch {
    /* ignore */
  }
}
