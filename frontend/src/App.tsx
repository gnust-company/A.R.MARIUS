import { useEffect, useState } from 'react'
import { Routes, Route, Navigate, Outlet } from 'react-router'
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
import Skills from './pages/Skills'
import SkillEditor from './pages/SkillEditor'
import Inbox from './pages/Inbox'
import Account from './pages/Account'
import CollaborationRoom from './pages/CollaborationRoom'
import { useMockSimulator } from './hooks/use-mock-simulator'
import { useMockStore } from './store/mockStore'

/** Real-API boot: rehydrate the session from the stored JWT before rendering routes, so the
 * auth guard doesn't bounce a logged-in user on a hard refresh. No-op under MOCK. */
function useBootSession() {
  const isMock = useMockStore((s) => s.isMock)
  const hydrateMe = useMockStore((s) => s.hydrateMe)
  const [booted, setBooted] = useState(isMock)
  useEffect(() => {
    if (isMock) return
    let active = true
    hydrateMe().finally(() => {
      if (active) setBooted(true)
    })
    return () => {
      active = false
    }
  }, [isMock, hydrateMe])
  return booted
}

/** Gate every authenticated route. In real mode, a missing session redirects to /login. */
function RequireAuth() {
  const isMock = useMockStore((s) => s.isMock)
  const currentUser = useMockStore((s) => s.currentUser)
  if (!isMock && !currentUser) return <Navigate to="/login" replace />
  return <Outlet />
}

export default function App() {
  // Simulated workspace control-plane SSE (liveness decay + connection state) — MOCK only.
  useMockSimulator()
  const booted = useBootSession()

  if (!booted) {
    return <div className="min-h-[100dvh] bg-[#1a1410]" />
  }

  return (
    <Routes>
      {/* Landing page — cinematic scroll storytelling (default) */}
      <Route path="/" element={<Landing />} />

      {/* Real-API login/register (never reached under MOCK) */}
      <Route path="/login" element={<Login />} />

      {/* Everything below requires an authenticated session in real mode */}
      <Route element={<RequireAuth />}>
        {/* Workspaces launcher — no sidebar */}
        <Route path="/workspaces" element={<Workspaces />} />

        {/* All other pages — with sidebar layout */}
        <Route element={<Layout />}>
          <Route path="/projects" element={<Projects />} />
          <Route path="/projects/new" element={<CreateProject />} />
          <Route path="/projects/:id" element={<ProjectBoard />} />
          <Route path="/projects/:id/roster" element={<Roster />} />
          <Route path="/projects/:id/commission" element={<Commission />} />
          <Route path="/directory" element={<Directory />} />
          <Route path="/skills" element={<Skills />} />
          <Route path="/skills/:id" element={<SkillEditor />} />
          <Route path="/inbox" element={<Inbox />} />
          <Route path="/account" element={<Account />} />
          <Route path="/tasks/:id" element={<CollaborationRoom />} />
        </Route>
      </Route>
    </Routes>
  )
}
