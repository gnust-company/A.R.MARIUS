import * as React from "react"

/** The two themes of DESIGN §4: daylight office, or the office at night with the lamps on. */
export type Theme = "light" | "dark"

const STORAGE_KEY = "armarius.theme"
const SYSTEM_DARK = "(prefers-color-scheme: dark)"

const listeners = new Set<() => void>()

function stored(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY)
    return value === "light" || value === "dark" ? value : null
  } catch {
    return null
  }
}

/** The person's explicit choice wins; until they make one, follow the OS. */
function read(): Theme {
  return stored() ?? (window.matchMedia(SYSTEM_DARK).matches ? "dark" : "light")
}

/** Mirror the theme onto <html> — every token in index.css keys off `data-theme`. The inline
 * script in index.html does the same before first paint, so a reload never flashes. */
function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#111b26" : "#f9f7f2")
}

function subscribe(onChange: () => void) {
  listeners.add(onChange)
  const mql = window.matchMedia(SYSTEM_DARK)
  const onSystem = () => {
    if (stored()) return
    apply(read())
    onChange()
  }
  mql.addEventListener("change", onSystem)
  return () => {
    listeners.delete(onChange)
    mql.removeEventListener("change", onSystem)
  }
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // Private mode / blocked storage: the switch still works for this visit.
  }
  apply(theme)
  listeners.forEach((fn) => fn())
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const theme = React.useSyncExternalStore(subscribe, read, () => "light" as Theme)
  return [theme, setTheme]
}
