// Rebuild a task's full trace from the durable run history (#113): every run (turn) in
// order, each run's events mapped to trace view-models. This is the backfill that makes
// reopening / tabbing back into a Room show the whole session, not just what the live SSE
// stream happened to catch. Owned by `hydrateTask` (single writer) so it can't race the
// task's own hydration.

import { listRunEvents, listTaskRuns } from '@/lib/api'
import { traceEventFromVM } from '@/lib/mappers'
import type { TraceEvent } from '@/store/appStore'

export async function loadTaskTrace(taskId: string): Promise<TraceEvent[]> {
  const runs = await listTaskRuns(taskId)
  // Oldest turn first so the trace reads top-to-bottom in chronological order.
  runs.sort((a, b) => (a.created_at ?? '').localeCompare(b.created_at ?? ''))
  const out: TraceEvent[] = []
  for (const run of runs) {
    const events = await listRunEvents(run.id)
    for (const e of events) {
      const mapped = traceEventFromVM(
        { event_type: e.type, payload: e.payload },
        { id: `${run.id}:${e.seq}`, timestamp: e.created_at ?? undefined, taskId },
      )
      if (mapped) out.push(mapped)
    }
  }
  return out
}
