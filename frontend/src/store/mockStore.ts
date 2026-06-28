import { create } from 'zustand'
import type { SetStateAction } from 'react'

// ── Types ───────────────────────────────────────────

export type AgentStatus = 'idle' | 'working' | 'offline' | 'invited' | 'revoked' | 'online' | 'pending'

export interface Marius {
  id: string
  name: string
  displayName?: string
  role: string
  avatar?: string
  status: AgentStatus
  workspaceId: string
  projectIds: string[]
  description?: string
  skills?: string[]
  adapterType?: string
  model?: string
  isWorkspaceAgent?: boolean
  lastSeen?: string
  roleKey?: string
}

export interface Task {
  id: string
  title: string
  description?: string
  status: TaskStatus
  priority: Priority
  projectId: string
  assigneeId?: string
  seatId?: string
  identifier?: string
  parentId?: string | null
  dependencies?: string[]
  artifacts?: TaskArtifact[]
  trace?: TraceEvent[]
  comments?: TaskComment[]
  checklist?: ChecklistItem[]
  definitionOfDone?: string
  participants?: TaskParticipant[]
  createdAt: string
  updatedAt?: string
}

export type TaskStatus = 'pending' | 'in-progress' | 'review' | 'done' | 'cancelled' | 'todo' | 'in_review' | 'in_progress' | 'backlog' | 'blocked'
export type Priority = 'low' | 'normal' | 'high' | 'urgent' | 'P0' | 'P1' | 'P2'

export interface TaskArtifact {
  id: string
  taskId: string
  type: 'file' | 'code' | 'doc' | 'link'
  title: string
  name?: string
  content?: string
  url?: string
  path?: string
}

export interface TraceEvent {
  id: string
  taskId: string
  type: 'thought' | 'tool_call' | 'tool_result' | 'message' | 'comment' | 'status_change'
  agentId?: string
  content: string
  timestamp: string
  model?: string
  tokens?: { input?: number; output?: number }
  toolName?: string
  args?: Record<string, unknown>
}

export interface TaskComment {
  id: string
  taskId: string
  authorId: string
  content: string
  timestamp: string
}

export interface TaskParticipant {
  id: string
  name: string
  role: string
}

export interface ChecklistItem {
  id: string
  text: string
  done: boolean
}

export interface ProjectSeat {
  id: string
  projectId: string
  mariusId: string | null
  role: string
}

export interface DraftTask {
  title: string
  description?: string
  priority?: Priority
  assigneeId?: string
  dependencies?: string[]
  checklist?: ChecklistItem[]
  workers?: DraftWorker[]
}

export interface DraftWorker {
  mariusId: string
  role: string
}

export interface SkillFile {
  id: string
  name: string
  path?: string
  language?: string
  description?: string
  content?: string
  code?: string
  workspaceId?: string
}

export interface Skill {
  id: string
  name: string
  description?: string
  mariusId?: string
  workspaceId?: string
  type?: 'builtin' | 'github' | 'custom'
  files?: SkillFile[]
}

export interface Workspace {
  id: string
  name: string
  ownerId: string
  description?: string
}

export interface Project {
  id: string
  name: string
  description?: string
  workspaceId: string
  seatIds?: string[]
  seats?: ProjectSeat[]
  status?: 'active' | 'archived' | 'setup'
  definitionOfDone?: string
  objective?: string
  githubUrl?: string
  createdAt?: string
}

export interface User {
  id: string
  name: string
  email?: string
  avatar?: string
  defaultWorkspaceId?: string
}

export interface ChatMessage {
  id: string
  taskId: string
  senderId: string
  content: string
  timestamp: string
}

export interface StoreEvent {
  id: string
  type: string
  payload: Record<string, unknown>
  timestamp: string
}

// ── Store interface ─────────────────────────────────

interface MockStoreState {
  // Data
  currentUser: User | null
  workspaces: Workspace[]
  projects: Project[]
  mariuses: Marius[]
  tasks: Task[]
  skills: Skill[]
  messages: ChatMessage[]
  comments: TaskComment[]
  events: StoreEvent[]
  traceEvents: TraceEvent[]
  activeWorkspaceId: string | null
  sseConnected: boolean
  sidebarCollapsed: boolean

