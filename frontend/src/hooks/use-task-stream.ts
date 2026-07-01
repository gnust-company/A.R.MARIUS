// Real per-task trace SSE (Sprint 6). Under MOCK this is a no-op — the CollaborationRoom
// fakes scripted run events on an interval. Under the real API it opens
// `/v1/tasks/{id}/stream` and appends each wake-run event to the task's trace.

import { useEffect } from 'react'

import { subscribeTaskTrace } from '@/lib/sse'
import { useMockStore } from '@/store/mockStore'

export function useTaskStream(taskId: string | null | undefined): void {
  const isMock = useMockStore((s) => s.isMock)
  const appendTrace = useMockStore((s) => s.appendTrace)

  useEffect(() => {
    if (isMock || !taskId) return
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
  }, [isMock, taskId, appendTrace])
}
