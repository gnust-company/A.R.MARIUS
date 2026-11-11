import { Suspense, lazy, useEffect, useState } from 'react'
import { Routes, Route, Navigate, Outlet } from 'react-router'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import { useAppStore } from './store/appStore'
import { notifyLoadFailed } from '@/lib/notify'
import { screenLoader } from '@/lib/chunkReload'

// Every screen is its own chunk, so opening the app downloads the shell and the one screen
// being looked at, not all of them. The two three.js pages matter most: three.js rides in
// their chunks and no other screen pays for it.
const pages = {
  Landing: () => import('./pages/Landing'),
  Observatory: () => import('./pages/Observatory'),
  Login: () => import('./pages/Login'),
  Workspaces: () => import('./pages/Workspaces'),
  LinkMachine: () => import('./pages/LinkMachine'),
  Onboarding: () => import('./pages/Onboarding'),
  Home: () => import('./pages/Home'),
  Projects: () => import('./pages/Projects'),
  CreateProject: () => import('./pages/CreateProject'),
  ProjectBoard: () => import('./pages/ProjectBoard'),
  ProjectPlan: () => import('./pages/ProjectPlan'),
  Roster: () => import('./pages/Roster'),
  Directory: () => import('./pages/Directory'),
  AgentDetail: () => import('./pages/AgentDetail'),
  Machines: () => import('./pages/Machines'),
  Skills: () => import('./pages/Skills'),
  SkillEditor: () => import('./pages/SkillEditor'),
  Inbox: () => import('./pages/Inbox'),
  Account: () => import('./pages/Account'),
  CollaborationRoom: () => import('./pages/CollaborationRoom'),
  RunTrace: () => import('./pages/RunTrace'),
}

// A screen being opened reloads the tab when its chunk is gone (a deploy happened under it).
// Only these wrapped loaders do: see `useWarmPages` for the bare ones.
const Landing = lazy(screenLoader(pages.Landing))
const Observatory = lazy(screenLoader(pages.Observatory))
const Login = lazy(screenLoader(pages.Login))
const Workspaces = lazy(screenLoader(pages.Workspaces))
const LinkMachine = lazy(screenLoader(pages.LinkMachine))
const Onboarding = lazy(screenLoader(pages.Onboarding))
const Home = lazy(screenLoader(pages.Home))
const Projects = lazy(screenLoader(pages.Projects))
const CreateProject = lazy(screenLoader(pages.CreateProject))
const ProjectBoard = lazy(screenLoader(pages.ProjectBoard))
const ProjectPlan = lazy(screenLoader(pages.ProjectPlan))
const Roster = lazy(screenLoader(pages.Roster))
const Directory = lazy(screenLoader(pages.Directory))
const AgentDetail = lazy(screenLoader(pages.AgentDetail))
const Machines = lazy(screenLoader(pages.Machines))
const Skills = lazy(screenLoader(pages.Skills))
const SkillEditor = lazy(screenLoader(pages.SkillEditor))
const Inbox = lazy(screenLoader(pages.Inbox))
const Account = lazy(screenLoader(pages.Account))
const CollaborationRoom = lazy(screenLoader(pages.CollaborationRoom))
const RunTrace = lazy(screenLoader(pages.RunTrace))

/** The in-workspace screens a signed-in person is likely to open next. Fetched once the
 *  browser is idle, so moving between them does not wait on the network. The three.js pages
 *  stay out: they are the heavy ones, and only whoever opens them should pay. */
const WARM: (keyof typeof pages)[] = [
  'Home', 'Inbox', 'Projects', 'ProjectBoard', 'CollaborationRoom', 'Directory', 'AgentDetail',
  'Machines', 'Skills',
]

function useWarmPages(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return
    // Somebody who asked their browser to save data did not ask for screens they may never open.
    const connection = (navigator as Navigator & { connection?: { saveData?: boolean } }).connection
    if (connection?.saveData) return
    let idle = 0
    // The bare imports, not the wrapped loaders: a warm-up that fails (the build changed under
    // an open tab) must stay silent, or it would reload a page somebody is typing into.
    const warm = () => WARM.forEach((name) => void pages[name]().catch(() => {}))
    // Not straight away: the first screen is still fetching its own data, and these downloads
    // would queue in front of it on the same few connections.
    const timer = setTimeout(() => {
      if ('requestIdleCallback' in window) idle = window.requestIdleCallback(warm, { timeout: 4000 })
      else warm()
    }, 2500)
    return () => {
      clearTimeout(timer)
      if (idle) window.cancelIdleCallback(idle)
    }
  }, [enabled])
}

/** Boot: rehydrate the session from the stored JWT before rendering routes, so the auth
 * guard doesn't bounce a logged-in user on a hard refresh. Also rehydrates the workspace
 * list + persisted active workspace so a refresh on a workspace-less URL (e.g. `/projects`)
 * keeps the user in context. */
