// Which runtime a host is about to be put on, and which ones it cannot be (spec 003 FR-125).
//
// Kept out of the picker so the rule can be tested without a DOM: the test runner here is
// Node only (vitest.config.ts), and this rule is the part a mistake in would cost the most —
// a host put on the wrong runtime stays there for life (FR-007).

import type { MachineDTO, WorkplaceChoiceDTO } from './api'

/** A runtime that is on a machine but cannot take an agent right now, and why. */
export interface UnavailableRuntime {
  id: string
  cliKind: string
  machineName: string
  /** A code for `machines.notReady.*`, never a sentence (Constitution VII). */
  reason: string
}

/**
 * What is picked before anybody picks.
 *
 * Exactly one ready runtime is not a choice, so it is made — and shown, so the person sees it
 * before they press the button. Two or more is a choice, and the system does not make it for
 * them: picking the first would be the very rule FR-112 took away, a rule that means nothing to
 * the person it affects.
 */
export function initialRuntimeChoice(ready: readonly Pick<WorkplaceChoiceDTO, 'id'>[]): string | null {
  return ready.length === 1 ? ready[0].id : null
}

/**
 * What is picked now: the person's pick while it is still on offer, otherwise the default.
 *
 * Derived on every render rather than stored, because the list changes under the person — a
 * daemon stopping takes its runtime away (`machine.workplaces_reported`). A stored pick would
 * keep pointing at a runtime that is gone and send it to the server.
 */
export function currentRuntimeChoice(
  ready: readonly Pick<WorkplaceChoiceDTO, 'id'>[],
  picked: string | null,
): string | null {
  if (picked && ready.some((one) => one.id === picked)) return picked
  return initialRuntimeChoice(ready)
}

/**
 * Every runtime the machines report that is not on offer, with the reason it is not.
 *
 * The ready list says what may be picked and nothing else. Without this half, a person whose
 * only CLI is not logged in sees an empty list and no idea why (spec 003, the edge case of a
 * machine that runs but has no ready runtime).
 */
export function unavailableRuntimes(
  machines: readonly MachineDTO[],
  ready: readonly Pick<WorkplaceChoiceDTO, 'id'>[],
): UnavailableRuntime[] {
  const offered = new Set(ready.map((one) => one.id))
  return machines.flatMap((machine) =>
    machine.workplaces
      .filter((place) => !offered.has(place.id))
      .map((place) => ({
        id: place.id,
        cliKind: place.cli_kind,
        machineName: machine.display_name,
        reason:
          place.not_ready_reason ?? (machine.reachable ? 'unknown' : 'machine_unreachable'),
      })),
  )
}
