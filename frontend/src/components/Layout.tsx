import { Outlet, useLocation } from 'react-router';
import Navbar from './Navbar';
import TopBar from './TopBar';

export default function Layout() {
  const location = useLocation();
  const isWorkspacesPage = location.pathname === '/workspaces';

  return (
    <div className="min-h-[100dvh]">
      {/* Navbar - hidden on workspaces page */}
      {!isWorkspacesPage && <Navbar />}

      {/* Main content area */}
      <div className={!isWorkspacesPage ? 'md:ml-[220px]' : ''}>
        {!isWorkspacesPage && <TopBar />}
        <main className="p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
