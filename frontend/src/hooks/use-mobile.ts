import * as React from "react"

const MOBILE_BREAKPOINT = 768

const query = `(max-width: ${MOBILE_BREAKPOINT - 1}px)`

function subscribe(onStoreChange: () => void) {
  const mql = window.matchMedia(query)
  mql.addEventListener("change", onStoreChange)
  return () => mql.removeEventListener("change", onStoreChange)
}

// The viewport is an external store, so it is subscribed to rather than copied
// into state. The previous shape mirrored it: first render returned `false`
// whatever the width was, then an effect wrote the real answer and rendered
// again — a wrong first paint on every mobile load, and a cascading render on
// every load. `useSyncExternalStore` reads the real width for the first render.
export function useIsMobile() {
  return React.useSyncExternalStore(
    subscribe,
    () => window.matchMedia(query).matches,
    // Server-side there is no viewport; desktop is the safe assumption, and it
    // matches what the mirrored version happened to return on its first pass.
    () => false
  )
}
