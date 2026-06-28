// @ts-nocheck
import { useLocation } from 'react-router';
import { motion } from 'framer-motion';
import { Search, Wifi, WifiOff } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useMockStore } from '@/store/mockStore';
import { cn } from '@/lib/utils';

// Known route segments → i18n nav keys (project/workspace names stay as data)
const SEGMENT_KEYS: Record<string, string> = {
  projects: 'nav.projects',
  directory: 'nav.directory',
  skills: 'nav.skills',
  inbox: 'nav.inbox',
  account: 'nav.account',
};

function useBreadcrumbs() {
  const { t } = useTranslation();
  const location = useLocation();
  const workspaces = useMockStore((s) => s.workspaces);
  const projects = useMockStore((s) => s.projects);
  const activeWorkspaceId = useMockStore((s) => s.activeWorkspaceId);

  const segments = location.pathname.split('/').filter(Boolean);
  const crumbs: { label: string; path?: string }[] = [];

  if (segments.length === 0 || location.pathname === '/') {
    const ws = workspaces.find((w) => w.id === activeWorkspaceId);
    crumbs.push({ label: ws?.name || t('nav.workspace') });
    crumbs.push({ label: t('nav.projects') });
    return crumbs;
  }

  // Add workspace name
  if (activeWorkspaceId) {
    const ws = workspaces.find((w) => w.id === activeWorkspaceId);
    crumbs.push({ label: ws?.name || t('nav.workspace'), path: '/workspaces' });
  }

  segments.forEach((seg) => {
    if (seg === 'workspaces') return;
    if (seg.startsWith('p-')) {
      const p = projects.find((pr) => pr.id === seg);
      crumbs.push({ label: p?.name || seg });
      return;
    }
    if (seg === 'new') {
      crumbs.push({ label: t('nav.new') });
      return;
    }
    if (SEGMENT_KEYS[seg]) {
      crumbs.push({ label: t(SEGMENT_KEYS[seg]) });
      return;
    }
    const label = seg.charAt(0).toUpperCase() + seg.slice(1).replace(/-/g, ' ');
    crumbs.push({ label });
  });

  return crumbs;
}

export default function TopBar() {
  const { t } = useTranslation();
  const sseConnected = useMockStore((s) => s.sseConnected);
  const currentUser = useMockStore((s) => s.currentUser);
  const crumbs = useBreadcrumbs();

  return (
    <header className="sticky top-0 z-sticky h-14 bg-vellum border-b border-vellum-dark flex items-center justify-between px-6">
      {/* Breadcrumbs */}
      <nav className="flex items-center gap-2 font-body text-body-sm text-ink-light">
        {crumbs.map((crumb, i) => (
          <span key={i} className="flex items-center gap-2">
            {i > 0 && <span className="text-ink-muted">/</span>}
            {crumb.path ? (
              <a href={crumb.path} className="hover:text-terracotta transition-colors">
                {crumb.label}
              </a>
            ) : (
              <span className={i === crumbs.length - 1 ? 'text-ink font-medium' : ''}>
                {crumb.label}
              </span>
            )}
          </span>
        ))}
      </nav>

      {/* Right side */}
      <div className="flex items-center gap-4">
        {/* SSE Indicator */}
        <motion.div
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-full text-body-xs font-medium',
            sseConnected ? 'bg-[#D8EADD] text-[#2A6E3A]' : 'bg-[#E8E0D8] text-[#8B7A6A]'
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
          className="p-2 rounded-md text-ink-muted hover:text-terracotta hover:bg-vellum-deep transition-colors"
          aria-label={t('common.search')}
        >
          <Search className="w-[18px] h-[18px]" />
        </button>

        {/* Profile */}
        <div className="flex items-center gap-2">
          <div
            className={cn(
              'w-8 h-8 rounded-full bg-vellum-deep border-2 flex items-center justify-center text-body-xs font-medium',
              sseConnected ? 'border-gold' : 'border-vellum-dark'
            )}
          >
            {currentUser?.name?.charAt(0).toUpperCase() || 'P'}
          </div>
        </div>
      </div>
    </header>
  );
}
