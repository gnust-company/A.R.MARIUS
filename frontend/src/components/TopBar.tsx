import { useLocation, Link } from 'react-router';
import { motion } from 'framer-motion';
import { Menu, Search, Wifi, WifiOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/store/appStore';
import { cn, wsHref } from '@/lib/utils';

// Known route segments → i18n nav keys (project/workspace names stay as data)
const SEGMENT_KEYS: Record<string, string> = {
  home: 'nav.home',
  projects: 'nav.projects',
  agents: 'nav.directory',
  machines: 'nav.machines',
  skills: 'nav.skills',
  inbox: 'nav.inbox',
  account: 'nav.account',
  roster: 'board.roster',
  plan: 'projectPlan.title',
  'leader-chat': 'leaderChat.title',
};

const UUID_LIKE = /^[0-9a-f]{8}-[0-9a-f]{4}/i;

function useBreadcrumbs() {
  const { t } = useTranslation();
  const location = useLocation();
  const workspaces = useAppStore((s) => s.workspaces);
  const projects = useAppStore((s) => s.projects);
  const tasks = useAppStore((s) => s.tasks);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);

  const raw = location.pathname.split('/').filter(Boolean);
  // Strip the `/w/:workspaceId` prefix — the workspace gets its own crumb below.
  const segments = raw[0] === 'w' ? raw.slice(2) : raw;

  const crumbs: { label: string; path?: string }[] = [];

  // Workspace crumb → up to the projects list (stays in-workspace).
  const ws = workspaces.find((w) => w.id === activeWorkspaceId);
  crumbs.push({
    label: ws?.name || t('nav.workspace'),
    path: activeWorkspaceId ? wsHref(activeWorkspaceId, '/home') : '/workspaces',
  });

  if (segments.length === 0) {
    crumbs.push({ label: t('nav.home') });
    return crumbs;
  }

  segments.forEach((seg, i) => {
    const isLast = i === segments.length - 1;

    // A project id → show its name, link to its board (unless it's the last crumb).
    const project = projects.find((pr) => pr.id === seg);
    if (project) {
      crumbs.push({
        label: project.name,
        path: isLast ? undefined : wsHref(activeWorkspaceId, `/projects/${seg}`),
      });
      return;
    }
    // `/tasks/:id` → the task's project (back to its board), then the task's identifier.
    if (seg === 'tasks') {
      const task = tasks.find((tk) => tk.id === segments[i + 1]);
      const owner = task && projects.find((pr) => pr.id === task.projectId);
      if (owner) crumbs.push({ label: owner.name, path: wsHref(activeWorkspaceId, `/projects/${owner.id}`) });
      return;
    }
    const taskHere = segments[i - 1] === 'tasks' ? tasks.find((tk) => tk.id === seg) : undefined;
    if (taskHere) {
      crumbs.push({ label: taskHere.identifier || taskHere.title });
      return;
    }
    if (seg === 'new') {
      crumbs.push({ label: t('nav.new') });
      return;
    }
    if (SEGMENT_KEYS[seg]) {
      // Top-level list segments link to their in-workspace page; sub-page labels don't.
      const listPath =
        seg === 'roster' || seg === 'plan' || seg === 'leader-chat'
          ? undefined
          : wsHref(activeWorkspaceId, `/${seg}`);
      crumbs.push({ label: t(SEGMENT_KEYS[seg]), path: isLast ? undefined : listPath });
      return;
    }
    // Unresolved id-like segment (agent/task/skill id not in the store) — skip the raw
    // UUID rather than rendering a mangled string.
    if (UUID_LIKE.test(seg)) return;
    const label = seg.charAt(0).toUpperCase() + seg.slice(1).replace(/-/g, ' ');
    crumbs.push({ label });
  });

  return crumbs;
}

export default function TopBar() {
  const { t } = useTranslation();
  const sseConnected = useAppStore((s) => s.sseConnected);
  const currentUser = useAppStore((s) => s.currentUser);
  const crumbs = useBreadcrumbs();
  const setDrawerOpen = useAppStore((s) => s.setNavDrawerOpen);

  return (
    <header className="sticky top-0 z-sticky h-14 bg-inset/95 backdrop-blur-sm border-b border-line flex items-center justify-between gap-3 px-4 sm:px-6 xl:px-9">
      {/* Phone: no rail, so the drawer opens from here; the last crumb names the page. */}
      <div className="flex sm:hidden items-center gap-2 min-w-0">
        <button
          onClick={() => setDrawerOpen(true)}
          className="-ml-2 w-11 h-11 flex items-center justify-center rounded-md text-ink hover:bg-paper"
          aria-label={t('nav.expandSidebar')}
        >
          <Menu className="w-5 h-5" />
        </button>
        <span className="font-body text-body-md font-medium text-ink truncate">{crumbs[crumbs.length - 1]?.label}</span>
      </div>

      {/* Breadcrumbs */}
      <nav className="hidden sm:flex items-center gap-2 font-body text-body-md text-ink-muted min-w-0 truncate">
        {crumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-2">
            {i > 0 && <span className="text-ink-muted">/</span>}
            {crumb.path ? (
              <Link to={crumb.path} className="hover:text-terracotta transition-colors">
                {crumb.label}
              </Link>
            ) : (
              <span className={i === crumbs.length - 1 ? 'text-ink font-medium' : ''}>
                {crumb.label}
              </span>
            )}
          </span>
        ))}
      </nav>

      {/* Right side */}
      <div className="flex items-center gap-2 sm:gap-4 ml-auto shrink-0">
        {/* SSE Indicator */}
        <motion.div
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-body-xs font-medium whitespace-nowrap',
            sseConnected ? 'bg-verdigris-bg text-verdigris-ink' : 'bg-ash-bg text-ink-light'
          )}
          animate={sseConnected ? { opacity: [1, 0.7, 1] } : {}}
          transition={{ duration: 2, repeat: Infinity, ease: 'easeInOut' }}
        >
          {sseConnected ? (
            <>
              <Wifi className="w-3 h-3" />
              <span>{t('topbar.live')}</span>
            </>
          ) : (
            <>
              <WifiOff className="w-3 h-3" />
              <span>{t('topbar.reconnecting')}</span>
            </>
          )}
        </motion.div>

        {/* Search */}
        <button
          className="p-2 rounded-md text-ink-muted hover:text-terracotta hover:bg-paper transition-colors"
          aria-label={t('common.search')}
        >
          <Search className="w-[18px] h-[18px]" />
        </button>

        {/* Profile */}
        <div className="flex items-center gap-2">
          <div
            className={cn(
              'w-9 h-9 rounded-full bg-paper border-[1.5px] flex items-center justify-center text-body-sm font-semibold text-gold-ink',
              sseConnected ? 'border-gold' : 'border-line'
            )}
          >
            {currentUser?.name?.charAt(0).toUpperCase() || 'P'}
          </div>
        </div>
      </div>
    </header>
  );
}
