import { Outlet, useLocation } from 'react-router';
import Navbar from './Navbar';
import TopBar from './TopBar';
import { useMockStore } from '@/store/mockStore';
import { useWorkspaceEvents } from '@/hooks/use-workspace-events';
import { cn } from '@/lib/utils';

export default function Layout() {
  const location = useLocation();
  const isWorkspacesPage = location.pathname === '/workspaces';
  const collapsed = useMockStore((s) => s.sidebarCollapsed);
  const activeWorkspaceId = useMockStore((s) => s.activeWorkspaceId);

  // Real-API mode: subscribe to the active workspace's control-plane SSE (MOCK no-op).
  useWorkspaceEvents(activeWorkspaceId);

  return (
    <div className="min-h-[100dvh]">
      {/* Navbar - hidden on workspaces page */}
      {!isWorkspacesPage && <Navbar />}

      {/* Main content area — margin tracks sidebar collapse state (68px / 240px) */}
      <div
        className={cn(
          'transition-[margin] duration-300',
          !isWorkspacesPage && (collapsed ? 'md:ml-[68px]' : 'md:ml-[240px]')
        )}
      >
        {!isWorkspacesPage && <TopBar />}
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
