/*
 * A tab left open across a deploy still holds the old build's chunk names; the first screen it
 * opens after that asks for a file that no longer exists. The entry HTML is never cached, so a
 * reload picks up the new build.
 *
 * The reload belongs to a screen somebody is opening, and only to that. It used to hang off
 * Vite's global `vite:preloadError`, which fires for every failed `import()` — including the
 * ones the app makes on its own while idle, to warm the screens a person may open next. A tab
 * sitting on a half-written comment would then reload itself a few seconds after a deploy,
 * and the comment was gone. So the reload lives on the loaders the router opens, and the idle
 * warm-up uses the bare imports: when one of those fails, nothing happens until the person
 * actually goes there.
 */

const KEY = 'armarius.chunkReload'
const QUIET_MS = 60_000

type ReloadStore = Pick<Storage, 'getItem' | 'setItem'>

/**
 * May this tab reload for a stale build now? At most once a minute, so a chunk that is really
 * broken surfaces as an error instead of a reload loop. Claiming records the reload. A store
 * that cannot be read or written means there is no way to count reloads, so none starts.
 */
export function claimReload(store: ReloadStore, now: number): boolean {
  try {
    const last = Number(store.getItem(KEY)) || 0
    if (now - last < QUIET_MS) return false
    store.setItem(KEY, String(now))
    return true
  } catch {
    return false
  }
}

interface Surroundings {
  /** Where reloads are counted; `null` when the browser offers none. */
  store: () => ReloadStore | null
  now: () => number
  online: () => boolean
  reload: () => void
}

const browser: Surroundings = {
  store: () => {
    try {
      return window.sessionStorage
    } catch {
      return null
    }
  },
  now: () => Date.now(),
  online: () => navigator.onLine !== false,
  reload: () => window.location.reload(),
}

/**
 * Wrap the loader of a screen the router opens. When its chunk cannot be fetched the tab
 * reloads onto the current build, and the returned promise stays pending so the loading state
 * holds until the page is replaced. When a reload is not on the table — one just happened, the
 * browser is offline, reloads cannot be counted — the failure is passed on to the error boundary.
 */
export function screenLoader<T>(load: () => Promise<T>, around: Surroundings = browser): () => Promise<T> {
  return () =>
    load().catch((error: unknown) => {
      const store = around.store()
      if (!around.online() || !store || !claimReload(store, around.now())) throw error
      around.reload()
      return new Promise<T>(() => {})
    })
}
