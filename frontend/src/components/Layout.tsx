import { useEffect } from 'react';
import { Outlet, Navigate, useParams } from 'react-router';
import Navbar from './Navbar';
import TopBar from './TopBar';
import { useAppStore } from '@/store/appStore';
import { useWorkspaceEvents } from '@/hooks/use-workspace-events';
import { cn } from '@/lib/utils';

export default function Layout() {
  // The URL is the source of truth for which workspace is open. Everything below the
  // Layout lives under /w/:workspaceId, so `workspaceId` is always present here.
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const collapsed = useAppStore((s) => s.sidebarCollapsed);
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
    void hydrateWorkspace(workspaceId).catch(() => {});
  }, [workspaceId, activeWorkspaceId, setActiveWorkspace, hydrateWorkspace]);

  // Subscribe to this workspace's control-plane SSE.
  useWorkspaceEvents(workspaceId ?? null);

  // A stale/unknown workspace id (e.g. an old deep link) → back to the launcher. Guard
  // only after the list has loaded so we don't bounce during the initial hydrate.
  if (workspaces.length > 0 && workspaceId && !workspaces.some((w) => w.id === workspaceId)) {
    return <Navigate to="/workspaces" replace />;
  }

  return (
    <div className="min-h-[100dvh]">
      <Navbar />

      {/* Main content area — margin tracks sidebar collapse state (68px / 240px) */}
      <div
        className={cn(
          'transition-[margin] duration-300',
          collapsed ? 'md:ml-[68px]' : 'md:ml-[240px]'
        )}
      >
        <TopBar />
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
