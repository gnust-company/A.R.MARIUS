// The two lists a runtime picker reads: what may be picked, and every machine with what it
// reported (spec 003 FR-122, FR-125).
//
// Read together and replaced together, so the picker never shows a ready list from one moment
// beside a machine list from another for longer than one read. Nothing here listens for
// changes: the first steps sit outside the workspace layout and open their own stream, the agent
// page rides the layout's — each caller calls `reload` when `machine.workplaces_reported`
// arrives (Constitution IV: pushed, never polled).

import { useCallback, useEffect, useState } from 'react'

import { listMachines, listWorkplaces, type MachineDTO, type WorkplaceChoiceDTO } from '@/lib/api'

export interface RuntimeOffer {
  ready: WorkplaceChoiceDTO[]
  machines: MachineDTO[]
  /** True until the first read has come back, whichever way it went. */
  loading: boolean
  /** The last read failed. The lists keep what the read before it said. */
  failed: boolean
  reload: () => void
}

export function useRuntimeOffer(workspaceId: string | null | undefined): RuntimeOffer {
  const [ready, setReady] = useState<WorkplaceChoiceDTO[]>([])
  const [machines, setMachines] = useState<MachineDTO[]>([])
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)

  const reload = useCallback(() => {
    if (!workspaceId) return
    Promise.all([listWorkplaces(workspaceId), listMachines(workspaceId)])
      .then(([readyRows, machineRows]) => {
        setReady(readyRows)
        setMachines(machineRows)
        setFailed(false)
      })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false))
  }, [workspaceId])

  useEffect(() => {
    reload()
  }, [reload])

  return { ready, machines, loading, failed, reload }
}
