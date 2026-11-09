import { useState, useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Home,
  LayoutDashboard,
  Users,
  Laptop,
  Wrench,
  Inbox,
  Settings,
  Palette,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Check,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore, type AgentStatus } from '@/store/appStore';
import { useViewport } from '@/hooks/use-viewport';
import { cn, wsHref } from '@/lib/utils';

// `external: true` = a top-level route (no workspace prefix), e.g. the launcher.
// `counter` names a store field whose number rides beside the label. It replaced a `badge: true`
// that painted the dot beside the inbox unconditionally — lit on an empty inbox, lit on a full
// one. A count is the only honest form of that mark, and a constant cannot be one.
/** Store fields a nav row may show a number from. One today; add a name, not a branch. */
type CounterName = 'inboxPending';

interface NavItem {
  path: string;
  labelKey: string;
  icon: LucideIcon;
  /** A top-level route with no workspace prefix, e.g. the launcher. */
  external?: boolean;
  /** Which store count rides beside this label. */
  counter?: CounterName;
}

const NAV_ITEMS: NavItem[] = [
  { path: '/home', labelKey: 'nav.home', icon: Home },
  { path: '/inbox', labelKey: 'nav.inbox', icon: Inbox, counter: 'inboxPending' },
  { path: '/projects', labelKey: 'nav.projects', icon: LayoutDashboard },
  { path: '/agents', labelKey: 'nav.directory', icon: Users },
  { path: '/machines', labelKey: 'nav.machines', icon: Laptop },
  { path: '/skills', labelKey: 'nav.skills', icon: Wrench },
];

const BOTTOM_ITEMS: NavItem[] = [
  { path: '/account', labelKey: 'nav.account', icon: Settings },
  { path: '/workspaces', labelKey: 'nav.atelier', icon: Palette, external: true },
];

