import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './i18n/en'
import vi from './i18n/vi'

i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    vi: { translation: vi },
  },
  lng: 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

export default i18n
