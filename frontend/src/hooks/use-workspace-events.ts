// Workspace control-plane SSE (Sprint 6): opens `/v1/workspaces/{ws}/events` and
// reconciles `marius.status_changed` events into the store.

import { useEffect } from 'react'

import { livenessToAgentStatus } from '@/lib/mappers'
import { subscribeWorkspaceEvents } from '@/lib/sse'
import { useAppStore, type AgentStatus } from '@/store/appStore'

/** Map a backend workspace-event `status` to the FE AgentStatus union. */
function statusToAgent(status: string): AgentStatus {
  if (status === 'approved') return 'online'
  if (status === 'invited') return 'invited'
  if (status === 'pending_review' || status === 'pending') return 'pending' // enrolled, awaiting approval (#51)
  if (status === 'revoked') return 'revoked'
  return livenessToAgentStatus(status) // liveness values (online/working/idle/...)
}

export interface WorkspaceEvent {
  type: string
  payload: Record<string, unknown>
}

/**
 * Listen to the workspace channel from anywhere, over the ONE connection `Layout` already
 * holds open.
 *
 * A page could call `subscribeWorkspaceEvents` itself, but that opens a second stream to
 * the same endpoint for the same data. Routing through the store's `events` array is the
 * other tempting shortcut and is worse: that array is never trimmed, so a page that reacts
 * to run traffic would make it grow for as long as the tab stays open.
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

export function useWorkspaceEvents(workspaceId: string | null | undefined): void {
  const setSseConnected = useAppStore((s) => s.setSseConnected)

  useEffect(() => {
    if (!workspaceId) return
    setSseConnected(true) // subscription initiated — the TopBar indicator reflects it
    const disconnect = subscribeWorkspaceEvents(
      workspaceId,
      (event) => {
        const payload = event.payload ?? {}
        const mariusId = (payload.marius_id ?? payload.mariusId) as string | undefined
        const status = payload.status as string | undefined
        // Scoped to `marius.*` on purpose. The channel also carries events that name an
        // agent and carry an unrelated `status` — a run's lifecycle says
        // `{marius_id, status: 'running'}` — and reading those as a liveness value would
        // set every agent that starts a run to whatever `statusToAgent` makes of it.
        if (mariusId && status && event.type.startsWith('marius.')) {
          const next = statusToAgent(status)
          useAppStore.setState((s) => ({
            mariuses: s.mariuses.map((m) =>
              m.id === mariusId ? { ...m, status: next } : m,
            ),
          }))
        }
        // Post-invite skill install (#74): patch per-skill install state in place so the
        // AgentDetail badges flip live — pushed → pending/failed, agent-confirmed → installed.
        if (mariusId && event.type === 'marius.skill_installed' && payload.slug) {
          const slug = payload.slug as string
          useAppStore.setState((s) => ({
            mariuses: s.mariuses.map((m) =>
              m.id === mariusId
                ? { ...m, skillInstalls: { ...(m.skillInstalls ?? {}), [slug]: 'installed' } }
                : m,
            ),
          }))
        }
        if (mariusId && event.type === 'marius.skills_updated' && Array.isArray(payload.installed)) {
          const state = payload.send_status === 'sent' ? 'pending' : 'failed'
          const slugs = payload.installed as string[]
          useAppStore.setState((s) => ({
            mariuses: s.mariuses.map((m) =>
              m.id === mariusId
                ? {
                    ...m,
                    skillInstalls: {
                      ...(m.skillInstalls ?? {}),
                      ...Object.fromEntries(slugs.map((sl) => [sl, state])),
                    },
                  }
                : m,
            ),
          }))
        }
        // Surface every workspace event so any subscriber (e.g. a future toast/log) sees it.
        useAppStore.getState().emitEvent({ type: event.type, payload })
        for (const listener of listeners) listener({ type: event.type, payload })
      },
      (err) => {
        setSseConnected(false)
        console.error('[workspace SSE]', err.message)
      },
    )
    return () => {
      disconnect()
      setSseConnected(false)
    }
  }, [workspaceId, setSseConnected])
}
