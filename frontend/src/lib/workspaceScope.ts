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
