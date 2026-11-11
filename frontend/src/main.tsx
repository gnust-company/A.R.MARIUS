import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { MotionConfig } from 'framer-motion'
import './i18n'
import './index.css'
import App from './App.tsx'
import Toaster from './components/Toaster'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      {/* reducedMotion="user" — every framer-motion animation honors the OS
          "reduce motion" setting app-wide (a11y), no per-component changes. */}
      <MotionConfig reducedMotion="user">
        <App />
        <Toaster />
      </MotionConfig>
    </BrowserRouter>
  </StrictMode>,
)