  // Actions
  inviteAgent: (mariusId: string, workspaceId: string) => void
  approveAgent: (mariusId: string) => void
  emitEvent: (event: Omit<StoreEvent, 'id' | 'timestamp'>) => void
  setCurrentUser: (user: User | null) => void
  logout: () => void
  setSidebarCollapsed: (collapsed: boolean) => void
  updateTask: (taskId: string, updater: SetStateAction<Task>) => void
  addComment: (taskId: string, comment: TaskComment) => void
  publishArtifact: (taskId: string, artifact: TaskArtifact) => void
  createSkill: (skill: Skill) => void
  updateSkill: (skillId: string, skill: Partial<Skill>) => void
  createWorkspace: (workspace: Workspace) => void
  setActiveWorkspace: (workspaceId: string) => void
  createTask: (task: Partial<Task> & { title: string; status: TaskStatus; priority: Priority; projectId: string }) => void
  grantSeat: (projectId: string, mariusId: string, role: string) => void
}

// ── Rich Seed Data ──────────────────────────────────

const dummyUser: User = {
  id: 'u1',
  name: 'Admin',
  email: 'admin@armarius.dev',
  avatar: '/avatar-admin.jpg',
  defaultWorkspaceId: 'w1',
}

// ── Workspaces ──────────────────────────────────────

const dummyWorkspaces: Workspace[] = [
  { id: 'w1', name: 'Atelier', ownerId: 'u1', description: 'Personal workspace' },
  { id: 'w2', name: 'R&D Lab', ownerId: 'u1', description: 'Research and development lab' },
]

// ── Agents / Marii ──────────────────────────────────

const dummyMariuses: Marius[] = [
  {
    id: 'm1',
    name: 'Atlas',
    displayName: 'Atlas',
    role: 'Project Leader',
    avatar: '/agent-avatar-atlas.jpg',
    status: 'online',
    workspaceId: 'w1',
    projectIds: ['p1'],
    description: 'Project Leader \u2014 drives task breakdown and commissioning',
    skills: ['planning', 'delegation'],
    adapterType: 'openai',
    model: 'gpt-4o',
    isWorkspaceAgent: true,
  },
  {
    id: 'm2',
    name: 'Vega',
    displayName: 'Vega',
    role: 'Frontend Developer',
    avatar: '/agent-avatar-vega.jpg',
    status: 'working',
    workspaceId: 'w1',
    projectIds: ['p1'],
    description: 'Frontend specialist \u2014 React, TypeScript, UI/UX',
    skills: ['react', 'typescript', 'tailwind'],
    adapterType: 'openai',
    model: 'gpt-4o',
  },
  {
    id: 'm3',
    name: 'Orion',
    displayName: 'Orion',
    role: 'Backend Developer',
    avatar: '/agent-avatar-orion.jpg',
    status: 'online',
    workspaceId: 'w1',
    projectIds: ['p1'],
    description: 'Backend engineer \u2014 API design, databases, infrastructure',
    skills: ['nodejs', 'postgresql', 'redis'],
    adapterType: 'openai',
    model: 'gpt-4o',
  },
  {
    id: 'm4',
    name: 'Lyra',
    displayName: 'Lyra',
    role: 'Designer',
    avatar: '/agent-avatar-lyra.jpg',
    status: 'idle',
    workspaceId: 'w1',
    projectIds: ['p1'],
    description: 'Visual design \u2014 Scriptorium aesthetic, brand systems',
    skills: ['figma', 'illustration', 'brand'],
    adapterType: 'openai',
    model: 'gpt-4o',
  },
  {
    id: 'm5',
    name: 'Nova',
    displayName: 'Nova',
    role: 'QA Engineer',
    avatar: '/agent-avatar-nova.jpg',
    status: 'offline',
    workspaceId: 'w1',
    projectIds: [],
    description: 'Quality assurance \u2014 testing, audits, edge cases',
    skills: ['playwright', 'jest', 'ci'],
    adapterType: 'openai',
    model: 'gpt-4o',
  },
  {
    id: 'm6',
    name: 'Marin',
    displayName: 'Marin',
    role: 'DevOps',
    status: 'pending',
    workspaceId: 'w1',
    projectIds: [],
    description: 'Pending approval \u2014 infrastructure and CI/CD',
    skills: ['docker', 'kubernetes', 'aws'],
    adapterType: 'openai',
    model: 'gpt-4o',
  },
  {
    id: 'm7',
    name: 'Echo-1',
    displayName: 'Echo-1',
    role: 'Assistant',
    status: 'invited',
    workspaceId: 'w1',
    projectIds: [],
    description: 'Invited \u2014 awaiting enrollment',
    skills: ['general'],
    adapterType: 'openai',
    model: 'gpt-4o-mini',
  },
]

// ── Projects ────────────────────────────────────────

