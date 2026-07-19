// Per-task trace SSE (Sprint 6): opens `/v1/tasks/{id}/stream` and appends each
// wake-run event to the task's trace.

import { useEffect } from 'react'

import { subscribeTaskTrace } from '@/lib/sse'
import { useAppStore } from '@/store/appStore'

export function useTaskStream(taskId: string | null | undefined): void {
  const appendTrace = useAppStore((s) => s.appendTrace)

  useEffect(() => {
    if (!taskId) return
    const disconnect = subscribeTaskTrace(
      taskId,
      (event) => {
        appendTrace(taskId, {
          type: event.type,
          content: event.content,
          agentId: event.agentId,
          model: event.model,
          toolName: event.toolName,
          args: event.args,
          tokens: event.tokens,
        })
      },
      (err) => console.error('[task SSE]', err.message),
    )
    return disconnect
  }, [taskId, appendTrace])
}
