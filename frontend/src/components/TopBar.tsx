import { Fragment } from 'react';
import { useLocation, Link } from 'react-router';
import { Bell, ChevronRight, Menu, Search } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/store/appStore';
import { cn, wsHref } from '@/lib/utils';
import ThemeSwitch from './ThemeSwitch';

// Known route segments → i18n nav keys (project/workspace names stay as data)
const SEGMENT_KEYS: Record<string, string> = {
  home: 'nav.home',
  observatory: 'nav.observatory',
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
  const projects = useAppStore((s) => s.projects);
  const tasks = useAppStore((s) => s.tasks);
  const mariuses = useAppStore((s) => s.mariuses);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);

  const raw = location.pathname.split('/').filter(Boolean);
  // Strip the `/w/:workspaceId` prefix — the workspace is the leading label of the bar.
  const segments = raw[0] === 'w' ? raw.slice(2) : raw;

  const crumbs: { label: string; path?: string }[] = [];

  if (segments.length === 0) {
    crumbs.push({ label: t('nav.home') });
    return crumbs;
  }

  segments.forEach((seg, i) => {
    const isLast = i === segments.length - 1;

    // A project id → its name, linking to its board (unless it's the last crumb).
    const project = projects.find((pr) => pr.id === seg);
    if (project) {
      crumbs.push({ label: project.name, path: isLast ? undefined : wsHref(activeWorkspaceId, `/projects/${seg}`) });
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
    const agentHere = segments[i - 1] === 'agents' ? mariuses.find((m) => m.id === seg) : undefined;
    if (agentHere) {
      crumbs.push({ label: agentHere.displayName || agentHere.name });
      return;
    }
    if (seg === 'new') {
      crumbs.push({ label: t('nav.new') });
      return;
    }
    if (SEGMENT_KEYS[seg]) {
      // Top-level list segments link to their in-workspace page; sub-page labels don't.
      const listPath =
        seg === 'roster' || seg === 'plan' || seg === 'leader-chat' ? undefined : wsHref(activeWorkspaceId, `/${seg}`);
      crumbs.push({ label: t(SEGMENT_KEYS[seg]), path: isLast ? undefined : listPath });
      return;
    }
    // Unresolved id-like segment (an id not in the store yet) — skip the raw UUID.
    if (UUID_LIKE.test(seg)) return;
    crumbs.push({ label: seg.charAt(0).toUpperCase() + seg.slice(1).replace(/-/g, ' ') });
  });

  return crumbs;
}

/** The bar above every in-workspace page: where you are, search (⌘K), theme, and the inbox. */
export default function TopBar({ onOpenCommand }: { onOpenCommand: () => void }) {
  const { t } = useTranslation();
  const crumbs = useBreadcrumbs();
  const setDrawerOpen = useAppStore((s) => s.setNavDrawerOpen);
  const workspaces = useAppStore((s) => s.workspaces);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const inboxPending = useAppStore((s) => s.inboxPending);
  const ws = workspaces.find((w) => w.id === activeWorkspaceId);
  const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform);

  return (
    <header className="sticky top-0 z-sticky h-[60px] md:h-[72px] flex items-center gap-3 md:gap-6 px-4 sm:px-6 xl:px-8 border-b border-line bg-canvas/90 backdrop-blur-[18px]">
      {/* Phone: no rail, so the drawer opens from here. */}
      <button
        type="button"
        onClick={() => setDrawerOpen(true)}
        className="md:hidden -ml-2 w-11 h-11 grid place-items-center rounded-full text-ink-light hover:bg-surface-hover hover:text-ink-strong"
        aria-label={t('nav.expandSidebar')}
      >
        <Menu className="w-[22px] h-[22px]" />
      </button>

      <nav aria-label={t('nav.breadcrumb')} className="hidden md:flex items-center gap-2 min-w-0 whitespace-nowrap">
        <Link
          to={wsHref(activeWorkspaceId, '/home')}
          className="font-mono text-[10px] uppercase tracking-[0.11em] text-ink-muted hover:text-ink-strong truncate max-w-[200px]"
        >
          {ws?.name || t('nav.workspace')}
        </Link>
        {crumbs.map((crumb, i) => {
          const last = i === crumbs.length - 1;
          return (
            <Fragment key={i}>
              <ChevronRight className="w-3 h-3 shrink-0 text-ink-muted" />
              {crumb.path ? (
                <Link to={crumb.path} className="text-[13px] text-ink-light hover:text-ink-strong truncate max-w-[220px]">
                  {crumb.label}
                </Link>
              ) : (
                <strong className={cn('text-[13px] truncate max-w-[260px]', last ? 'font-semibold text-ink-strong' : 'font-normal text-ink-light')}>
                  {crumb.label}
                </strong>
              )}
            </Fragment>
          );
        })}
      </nav>

      {/* Search: a full trigger from md up, an icon on a phone (DESIGN §9 mobile). */}
      <button
        type="button"
        onClick={onOpenCommand}
        className="hidden md:flex items-center gap-2.5 w-[min(360px,32vw)] min-h-[40px] mx-auto px-3 rounded-md border border-line-strong bg-surface/60 text-[13px] text-ink-muted hover:border-sapphire hover:text-ink transition-colors"
      >
        <Search className="w-[17px] h-[17px] shrink-0" />
        <span className="flex-1 text-left truncate">{t('command.trigger')}</span>
        <kbd className="kbd">{isMac ? '⌘' : 'Ctrl'} K</kbd>
      </button>
      <button
        type="button"
        onClick={onOpenCommand}
        className="md:hidden mx-auto w-11 h-11 grid place-items-center rounded-full border border-line-strong text-ink-light hover:text-ink-strong"
        aria-label={t('command.trigger')}
      >
        <Search className="w-5 h-5" />
      </button>

      <div className="flex items-center gap-2 md:gap-3 shrink-0">
        <ThemeSwitch compact className="lg:hidden" />
        <ThemeSwitch className="hidden lg:flex" />
        <Link
          to={wsHref(activeWorkspaceId, '/inbox')}
          className="relative w-11 h-11 grid place-items-center rounded-full text-ink-light hover:bg-surface-hover hover:text-ink-strong"
          aria-label={t('nav.inboxWaiting', { count: inboxPending })}
        >
          <Bell className="w-5 h-5" strokeWidth={1.7} />
          {inboxPending > 0 && (
            <b className="absolute top-[3px] right-px grid place-items-center min-w-[18px] h-[18px] px-1 rounded-full border-2 border-canvas bg-amber text-[10px] font-semibold text-[oklch(0.23_0.03_70)]">
              {inboxPending > 99 ? '99+' : inboxPending}
            </b>
          )}
        </Link>
      </div>
    </header>
  );
}