function useBootSession() {
  const hydrateMe = useAppStore((s) => s.hydrateMe)
  const hydrateWorkspaces = useAppStore((s) => s.hydrateWorkspaces)
  const [booted, setBooted] = useState(false)
  useEffect(() => {
    let active = true
    void (async () => {
      try {
        await hydrateMe()
        // Only fetch workspaces when authenticated; otherwise the auth guard redirects to
        // /login and there's nothing to hydrate (also avoids a stray 401 here).
        if (useAppStore.getState().currentUser) {
          await hydrateWorkspaces().catch(notifyLoadFailed)
        }
      } catch (e) {
        // A failed hydrate still has to release the boot gate, or the app never renders
        // at all — this is the `finally` that used to sit here, spelled out on both paths
        // because the React Compiler cannot lower a `finally` and bails on the whole
        // component when it meets one. The rethrow keeps the failure just as loud.
        if (active) setBooted(true)
        throw e
      }
      if (active) setBooted(true)
    })()
    return () => {
      active = false
    }
  }, [hydrateMe, hydrateWorkspaces])
  return booted
}

/** Gate every authenticated route: a missing session redirects to /login. */
function RequireAuth() {
  const currentUser = useAppStore((s) => s.currentUser)
  if (!currentUser) return <Navigate to="/login" replace />
  return <Outlet />
}

export default function App() {
  const booted = useBootSession()
  const signedIn = useAppStore((s) => Boolean(s.currentUser))
  useWarmPages(booted && signedIn)

  if (!booted) {
    return <div className="min-h-[100dvh] bg-canvas" />
  }

  return (
    <ErrorBoundary>
    {/* Catches the screens outside the workspace layout while their chunk loads. The screens
        inside it suspend at the layout's own boundary, so the sidebar and top bar stay put. */}
    <Suspense fallback={<div className="min-h-[100dvh] bg-canvas" />}>
    <Routes>
      {/* Landing page — cinematic scroll storytelling (default) */}
      <Route
        path="/"
        element={
          <Suspense fallback={<div className="min-h-[100dvh] bg-canvas-deep" />}>
            <Landing />
          </Suspense>
        }
      />

      {/* Login / register */}
      <Route path="/login" element={<Login />} />

      {/* Everything below requires an authenticated session in real mode */}
      <Route element={<RequireAuth />}>
        {/* Workspaces launcher — no sidebar */}
        <Route path="/workspaces" element={<Workspaces />} />

        {/* The three steps a new account walks through (FR-100). Outside `/w/:workspaceId`:
            the workspace exists by now, but naming it is one of the steps, so a layout with
            that workspace's sidebar around it would show the answer beside the question. */}
        <Route path="/onboarding" element={<Onboarding />} />

        {/* Approving a machine into a workspace. Outside /w/:workspaceId on purpose: at the
            moment the code is typed the machine belongs to no workspace, and picking which
            one it joins is the whole decision being made here. */}
        <Route path="/link" element={<LinkMachine />} />

        {/* All in-workspace pages carry the workspace id on the URL (/w/:workspaceId/…)
            so a hard refresh restores the right workspace + its skills. */}
        <Route path="/w/:workspaceId" element={<Layout />}>
          <Route index element={<Navigate to="home" replace />} />
          <Route path="home" element={<Home />} />
          <Route
            path="observatory"
            element={
              <Suspense fallback={<div className="h-[600px] rounded-xl border border-line bg-canvas-deep md:h-[680px]" />}>
                <Observatory />
              </Suspense>
            }
          />
          <Route path="projects" element={<Projects />} />
          <Route path="projects/new" element={<CreateProject />} />
          <Route path="projects/:id" element={<ProjectBoard />} />
          <Route path="projects/:id/roster" element={<Roster />} />
          <Route path="projects/:id/plan" element={<ProjectPlan />} />
          {/* Leader chat is a side panel on the board; redirect old deep links there. */}
          <Route
            path="projects/:id/leader-chat"
            element={<Navigate to=".." relative="path" replace />}
          />
          <Route path="agents" element={<Directory />} />
          <Route path="agents/:id" element={<AgentDetail />} />
          <Route path="machines" element={<Machines />} />
          <Route path="skills" element={<Skills />} />
          <Route path="skills/:id" element={<SkillEditor />} />
          <Route path="inbox" element={<Inbox />} />
          <Route path="account" element={<Account />} />
          <Route path="tasks/:id" element={<CollaborationRoom />} />
          <Route path="runs/:runId" element={<RunTrace />} />
        </Route>
      </Route>
    </Routes>
    </Suspense>
    </ErrorBoundary>
  )
}
