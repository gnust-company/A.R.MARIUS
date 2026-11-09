// What an agent is holding right now, shared by the agent list and the agent's own page so the
// two screens cannot disagree about it.
import { useEffect } from 'react';
import { useAppStore } from '@/store/appStore';
import type { Task } from '@/store/appStore';

/** Which of an agent's tasks says most about what it is doing — running beats waiting. */
const HOLDING_ORDER = ['in_progress', 'in_review', 'blocked', 'todo'];

/** The agent's tasks that are still open, most telling first. */
export function heldTasks(tasks: Task[], agentId: string): Task[] {
  const own = tasks.filter((tk) => tk.assigneeId === agentId);
  return HOLDING_ORDER.flatMap((st) => own.filter((tk) => tk.status === st));
}

/**
 * Tasks are loaded per project, so a screen that says what an agent holds has to ask for the
 * active workspace's projects first. Re-runs only when the set of projects changes.
 */
export function useHydrateWorkspaceTasks() {
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const allProjects = useAppStore((s) => s.projects);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const projectKey = allProjects
    .filter((p) => p.workspaceId === activeWorkspaceId)
    .map((p) => p.id)
    .join(',');
  useEffect(() => {
    projectKey.split(',').filter(Boolean).forEach((id) => void hydrateProject(id).catch(() => {}));
  }, [projectKey, hydrateProject]);
}
