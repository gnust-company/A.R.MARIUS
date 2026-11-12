/**
 * The agents of one workspace, out of the store's list of every workspace's agents (FR-007q).
 *
 * The store holds every workspace's agents in one list so the workspace picker can count each
 * one's agents from first paint. That makes every screen about *one* workspace responsible for
 * narrowing it, and three of them did not: the agents page, project creation and inviting an
 * agent to a project all offered agents from other workspaces — which the server then refused.
 * The rule lives here so the next screen that needs the list goes through it instead of
 * remembering to filter.
 *
 * No workspace yet means nobody, not everybody: answering with the whole list is the original
 * bug again, only during the moment the app is still finding out where it is.
 */
export function agentsOf<T extends { workspaceId: string }>(
  agents: readonly T[],
  workspaceId: string | null | undefined,
): T[] {
  if (!workspaceId) return []
  return agents.filter((agent) => agent.workspaceId === workspaceId)
}

/**
 * The letters of one workspace, out of everything waiting on this person.
 *
 * The inbox is answered per person — a letter is addressed to somebody, not to a workspace —
 * so the server hands back every workspace's letters in one list. The inbox screen, the badge
 * beside it and the home page each sit **inside** one workspace, and two of the three showed
 * the whole list: a workspace with a single finished project carried four stalled tasks from
 * another one, with links that led out of the workspace the reader was in (found 2026-11-12).
 *
 * A letter that names no workspace belongs to whichever one is asking. That is how rows older
 * than the field read, and dropping them would hide a decision somebody is still waiting on.
 */
export function lettersOf<T extends { workspace_id?: string | null }>(
  letters: readonly T[],
  workspaceId: string | null | undefined,
): T[] {
  if (!workspaceId) return []
  return letters.filter((letter) => !letter.workspace_id || letter.workspace_id === workspaceId)
}