/** Workspace switcher — a droplist below the brand that swaps the active workspace. */
function WorkspaceSwitcher() {
  const { t } = useTranslation();
  const workspaces = useAppStore((s) => s.workspaces);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const setActiveWorkspace = useAppStore((s) => s.setActiveWorkspace);
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const active = workspaces.find((w) => w.id === activeWorkspaceId);

  return (
    <div ref={ref} className="relative px-3 pt-3">
      <p className="font-body text-body-xs text-ash px-1 mb-1.5">{t('nav.workspace')}</p>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'w-full min-h-[44px] flex items-center justify-between gap-2 px-3 rounded-md',
          'bg-[#2E261C] border transition-colors',
          open ? 'border-gold-muted' : 'border-[#43382A] hover:border-gold-muted/60'
        )}
      >
        <span className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full bg-[#4FA673] shrink-0" />
          <span className="font-body text-body-md font-medium text-[#EDE3CE] truncate">
            {active?.name || t('nav.selectWorkspace')}
          </span>
        </span>
        <ChevronDown
          className={cn('w-4 h-4 text-ash transition-transform duration-200', open && 'rotate-180')}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute left-3 right-3 top-full mt-1 z-50 rounded-md border border-line bg-paper shadow-lg overflow-hidden"
          >
            {workspaces.map((w) => {
              const isActive = w.id === activeWorkspaceId;
              return (
                <button
                  key={w.id}
                  onClick={() => {
                    // Switching workspace changes the URL; the Layout effect then loads
                    // the new workspace's slice (agents/projects/skills).
                    setActiveWorkspace(w.id);
                    navigate(wsHref(w.id, '/home'));
                    setOpen(false);
                  }}
                  className={cn(
                    'w-full flex items-center gap-2 px-2.5 py-2 text-left font-body text-body-md transition-colors',
                    isActive ? 'bg-inset text-ink font-medium' : 'text-ink hover:bg-inset'
                  )}
                >
                  <span
                    className={cn(
                      'w-2 h-2 rounded-full shrink-0',
                      isActive ? 'bg-verdigris' : 'bg-ink-muted/50'
                    )}
                  />
                  <span className="truncate">{w.name}</span>
                  {isActive && <Check className="w-3.5 h-3.5 ml-auto text-ink shrink-0" />}
                </button>
              );
            })}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Ring colour per liveness — the same lapis/verdigris the rest of the screen uses. */
const PRESENCE_RING: Record<AgentStatus, string> = {
  working: 'ring-lapis',
  online: 'ring-verdigris',
  idle: 'ring-verdigris',
  offline: 'ring-transparent',
};

/** Who is around right now: one initial per agent of this workspace, ringed by liveness. */
function PresentAgents() {
  const { t } = useTranslation();
  const { workspaceId } = useParams();
  const allMariuses = useAppStore((s) => s.mariuses);
  const mariuses = allMariuses.filter((m) => m.workspaceId === workspaceId);
  if (mariuses.length === 0) return null;

  return (
    <div className="px-5 pb-4">
      <p className="font-body text-body-xs text-ash mb-2.5">{t('nav.present')}</p>
      <div className="flex flex-wrap gap-2.5">
        {mariuses.slice(0, 10).map((m) => (
          <Link
            key={m.id}
            to={wsHref(workspaceId, `/agents/${m.id}`)}
            title={`${m.displayName || m.name} · ${t(`directory.status.${m.status}`, { defaultValue: m.status })}`}
            aria-label={`${m.displayName || m.name} · ${t(`directory.status.${m.status}`, { defaultValue: m.status })}`}
            className={cn(
              'w-8 h-8 rounded-full flex items-center justify-center font-body text-body-xs font-semibold',
              'ring-2 ring-offset-2 ring-offset-ink-frame',
              m.status === 'offline'
                ? 'bg-[#2E261C] text-ash border border-dashed border-[#5C4F3E]'
                : 'bg-ink-frame-raised text-[#FFF8E8]',
              PRESENCE_RING[m.status]
            )}
          >
            {(m.displayName || m.name).charAt(0).toUpperCase()}
          </Link>
        ))}
      </div>
    </div>
  );
}

export default function Navbar() {
  const { t } = useTranslation();
  const location = useLocation();
  const { workspaceId } = useParams();
  const userCollapsed = useAppStore((s) => s.sidebarCollapsed);
  const setSidebarCollapsed = useAppStore((s) => s.setSidebarCollapsed);
  const drawerOpen = useAppStore((s) => s.navDrawerOpen);
  const setDrawerOpen = useAppStore((s) => s.setNavDrawerOpen);
  const viewport = useViewport();
  // Desktop keeps the person's own choice. Below it the rail stays narrow so pages keep their
  // width, and opening it lays the full sidebar over the page instead of pushing it aside.
  const overlay = viewport !== 'desktop';
  const collapsed = overlay ? !drawerOpen : userCollapsed;

  // Following a link closes the drawer; on a phone it would otherwise cover the page it opened.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname, setDrawerOpen]);
  // The numbers a nav row may carry, looked up by the `counter` name on the row. One entry today;
  // a map rather than a single value so the next row that needs a count adds a key, not a branch.
  const counters: Record<CounterName, number> = {
    inboxPending: useAppStore((s) => s.inboxPending),
  };

  // Compare against the workspace-relative sub-path (strip the /w/:workspaceId prefix).
  const base = workspaceId ? `/w/${workspaceId}` : '';
  const sub = location.pathname.startsWith(base)
    ? location.pathname.slice(base.length) || '/'
    : location.pathname;

  const linkTo = (item: { path: string; external?: boolean }) =>
    item.external ? item.path : wsHref(workspaceId, item.path);

  const isActive = (item: { path: string; external?: boolean }) => {
    if (item.external) return location.pathname.startsWith(item.path);
    if (item.path === '/home') return sub === '/' || sub.startsWith('/home');
    // A task belongs to a project, so the task page keeps "Projects" lit.
    if (item.path === '/projects') return sub.startsWith('/projects') || sub.startsWith('/tasks');
    return sub.startsWith(item.path);
  };

  // A phone has no rail: the sidebar exists only while the drawer is open.
  const hidden = viewport === 'phone' && !drawerOpen;

  return (
    <>
    {overlay && drawerOpen && (
      <div
        className="fixed inset-0 z-[99] bg-ink-frame/40"
        onClick={() => setDrawerOpen(false)}
        aria-hidden="true"
      />
    )}
    <nav
      aria-label={t('nav.workspace')}
      className={cn(
        'fixed left-0 top-0 h-[100dvh] bg-ink-frame text-[#EDE3CE] z-sidebar flex flex-col',
        'transition-[width,transform] duration-300',
        collapsed ? 'w-[68px]' : 'w-[240px]',
        hidden && '-translate-x-full',
        overlay && drawerOpen && 'shadow-2xl'
      )}
    >
      {/* ── Brand row — fixed h-14 so its bottom border aligns with the TopBar ── */}
      <div
        className={cn(
          'h-14 flex items-center shrink-0 border-b border-ink-frame-raised',
          collapsed ? 'justify-center px-2' : 'px-4'
        )}
      >
        <Link to="/workspaces" className="flex items-center gap-[1px] no-underline">
          {/* Gilt initial "A" doubles as the mark; the wordmark continues with "rmarius" */}
          <span
            style={{
              fontFamily: "'Cinzel Decorative', 'Cinzel', serif",
              fontSize: collapsed ? '26px' : '30px',
              color: '#D4A843',
              fontWeight: 700,
              lineHeight: 1,
            }}
          >
            A
          </span>
          {!collapsed && (
            <span className="font-display text-[24px] font-semibold text-[#F5ECD8] tracking-tight leading-none">
              rmarius
            </span>
          )}
        </Link>
      </div>

      {/* ── Floating collapse toggle (straddles the right border). A phone opens the drawer
          from the top bar instead; here it would poke out over the page's left edge. ── */}
      {viewport !== 'phone' && (
      <button
        onClick={() => (overlay ? setDrawerOpen(!drawerOpen) : setSidebarCollapsed(!collapsed))}
        className={cn(
          'absolute top-4 -right-3 z-[60] w-6 h-6 rounded-full',
          'flex items-center justify-center',
          'bg-ink-frame border border-[#43382A] text-ash',
          'hover:text-gold hover:border-gold-muted',
          'shadow-sm transition-colors'
        )}
        aria-label={collapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
      >
        {collapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronLeft className="w-3.5 h-3.5" />}
      </button>
      )}

      {/* ── Workspace switcher (hidden when collapsed) ── */}
      {!collapsed && <WorkspaceSwitcher />}

      {/* ── Main Nav ── */}
      <div className="flex-1 flex flex-col gap-1 px-2 mt-3 overflow-y-auto">
        {NAV_ITEMS.map((item, i) => {
          const active = isActive(item);
          const waiting = item.counter ? counters[item.counter] : 0;
          return (
            <motion.div
              key={item.path}
              initial={false}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.06, duration: 0.35 }}
            >
              <Link
                to={linkTo(item)}
                className={cn(
                  'flex items-center gap-3 px-3 min-h-[44px] rounded-md font-body text-body-md transition-colors relative',
                  active
                    ? 'bg-ink-frame-raised text-[#FFF8E8]'
                    : 'text-[#C9BCA3] hover:bg-ink-frame-raised/60 hover:text-[#FFF8E8]',
                  collapsed && 'justify-center px-2'
                )}
                title={collapsed ? t(item.labelKey) : undefined}
              >
                <item.icon
                  className={cn('w-[18px] h-[18px] flex-shrink-0', active ? 'text-gold' : 'text-[#C9BCA3]')}
                />
                {!collapsed && (
                  <span className="truncate">
                    {t(item.labelKey)}
                    {waiting > 0 && (
                      <span className="ml-2 inline-flex items-center justify-center min-w-[20px] h-[18px] px-1.5 rounded-full text-[11px] font-semibold leading-none text-ink-frame bg-gold align-middle">
                        {waiting > 99 ? '99+' : waiting}
                      </span>
                    )}
                  </span>
                )}
                {/* Collapsed to icons there is no room for a number, so the mark degrades to a
                    dot — still driven by the same count, so it is still telling the truth. */}
                {collapsed && waiting > 0 && (
                  <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-gold" />
                )}
              </Link>
            </motion.div>
          );
        })}
      </div>

      {!collapsed && <PresentAgents />}

      {/* ── Bottom Nav ── */}
      <div className="flex flex-col gap-1 px-2 pb-2 border-t border-ink-frame-raised pt-2">
        {BOTTOM_ITEMS.map((item, i) => {
          const active = isActive(item);
          return (
            <motion.div
              key={item.path}
              initial={false}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: (NAV_ITEMS.length + i) * 0.06, duration: 0.35 }}
            >
              <Link
                to={linkTo(item)}
                className={cn(
                  'flex items-center gap-3 px-3 min-h-[44px] rounded-md font-body text-body-md transition-colors',
                  active
                    ? 'bg-ink-frame-raised text-[#FFF8E8]'
                    : 'text-[#C9BCA3] hover:bg-ink-frame-raised/60 hover:text-[#FFF8E8]',
                  collapsed && 'justify-center px-2'
                )}
                title={collapsed ? t(item.labelKey) : undefined}
              >
                <item.icon
                  className={cn('w-[18px] h-[18px] flex-shrink-0', active ? 'text-gold' : 'text-[#C9BCA3]')}
                />
                {!collapsed && <span>{t(item.labelKey)}</span>}
              </Link>
            </motion.div>
          );
        })}
      </div>
    </nav>
    </>
  );
}
