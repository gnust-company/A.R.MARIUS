import * as React from "react"

/** How much room the app shell has, by the widths the layout actually changes at.
 *
 * - `phone`   < 768px  — no room for a rail; the navigation is a drawer.
 * - `tablet`  < 1280px — the navigation stays as an icon rail so pages keep their width.
 * - `desktop` ≥ 1280px — the full sidebar, unless the person collapsed it.
 */
export type Viewport = "phone" | "tablet" | "desktop"

const TABLET_MIN = 768
const DESKTOP_MIN = 1280

const queries = [`(min-width: ${TABLET_MIN}px)`, `(min-width: ${DESKTOP_MIN}px)`]

function read(): Viewport {
  if (window.matchMedia(queries[1]).matches) return "desktop"
  if (window.matchMedia(queries[0]).matches) return "tablet"
  return "phone"
}

function subscribe(onStoreChange: () => void) {
  const lists = queries.map((q) => window.matchMedia(q))
  lists.forEach((mql) => mql.addEventListener("change", onStoreChange))
  return () => lists.forEach((mql) => mql.removeEventListener("change", onStoreChange))
}

// Subscribed rather than mirrored into state, for the same reason as `useIsMobile`: the
// first render reads the real width instead of painting the desktop shell on a phone.
export function useViewport(): Viewport {
  return React.useSyncExternalStore(subscribe, read, () => "desktop")
}