const dummyProjects: Project[] = [
  {
    id: 'p1',
    name: 'Settings Redesign',
    workspaceId: 'w1',
    status: 'active',
    objective: 'Redesign the settings page with WCAG AA contrast, dark mode toggle, responsive navigation',
    githubUrl: 'https://github.com/armarius/demo-project',
    createdAt: '2026-06-15T08:00:00Z',
    seats: [
      { id: 's1', projectId: 'p1', mariusId: 'm1', role: 'leader' },
      { id: 's2', projectId: 'p1', mariusId: 'm2', role: 'worker' },
      { id: 's3', projectId: 'p1', mariusId: 'm3', role: 'worker' },
      { id: 's4', projectId: 'p1', mariusId: 'm4', role: 'worker' },
    ],
  },
  {
    id: 'p2',
    name: 'Docs Site',
    workspaceId: 'w1',
    status: 'setup',
    objective: 'Build documentation site with searchable API reference and guides',
    githubUrl: 'https://github.com/armarius/docs-site',
    createdAt: '2026-06-25T09:00:00Z',
    seats: [
      { id: 's5', projectId: 'p2', mariusId: null, role: 'leader' },
      { id: 's6', projectId: 'p2', mariusId: null, role: 'worker' },
    ],
  },
]

// ── Tasks ───────────────────────────────────────────

