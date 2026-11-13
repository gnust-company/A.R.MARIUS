/**
 * Which signatures still speak for the work in review (FR-033a).
 *
 * The server records it: a signature is `superseded` once the work went back, because what
 * it signed no longer exists. This screen used to work the same thing out for itself — from
 * a `round` the server sent as 1 on every row — so after one rejection it looked for a
 * round-2 signature that could not exist, and the patron's own buttons stayed disabled for
 * the rest of the task's life (found 2026-11-13). Read, not derived.
 */
export interface Signed {
  signer_kind: string
  result: string
  superseded?: boolean | null
}

/** The signatures standing on what is in review now, in the order they were given. */
export function standing<T extends Signed>(signatures: readonly T[]): T[] {
  return signatures.filter((one) => !one.superseded)
}

/** Has the Leader passed the work now in review? The patron signs only after that (FR-033). */
export function leaderHasSigned(signatures: readonly Signed[]): boolean {
  return standing(signatures).some((one) => one.signer_kind === 'leader' && one.result === 'approve')
}
