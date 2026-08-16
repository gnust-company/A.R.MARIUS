// Workspace control-plane SSE: opens `/v1/workspaces/{ws}/events` and turns every
// `marius.*` event into a re-read of that workspace's agents.
//
// It used to patch the store from each event's payload instead, which is what principle 1
// of `contracts/push-events.md` forbids — an event is a signal to re-read, never the state
// itself. That inversion cost the status dot outright (T169): the server publishes
// `marius.online` as a bare id, this hook demanded a `status` field before it would touch
// anything, and so the one event that says an agent came back was dropped on the floor. A
// dot that only changes on page reload is the same failure as polling, arrived at from the
// other side.

import { useEffect } from 'react'

import { subscribeWorkspaceEvents } from '@/lib/sse'
import { useAppStore } from '@/store/appStore'

export interface WorkspaceEvent {
  type: string
  payload: Record<string, unknown>
}

/**
 * Listen to the workspace channel from anywhere, over the ONE connection `Layout` already
 * holds open.
 *
 * A page could call `subscribeWorkspaceEvents` itself, but that opens a second stream to
 * the same endpoint for the same data.
 *
 * Returns its own unsubscribe.
 */
const listeners = new Set<(event: WorkspaceEvent) => void>()

export function onWorkspaceEvent(listener: (event: WorkspaceEvent) => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Coalescing window for agent re-reads, in ms. */
const REFRESH_DEBOUNCE_MS = 300

export function useWorkspaceEvents(workspaceId: string | null | undefined): void {
  const setSseConnected = useAppStore((s) => s.setSseConnected)

  useEffect(() => {
    if (!workspaceId) return
    setSseConnected(true) // subscription initiated — the TopBar indicator reflects it
    // Installing skills on an agent lands several events back to back (one push, then one
    // confirmation per slug); a burst of runs does the same. Coalesce them into one read.
    let pending: ReturnType<typeof setTimeout> | null = null
    const scheduleRefresh = () => {
      if (pending) return
      pending = setTimeout(() => {
        pending = null
        void useAppStore.getState().refreshMariuses(workspaceId).catch(() => {})
      }, REFRESH_DEBOUNCE_MS)
    }

    const disconnect = subscribeWorkspaceEvents(
      workspaceId,
      (event) => {
        const payload = event.payload ?? {}
        // Every `marius.*` event means the same thing to this hook — something about an
        // agent changed, go look. Deliberately NOT a list of known event names: the last
        // time this was a list, a new event type shipped and nothing updated for it.
        // Liveness (`marius.online` / `marius.offline`), invite and delete
        // (`marius.status_changed`), and skill install state (`marius.skills_updated`,
        // `marius.skill_installed`) all ride this one read.
        if (event.type.startsWith('marius.')) {
          scheduleRefresh()
        }
        for (const listener of listeners) listener({ type: event.type, payload })
      },
      (err) => {
        setSseConnected(false)
        console.error('[workspace SSE]', err.message)
      },
    )
    return () => {
      if (pending) clearTimeout(pending)
      disconnect()
      setSseConnected(false)
    }
  }, [workspaceId, setSseConnected])
}