const dummyTasks: Task[] = [
  {
    id: 't1',
    identifier: 'ARM-1',
    title: 'WCAG audit current settings',
    status: 'done',
    priority: 'P1',
    projectId: 'p1',
    assigneeId: 'm2',
    createdAt: '2026-06-20T10:00:00Z',
    checklist: [
      { id: 'c1', text: 'Run contrast checker', done: true },
      { id: 'c2', text: 'Document violations', done: true },
    ],
    comments: [],
    artifacts: [
      { id: 'a1', taskId: 't1', type: 'file', title: 'audit-report.md', name: 'audit-report.md' },
    ],
    trace: [],
    participants: [
      { id: 'm2', name: 'Vega', role: 'Frontend Developer' },
    ],
    dependencies: [],
    definitionOfDone: 'All contrast violations documented with severity ratings',
  },
  {
    id: 't2',
    identifier: 'ARM-2',
    title: 'Implement dark mode toggle',
    status: 'in_progress',
    priority: 'P0',
    projectId: 'p1',
    assigneeId: 'm2',
    createdAt: '2026-06-21T08:30:00Z',
    checklist: [
      { id: 'c3', text: 'Create ThemeContext', done: true },
      { id: 'c4', text: 'Add toggle switch UI', done: true },
      { id: 'c5', text: 'Persist preference to localStorage', done: false },
      { id: 'c6', text: 'Test system preference detection', done: false },
    ],
    comments: [
      { id: 'cm1', taskId: 't2', authorId: 'm2', content: 'Using CSS variables approach, much cleaner than the old JS-based one.', timestamp: '2026-06-22T14:00:00Z' },
    ],
    artifacts: [
      { id: 'a2', taskId: 't2', type: 'code', title: 'ThemeContext.tsx', name: 'ThemeContext.tsx' },
    ],
    trace: [],
    participants: [
      { id: 'm2', name: 'Vega', role: 'Frontend Developer' },
      { id: 'm4', name: 'Lyra', role: 'Designer' },
    ],
    dependencies: ['t1'],
    definitionOfDone: 'Toggle works across all routes and persists user preference',
  },
  {
    id: 't3',
    identifier: 'ARM-3',
    title: 'Build responsive navigation sidebar',
    status: 'in_progress',
    priority: 'P1',
    projectId: 'p1',
    assigneeId: 'm4',
    createdAt: '2026-06-21T11:00:00Z',
    checklist: [
      { id: 'c7', text: 'Mobile collapsible menu', done: true },
      { id: 'c8', text: 'Desktop persistent sidebar', done: true },
      { id: 'c9', text: 'Active state indicators', done: false },
    ],
    comments: [],
    artifacts: [],
    trace: [],
    participants: [
      { id: 'm4', name: 'Lyra', role: 'Designer' },
      { id: 'm2', name: 'Vega', role: 'Frontend Developer' },
    ],
    dependencies: [],
    definitionOfDone: 'Navigation works on 320px to 4K without horizontal scroll',
  },
  {
    id: 't4',
    identifier: 'ARM-4',
    title: 'Design system token updates',
    status: 'in_review',
    priority: 'P1',
    projectId: 'p1',
    assigneeId: 'm4',
    createdAt: '2026-06-22T09:00:00Z',
    checklist: [
      { id: 'c10', text: 'New color tokens', done: true },
      { id: 'c11', text: 'Typography scale', done: true },
      { id: 'c12', text: 'Spacing tokens', done: true },
      { id: 'c13', text: 'Shadow/elevation tokens', done: true },
    ],
    comments: [
      { id: 'cm2', taskId: 't4', authorId: 'm1', content: 'The terracotta shade looks great in dark mode.', timestamp: '2026-06-23T10:30:00Z' },
    ],
    artifacts: [
      { id: 'a3', taskId: 't4', type: 'file', title: 'tokens.json', name: 'tokens.json' },
      { id: 'a4', taskId: 't4', type: 'file', title: 'tokens.css', name: 'tokens.css' },
    ],
    trace: [],
    participants: [
      { id: 'm4', name: 'Lyra', role: 'Designer' },
      { id: 'm1', name: 'Atlas', role: 'Project Leader' },
    ],
    dependencies: [],
    definitionOfDone: 'All components use new tokens, zero hardcoded values remain',
  },
  {
    id: 't5',
    identifier: 'ARM-5',
    title: 'API endpoints for user preferences',
    status: 'in_progress',
    priority: 'P0',
    projectId: 'p1',
    assigneeId: 'm3',
    createdAt: '2026-06-22T10:00:00Z',
    checklist: [
      { id: 'c14', text: 'GET /preferences endpoint', done: true },
      { id: 'c15', text: 'PATCH /preferences endpoint', done: true },
      { id: 'c16', text: 'Validation schema', done: true },
      { id: 'c17', text: 'Integration tests', done: false },
    ],
    comments: [],
    artifacts: [
      { id: 'a5', taskId: 't5', type: 'code', title: 'preferences.routes.ts', name: 'preferences.routes.ts' },
      { id: 'a6', taskId: 't5', type: 'code', title: 'preferences.test.ts', name: 'preferences.test.ts' },
    ],
    trace: [],
    participants: [
      { id: 'm3', name: 'Orion', role: 'Backend Developer' },
    ],
    dependencies: [],
    definitionOfDone: 'Both endpoints tested with >90% coverage and documented',
  },
  {
    id: 't6',
    identifier: 'ARM-6',
    title: 'Set up documentation site scaffolding',
    status: 'todo',
    priority: 'P2',
    projectId: 'p2',
    assigneeId: undefined,
    createdAt: '2026-06-25T09:00:00Z',
    checklist: [
      { id: 'c18', text: 'Choose SSG framework', done: false },
      { id: 'c19', text: 'Initial project structure', done: false },
      { id: 'c20', text: 'CI pipeline for deploy', done: false },
    ],
    comments: [],
    artifacts: [],
    trace: [],
    participants: [],
    dependencies: [],
    definitionOfDone: 'Site deploys automatically on merge to main',
  },
  {
    id: 't7',
    identifier: 'ARM-7',
    title: 'Database migration for theme storage',
    status: 'blocked',
    priority: 'P0',
    projectId: 'p1',
    assigneeId: 'm3',
    createdAt: '2026-06-23T08:00:00Z',
    checklist: [
      { id: 'c21', text: 'Add theme_preferences column', done: false },
      { id: 'c22', text: 'Write migration script', done: false },
    ],
    comments: [
      { id: 'cm3', taskId: 't7', authorId: 'm3', content: 'Blocked until DBA reviews the schema change.', timestamp: '2026-06-23T12:00:00Z' },
    ],
    artifacts: [],
    trace: [],
    participants: [
      { id: 'm3', name: 'Orion', role: 'Backend Developer' },
    ],
    dependencies: ['t5'],
    definitionOfDone: 'Migration runs idempotently, rollback tested',
  },
]

// ── Skills ──────────────────────────────────────────

const dummySkills: Skill[] = [
  {
    id: 'sk1',
    name: 'armarius-http',
    description: 'HTTP client for Armarius API calls',
    type: 'builtin',
    workspaceId: 'w1',
    files: [{ id: 'f1', name: 'SKILL.md', path: 'SKILL.md', language: 'markdown', content: '# armarius-http\n\nHTTP client for Armarius API.', workspaceId: 'w1' }],
  },
  {
    id: 'sk2',
    name: 'algorithmic-art',
    description: 'Generative art algorithms and rendering',
    type: 'github',
    workspaceId: 'w1',
    files: [{ id: 'f2', name: 'SKILL.md', path: 'SKILL.md', language: 'markdown', content: '# algorithmic-art\n\nGenerative art algorithms.', workspaceId: 'w1' }, { id: 'f3', name: 'src/index.ts', path: 'src/index.ts', language: 'typescript', content: '// Algorithm implementations\n', workspaceId: 'w1' }],
  },
]

