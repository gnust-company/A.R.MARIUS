// @ts-nocheck
import { useState } from 'react';
import { Link, useLocation } from 'react-router';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Diamond,
  LayoutDashboard,
  Users,
  Wrench,
  Inbox,
  Settings,
  Palette,
  ChevronLeft,
  ChevronRight,
  Bot,
} from 'lucide-react';
import { useMockStore } from '@/store/mockStore';
import { cn } from '@/lib/utils';

const NAV_ITEMS = [
  { path: '/projects', label: 'Projects', icon: LayoutDashboard },
  { path: '/directory', label: 'Agents', icon: Users },
  { path: '/skills', label: 'Skills', icon: Wrench },
  { path: '/inbox', label: 'Patron Inbox', icon: Inbox, badge: true },
];

const BOTTOM_ITEMS = [
  { path: '/account', label: 'Account', icon: Settings },
  { path: '/workspaces', label: 'Atelier', icon: Palette },
];

export default function Navbar() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(false);
  const activeWorkspaceId = useMockStore((s) => s.activeWorkspaceId);
  const workspaces = useMockStore((s) => s.workspaces);
  const mariuses = useMockStore((s) => s.mariuses);
  const activeWs = workspaces.find((w) => w.id === activeWorkspaceId);
  const workspaceMariuses = mariuses.filter((m) => m.workspaceId === activeWorkspaceId);

  const isActive = (path: string) => {
    if (path === '/projects') return location.pathname === '/' || location.pathname === '/projects' || location.pathname.startsWith('/projects');
    return location.pathname.startsWith(path);
  };

  return (
    <motion.nav
      className={cn(
        'fixed left-0 top-0 h-screen bg-vellum border-r border-vellum-dark z-sidebar flex flex-col',
        'transition-all duration-300',
        collapsed ? 'w-[60px]' : 'w-[220px]'
      )}
      initial={{ x: -220 }}
      animate={{ x: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] as [number, number, number, number] }}
    >
      {/* Brand */}
      <div className={cn('p-4 border-b border-vellum-dark', collapsed && 'px-2')}>
        <Link to="/workspaces" className="flex items-center gap-0.5 no-underline">
          {/* Gilt initial "A" doubles as the mark; the wordmark continues with "rmarius" */}
          <span style={{ fontFamily: "'Cinzel Decorative', 'Cinzel', serif", fontSize: '26px', color: '#D4A843', fontWeight: 700, lineHeight: 1 }}>A</span>
          {!collapsed && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              <span className="font-display text-body-md font-semibold text-ink">rmarius</span>
              {activeWs && (
                <p className="font-body text-body-xs text-ink-light mt-0.5 truncate">{activeWs.name}</p>
              )}
            </motion.div>
          )}
        </Link>
      </div>

      {/* Toggle */}
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="mx-2 mt-2 p-1.5 rounded-md text-ink-muted hover:text-ink hover:bg-vellum-deep transition-colors self-end"
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
      </button>

      {/* Main Nav */}
      <div className="flex-1 flex flex-col gap-1 px-2 mt-2">
        {NAV_ITEMS.map((item, i) => {
          const active = isActive(item.path);
          return (
            <motion.div
              key={item.path}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: i * 0.06, duration: 0.35 }}
            >
              <Link
                to={item.path}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-md font-body text-body-md font-medium transition-colors relative',
                  active
                    ? 'bg-vellum-deep text-terracotta border-l-[3px] border-terracotta'
                    : 'text-ink-light hover:bg-vellum-deep hover:text-ink border-l-[3px] border-transparent',
                  collapsed && 'justify-center px-2'
                )}
              >
                <item.icon className={cn('w-[18px] h-[18px] flex-shrink-0', active ? 'text-terracotta' : 'text-ink-light')} />
                {!collapsed && (
                  <span className="truncate">
                    {item.label}
                    {item.badge && (
                      <span className="ml-2 inline-flex w-2 h-2 rounded-full bg-terracotta" />
                    )}
                  </span>
                )}
              </Link>
            </motion.div>
          );
        })}
      </div>

      {/* Bottom Nav */}
      <div className="flex flex-col gap-1 px-2 pb-2 border-t border-vellum-dark pt-2">
        {BOTTOM_ITEMS.map((item, i) => {
          const active = isActive(item.path);
          return (
            <motion.div
              key={item.path}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: (NAV_ITEMS.length + i) * 0.06, duration: 0.35 }}
            >
              <Link
                to={item.path}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-md font-body text-body-md font-medium transition-colors',
                  active
                    ? 'bg-vellum-deep text-terracotta border-l-[3px] border-terracotta'
                    : 'text-ink-light hover:bg-vellum-deep hover:text-ink border-l-[3px] border-transparent',
                  collapsed && 'justify-center px-2'
                )}
              >
                <item.icon className={cn('w-[18px] h-[18px] flex-shrink-0', active ? 'text-terracotta' : 'text-ink-light')} />
                {!collapsed && <span>{item.label}</span>}
              </Link>
            </motion.div>
          );
        })}
      </div>

      {/* Agent mini-bar */}
      {activeWorkspaceId && workspaceMariuses.length > 0 && (
        <div className={cn('border-t border-vellum-dark p-2', collapsed && 'flex flex-col items-center')}>
          <AnimatePresence>
            {!collapsed && (
              <motion.p
                className="text-body-xs text-ink-muted mb-2 px-2"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
              >
                {workspaceMariuses.length} agents
              </motion.p>
            )}
          </AnimatePresence>
          <div className={cn('flex gap-1', collapsed && 'flex-col')}>
            {workspaceMariuses.slice(0, collapsed ? 3 : 5).map((m) => (
              <div
                key={m.id}
                className="relative"
                title={m.displayName}
              >
                <div className="w-7 h-7 rounded-full bg-vellum-dark overflow-hidden border border-vellum-dark">
                  {m.avatar ? (
                    <img src={m.avatar} alt={m.displayName} className="w-full h-full object-cover" />
                  ) : (
                    <Bot className="w-4 h-4 m-1.5 text-ink-muted" />
                  )}
                </div>
                {/* Status dot */}
                <span
                  className={cn(
                    'absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full border-2 border-vellum',
                    m.status === 'online' && 'bg-status-online animate-pulse-dot',
                    m.status === 'working' && 'bg-status-working animate-pulse-working',
                    m.status === 'idle' && 'bg-status-idle',
                    m.status === 'offline' && 'bg-status-offline',
                    m.status === 'pending' && 'bg-status-pending',
                    m.status === 'invited' && 'bg-status-invited',
                  )}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </motion.nav>
  );
}
