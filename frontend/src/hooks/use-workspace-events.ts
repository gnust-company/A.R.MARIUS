// Workspace control-plane SSE (Sprint 6): opens `/v1/workspaces/{ws}/events` and
// reconciles `marius.status_changed` events into the store.

import { useEffect } from 'react'

import { livenessToAgentStatus } from '@/lib/mappers'
import { subscribeWorkspaceEvents } from '@/lib/sse'
import { useMockStore, type AgentStatus } from '@/store/mockStore'

/** Map a backend workspace-event `status` to the FE AgentStatus union. */
function statusToAgent(status: string): AgentStatus {
  if (status === 'approved') return 'online'
  if (status === 'invited') return 'invited'
  if (status === 'pending_review' || status === 'pending') return 'pending' // enrolled, awaiting approval (#51)
  if (status === 'revoked') return 'revoked'
  return livenessToAgentStatus(status) // liveness values (online/working/idle/...)
}

export function useWorkspaceEvents(workspaceId: string | null | undefined): void {
  const setSseConnected = useMockStore((s) => s.setSseConnected)

  useEffect(() => {
    if (!workspaceId) return
    setSseConnected(true) // subscription initiated — the TopBar indicator reflects it
    const disconnect = subscribeWorkspaceEvents(
      workspaceId,
      (event) => {
        const payload = event.payload ?? {}
        const mariusId = (payload.marius_id ?? payload.mariusId) as string | undefined
        const status = payload.status as string | undefined
        if (mariusId && status) {
          const next = statusToAgent(status)
          useMockStore.setState((s) => ({
            mariuses: s.mariuses.map((m) =>
              m.id === mariusId ? { ...m, status: next } : m,
            ),
          }))
        }
        // Surface every workspace event so any subscriber (e.g. a future toast/log) sees it.
        useMockStore.getState().emitEvent({ type: event.type, payload })
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
