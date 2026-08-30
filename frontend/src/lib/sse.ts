// Server‑Sent Events client using `fetch` + `ReadableStream`.
//
// Why not `EventSource`? The SSE routes (`/v1/workspaces/{ws}/events`, `/v1/tasks/{id}/stream`)
// require an `Authorization: Bearer <jwt>` header, and the standard `EventSource` API cannot
// send custom headers. This module implements a lightweight reader that:
//
//   • Sends the Bearer token on the initial request.
//   • Resumes from `Last-Event-ID` (or a numeric fallback).
//   • Parses `text/event-stream` framing (`event:`, `data:`, `id:`) into callbacks.
//   • Auto‑reconnects with exponential backoff (up to 30s).
//   • Handles `?live=0` catch‑up mode (the server closes the stream after the backlog).
//
// The caller receives typed payloads via `onMessage({ type, data, id })`. Higher‑level hooks
// (`use-workspace-events`, `use-task-stream`) map these to store actions.

import { getToken, refreshAccessToken } from './auth'
import { API_BASE } from './env'
import type { RunEventDTO } from './api'
import { traceEventFromVM, workspaceEventFromVM } from './mappers'

export interface SSEMessage {
  type: string
  data: unknown
  id: string
}

export interface SSEOptions {
  signal?: AbortSignal
  lastEventId?: string | number
}

/**
 * Subscribe to an SSE stream. Returns a `disconnect` function.
 *
 * The `onMessage` callback fires for every event block received. Errors surface via
 * `onError` (useful for toast alerts); the reader retries automatically.
 *
 * `reconnectInterval` caps the delay between attempts (default 30s). Set `0` to disable
 * auto‑reconnect (useful for `?live=0` catch‑up mode).
 */
export function subscribeSSE(
  url: string,
  onMessage: (msg: SSEMessage) => void,
  onError?: (error: Error) => void,
  options?: SSEOptions & { reconnectInterval?: number },
): () => void {
  let lastId = options?.lastEventId ? String(options.lastEventId) : ''
  let backoff = 1000
  const maxBackoff = options?.reconnectInterval ?? 30000
  let aborted = false
  let controller: AbortController | null = null
  // One refresh attempt per live connection: a mid-stream 401 (token expired while the stream
  // was open) triggers a token refresh + immediate reconnect. Reset on every successful connect
  // so a later expiry can refresh again; guards against a fresh token that still 401s.
  let refreshedThisConnect = false

  async function run(): Promise<void> {
    while (!aborted) {
      try {
        controller = new AbortController()
        const signal = options?.signal ?? controller.signal

        const headers: Record<string, string> = {
          Accept: 'text/event-stream',
        }
        const token = getToken()
        if (token) {
          headers.Authorization = `Bearer ${token}`
        }
        if (lastId) {
          headers['Last-Event-ID'] = lastId
        }

        const res = await fetch(url, { headers, signal })

        if (!res.ok) {
          // 401 → the access token likely expired mid-stream. Try a single refresh and
          // reconnect immediately; only give up (fatal onError) if the refresh itself fails
          // or a freshly refreshed token still 401s.
          if (res.status === 401) {
            if (!refreshedThisConnect && (await refreshAccessToken())) {
              refreshedThisConnect = true
              continue // reconnect now with the new token (skip backoff)
            }
            onError?.(new Error('Unauthorized (401)'))
            return
          }
          throw new Error(`SSE ${res.status}: ${res.statusText}`)
        }

        if (!res.body) {
          throw new Error('SSE response body is null')
        }

        // Success → reset backoff and re-arm the one-shot refresh for the next expiry.
        backoff = 1000
        refreshedThisConnect = false

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let inEvent = false
        let currentType = ''
        let currentData = ''
        let currentId = ''

        while (!aborted) {
          const { done, value } = await reader.read()
          if (done) {
            // Stream closed normally (e.g., catch‑up mode with `?live=0`).
            break
          }

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split(/\r?\n/)
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (line === '') {
              // Empty line → end of event block.
              if (inEvent) {
                // An event with no `event:` line is named `message` — that is the default the
                // spec gives it, not a nameless event. `/v1/runs/{id}/stream` sends every one
                // of its events that way on purpose, so that a browser's own EventSource, whose
                // `onmessage` only ever hears `message`, receives all of them.
                onMessage({ type: currentType || 'message', data: currentData, id: currentId })
                lastId = currentId
                currentType = ''
                currentData = ''
                currentId = ''
                inEvent = false
              }
            } else if (line.startsWith(':')) {
              // Comment – ignore.
            } else if (line.startsWith('event:')) {
              currentType = line.slice(6).trim()
              inEvent = true
            } else if (line.startsWith('data:')) {
              // `inEvent` here too, and this is the whole of a real bug: without it a block
              // carrying only `data:` was read to the end and then thrown away, so every
              // unnamed event on every stream vanished with no error anywhere. Nothing noticed
              // because until now no screen subscribed to a stream that sends them.
              const value = line.slice(5).trim()
              currentData = currentData ? `${currentData}\n${value}` : value
              inEvent = true
            } else if (line.startsWith('id:')) {
              currentId = line.slice(3).trim()
            } else if (line.startsWith('retry:')) {
              // Server‑requested retry interval (ms). Ignore; we control backoff.
            }
          }
        }
      } catch (e) {
        if (aborted) return
        const err = e instanceof Error ? e : new Error(String(e))
        onError?.(err)
      }

      // Wait before reconnecting (exponential backoff capped at maxBackoff).
      if (!aborted) {
        await new Promise((resolve) => setTimeout(resolve, backoff))
        backoff = Math.min(backoff * 2, maxBackoff)
      }
    }
  }

  // Start the loop in the background.
  run().catch((e) => {
    if (!aborted) {
      onError?.(e instanceof Error ? e : new Error(String(e)))
    }
  })

  // Return a disconnect function.
  return () => {
    aborted = true
    controller?.abort()
  }
}

