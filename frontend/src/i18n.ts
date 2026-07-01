import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './i18n/en'
import vi from './i18n/vi'

// Persist the chosen language so a hard refresh (or a return visit) keeps it. No extra
// dependency: read the stored value up front, and re-save on every `languageChanged`.
const LANG_KEY = 'armarius.lang'
const initialLang =
  (typeof localStorage !== 'undefined' && localStorage.getItem(LANG_KEY)) || 'en'

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    vi: { translation: vi },
  },
  lng: initialLang,
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

i18n.on('languageChanged', (lng) => {
  try {
    localStorage.setItem(LANG_KEY, lng)
  } catch {
    // storage unavailable (private mode / disabled) — non-fatal, keep this session's choice in memory
  }
})

export default i18n
