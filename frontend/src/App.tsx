import { Routes, Route } from 'react-router'
import Layout from './components/Layout'
import Landing from './pages/Landing'
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

export default function App() {
  return (
    <Routes>
      {/* Landing page — cinematic scroll storytelling (default) */}
      <Route path="/" element={<Landing />} />

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
    </Routes>
  )
}
