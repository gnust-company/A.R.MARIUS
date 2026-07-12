import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, Outlet } from 'react-router'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Workspaces from './pages/Workspaces'
import Projects from './pages/Projects'
import CreateProject from './pages/CreateProject'
import ProjectBoard from './pages/ProjectBoard'
import Roster from './pages/Roster'
import Commission from './pages/Commission'
import Directory from './pages/Directory'
import AgentDetail from './pages/AgentDetail'
import Skills from './pages/Skills'
import SkillEditor from './pages/SkillEditor'
import Inbox from './pages/Inbox'
import Account from './pages/Account'
import CollaborationRoom from './pages/CollaborationRoom'
import { useMockStore } from './store/mockStore'

/** Boot: rehydrate the session from the stored JWT before rendering routes, so the auth
 * guard doesn't bounce a logged-in user on a hard refresh. Also rehydrates the workspace
 * list + persisted active workspace so a refresh on a workspace-less URL (e.g. `/projects`)
 * keeps the user in context. */
function useBootSession() {
  const hydrateMe = useMockStore((s) => s.hydrateMe)
  const hydrateWorkspaces = useMockStore((s) => s.hydrateWorkspaces)
  const [booted, setBooted] = useState(false)
  useEffect(() => {
    let active = true
    void (async () => {
      try {
        await hydrateMe()
        // Only fetch workspaces when authenticated; otherwise the auth guard redirects to
        // /login and there's nothing to hydrate (also avoids a stray 401 here).
        if (useMockStore.getState().currentUser) {
          await hydrateWorkspaces().catch(() => {})
        }
      } finally {
        if (active) setBooted(true)
      }
    })()
    return () => {
      active = false
    }
  }, [hydrateMe, hydrateWorkspaces])
  return booted
}

/** Gate every authenticated route: a missing session redirects to /login. */
function RequireAuth() {
  const currentUser = useMockStore((s) => s.currentUser)
  if (!currentUser) return <Navigate to="/login" replace />
  return <Outlet />
}

export default function App() {
  const booted = useBootSession()

  if (!booted) {
    return <div className="min-h-[100dvh] bg-[#1a1410]" />
  }

  return (
    <ErrorBoundary>
    <Routes>
      {/* Landing page — cinematic scroll storytelling (default) */}
      <Route path="/" element={<Landing />} />

      {/* Login / register */}
      <Route path="/login" element={<Login />} />

      {/* Everything below requires an authenticated session in real mode */}
      <Route element={<RequireAuth />}>
        {/* Workspaces launcher — no sidebar */}
        <Route path="/workspaces" element={<Workspaces />} />

        {/* All in-workspace pages carry the workspace id on the URL (/w/:workspaceId/…)
            so a hard refresh restores the right workspace + its skills. */}
        <Route path="/w/:workspaceId" element={<Layout />}>
          <Route index element={<Navigate to="projects" replace />} />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/new" element={<CreateProject />} />
          <Route path="projects/:id" element={<ProjectBoard />} />
          <Route path="projects/:id/roster" element={<Roster />} />
          <Route path="projects/:id/commission" element={<Commission />} />
          <Route path="agents" element={<Directory />} />
          <Route path="agents/:id" element={<AgentDetail />} />
          <Route path="skills" element={<Skills />} />
          <Route path="skills/:id" element={<SkillEditor />} />
          <Route path="inbox" element={<Inbox />} />
          <Route path="account" element={<Account />} />
          <Route path="tasks/:id" element={<CollaborationRoom />} />
        </Route>
      </Route>
    </Routes>
    </ErrorBoundary>
  )
}
