// Per-task LIVE trace tail (#113). The durable backfill (every run, in order) is done by
// `hydrateTask` so it can't race the task's own hydration; this hook only live-tails
// `/v1/tasks/{id}/stream` and appends new events. Events carry stable ids, so any overlap
// between the SSE backlog replay and the backfill is de-duplicated in `appendTrace`.

import { useEffect } from 'react'

import { subscribeTaskTrace } from '@/lib/sse'
import { useAppStore } from '@/store/appStore'

export function useTaskStream(taskId: string | null | undefined): void {
  const appendTrace = useAppStore((s) => s.appendTrace)

  useEffect(() => {
    if (!taskId) return
    const disconnect = subscribeTaskTrace(
      taskId,
      (event) =>
        appendTrace(taskId, {
          id: event.id,
          type: event.type,
          content: event.content,
          agentId: event.agentId,
          model: event.model,
          toolName: event.toolName,
          args: event.args,
          tokens: event.tokens,
          timestamp: event.timestamp,
        }),
      (err) => console.error('[task SSE]', err.message),
    )
    return disconnect
  }, [taskId, appendTrace])
}