// ── Typed subscriptions (convenient helpers for the SSE hooks) ─────────────────────────────

/**
 * Subscribe to the workspace control‑plane SSE (`/v1/workspaces/{ws}/events`).
 *
 * The callback receives the already‑mapped `{ type, payload }` (see `workspaceEventFromVM`).
 */
export function subscribeWorkspaceEvents(
  workspaceId: string,
  onEvent: (event: { type: string; payload: Record<string, unknown> }) => void,
  onError?: (error: Error) => void,
): () => void {
  const url = `${API_BASE}/v1/workspaces/${workspaceId}/events`
  return subscribeSSE(
    url,
    (msg) => {
      const mapped = workspaceEventFromVM({ event_type: msg.type, payload: parseData(msg.data) })
      if (mapped) onEvent(mapped)
    },
    onError,
  )
}

/**
 * Subscribe to the per‑task trace SSE (`/v1/tasks/{id}/stream`).
 *
 * The callback receives the already‑mapped `TraceEvent` view‑model (see `traceEventFromVM`).
 */
export function subscribeTaskTrace(
  taskId: string,
  onTrace: (event: NonNullable<ReturnType<typeof traceEventFromVM>>) => void,
  onError?: (error: Error) => void,
  lastEventId?: string | number,
): () => void {
  const url = `${API_BASE}/v1/tasks/${taskId}/stream`
  return subscribeSSE(
    url,
    (msg) => {
      const parsed = parseData(msg.data)
      const event = traceEventFromVM({ event_type: msg.type, payload: parsed })
      if (event) onTrace(event)
    },
    onError,
    { lastEventId },
  )
}

/**
 * Subscribe to one run's own trace SSE (`/v1/runs/{id}/stream`, FR-046).
 *
 * Raw on purpose. `subscribeTaskTrace` above maps into the Room's view-model, which drops
 * whatever it cannot draw as a chat bubble — the right thing for a conversation and the wrong
 * thing for a log, where *every* event is the point and the filter works on the real type
 * names (FR-052). So this hands back what the server sent.
 *
 * The four facts about the record arrive folded into the payload here, under underscored names,
 * because a push has no payload wrapper to put them beside. They are lifted back out to the
 * shape the stored log uses, so a screen reading the same run two ways sees it one way.
 */
