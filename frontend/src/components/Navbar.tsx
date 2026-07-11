// @ts-nocheck
import { useState, useEffect, useRef } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  Users,
  Wrench,
  Inbox,
  Settings,
  Palette,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Check,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useMockStore } from '@/store/mockStore';
import { cn, wsHref } from '@/lib/utils';

// `external: true` = a top-level route (no workspace prefix), e.g. the launcher.
const NAV_ITEMS = [
  { path: '/projects', labelKey: 'nav.projects', icon: LayoutDashboard },
  { path: '/agents', labelKey: 'nav.directory', icon: Users },
  { path: '/skills', labelKey: 'nav.skills', icon: Wrench },
  { path: '/inbox', labelKey: 'nav.inbox', icon: Inbox, badge: true },
];

const BOTTOM_ITEMS = [
  { path: '/account', labelKey: 'nav.account', icon: Settings },
  { path: '/workspaces', labelKey: 'nav.atelier', icon: Palette, external: true },
];

/** Workspace switcher — a droplist below the brand that swaps the active workspace. */
function WorkspaceSwitcher() {
  const { t } = useTranslation();
  const workspaces = useMockStore((s) => s.workspaces);
  const activeWorkspaceId = useMockStore((s) => s.activeWorkspaceId);
  const setActiveWorkspace = useMockStore((s) => s.setActiveWorkspace);
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
      <p className="font-body text-body-xs text-ink-muted px-1 mb-1.5 uppercase tracking-[0.08em]">
        {t('nav.workspace')}
      </p>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'w-full flex items-center justify-between gap-2 px-2.5 py-2 rounded-md',
          'bg-vellum-deep border border-vellum-dark transition-colors',
          open ? 'border-gold-muted' : 'hover:border-gold-muted/60'
        )}
      >
        <span className="flex items-center gap-2 min-w-0">
          <span className="w-2 h-2 rounded-full bg-terracotta shrink-0" />
          <span className="font-display text-body-md font-semibold text-ink truncate">
            {active?.name || t('nav.selectWorkspace')}
          </span>
        </span>
        <ChevronDown
          className={cn('w-4 h-4 text-ink-muted transition-transform duration-200', open && 'rotate-180')}
        />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.15 }}
            className="absolute left-3 right-3 top-full mt-1 z-50 rounded-md border border-vellum-dark bg-vellum shadow-lg overflow-hidden"
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
                    navigate(wsHref(w.id, '/projects'));
                    setOpen(false);
                  }}
                  className={cn(
                    'w-full flex items-center gap-2 px-2.5 py-2 text-left font-body text-body-md transition-colors',
                    isActive ? 'bg-vellum-deep text-terracotta font-medium' : 'text-ink hover:bg-vellum-deep'
                  )}
                >
                  <span
                    className={cn(
                      'w-2 h-2 rounded-full shrink-0',
                      isActive ? 'bg-terracotta' : 'bg-ink-muted/50'
                    )}
                  />
                  <span className="truncate">{w.name}</span>
                  {isActive && <Check className="w-3.5 h-3.5 ml-auto text-terracotta shrink-0" />}
                </button>
              );
            })}
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
  const collapsed = useMockStore((s) => s.sidebarCollapsed);
  const setSidebarCollapsed = useMockStore((s) => s.setSidebarCollapsed);

  // Compare against the workspace-relative sub-path (strip the /w/:workspaceId prefix).
  const base = workspaceId ? `/w/${workspaceId}` : '';
  const sub = location.pathname.startsWith(base)
    ? location.pathname.slice(base.length) || '/'
    : location.pathname;

  const linkTo = (item: { path: string; external?: boolean }) =>
    item.external ? item.path : wsHref(workspaceId, item.path);

  const isActive = (item: { path: string; external?: boolean }) => {
    if (item.external) return location.pathname.startsWith(item.path);
    if (item.path === '/projects') return sub === '/' || sub.startsWith('/projects');
    return sub.startsWith(item.path);
  };

  return (
    <motion.nav
      className={cn(
        'fixed left-0 top-0 h-screen bg-vellum border-r border-vellum-dark z-sidebar flex flex-col',
        'transition-all duration-300',
        collapsed ? 'w-[68px]' : 'w-[240px]'
      )}
      initial={{ x: -240 }}
      animate={{ x: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
    >
      {/* ── Brand row — fixed h-14 so its bottom border aligns with the TopBar ── */}
      <div
        className={cn(
          'h-14 flex items-center shrink-0 border-b border-vellum-dark',
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
            <span className="font-display text-[24px] font-bold text-ink tracking-tight leading-none">
              rmarius
            </span>
          )}
        </Link>
      </div>

      {/* ── Floating collapse toggle (straddles the right border) ── */}
      <button
        onClick={() => setSidebarCollapsed(!collapsed)}
        className={cn(
          'absolute top-4 -right-3 z-[60] w-6 h-6 rounded-full',
          'flex items-center justify-center',
          'bg-vellum border border-vellum-dark text-ink-muted',
          'hover:text-terracotta hover:border-gold-muted hover:bg-vellum-deep',
          'shadow-sm transition-colors'
        )}
        aria-label={collapsed ? t('nav.expandSidebar') : t('nav.collapseSidebar')}
      >
        {collapsed ? <ChevronRight className="w-3.5 h-3.5" /> : <ChevronLeft className="w-3.5 h-3.5" />}
      </button>

      {/* ── Workspace switcher (hidden when collapsed) ── */}
      {!collapsed && <WorkspaceSwitcher />}

      {/* ── Main Nav ── */}
      <div className="flex-1 flex flex-col gap-1 px-2 mt-3 overflow-y-auto">
        {NAV_ITEMS.map((item, i) => {
          const active = isActive(item);
          return (
            <motion.div
              key={item.path}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.06, duration: 0.35 }}
            >
              <Link
                to={linkTo(item)}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-md font-body text-body-md font-medium transition-colors relative',
                  active
                    ? 'bg-vellum-deep text-terracotta border-l-[3px] border-terracotta'
                    : 'text-ink-light hover:bg-vellum-deep hover:text-ink border-l-[3px] border-transparent',
                  collapsed && 'justify-center px-2'
                )}
                title={collapsed ? t(item.labelKey) : undefined}
              >
                <item.icon
                  className={cn('w-[18px] h-[18px] flex-shrink-0', active ? 'text-terracotta' : 'text-ink-light')}
                />
                {!collapsed && (
                  <span className="truncate">
                    {t(item.labelKey)}
                    {item.badge && <span className="ml-2 inline-flex w-2 h-2 rounded-full bg-terracotta" />}
                  </span>
                )}
              </Link>
            </motion.div>
          );
        })}
      </div>

      {/* ── Bottom Nav ── */}
      <div className="flex flex-col gap-1 px-2 pb-2 border-t border-vellum-dark pt-2">
        {BOTTOM_ITEMS.map((item, i) => {
          const active = isActive(item);
          return (
            <motion.div
              key={item.path}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: (NAV_ITEMS.length + i) * 0.06, duration: 0.35 }}
            >
              <Link
                to={linkTo(item)}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-md font-body text-body-md font-medium transition-colors',
                  active
                    ? 'bg-vellum-deep text-terracotta border-l-[3px] border-terracotta'
                    : 'text-ink-light hover:bg-vellum-deep hover:text-ink border-l-[3px] border-transparent',
                  collapsed && 'justify-center px-2'
                )}
                title={collapsed ? t(item.labelKey) : undefined}
              >
                <item.icon
                  className={cn('w-[18px] h-[18px] flex-shrink-0', active ? 'text-terracotta' : 'text-ink-light')}
                />
                {!collapsed && <span>{t(item.labelKey)}</span>}
              </Link>
            </motion.div>
          );
        })}
      </div>
    </motion.nav>
  );
}
