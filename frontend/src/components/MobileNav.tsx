import { Link, useLocation, useParams } from 'react-router';
import { CalendarDays, KanbanSquare, Mail, Menu, Telescope } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/store/appStore';
import { cn, wsHref } from '@/lib/utils';
import { activeNavPath } from '@/lib/nav';

const ITEMS = [
  { path: '/observatory', labelKey: 'nav.short.observatory', icon: Telescope },
  { path: '/home', labelKey: 'nav.short.home', icon: CalendarDays },
  { path: '/projects', labelKey: 'nav.short.projects', icon: KanbanSquare },
  { path: '/inbox', labelKey: 'nav.short.inbox', icon: Mail },
];

/** Phone bottom bar: the four screens used most, plus "More" for the full drawer (DESIGN §9). */
export default function MobileNav() {
  const { t } = useTranslation();
  const { workspaceId } = useParams();
  const location = useLocation();
  const inboxPending = useAppStore((s) => s.inboxPending);
  const setDrawerOpen = useAppStore((s) => s.setNavDrawerOpen);
  const base = workspaceId ? `/w/${workspaceId}` : '';
  const current = activeNavPath(location.pathname.slice(base.length) || '/');

  return (
    <nav
      aria-label={t('nav.mobile')}
      className="fixed inset-x-0 bottom-0 z-sticky grid grid-cols-5 border-t border-line bg-canvas/95 backdrop-blur-[18px] pb-[env(safe-area-inset-bottom)]"
    >
      {ITEMS.map((item) => {
        const active = current === item.path;
        return (
          <Link
            key={item.path}
            to={wsHref(workspaceId, item.path)}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'flex flex-col items-center justify-center gap-1 min-h-[64px] text-[11px]',
              active ? 'text-sapphire-strong' : 'text-ink-light'
            )}
          >
            <span className="relative">
              <item.icon className="w-[21px] h-[21px]" strokeWidth={active ? 2 : 1.6} />
              {item.path === '/inbox' && inboxPending > 0 && (
                <b className="absolute -top-2 -right-3 grid place-items-center min-w-[17px] h-[17px] px-1 rounded-full border-2 border-canvas bg-amber text-[9px] font-semibold text-[oklch(0.23_0.03_70)]">
                  {inboxPending > 99 ? '99+' : inboxPending}
                </b>
              )}
            </span>
            {t(item.labelKey)}
          </Link>
        );
      })}
      <button
        type="button"
        onClick={() => setDrawerOpen(true)}
        className="flex flex-col items-center justify-center gap-1 min-h-[64px] text-[11px] text-ink-light"
      >
        <Menu className="w-[21px] h-[21px]" strokeWidth={1.6} />
        {t('nav.short.more')}
      </button>
    </nav>
  );
}
