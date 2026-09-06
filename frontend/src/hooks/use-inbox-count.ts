// How many letters are waiting on the patron, kept true without polling.
//
// The sidebar used to paint the dot beside *Hộp thư Patron* from a literal `true` in the nav
// table, so it was lit on an empty inbox and lit on a full one — a lamp that is always on is the
// same as no lamp. The count has to come from somewhere real, and it has to stay right without
// the interface asking in a loop (Hiến pháp — Điều IV).
//
// So: read it once, then re-read whenever the inbox channel says something happened. An event is
// a signal to re-read, never the state itself — the events deliberately carry no letter bodies,
// and a count patched from an event's payload would drift the first time one was missed.
//
// The channel it listens on is not new: `subscribeInboxEvents` and `/v1/inbox/events` were both
// written long before this, and neither had a single caller. Nothing needed building here except
// somebody to actually listen.

import { useEffect } from 'react'

import { getInbox } from '@/lib/api'
import { subscribeInboxEvents } from '@/lib/sse'
import { useAppStore } from '@/store/appStore'

/** Coalescing window, in ms. Resolving a letter lands its own event next to whatever caused it. */
const REFRESH_DEBOUNCE_MS = 300

/**
 * Keep `inboxPending` in the store true, over ONE connection.
 *
 * Mounted by `Layout` and nowhere else: a second caller would open a second stream to the same
 * endpoint for the same data.
 */
export function useInboxCount(enabled: boolean): void {
  const setInboxPending = useAppStore((s) => s.setInboxPending)

  useEffect(() => {
    if (!enabled) return

    let alive = true
    let timer: ReturnType<typeof setTimeout> | null = null

    const read = async () => {
      try {
        const items = await getInbox({ status: 'pending' })
        if (alive) setInboxPending(items.length)
      } catch {
        // A failed read leaves the last known count alone. Zeroing it here would turn a network
        // hiccup into "nothing is waiting for you", which is the one wrong answer that costs
        // something: the patron stops looking.
      }
    }

    void read()

    const unsubscribe = subscribeInboxEvents(() => {
      if (timer) clearTimeout(timer)
      timer = setTimeout(() => void read(), REFRESH_DEBOUNCE_MS)
    })

    return () => {
      alive = false
      if (timer) clearTimeout(timer)
      unsubscribe()
    }
  }, [enabled, setInboxPending])
}