// ── Store ───────────────────────────────────────────

export const useMockStore = create<MockStoreState>((set, get) => ({
  currentUser: dummyUser,
  workspaces: dummyWorkspaces,
  projects: dummyProjects,
  mariuses: dummyMariuses,
  tasks: dummyTasks,
  skills: dummySkills,
  messages: [],
  comments: [],
  events: [],
  traceEvents: [],
  activeWorkspaceId: 'w1',
  sseConnected: false,
  sidebarCollapsed: false,

  inviteAgent: (mariusId: string, workspaceId: string) => {
    const state = get()
    const updated = state.mariuses.map((m) =>
      m.id === mariusId ? { ...m, workspaceId, status: 'invited' as AgentStatus } : m
    )
    set({ mariuses: updated })
  },

  approveAgent: (mariusId: string) => {
    const state = get()
    const updated = state.mariuses.map((m) =>
      m.id === mariusId ? { ...m, status: 'idle' as AgentStatus } : m
    )
    set({ mariuses: updated })
  },

  emitEvent: (event) => {
    const state = get()
    const newEvent: StoreEvent = {
      ...event,
      id: `evt_${Date.now()}`,
      timestamp: new Date().toISOString(),
    }
    set({ events: [...state.events, newEvent] })
  },

  setCurrentUser: (user) => set({ currentUser: user }),

  setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

  logout: () => set({ currentUser: null }),

  updateTask: (taskId: string, updater: SetStateAction<Task>) => {
    const state = get()
    const updatedTasks = state.tasks.map((t) => {
      if (t.id !== taskId) return t
      const newTask = typeof updater === 'function' ? (updater as (prev: Task) => Task)(t) : { ...t, ...updater }
      return newTask
    })
    set({ tasks: updatedTasks })
  },

  addComment: (taskId: string, comment: TaskComment) => {
    const state = get()
    const updatedTasks = state.tasks.map((t) => {
      if (t.id !== taskId) return t
      return { ...t, comments: [...(t.comments || []), comment] }
    })
    set({ tasks: updatedTasks })
  },

  publishArtifact: (taskId: string, artifact: TaskArtifact) => {
    const state = get()
    const updatedTasks = state.tasks.map((t) => {
      if (t.id !== taskId) return t
      return { ...t, artifacts: [...(t.artifacts || []), artifact] }
    })
    set({ tasks: updatedTasks })
  },

  createSkill: (skill: Skill) => {
    const state = get()
    set({ skills: [...state.skills, skill] })
  },

  updateSkill: (skillId: string, skillUpdate: Partial<Skill>) => {
    const state = get()
    const updatedSkills = state.skills.map((s) =>
      s.id === skillId ? { ...s, ...skillUpdate } : s
    )
    set({ skills: updatedSkills })
  },

  createWorkspace: (workspace: Workspace) => {
    const state = get()
    set({ workspaces: [...state.workspaces, workspace] })
  },

  setActiveWorkspace: (workspaceId: string) => {
    set({ activeWorkspaceId: workspaceId })
  },

  grantSeat: (projectId: string, mariusId: string, role: string) => {
    const state = get()
    const project = state.projects.find((p) => p.id === projectId)
    if (!project || !project.seats) return
    // Find first empty seat matching role, or any empty seat
    const updatedSeats = project.seats.map((s) => {
      if (!s.mariusId && s.role === role) {
        return { ...s, mariusId }
      }
      return s
    })
    // If no matching role found, fill first empty seat
    const hasMatch = updatedSeats.some((s) => s.mariusId === mariusId)
    if (!hasMatch) {
      const firstEmpty = project.seats.find((s) => !s.mariusId)
      if (firstEmpty) {
        const idx = project.seats.indexOf(firstEmpty)
        updatedSeats[idx] = { ...firstEmpty, mariusId }
      }
    }
    const updatedProjects = state.projects.map((p) =>
      p.id === projectId ? { ...p, seats: updatedSeats } : p
    )
    set({ projects: updatedProjects })
  },

  createTask: (task) => {
    const state = get()
    const newTask: Task = {
      id: `t_${Date.now()}`,
      createdAt: new Date().toISOString(),
      comments: [],
      artifacts: [],
      trace: [],
      checklist: [],
      participants: [],
      dependencies: [],
      ...task,
    } as Task
    set({ tasks: [...state.tasks, newTask] })
  },
}))
