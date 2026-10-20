// How far the *connect a machine* step has got, read off the server (spec 003 FR-120, R5).
//
// Off the server and not out of this tab's memory, because reloading the page or opening it on
// another computer has to land in the same place (FR-104). The one thing the tab adds is having
// heard `machine.linked`: between approving a machine and its daemon collecting its papers there
// are a few seconds with no machine row at all, and in those seconds the approval is still real.

import type { MachineDTO } from './api'

export interface ConnectProgress {
  /** A machine has been approved into this workspace. Installing has no mark of its own: the
   *  system cannot see it, and a linked machine is proof enough that it happened. */
  linked: boolean
  /** A machine has reported its runtimes, ready or not. This is what `armarius-daemon start`
   *  does, and the step is waiting for nothing else. */
  running: boolean
}

export function connectProgress(
  machines: readonly Pick<MachineDTO, 'workplaces'>[],
  heardLinked: boolean,
): ConnectProgress {
  const running = machines.some((machine) => machine.workplaces.length > 0)
  return { linked: heardLinked || machines.length > 0, running }
}