export function subscribeRunTrace(
  runId: string,
  onEvent: (event: RunEventDTO) => void,
  onError?: (error: Error) => void,
): () => void {
  const url = `${API_BASE}/v1/runs/${runId}/stream`
  return subscribeSSE(
    url,
    (msg) => {
      const frame = parseData(msg.data) as Record<string, unknown> | null
      if (!frame || typeof frame !== 'object') return
      const payload = (frame.payload ?? {}) as Record<string, unknown>
      const seq = typeof frame.seq === 'number' ? frame.seq : Number(payload._seq)
      if (!Number.isFinite(seq)) return
      // Beside the payload when the row came out of the store, folded into it under underscored
      // names when it came off the live bus — a push has no payload wrapper to put them beside.
      // Read both, because the backlog and the tail arrive down the same pipe and a reader must
      // not be shown two versions of one run depending on which half an event landed in.
      const size = Number(frame.original_byte_size ?? payload._original_byte_size)
      const reason = frame.omission_reason ?? payload._omission_reason
      const field = frame.full_field ?? payload._full_field
      const fullSize = Number(frame.full_byte_size ?? payload._full_byte_size)
      onEvent({
        seq,
        type: String(frame.type ?? msg.type ?? ''),
        payload,
        truncated: Boolean(frame.truncated ?? payload._truncated),
        original_byte_size: Number.isFinite(size) ? size : null,
        omission_reason: reason ? String(reason) : null,
        redacted: Boolean(frame.redacted ?? payload._redacted),
        full_field: field ? String(field) : null,
        full_byte_size: Number.isFinite(fullSize) ? fullSize : null,
        created_at: frame.created_at ? String(frame.created_at) : new Date().toISOString(),
      })
    },
    onError,
  )
}

/**
 * Subscribe to the project-level Chat-with-Leader SSE (`/v1/projects/{id}/leader-chat/stream`, #82).
 *
 * The Leader's reply streams here as `assistant.delta` events; `chat.state` marks the
 * turn's lifecycle and `leader.message` carries the final durable reply. The callback
 * receives the raw `{ type, data }` (data already JSON-parsed) — the chat page interprets it.
 */
export function subscribeLeaderChat(
  projectId: string,
  onEvent: (event: { type: string; data: Record<string, unknown> }) => void,
  onError?: (error: Error) => void,
): () => void {
  const url = `${API_BASE}/v1/projects/${projectId}/leader-chat/stream`
  return subscribeSSE(
    url,
    (msg) => {
      const parsed = parseData(msg.data)
      onEvent({ type: msg.type, data: (parsed ?? {}) as Record<string, unknown> })
    },
    onError,
  )
}

/**
 * Subscribe to the project board SSE (`/v1/projects/{id}/events`, spec 001).
 *
 * Carries phase changes, task status changes, stall flags and plan decisions. The
 * callback receives the raw `{ type, data }` (data already JSON-parsed) — events are a
 * signal, not the source of truth: on receipt the page re-reads the slice it needs.
 */
export function subscribeProjectEvents(
  projectId: string,
  onEvent: (event: { type: string; data: Record<string, unknown> }) => void,
  onError?: (error: Error) => void,
  lastEventId?: string | number,
): () => void {
  const url = `${API_BASE}/v1/projects/${projectId}/events`
  return subscribeSSE(
    url,
    (msg) => {
      onEvent({ type: msg.type, data: (parseData(msg.data) ?? {}) as Record<string, unknown> })
    },
    onError,
    { lastEventId },
  )
}

/**
 * Subscribe to the caller's inbox SSE (`/v1/inbox/events`, spec 001).
 *
 * Keyed server-side by the authenticated user — there is no id to pass, and no way to
 * watch anyone else's inbox. This is what keeps the Inbox page off a polling loop
 * (Constitution IV).
 */
export function subscribeInboxEvents(
  onEvent: (event: { type: string; data: Record<string, unknown> }) => void,
  onError?: (error: Error) => void,
  lastEventId?: string | number,
): () => void {
  const url = `${API_BASE}/v1/inbox/events`
  return subscribeSSE(
    url,
    (msg) => {
      onEvent({ type: msg.type, data: (parseData(msg.data) ?? {}) as Record<string, unknown> })
    },
    onError,
    { lastEventId },
  )
}

function parseData(data: unknown): unknown {
  if (typeof data === 'string') {
    try {
      return JSON.parse(data)
    } catch {
      return { raw: data }
    }
  }
  return data
}
