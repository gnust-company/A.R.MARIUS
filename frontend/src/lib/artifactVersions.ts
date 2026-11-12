/**
 * Which published file is the current one, when a name was published more than once.
 *
 * An agent that fixes a file publishes it again under the same name. The list then shows the
 * name twice with nothing to tell the two apart — a patron about to sign could not see which
 * `script.js` was the corrected one, and neither could the Leader (found 2026-11-12). The
 * server keeps every version on purpose; saying which is which is the screen's job.
 *
 * Order is the list's own: the server hands artifacts back oldest first, and a later row of
 * the same name replaces an earlier one.
 */
export interface Versioned<T> {
  artifact: T
  /** 1 for the first publish of this name, 2 for the next, and so on. */
  version: number
  /** How many times this name was published. 1 means there is nothing to tell apart. */
  of: number
  /** Whether this is the newest publish of its name. */
  current: boolean
}

/** A file with no name is its own file: two unnamed rows are not two versions of anything. */
const nameOf = (artifact: { name?: string }, index: number) => artifact.name || `\u0000${index}`

export function withVersions<T extends { name?: string }>(artifacts: readonly T[]): Versioned<T>[] {
  const total = new Map<string, number>()
  artifacts.forEach((artifact, i) => total.set(nameOf(artifact, i), (total.get(nameOf(artifact, i)) ?? 0) + 1))
  const seen = new Map<string, number>()
  return artifacts.map((artifact, i) => {
    const name = nameOf(artifact, i)
    const version = (seen.get(name) ?? 0) + 1
    seen.set(name, version)
    const of = total.get(name) ?? 1
    return { artifact, version, of, current: version === of }
  })
}

/** Only the newest publish of each name, in the order the names first appeared. */
export function currentOnly<T extends { name?: string }>(artifacts: readonly T[]): Versioned<T>[] {
  const firstSeen = new Map<string, number>()
  artifacts.forEach((artifact, i) => {
    if (!firstSeen.has(nameOf(artifact, i))) firstSeen.set(nameOf(artifact, i), i)
  })
  return withVersions(artifacts)
    .map((row, i) => ({ row, at: firstSeen.get(nameOf(row.artifact, i)) ?? i }))
    .filter(({ row }) => row.current)
    .sort((a, b) => a.at - b.at)
    .map(({ row }) => row)
}
