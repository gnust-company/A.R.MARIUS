// One run's log: everything already written, then everything that happens next (T103, FR-046).
//
// Two roads to the same run, and the whole job of this hook is to make them one. The durable
// list is read once, in order; the SSE stream replays its own backlog and then live-tails. They
// overlap, on purpose — the stream starts from the beginning so nothing can fall between the
// two calls — so the merge is by `seq`, which is the run's own numbering and unique within it
// (FR-045). A second copy of a number already held is dropped.
//
// The list is kept sorted by `seq` rather than by arrival. A batch that was held back while the
// road was shut arrives after later ones, and a log that shows what happened in the order the
// network delivered it is not a log of what happened.
//
// One piece of state, carrying the run it belongs to. Changing runs is then a fact read during
// render rather than three setState calls in an effect — which is the same thing to look at and
// a cascade of renders to React.

import { useEffect, useMemo, useState } from 'react'

import { listRunEvents, type RunEventDTO } from '@/lib/api'
import { subscribeRunTrace } from '@/lib/sse'

export interface RunTrace {
  events: RunEventDTO[]
  /** Every kind present in this run, in the order it first appeared — what the filter offers. */
  kinds: string[]
  loading: boolean
  error: string | null
  /** Whether the live channel is attached. False means what is on screen is the stored log. */
  live: boolean
}

interface Held {
  runId?: string
  events: RunEventDTO[]
  /** Whether the durable read has come back. The stream keeps arriving after it. */
  read: boolean
  error: string | null
  channelLost: boolean
}

const NOTHING: Held = { events: [], read: false, error: null, channelLost: false }

/** How many events one ask brings back — the server's own ceiling, matched here so a
 *  full page is read as *there is more* rather than as the end of the run. */
const PAGE = 1000

export function useRunTrace(runId: string | undefined): RunTrace {
  const [held, setHeld] = useState<Held>(NOTHING)

  useEffect(() => {
    if (!runId) return
    let dropped = false
    // The numbers already held, local to this subscription: a new run starts a new set, and
    // nothing from the old one can survive into it.
    const seen = new Set<number>()

    const onto = (prev: Held): Held => (prev.runId === runId ? prev : { ...NOTHING, runId })

    const take = (incoming: RunEventDTO[]) => {
      if (dropped || incoming.length === 0) return
      setHeld((prev) => {
        const base = onto(prev)
        const fresh = incoming.filter((e) => !seen.has(e.seq))
        if (fresh.length === 0) return base
        for (const e of fresh) seen.add(e.seq)
        return { ...base, events: [...base.events, ...fresh].sort((a, b) => a.seq - b.seq) }
      })
    }

    // Walked, not fetched once. The door answers at most one page, so a run longer than a page
    // would otherwise stop dead at the cut with nothing on screen saying it had — which is the
    // exact shape of gap this whole feature exists to remove (FR-047). `after_seq` walks by the
    // run's own numbering, so a page boundary cannot land twice or skip.
    const walk = async () => {
      let from: number | undefined
      for (;;) {
        const page = await listRunEvents(runId, { afterSeq: from, limit: PAGE })
        if (dropped) return
        take(page)
        if (page.length < PAGE) return
        from = page[page.length - 1].seq
      }
    }

    walk()
      .catch((e: unknown) => {
        if (!dropped) {
          const why = e instanceof Error ? e.message : String(e)
          setHeld((prev) => ({ ...onto(prev), error: why }))
        }
      })
      .finally(() => {
        if (!dropped) setHeld((prev) => ({ ...onto(prev), read: true }))
      })

    const disconnect = subscribeRunTrace(
      runId,
      (event) => take([event]),
      () => {
        if (!dropped) setHeld((prev) => ({ ...onto(prev), channelLost: true }))
      },
    )
    return () => {
      dropped = true
      disconnect()
    }
  }, [runId])

  const mine = Boolean(runId) && held.runId === runId
  // Its own memo: a fresh `[]` on every render would make the list below recompute forever,
  // and the list is the thing a thousand-event run cannot afford to redo (SC-014).
  const events = useMemo(() => (mine ? held.events : []), [mine, held.events])

  const kinds = useMemo(() => {
    const seen: string[] = []
    for (const event of events) if (!seen.includes(event.type)) seen.push(event.type)
    return seen
  }, [events])

  return {
    events,
    kinds,
    loading: Boolean(runId) && (!mine || !held.read),
    error: mine ? held.error : null,
    live: Boolean(runId) && (!mine || !held.channelLost),
  }
}
