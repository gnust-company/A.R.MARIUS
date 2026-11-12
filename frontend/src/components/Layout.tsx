import { Suspense, useEffect, useState } from 'react';
import { Outlet, Navigate, useParams } from 'react-router';
import CommandPalette from './CommandPalette';
import MobileNav from './MobileNav';
import Navbar from './Navbar';
import TopBar from './TopBar';
import { useAppStore } from '@/store/appStore';
import { useDocumentTitle } from '@/hooks/use-document-title';
import { useInboxCount } from '@/hooks/use-inbox-count';
import { useWorkspaceEvents } from '@/hooks/use-workspace-events';
import { cn } from '@/lib/utils';
import { useViewport } from '@/hooks/use-viewport';
import { notifyLoadFailed } from '@/lib/notify';

export default function Layout() {
  // The URL is the source of truth for which workspace is open. Everything below the
  // Layout lives under /w/:workspaceId, so `workspaceId` is always present here.
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const collapsed = useAppStore((s) => s.sidebarCollapsed);
  const viewport = useViewport();
  const workspaces = useAppStore((s) => s.workspaces);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const setActiveWorkspace = useAppStore((s) => s.setActiveWorkspace);
  const hydrateWorkspace = useAppStore((s) => s.hydrateWorkspace);

  // Sync the active workspace to the URL and load its slice (agents/projects/SKILLS).
  // This is what makes a hard refresh on e.g. /w/<id>/skills keep the skills — boot only
  // hydrates the workspace *list*; the per-workspace slice is loaded here from the URL.
  useEffect(() => {
    if (!workspaceId) return;
    if (workspaceId !== activeWorkspaceId) setActiveWorkspace(workspaceId);
    void hydrateWorkspace(workspaceId).catch(notifyLoadFailed);
  }, [workspaceId, activeWorkspaceId, setActiveWorkspace, hydrateWorkspace]);

  // Subscribe to this workspace's control-plane SSE.
  useWorkspaceEvents(workspaceId ?? null);

  // And to the patron's own inbox channel, which is a different channel on purpose: a letter is
  // addressed to a person, not to a workspace, so it arrives keyed by who is asking. Mounted
  // here because the sidebar shows the count on every screen.
  useInboxCount(workspaceId);

  // The tab says which screen it holds and how many letters are waiting.
  useDocumentTitle();

  // ⌘K / Ctrl+K opens "go anywhere" from every in-workspace page.
  const [commandOpen, setCommandOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setCommandOpen((v) => !v);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // A stale/unknown workspace id (e.g. an old deep link) → back to the launcher. Guard
  // only after the list has loaded so we don't bounce during the initial hydrate.
  if (workspaces.length > 0 && workspaceId && !workspaces.some((w) => w.id === workspaceId)) {
    return <Navigate to="/workspaces" replace />;
  }

  return (
    <div className="min-h-[100dvh]">
      <Navbar />

      {/* Main content area — margin tracks the rail: none on a phone (drawer), the icon rail
          below desktop, and the person's own collapse choice on desktop (68px / 240px). */}
      <div
        className={cn(
          'transition-[margin] duration-300',
          viewport === 'tablet' && 'ml-[68px]',
          viewport === 'desktop' && (collapsed ? 'ml-[68px]' : 'ml-[240px]')
        )}
      >
        <TopBar onOpenCommand={() => setCommandOpen(true)} />
        {/* On a phone the bottom bar sits over the page, so the page keeps clear of it. */}
        <main className={cn('px-4 py-6 sm:px-6 sm:py-8 xl:px-9', viewport === 'phone' && 'pb-28')}>
          {/* Each screen is its own chunk. While one loads, only this area waits: the shell
              around it stays, and the reserved height keeps the footer from jumping up. */}
          <Suspense fallback={<div className="min-h-[60vh]" aria-busy="true" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      {viewport === 'phone' && <MobileNav />}
      <CommandPalette open={commandOpen} onClose={() => setCommandOpen(false)} />
    </div>
  );
}
