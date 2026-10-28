// What may be picked for one setting, given what the others are set to (FR-007k, revised
// 2026-10-26).
//
// A tool can say that picking one value narrows another setting — Claude Code says which effort
// levels each of its models takes, and one takes none. The rule arrives as data keyed by the
// settings' own keys, so nothing here knows which key is a model. Kept out of the form so it can
// be tested without a DOM (vitest.config.ts runs in Node).

import type { PlacementOption } from '@/store/appStore'

/** A list the person may only pick from, as opposed to one they may type past. */
export function isClosed(option: PlacementOption): boolean {
  return option.source === 'tool_declared' || option.source === 'known_names'
}

/** The readable name the tool gave a value, or the value itself. */
export function labelOf(option: PlacementOption, value: string): string {
  return option.labels?.[value] || value
}

/**
 * What `key` may take given every other setting's value, or `null` when nothing narrows it.
 * Two settings narrowing the same one leave what both allow. An empty list is an answer: only
 * blank.
 */
export function narrowedTo(
  options: readonly PlacementOption[],
  chosen: Readonly<Record<string, string>>,
  key: string,
): string[] | null {
  let allowed: string[] | null = null
  for (const other of options) {
    if (other.key === key) continue
    const picked = chosen[other.key]
    if (!picked) continue
    const rule = other.narrows?.[picked]?.[key]
    if (!rule) continue
    allowed = allowed === null ? [...rule] : allowed.filter((value) => rule.includes(value))
  }
  return allowed
}

/** The values to offer for one setting: its own list, narrowed by the others. */
export function offeredValues(
  options: readonly PlacementOption[],
  chosen: Readonly<Record<string, string>>,
  option: PlacementOption,
): string[] {
  const narrowed = narrowedTo(options, chosen, option.key)
  if (narrowed === null) return option.values
  return isClosed(option) ? option.values.filter((value) => narrowed.includes(value)) : narrowed
}

/**
 * Pick `value` for `key`, and put back to blank every other setting the new value leaves out.
 *
 * Returns only what changes, the picked setting first. Blanking rather than keeping is what the
 * person would otherwise have to discover by being refused: a level the new model does not take
 * cannot be saved, and blank — the tool's own default — always can.
 */
export function choose(
  options: readonly PlacementOption[],
  chosen: Readonly<Record<string, string>>,
  key: string,
  value: string,
): Record<string, string> {
  const next: Record<string, string> = { ...chosen, [key]: value }
  const changes: Record<string, string> = { [key]: value }
  for (const other of options) {
    if (other.key === key) continue
    const current = next[other.key]
    if (!current) continue
    const narrowed = narrowedTo(options, next, other.key)
    if (narrowed !== null && !narrowed.includes(current)) {
      next[other.key] = ''
      changes[other.key] = ''
    }
  }
  return changes
}
