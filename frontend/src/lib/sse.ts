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
                onMessage({ type: currentType, data: currentData, id: currentId })
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
              currentData = line.slice(5).trim()
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
