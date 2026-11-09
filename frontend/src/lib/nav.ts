import { BookOpen, CalendarDays, KanbanSquare, Mail, Monitor, Telescope, Users } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

/** Store fields a nav row may show a number from. One today; add a name, not a branch. */
export type CounterName = 'inboxPending';

export interface NavItem {
  path: string;
  labelKey: string;
  icon: LucideIcon;
  /** Which store count rides beside this label. A count is the only honest form of that mark:
   *  a constant dot would be lit on an empty inbox and on a full one alike. */
  counter?: CounterName;
}

/** The three groups of DESIGN's sidebar: see the whole, run the work, look after the team. */
export const NAV_GROUPS: { labelKey: string; items: NavItem[] }[] = [
  {
    labelKey: 'nav.groupOverview',
    items: [
      { path: '/observatory', labelKey: 'nav.observatory', icon: Telescope },
      { path: '/home', labelKey: 'nav.home', icon: CalendarDays },
    ],
  },
  {
    labelKey: 'nav.groupOperate',
    items: [
      { path: '/projects', labelKey: 'nav.projects', icon: KanbanSquare },
      { path: '/inbox', labelKey: 'nav.inbox', icon: Mail, counter: 'inboxPending' },
    ],
  },
  {
    labelKey: 'nav.groupTeam',
    items: [
      { path: '/agents', labelKey: 'nav.directory', icon: Users },
      { path: '/machines', labelKey: 'nav.machines', icon: Monitor },
      { path: '/skills', labelKey: 'nav.skills', icon: BookOpen },
    ],
  },
];

/** Two letters for a name: the first letters of its first two words, else its first two. */
export function initials(name: string | undefined) {
  const words = (name || '').trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) return '·';
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

/** Which nav row a sub-path belongs to (the path after /w/:workspaceId). */
export function activeNavPath(sub: string): string | null {
  if (sub === '/' || sub.startsWith('/home')) return '/home';
  // A task belongs to a project, so the task page keeps "Projects" lit; a run belongs to a task.
  if (sub.startsWith('/projects') || sub.startsWith('/tasks') || sub.startsWith('/runs')) return '/projects';
  for (const group of NAV_GROUPS) {
    for (const item of group.items) if (sub.startsWith(item.path)) return item.path;
  }
  return null;
}

