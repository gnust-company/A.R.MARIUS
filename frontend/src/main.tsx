import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import { MotionConfig } from 'framer-motion'
import './i18n'
import './index.css'
import App from './App.tsx'
import Toaster from './components/Toaster'

// A tab left open across a deploy still holds the old build's chunk names; the first screen it
// opens after that asks for a file that no longer exists. The entry HTML is never cached, so a
// reload picks up the new build. Once per minute at most, so a chunk that is really broken
// surfaces as an error instead of a reload loop.
window.addEventListener('vite:preloadError', () => {
  const KEY = 'armarius.chunkReload'
  let last = 0
  try {
    last = Number(sessionStorage.getItem(KEY)) || 0
    if (Date.now() - last < 60_000) return
    sessionStorage.setItem(KEY, String(Date.now()))
  } catch {
    // No session storage: without a way to count reloads, do not start one.
    return
  }
  window.location.reload()
})

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
