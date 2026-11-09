import { useState, useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronLeft,
  ChevronRight,
  ChevronsUpDown,
  Check,
  LayoutGrid,
  Sparkles,
  CheckCircle2,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/store/appStore';
import { useViewport } from '@/hooks/use-viewport';
import { cn, wsHref } from '@/lib/utils';
import { Brand } from './Brand';
import { NAV_GROUPS, activeNavPath, initials, type CounterName } from '@/lib/nav';

/** The workspace this sidebar belongs to; opening it switches to another one. */
function WorkspaceIdentity({ collapsed }: { collapsed: boolean }) {
  const { t } = useTranslation();
  const workspaces = useAppStore((s) => s.workspaces);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const setActiveWorkspace = useAppStore((s) => s.setActiveWorkspace);
  const sseConnected = useAppStore((s) => s.sseConnected);
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
  const name = active?.name || t('nav.selectWorkspace');

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={collapsed ? name : undefined}
        title={collapsed ? name : undefined}
        className={cn(
          'w-full flex items-center gap-2.5 py-3 border-y border-sidebar-border text-left transition-colors hover:bg-sidebar-hover',
          collapsed ? 'justify-center px-0' : 'px-2.5'
        )}
      >
        <span className="grid place-items-center shrink-0 w-[34px] h-[34px] rounded-full border border-sidebar-border font-display text-[12px] text-gold">
          {initials(active?.name)}
        </span>
        {!collapsed && (
          <>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13px] font-semibold text-sidebar-foreground">{name}</span>
              <span className="block truncate text-[11px] text-sidebar-nav">
                {sseConnected ? t('nav.workspaceLive') : t('nav.workspaceReconnecting')}
              </span>
            </span>
            <ChevronsUpDown className="w-4 h-4 shrink-0 text-sidebar-nav" />
          </>
        )}
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className={cn(
              'absolute top-full mt-1 z-50 rounded-lg border border-line-strong bg-popover text-ink shadow-soft overflow-hidden',
              collapsed ? 'left-0 w-60' : 'left-0 right-0'
            )}
          >
            <p className="px-3 pt-2.5 pb-1 font-mono text-eyebrow uppercase text-ink-muted">{t('nav.workspace')}</p>
            {workspaces.map((w) => {
              const isActive = w.id === activeWorkspaceId;
              return (
                <button
                  key={w.id}
                  type="button"
                  onClick={() => {
                    // Switching changes the URL; the Layout effect then loads that workspace's slice.
                    setActiveWorkspace(w.id);
                    navigate(wsHref(w.id, '/home'));
                    setOpen(false);
                  }}
                  className={cn(
                    'w-full flex items-center gap-2.5 px-3 min-h-[40px] text-left text-body-sm transition-colors',
                    isActive ? 'bg-surface-hover font-medium' : 'hover:bg-surface-hover'
                  )}
                >
                  <span className="grid place-items-center w-6 h-6 rounded-full border border-line font-display text-[10px] text-gold shrink-0">
                    {initials(w.name)}
                  </span>
                  <span className="truncate">{w.name}</span>
                  {isActive && <Check className="w-3.5 h-3.5 ml-auto shrink-0" />}
                </button>
              );
            })}
            <Link
              to="/workspaces"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2.5 px-3 min-h-[40px] border-t border-line text-body-sm text-sapphire-strong hover:bg-surface-hover"
            >
              <LayoutGrid className="w-4 h-4" />
              {t('nav.allWorkspaces')}
            </Link>
          </motion.div>
        )}
      </AnimatePresence>
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
  const sseConnected = useAppStore((s) => s.sseConnected);
  const currentUser = useAppStore((s) => s.currentUser);
  const viewport = useViewport();
  // Desktop keeps the person's own choice. Below it the rail stays narrow so pages keep their
  // width, and opening it lays the full sidebar over the page instead of pushing it aside.
  const overlay = viewport !== 'desktop';
  const collapsed = overlay ? !drawerOpen : userCollapsed;

  // Following a link closes the drawer; on a phone it would otherwise cover the page it opened.
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname, setDrawerOpen]);

  const counters: Record<CounterName, number> = {
    inboxPending: useAppStore((s) => s.inboxPending),
  };

  const base = workspaceId ? `/w/${workspaceId}` : '';
  const sub = location.pathname.startsWith(base) ? location.pathname.slice(base.length) || '/' : location.pathname;
  const current = activeNavPath(sub);
  const accountActive = sub.startsWith('/account');

  // A phone has no rail: the sidebar exists only while the drawer is open.
  const hidden = viewport === 'phone' && !drawerOpen;

  return (
    <>
      <AnimatePresence>
        {overlay && drawerOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-[99] bg-ink-strong/30 backdrop-blur-[2px]"
            onClick={() => setDrawerOpen(false)}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>
      <nav
        aria-label={t('nav.main')}
        className={cn(
          'fixed left-0 top-0 h-[100dvh] z-sidebar flex flex-col bg-sidebar text-sidebar-foreground border-r border-sidebar-border',
          'transition-[width,transform] duration-300',
          collapsed ? 'w-[68px] px-2.5' : 'w-[240px] px-4',
          'pt-5 pb-4',
          hidden && '-translate-x-full',
          overlay && drawerOpen && 'shadow-2xl'
        )}
      >
        <Link
          to={wsHref(workspaceId, '/home')}
          className={cn('flex items-center min-h-[48px] shrink-0', collapsed ? 'justify-center' : 'px-1.5')}
          aria-label="Armarius"
        >
          <Brand compact={collapsed} />
        </Link>

        {/* Collapse toggle straddling the right border. A phone opens the drawer from the bottom
            bar instead; here it would poke out over the page's left edge. */}
        {viewport !== 'phone' && (
          <button
            type="button"
            onClick={() => (overlay ? setDrawerOpen(!drawerOpen) : setSidebarCollapsed(!collapsed))}
            className="absolute top-7 -right-3 z-[60] w-6 h-6 rounded-full grid place-items-center bg-surface border border-line-strong text-ink-muted hover:text-ink-strong shadow-sm transition-colors"
            aria-label={collapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
          >
            {collapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronLeft className="w-3.5 h-3.5" />}
          </button>
        )}

        <div className="mt-5 mb-6">
          <WorkspaceIdentity collapsed={collapsed} />
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto no-scrollbar flex flex-col gap-6">
          {NAV_GROUPS.map((group) => (
            <div key={group.labelKey} className="flex flex-col gap-[3px]">
              {collapsed ? (
                <span className="mx-auto mb-1 w-5 border-t border-sidebar-border" aria-hidden="true" />
              ) : (
                <span className="px-3 pb-1.5 font-mono text-[9px] uppercase tracking-[0.16em] text-sidebar-nav opacity-80">
                  {t(group.labelKey)}
                </span>
              )}
              {group.items.map((item) => {
                const active = current === item.path;
                const waiting = item.counter ? counters[item.counter] : 0;
                const label = t(item.labelKey);
                return (
                  <Link
                    key={item.path}
                    to={wsHref(workspaceId, item.path)}
                    aria-current={active ? 'page' : undefined}
                    title={collapsed ? label : undefined}
                    aria-label={collapsed ? (waiting > 0 ? `${label} · ${waiting}` : label) : undefined}
                    className={cn(
                      'relative flex items-center gap-3 min-h-[44px] rounded-md text-[14px] transition-colors',
                      collapsed ? 'justify-center px-0' : 'px-3',
                      active
                        ? 'bg-sidebar-active text-sidebar-foreground'
                        : 'text-sidebar-nav hover:bg-sidebar-hover hover:text-sidebar-foreground'
                    )}
                  >
                    {active && (
                      <motion.i
                        layoutId="nav-active-mark"
                        className="absolute left-0 w-[2px] h-[18px] rounded-sm bg-gold"
                        transition={{ type: 'spring', stiffness: 420, damping: 34 }}
                      />
                    )}
                    <item.icon className="w-5 h-5 shrink-0" strokeWidth={active ? 2 : 1.6} />
                    {!collapsed && <span className="flex-1 truncate">{label}</span>}
                    {!collapsed && waiting > 0 && (
                      <b className="grid place-items-center min-w-[21px] h-[21px] px-1.5 rounded-full bg-amber text-[11px] font-semibold text-[oklch(0.22_0.04_70)]">
                        {waiting > 99 ? '99+' : waiting}
                      </b>
                    )}
                    {/* Collapsed there is no room for a number, so the mark degrades to a dot —
                        still driven by the same count, so it still tells the truth. */}
                    {collapsed && waiting > 0 && (
                      <span className="absolute top-1.5 right-2 w-2 h-2 rounded-full bg-amber" />
                    )}
                  </Link>
                );
              })}
            </div>
          ))}
        </div>

        <div className="mt-4 shrink-0 flex flex-col gap-2.5">
          {!collapsed && (
            <div className="flex gap-2.5 px-2.5 py-3.5 rounded-lg border border-sidebar-border bg-sidebar-subtle">
              <Sparkles className="w-4 h-4 mt-0.5 shrink-0 text-gold" />
              <div className="min-w-0 text-[11px] leading-snug">
                <strong className="block font-semibold">
                  {sseConnected ? t('nav.listening') : t('nav.reconnecting')}
                </strong>
                <span className="block text-sidebar-nav">
                  {sseConnected ? t('nav.listeningDetail') : t('nav.reconnectingDetail')}
                </span>
              </div>
            </div>
          )}
          <Link
            to={wsHref(workspaceId, '/account')}
            aria-current={accountActive ? 'page' : undefined}
            title={collapsed ? t('nav.account') : undefined}
            aria-label={collapsed ? t('nav.account') : undefined}
            className={cn(
              'flex items-center gap-2.5 rounded-lg transition-colors',
              collapsed ? 'justify-center p-1.5' : 'p-2.5',
              accountActive ? 'bg-sidebar-active' : 'hover:bg-sidebar-hover'
            )}
          >
            <span className="grid place-items-center shrink-0 w-[34px] h-[34px] rounded-full bg-sidebar-subtle font-display text-[15px] text-gold">
              {(currentUser?.name || 'P').charAt(0).toUpperCase()}
            </span>
            {!collapsed && (
              <>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[12px] font-semibold">{currentUser?.name || 'Patron'}</span>
                  <span className="block truncate text-[10px] text-sidebar-nav">{t('nav.patronRole')}</span>
                </span>
                <CheckCircle2 className="w-4 h-4 shrink-0 text-success" />
              </>
            )}
          </Link>
        </div>
      </nav>
    </>
  );
}
