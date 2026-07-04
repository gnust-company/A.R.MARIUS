import { create } from 'zustand'
import type { SetStateAction } from 'react'

import { MOCK } from '@/lib/env'
import { clearTokens } from '@/lib/auth'
import * as api from '@/lib/api'
import {
  artifactToVM,
  commentToVM,
  mariusToVM,
  onboardingToVM,
  projectDetailToVM,
  projectToVM,
  skillToVM,
  taskToVM,
  workspaceToVM,
} from '@/lib/mappers'

/** Replace an item by id, or append it. Used to upsert hydrated entities into the store. */
function upsertById<T extends { id: string }>(list: T[], item: T): T[] {
  const idx = list.findIndex((x) => x.id === item.id)
  if (idx === -1) return [...list, item]
  const copy = [...list]
  copy[idx] = item
  return copy
}

/** Merge incoming list-level projects into the store without clobbering richer
 * detail-level entries (e.g. a project already opened via `hydrateProject`, which
 * carries seats). Existing entries win; incoming ones are added. */
function mergeProjects(existing: Project[], incoming: Project[]): Project[] {
  const map = new Map(existing.map((p) => [p.id, p]))
  for (const p of incoming) if (!map.has(p.id)) map.set(p.id, p)
  return [...map.values()]
}

// Persist the active workspace across reloads so a hard refresh on `/projects` (whose URL
// carries no workspace id) doesn't drop the user out of context. MOCK ignores storage and
// keeps its seeded `'w1'`.
const ACTIVE_WS_KEY = 'armarius.activeWorkspace'
function loadActiveWorkspace(): string | null {
  if (MOCK) return 'w1'
  try {
    return localStorage.getItem(ACTIVE_WS_KEY)
  } catch {
    return null
  }
}
function saveActiveWorkspace(id: string | null): void {
  if (MOCK) return
  try {
    if (id) localStorage.setItem(ACTIVE_WS_KEY, id)
    else localStorage.removeItem(ACTIVE_WS_KEY)
  } catch {
    // storage unavailable — non-fatal
  }
}

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

export type TaskStatus = 'pending' | 'in-progress' | 'review' | 'done' | 'cancelled' | 'todo' | 'in_review' | 'in_progress' | 'backlog' | 'blocked' | 'draft'
export type Priority = 'low' | 'normal' | 'high' | 'urgent' | 'P0' | 'P1' | 'P2'

// Backend commission proposal status — a draft task only promotes to `todo` on confirm.
// Alias kept so the mappers module can speak the backend artifact shape generically.
export type Artifact = TaskArtifact

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

export type TraceEventType =
  | 'run.delta'
  | 'run.tool'
  | 'run.usage'
  | 'run.complete'
  | 'run.error'
  | 'agent.comment'
  | 'agent.status'
  // legacy shapes kept so older fixtures still type-check
  | 'thought'
  | 'tool_call'
  | 'tool_result'
  | 'message'
  | 'comment'
  | 'status_change'

export interface TraceEvent {
  id: string
  taskId: string
  type: TraceEventType
  agentId?: string
  content: string
  timestamp: string
  model?: string
  tokens?: { input?: number; output?: number; used?: number; total?: number; prompt?: number; completion?: number }
  toolName?: string
  args?: Record<string, unknown>
}

export interface TaskComment {
  id: string
  taskId: string
  authorId: string
  authorName?: string
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

// ── Commission view-model (backend CommissionOut → UI) ──────────────────────────────
// The Commission page keeps its own rich local session state; this is the slim shape the
// API mapper (`commissionToVM`) normalizes to so the store can hold the active session.
export interface CommissionDraftTask {
  id: string
  title: string
  description: string
  priority: Priority
  assigneeId?: string
  checklist: ChecklistItem[]
  dependencies: string[]
}

export interface CommissionSession {
  id: string
  projectId: string
  leaderMariusId?: string
  taskId?: string
  status: 'open' | 'confirmed' | 'abandoned'
  leaderState: 'thinking' | 'waiting' | 'leader_offline'
  transcript: Array<{ role: string; text: string }>
  messages: Array<{ role: string; text: string }>
  draftTask: CommissionDraftTask | null
}

// ── Onboarding view-model (backend OnboardingOut → UI) ───────────────────────────────
// The agent-assisted project-setup chat. The Workspace Agent runs a scripted playbook
// (greet → propose a roster → confirm); `finalize` creates a real project + roster and the
// store swaps the session for the new project id.
export interface OnboardingTurn {
  id: string
  role: 'agent' | 'patron' | 'system'
  text: string
  timestamp: string
}

export interface OnboardingSessionVM {
  id: string
  workspaceId: string
  status: 'open' | 'finalized' | 'abandoned'
  transcript: OnboardingTurn[]
  collected: Record<string, unknown>
  createdProjectId?: string
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
  /** Present for GitHub-imported skills; absent for manual/built-in ones. */
  sourceUrl?: string
  files?: SkillFile[]
}

export interface Workspace {
  id: string
  name: string
  ownerId: string
  description?: string
  /** The designated host Marius (Workspace Agent) — undefined until one is seated (#32). */
  workspaceAgentId?: string
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
  activeOnboarding: OnboardingSessionVM | null
  sseConnected: boolean
  sidebarCollapsed: boolean
  /** True when running the frozen in-memory demo (VITE_MOCK=true). When false the store is a
   * cache over the real API: it starts empty and is filled by the `hydrate*` thunks. */
  isMock: boolean

  // Actions
  /** Invite a new agent into the active workspace. Real mode posts to the backend and
   * returns its onboarding materials verbatim (the copyable `invite` prompt + one-time
   * enrollment code); mock mode fabricates an equivalent demo prompt client-side. */
  inviteNewAgent: (input: {
    name: string
    adapterType: string
    skillIds: string[]
    /** Seat the newcomer as Workspace Agent; a sitting host is demoted, kept (#32). */
    isWorkspaceAgent?: boolean
  }) => Promise<{ agent: Marius; invite: string; enrollmentCode: string }>
  /** Hand the Workspace Agent seat to this Marius (real endpoint in API mode, #32). */
  designateWorkspaceAgent: (mariusId: string) => Promise<void>
  /** Internal: stamp WA flags + the workspace pointer after a designation (#32). */
  applyDesignation: (workspaceId: string, mariusId: string) => void
  approveAgent: (mariusId: string) => Promise<void>
  emitEvent: (event: Omit<StoreEvent, 'id' | 'timestamp'>) => void
  setCurrentUser: (user: User | null) => void
  logout: () => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setSseConnected: (connected: boolean) => void
  /** Simulated workspace control-plane SSE — cycle one agent's liveness per tick. */
  simulateLivenessTick: () => void
  updateTask: (taskId: string, updater: SetStateAction<Task>) => Promise<void>
  addComment: (taskId: string, comment: Partial<TaskComment> & { authorId: string; content: string }) => Promise<void>
  /** Simulated per-task trace SSE — append one streamed run event. */
  appendTrace: (taskId: string, event: Partial<TraceEvent> & { type: TraceEvent['type']; content: string }) => void
  publishArtifact: (taskId: string, artifact: TaskArtifact) => Promise<void>
  createSkill: (input: Omit<Skill, 'id'> & { id?: string }) => Promise<Skill>
  importSkill: (url: string, workspaceId?: string) => Promise<Skill>
  updateSkill: (skillId: string, skill: Partial<Skill>) => void
  deleteSkill: (skillId: string) => Promise<void>
  createWorkspace: (workspace: Workspace) => Promise<Workspace>
  updateWorkspace: (workspaceId: string, name: string) => Promise<void>
  deleteWorkspace: (workspaceId: string) => Promise<void>
  updateMarius: (mariusId: string, patch: { name?: string; role?: string }) => Promise<void>
  deleteMarius: (mariusId: string) => Promise<void>
  setActiveWorkspace: (workspaceId: string) => void
  createProject: (input: {
    name: string
    description?: string
    objective?: string
    workspaceId?: string
    leaderId?: string
    seats?: Array<{ roleKey: string; roleLabel: string; mariusId: string | null; skillsRequired: string[] }>
  }) => Promise<Project>
  createTask: (task: Partial<Task> & { title: string; status: TaskStatus; priority: Priority; projectId: string }) => Promise<Task>
  deleteProject: (projectId: string) => Promise<void>
  grantSeat: (projectId: string, mariusId: string, role: string) => Promise<void>

  // ── Onboarding (agent-assisted project setup · Sprint 7) ───────────────────────────
  /** Open (or rejoin) the active workspace's agent-setup chat. */
  startOnboarding: () => Promise<OnboardingSessionVM>
  /** Send a Patron turn; the Workspace Agent responds (scripted). */
  postOnboardingMessage: (text: string) => Promise<OnboardingSessionVM>
  /** Lock the plan → creates a real project + roster (MOCK: a local project). */
  finalizeOnboarding: () => Promise<OnboardingSessionVM>
  /** Drop the active chat. */
  abandonOnboarding: () => Promise<void>
  /** Rehydrate the active chat on mount, if one is open. */
  hydrateActiveOnboarding: () => Promise<void>

  // ── API hydration thunks (no-ops under MOCK) ───────────────────────────────────────
  hydrateMe: () => Promise<void>
  hydrateWorkspaces: () => Promise<void>
  hydrateWorkspace: (workspaceId: string) => Promise<void>
  hydrateProject: (projectId: string) => Promise<void>
  hydrateTask: (taskId: string) => Promise<void>
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
    trace: [
      { id: 'tr1', taskId: 't2', type: 'run.delta', agentId: 'm2', model: 'gpt-4o', content: 'Reviewing the existing theme handling. The old approach toggles a class on <body>; I will replace it with a ThemeContext + CSS custom properties so it works across every route.', timestamp: '2026-06-22T13:55:02Z' },
      { id: 'tr2', taskId: 't2', type: 'run.tool', agentId: 'm2', toolName: 'read_file', content: 'Read src/theme/legacy-theme.js', args: { path: 'src/theme/legacy-theme.js' }, timestamp: '2026-06-22T13:55:08Z' },
      { id: 'tr3', taskId: 't2', type: 'run.tool', agentId: 'm2', toolName: 'write_file', content: 'Created src/theme/ThemeContext.tsx with a provider + useTheme() hook persisting to localStorage.', args: { path: 'src/theme/ThemeContext.tsx', bytes: 1840 }, timestamp: '2026-06-22T13:56:10Z' },
      { id: 'tr4', taskId: 't2', type: 'run.delta', agentId: 'm2', model: 'gpt-4o', content: 'Wiring the toggle switch into the settings header and defaulting to the system preference via prefers-color-scheme.', timestamp: '2026-06-22T13:56:44Z' },
      { id: 'tr5', taskId: 't2', type: 'run.usage', agentId: 'm2', model: 'gpt-4o', content: 'turn usage', tokens: { used: 3120, total: 128000, prompt: 2440, completion: 680 }, timestamp: '2026-06-22T13:56:45Z' },
    ],
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
    trace: [
      { id: 'tr6', taskId: 't3', type: 'run.delta', agentId: 'm4', model: 'gpt-4o', content: 'Designing the responsive breakpoints: a slide-over drawer under 768px and a persistent rail above it. Checking the active-route indicator next.', timestamp: '2026-06-22T15:10:00Z' },
      { id: 'tr7', taskId: 't3', type: 'run.tool', agentId: 'm4', toolName: 'write_file', content: 'Updated src/components/Sidebar.tsx with the collapsible drawer.', args: { path: 'src/components/Sidebar.tsx', bytes: 2210 }, timestamp: '2026-06-22T15:11:20Z' },
    ],
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
    trace: [
      { id: 'tr8', taskId: 't5', type: 'run.delta', agentId: 'm3', model: 'gpt-4o', content: 'Both endpoints are implemented and validated against the JSON schema. Now adding integration tests to push coverage above 90%.', timestamp: '2026-06-22T16:02:00Z' },
      { id: 'tr9', taskId: 't5', type: 'run.tool', agentId: 'm3', toolName: 'run_tests', content: 'pytest tests/preferences — 11 passed, coverage 87%.', args: { suite: 'preferences', passed: 11, coverage: 0.87 }, timestamp: '2026-06-22T16:03:30Z' },
      { id: 'tr10', taskId: 't5', type: 'run.usage', agentId: 'm3', model: 'gpt-4o', content: 'turn usage', tokens: { used: 5400, total: 128000, prompt: 4100, completion: 1300 }, timestamp: '2026-06-22T16:03:31Z' },
    ],
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

// ── Onboarding scripted brain (MOCK path only) ───────────────────────────────────────
// Mirrors the backend's deterministic onboarder so the frozen demo's agent-mode tab works
// end-to-end without a real gateway. The real path ignores this and talks to the API.
const ONBOARDING_GREETING =
  "Hi — I'm the Workspace Agent. Tell me what you'd like to build and I'll propose a team for it: the objective, who you need (e.g. frontend, backend, design), and I'll stand up the project with a Project Leader plus those worker roles."

const MOCK_ROLE_KEYWORDS: Array<[string[], string]> = [
  [['frontend', 'ui', 'react', 'css', 'web'], 'Frontend'],
  [['backend', 'api', 'server', 'database', 'db'], 'Backend'],
  [['design', 'ux', 'figma'], 'Design'],
  [['test', 'qa', 'review', 'security'], 'QA / Reviewer'],
]
const MOCK_CONFIRM = ['looks good', 'yes', 'confirm', 'ok', 'create', 'go ahead', 'perfect', 'ship', 'finalize']
const MOCK_RECONSIDER = ['no', 'change', 'add', 'remove', 'instead', 'swap', 'replace']

function mockOnboardingConfirm(text: string): boolean {
  const l = text.toLowerCase()
  if (MOCK_RECONSIDER.some((w) => l.includes(w))) return false
  return MOCK_CONFIRM.some((w) => l.includes(w))
}

interface MockRole {
  key: string
  title: string
  is_leader: boolean
}

function mockProposePlan(objective: string): { name: string; roles: MockRole[] } {
  const l = objective.toLowerCase()
  const workerTitles = MOCK_ROLE_KEYWORDS.filter(([kw]) => kw.some((k) => l.includes(k))).map(([, t]) => t)
  const workers = (workerTitles.length ? workerTitles : ['Frontend', 'Backend']).map((t) => ({
    key: t.toLowerCase().replace(/[^a-z0-9]+/g, '-'),
    title: t,
    is_leader: false,
  }))
  const name = objective.trim()
    ? objective
        .trim()
        .split(/\s+/)
        .slice(0, 4)
        .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
        .join(' ')
    : 'New Project'
  return { name, roles: [{ key: 'leader', title: 'Project Leader', is_leader: true }, ...workers] }
}

function mockRespond(
  collected: Record<string, unknown>,
  text: string,
): { reply: string; collected: Record<string, unknown> } {
  if (mockOnboardingConfirm(text) && collected.roles) {
    return {
      reply: "Locked in. Hit “Create project” and I'll stand it up — a Project Leader seat plus the worker roles we agreed on.",
      collected: { ...collected, ready: true },
    }
  }
  const plan = mockProposePlan(text)
  const workerLines = plan.roles
    .filter((r) => !r.is_leader)
    .map((r) => `  • ${r.title}`)
    .join('\n')
  return {
    reply: `Got it — I'll set up ${plan.name} with one Project Leader plus:\n${workerLines}\n\nIf that looks right, say “looks good” (or hit Create). Want to add or swap a role? Tell me what you need.`,
    collected: { objective: text.trim(), project_name: plan.name, roles: plan.roles, ready: false },
  }
}

function mockPlanFromCollected(collected: Record<string, unknown>): {
  name: string
  objective: string
  roles: MockRole[]
} {
  const raw = (collected.roles as MockRole[] | undefined) ?? mockProposePlan('').roles
  const name = (collected.project_name as string) || 'New Project'
  return { name, objective: (collected.objective as string) || name, roles: raw }
}

// ── Store ───────────────────────────────────────────

export const useMockStore = create<MockStoreState>((set, get) => ({
  currentUser: MOCK ? dummyUser : null,
  workspaces: MOCK ? dummyWorkspaces : [],
  projects: MOCK ? dummyProjects : [],
  mariuses: MOCK ? dummyMariuses : [],
  tasks: MOCK ? dummyTasks : [],
  skills: MOCK ? dummySkills : [],
  messages: [],
  comments: [],
  events: [],
  traceEvents: [],
  activeWorkspaceId: loadActiveWorkspace(),
  activeOnboarding: null,
  sseConnected: false,
  sidebarCollapsed: false,
  isMock: MOCK,

  inviteNewAgent: async ({ name, adapterType, skillIds, isWorkspaceAgent }) => {
    const workspaceId = get().activeWorkspaceId || 'w1'
    const skillNames = get()
      .skills.filter((s) => skillIds.includes(s.id))
      .map((s) => s.name)

    if (!get().isMock) {
      // Real mode: the backend creates the INVITED Marius, mints the enrollment code and
      // assembles the full onboarding prompt (STEP 0–4, absolute public URL). Send
      // skill_ids — that is what `_build_invite` resolves for the prompt's install step.
      const dto = await api.inviteMarius(workspaceId, {
        name,
        skills: skillNames,
        skill_ids: skillIds,
        adapter_type: adapterType,
        is_workspace_agent: isWorkspaceAgent ?? false,
      })
      const agent: Marius = {
        ...mariusToVM(dto),
        // A fresh invite has no liveness yet (maps to `offline`); its real state is the
        // invite lifecycle, which we know is `invited` on a 201.
        status: 'invited',
        displayName: name,
        isWorkspaceAgent: isWorkspaceAgent === true,
      }
      set({ mariuses: [...get().mariuses, agent] })
      if (isWorkspaceAgent) get().applyDesignation(workspaceId, agent.id)
      return { agent, invite: dto.invite ?? '', enrollmentCode: dto.enrollment_code ?? '' }
    }

    // Mock mode: fabricate the same shape client-side so the demo mirrors the real flow.
    const enrollmentCode = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
    const agent: Marius = {
      id: `m-${Date.now().toString(36)}`,
      name: name.toLowerCase().replace(/\s+/g, '-'),
      displayName: name,
      role: '',
      adapterType,
      skills: skillNames,
      avatar: '/agent-avatar-echo.jpg',
      status: 'invited',
      workspaceId,
      projectIds: [],
    }
    set({ mariuses: [...get().mariuses, agent] })
    if (isWorkspaceAgent) get().applyDesignation(workspaceId, agent.id)

    // Simulate the agent presenting its code shortly after (invited → pending review).
    setTimeout(() => {
      const store = get()
      const current = store.mariuses.find((m) => m.id === agent.id)
      if (current && current.status === 'invited') {
        set({
          mariuses: store.mariuses.map((m) =>
            m.id === agent.id ? { ...m, status: 'pending' as AgentStatus } : m,
          ),
        })
        store.emitEvent({
          type: 'marius.status_changed',
          payload: { mariusId: agent.id, from: 'invited', to: 'pending' },
        })
      }
    }, 3000)

    // A condensed stand-in for the backend's STEP 0–4 onboarding prompt (demo only).
    const base = window.location.origin
    const invite = [
      'ARMARIUS · AGENT ONBOARDING (demo)',
      '',
      `You are "${name}", joining this workspace.`,
      '',
      'STEP 0 · ENROLL AND WAIT FOR APPROVAL',
      `  POST ${base}/agent/enroll`,
      `  {"marius_id": "${agent.id}", "enrollment_code": "${enrollmentCode}"}`,
      '  → 200 {"agent_token": "arm_..."} once your patron approves.',
      '',
      'STEP 1 · SAVE YOUR CREDENTIALS to ~/.armarius/credentials/',
      `STEP 2 · CONFIRM YOU ARE ONLINE — GET ${base}/agent/me`,
      ...(skillNames.length > 0
        ? [
            'STEP 3 · INSTALL YOUR SKILLS',
            ...skillNames.map((s) => `  - ${s}  (GET ${base}/agent/skills/<slug>)`),
          ]
        : []),
    ].join('\n')
    return { agent, invite, enrollmentCode }
  },

  applyDesignation: (workspaceId: string, mariusId: string) => {
    set({
      mariuses: get().mariuses.map((m) =>
        m.workspaceId !== workspaceId
          ? m
          : {
              ...m,
              isWorkspaceAgent: m.id === mariusId,
              // Mirror the backend swap: the new host wears the role, the demoted one
              // drops to a plain agent (kept, not revoked — #32).
              role: m.id === mariusId ? 'Workspace Agent' : m.isWorkspaceAgent ? '' : m.role,
            },
      ),
      workspaces: get().workspaces.map((w) =>
        w.id === workspaceId ? { ...w, workspaceAgentId: mariusId } : w,
      ),
    })
  },

  designateWorkspaceAgent: async (mariusId: string) => {
    const workspaceId =
      get().mariuses.find((m) => m.id === mariusId)?.workspaceId ||
      get().activeWorkspaceId ||
      ''
    if (!get().isMock) {
      await api.designateWorkspaceAgent(workspaceId, mariusId)
    }
    get().applyDesignation(workspaceId, mariusId)
    get().emitEvent({ type: 'workspace_agent.designated', payload: { mariusId } })
  },

  approveAgent: async (mariusId: string) => {
    if (get().isMock) {
      const updated = get().mariuses.map((m) =>
        m.id === mariusId ? { ...m, status: 'online' as AgentStatus, lastSeen: new Date().toISOString() } : m,
      )
      set({ mariuses: updated })
      get().emitEvent({ type: 'marius.online', payload: { mariusId } })
      return
    }
    const existing = get().mariuses.find((m) => m.id === mariusId)
    const workspaceId = existing?.workspaceId
    if (!workspaceId) return
    const dto = await api.approveMarius(workspaceId, mariusId)
    const vm = mariusToVM(dto)
    set({ mariuses: get().mariuses.map((m) => (m.id === mariusId ? { ...vm, projectIds: m.projectIds } : m)) })
    get().emitEvent({ type: 'marius.online', payload: { mariusId } })
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

  setSseConnected: (connected) => set({ sseConnected: connected }),

  // Simulated Hybrid SSE — workspace control-plane channel. Each tick decays one
  // agent's liveness ONLINE → idle(checking) → offline, occasionally reviving it,
  // so the directory dots feel alive without a backend.
  simulateLivenessTick: () => {
    const state = get()
    // Only cycle agents that are part of the workspace (skip invited/pending/revoked).
    const cyclable = state.mariuses.filter(
      (m) => !['invited', 'pending', 'revoked'].includes(m.status)
    )
    if (cyclable.length === 0) return
    const target = cyclable[Math.floor(Math.random() * cyclable.length)]
    const decay: Record<string, AgentStatus> = {
      online: 'idle',
      working: 'online',
      idle: 'offline',
      offline: 'online',
    }
    const next = decay[target.status] ?? 'online'
    set({
      mariuses: state.mariuses.map((m) =>
        m.id === target.id ? { ...m, status: next, lastSeen: new Date().toISOString() } : m
      ),
    })
    get().emitEvent({ type: 'marius.liveness', payload: { mariusId: target.id, status: next } })
  },

  logout: () => {
    if (!MOCK) clearTokens()
    saveActiveWorkspace(null)
    set({ currentUser: null, activeWorkspaceId: null })
  },

  updateTask: async (taskId: string, updater: SetStateAction<Task>) => {
    const prev = get().tasks.find((t) => t.id === taskId)
    if (!prev) return
    const newTask = typeof updater === 'function' ? (updater as (prev: Task) => Task)(prev) : { ...prev, ...updater }
    set({ tasks: get().tasks.map((t) => (t.id === taskId ? newTask : t)) })
    // Real mode: persist a status transition; revert optimistically on rejection (e.g. the
    // backend DONE-gate returns 409 when artifacts are missing). Call sites are fire-and-
    // forget, so we revert + log rather than throw (avoids unhandled promise rejections).
    if (!get().isMock && newTask.status !== prev.status) {
      try {
        await api.updateTaskStatus(taskId, newTask.status)
      } catch (e) {
        set({ tasks: get().tasks.map((t) => (t.id === taskId ? prev : t)) })
        console.error('updateTask status failed, reverted:', e)
      }
    }
  },

  addComment: async (taskId, comment) => {
    if (get().isMock) {
      const full: TaskComment = {
        id: comment.id ?? `cm_${Date.now()}`,
        taskId,
        authorId: comment.authorId,
        authorName: comment.authorName,
        content: comment.content,
        timestamp: comment.timestamp ?? new Date().toISOString(),
      }
      set({ tasks: get().tasks.map((t) => (t.id === taskId ? { ...t, comments: [...(t.comments || []), full] } : t)) })
      return
    }
    const dto = await api.postComment(taskId, comment.content)
    const full = commentToVM(dto)
    full.authorName = comment.authorName // author display name resolved client-side
    set({ tasks: get().tasks.map((t) => (t.id === taskId ? { ...t, comments: [...(t.comments || []), full] } : t)) })
  },

  appendTrace: (taskId, event) => {
    const state = get()
    const full: TraceEvent = {
      id: event.id ?? `tr_${Date.now()}_${Math.floor(Math.random() * 1000)}`,
      taskId,
      type: event.type,
      agentId: event.agentId,
      content: event.content,
      timestamp: event.timestamp ?? new Date().toISOString(),
      model: event.model,
      tokens: event.tokens,
      toolName: event.toolName,
      args: event.args,
    }
    const updatedTasks = state.tasks.map((t) => {
      if (t.id !== taskId) return t
      return { ...t, trace: [...(t.trace || []), full] }
    })
    set({ tasks: updatedTasks })
  },

  publishArtifact: async (taskId: string, artifact: TaskArtifact) => {
    if (get().isMock) {
      set({ tasks: get().tasks.map((t) => (t.id === taskId ? { ...t, artifacts: [...(t.artifacts || []), artifact] } : t)) })
      return
    }
    const kind = artifact.type === 'link' ? 'link' : 'file'
    const name = artifact.name || artifact.title || 'artifact'
    const dto = await api.publishArtifact(taskId, name, kind, artifact.url)
    const full = artifactToVM(dto)
    set({ tasks: get().tasks.map((t) => (t.id === taskId ? { ...t, artifacts: [...(t.artifacts || []), full] } : t)) })
  },

  createSkill: async (input) => {
    const workspaceId = input.workspaceId || get().activeWorkspaceId || undefined
    // Real mode: persist manual skills through the backend so they survive an F5 and
    // carry a real id (the detail route resolves against it). GitHub imports go through
    // the dedicated importSkill() path — the backend clones + persists them there.
    if (!get().isMock && workspaceId) {
      const dto = await api.createManualSkill(workspaceId, {
        name: input.name,
        description: input.description,
      })
      const vm = skillToVM(dto)
      set({ skills: [...get().skills, vm] })
      return vm
    }
    // Mock mode: build it client-side with a real id so navigation lands on /skills/<id>
    // instead of /skills/undefined.
    const skill: Skill = { ...input, id: input.id ?? `sk_${Date.now()}`, workspaceId }
    set({ skills: [...get().skills, skill] })
    return skill
  },

  importSkill: async (url: string, workspaceId?: string) => {
    const wsId = workspaceId || get().activeWorkspaceId || undefined
    // Real mode: the backend actually clones the GitHub folder (detects SKILL.md, pulls
    // that folder) and persists the skill — so it survives F5 and carries a real id. A
    // bad URL / missing SKILL.md throws here (the modal surfaces the message); we never
    // fabricate a placeholder skill (issues #41, #42).
    if (!get().isMock && wsId) {
      const dto = await api.importSkill(wsId, url)
      const vm = skillToVM(dto)
      set({ skills: [...get().skills, vm] })
      return vm
    }
    // Mock/demo only (no backend to clone from): stand up a minimal skill from the URL so
    // the frozen demo still navigates. The deployed stack never takes this branch.
    const seg = url.replace(/\/+$/, '').split('/').pop() || 'imported-skill'
    const name = seg.replace(/\.(md|markdown)$/i, '') || 'imported-skill'
    const skill: Skill = {
      id: `sk_${Date.now()}`,
      name,
      description: `Imported from ${url}`,
      type: 'github',
      sourceUrl: url,
      workspaceId: wsId,
      files: [
        { id: 'skill-md', name: 'SKILL.md', path: 'SKILL.md', language: 'markdown', content: `---\nname: ${name}\n---\n`, workspaceId: wsId },
      ],
    }
    set({ skills: [...get().skills, skill] })
    return skill
  },

  updateSkill: (skillId: string, skillUpdate: Partial<Skill>) => {
    const state = get()
    const updatedSkills = state.skills.map((s) =>
      s.id === skillId ? { ...s, ...skillUpdate } : s
    )
    set({ skills: updatedSkills })
  },

  deleteSkill: async (skillId: string) => {
    const skill = get().skills.find((s) => s.id === skillId)
    const workspaceId = skill?.workspaceId || get().activeWorkspaceId
    // Only call the backend for a persisted skill. A client-only id (never saved — e.g. a
    // stale pre-persistence import) isn't a UUID, so the `{skill_id}` route would 422;
    // just drop it locally instead (issue #41).
    if (!get().isMock && workspaceId && !skillId.startsWith('sk_')) {
      await api.deleteSkill(workspaceId, skillId)
    }
    set({ skills: get().skills.filter((s) => s.id !== skillId) })
  },

  createWorkspace: async (workspace: Workspace) => {
    if (get().isMock) {
      set({ workspaces: [...get().workspaces, workspace] })
      return workspace
    }
    const dto = await api.createWorkspace(workspace.name)
    const ownerId = get().currentUser?.id ?? ''
    const vm = workspaceToVM(dto, ownerId)
    set({ workspaces: [...get().workspaces, vm] })
    return vm
  },

  updateWorkspace: async (workspaceId: string, name: string) => {
    if (!get().isMock) {
      await api.updateWorkspace(workspaceId, name)
    }
    set({
      workspaces: get().workspaces.map((w) => (w.id === workspaceId ? { ...w, name } : w)),
    })
  },

  deleteWorkspace: async (workspaceId: string) => {
    if (!get().isMock) {
      await api.deleteWorkspace(workspaceId)
    }
    // Drop the workspace and everything scoped to it (the backend cascades server-side).
    const remaining = get().workspaces.filter((w) => w.id !== workspaceId)
    set({
      workspaces: remaining,
      projects: get().projects.filter((p) => p.workspaceId !== workspaceId),
      mariuses: get().mariuses.filter((m) => m.workspaceId !== workspaceId),
      skills: get().skills.filter((s) => s.workspaceId !== workspaceId),
    })
    // If the deleted workspace was active, fall back to another (or none).
    if (get().activeWorkspaceId === workspaceId) {
      const next = remaining[0]?.id ?? null
      saveActiveWorkspace(next)
      set({ activeWorkspaceId: next })
    }
  },

  updateMarius: async (mariusId: string, patchBody: { name?: string; role?: string }) => {
    const m = get().mariuses.find((x) => x.id === mariusId)
    const workspaceId = m?.workspaceId || get().activeWorkspaceId
    if (!get().isMock && workspaceId) {
      await api.updateMarius(workspaceId, mariusId, {
        name: patchBody.name,
        role: patchBody.role,
      })
    }
    set({
      mariuses: get().mariuses.map((x) =>
        x.id === mariusId
          ? {
              ...x,
              // Wire contract renames on `name` (mariusToVM maps dto.name → name), so write
              // `name` — the canonical field — not just `displayName` (issue #29). Keep
              // displayName in sync so the Directory's `displayName || name` render matches.
              ...(patchBody.name ? { name: patchBody.name, displayName: patchBody.name } : {}),
              ...(patchBody.role ? { role: patchBody.role } : {}),
            }
          : x,
      ),
    })
  },

  deleteMarius: async (mariusId: string) => {
    const m = get().mariuses.find((x) => x.id === mariusId)
    const workspaceId = m?.workspaceId || get().activeWorkspaceId
    if (!get().isMock && workspaceId) {
      await api.deleteMarius(workspaceId, mariusId)
    }
    set({ mariuses: get().mariuses.filter((x) => x.id !== mariusId) })
  },

  setActiveWorkspace: (workspaceId: string) => {
    saveActiveWorkspace(workspaceId)
    set({ activeWorkspaceId: workspaceId })
  },

  grantSeat: async (projectId: string, mariusId: string, role: string) => {
    const project = get().projects.find((p) => p.id === projectId)
    if (!project) return

    if (get().isMock) {
      if (!project.seats) return
      // Find first empty seat matching role, or any empty seat
      const updatedSeats = project.seats.map((s) => (!s.mariusId && s.role === role ? { ...s, mariusId } : s))
      const hasMatch = updatedSeats.some((s) => s.mariusId === mariusId)
      if (!hasMatch) {
        const firstEmpty = project.seats.find((s) => !s.mariusId)
        if (firstEmpty) {
          const idx = project.seats.indexOf(firstEmpty)
          updatedSeats[idx] = { ...firstEmpty, mariusId }
        }
      }
      // Recompute the setup→active gate: a project goes active once every seat is filled.
      const allSeated = updatedSeats.length > 0 && updatedSeats.every((s) => s.mariusId)
      const nextStatus = allSeated && project.status === 'setup' ? 'active' : project.status
      const becameActive = nextStatus === 'active' && project.status === 'setup'
      set({ projects: get().projects.map((p) => (p.id === projectId ? { ...p, seats: updatedSeats, status: nextStatus } : p)) })
      if (becameActive) {
        get().emitEvent({ type: 'project.active', payload: { projectId } })
      }
      return
    }

    // Real mode: the backend grants the seat (system-only) and recomputes setup→active.
    await api.grantSeat(projectId, { marius_id: mariusId, role_key: role })
    await get().hydrateProject(projectId)
    if (get().projects.find((p) => p.id === projectId)?.status === 'active') {
      get().emitEvent({ type: 'project.active', payload: { projectId } })
    }
  },

  createTask: async (task) => {
    if (get().isMock) {
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
      set({ tasks: [...get().tasks, newTask] })
      return newTask
    }
    const dto = await api.createTask(task.projectId, task.title, task.description)
    const newTask = taskToVM(dto)
    set({ tasks: [...get().tasks, newTask] })
    return newTask
  },

  deleteProject: async (projectId: string) => {
    // Drop the project + its tasks locally either way; the backend cascade
    // (tasks/artifacts/comments/seats/roles) is triggered in real mode.
    if (!get().isMock) {
      await api.deleteProject(projectId)
    }
    set({
      projects: get().projects.filter((p) => p.id !== projectId),
      tasks: get().tasks.filter((t) => t.projectId !== projectId),
    })
  },

  createProject: async (input) => {
    const workspaceId = input.workspaceId || get().activeWorkspaceId || ''
    if (get().isMock) {
      const id = `p_${Date.now()}`
      const project: Project = {
        id,
        name: input.name,
        description: input.description,
        objective: input.objective,
        workspaceId,
        status: 'setup',
        seats: [
          { id: `${id}-leader`, projectId: id, mariusId: input.leaderId || null, role: 'leader' },
          ...(input.seats ?? []).map((s, i) => ({ id: `${id}-${i}`, projectId: id, mariusId: null, role: s.roleKey })),
        ],
      }
      set({ projects: [...get().projects, project] })
      return project
    }
    // Real: reconstruct role specs from the flat seat list the wizard emits (one entry per
    // seat; group worker seats by their display title → {title, seats, skill_ids}).
    const workerSeats = (input.seats ?? []).filter((s) => s.roleKey !== 'leader')
    const roleMap = new Map<string, { title: string; seats: number; skill_ids: string[] }>()
    for (const s of workerSeats) {
      const entry = roleMap.get(s.roleLabel) ?? { title: s.roleLabel, seats: 0, skill_ids: s.skillsRequired ?? [] }
      entry.seats += 1
      roleMap.set(s.roleLabel, entry)
    }
    const body: api.CreateProjectBody = {
      name: input.name,
      description: input.description,
      objective: input.objective,
      leader: { marius_id: input.leaderId || undefined, responsibilities: '' },
      roles: [...roleMap.values()].map((r) => ({ title: r.title, seats: r.seats, skill_ids: r.skill_ids })),
    }
    const dto = await api.createProject(workspaceId, body)
    const project = projectDetailToVM(dto)
    set({ projects: upsertById(get().projects, project) })
    return project
  },

  // ── Onboarding (agent-assisted project setup · Sprint 7) ───────────────────────────
  startOnboarding: async () => {
    const workspaceId = get().activeWorkspaceId || ''
    if (get().isMock) {
      const vm: OnboardingSessionVM = {
        id: `ob_${Date.now()}`,
        workspaceId,
        status: 'open',
        transcript: [
          { id: 'greet', role: 'agent', text: ONBOARDING_GREETING, timestamp: new Date().toISOString() },
        ],
        collected: {},
      }
      set({ activeOnboarding: vm })
      return vm
    }
    // Rejoin an already-open chat if one exists; otherwise open a fresh one.
    const existing = await api.getActiveOnboarding(workspaceId)
    const dto = existing ?? (await api.startOnboarding(workspaceId))
    const vm = onboardingToVM(dto)
    set({ activeOnboarding: vm })
    return vm
  },

  postOnboardingMessage: async (text: string) => {
    const session = get().activeOnboarding
    if (!session) throw new Error('no active onboarding session')
    if (get().isMock) {
      const { reply, collected } = mockRespond(session.collected, text)
      const ts = new Date().toISOString()
      const base = session.transcript.length
      const vm: OnboardingSessionVM = {
        ...session,
        transcript: [
          ...session.transcript,
          { id: `${session.id}-${base}`, role: 'patron', text, timestamp: ts },
          { id: `${session.id}-${base + 1}`, role: 'agent', text: reply, timestamp: ts },
        ],
        collected,
      }
      set({ activeOnboarding: vm })
      return vm
    }
    const dto = await api.postOnboardingMessage(session.id, text)
    const vm = onboardingToVM(dto)
    set({ activeOnboarding: vm })
    return vm
  },

  finalizeOnboarding: async () => {
    const session = get().activeOnboarding
    if (!session) throw new Error('no active onboarding session')
    if (get().isMock) {
      // Materialise a local project from the collected plan (mirrors backend finalize).
      const plan = mockPlanFromCollected(session.collected)
      const id = `p_${Date.now()}`
      const project: Project = {
        id,
        name: plan.name,
        description: plan.objective,
        objective: plan.objective,
        workspaceId: session.workspaceId,
        status: 'setup',
        seats: plan.roles.map((r, i) => ({ id: `${id}-${i}`, projectId: id, mariusId: null, role: r.key })),
      }
      set({ projects: [...get().projects, project] })
      const vm: OnboardingSessionVM = { ...session, status: 'finalized', createdProjectId: id }
      set({ activeOnboarding: vm })
      return vm
    }
    const dto = await api.finalizeOnboarding(session.id)
    const vm = onboardingToVM(dto)
    set({ activeOnboarding: vm })
    return vm
  },

  abandonOnboarding: async () => {
    const session = get().activeOnboarding
    if (!session) return
    if (!get().isMock) {
      await api.abandonOnboarding(session.id)
    }
    set({ activeOnboarding: null })
  },

  hydrateActiveOnboarding: async () => {
    if (get().isMock) return
    const workspaceId = get().activeWorkspaceId || ''
    if (!workspaceId) return
    const dto = await api.getActiveOnboarding(workspaceId)
    set({ activeOnboarding: dto ? onboardingToVM(dto) : null })
  },

  // ── API hydration thunks ───────────────────────────────────────────────────────────
  hydrateMe: async () => {
    if (get().isMock) return
    try {
      const user = await api.getMe()
      set({ currentUser: { id: user.id, name: user.full_name, email: user.email } })
    } catch {
      // Not logged in (401) — leave currentUser null; the auth guard redirects to Landing.
    }
  },

  hydrateWorkspaces: async () => {
    if (get().isMock) return
    const ownerId = get().currentUser?.id ?? ''
    const dtos = await api.listWorkspaces()
    const vms = dtos.map((d) => workspaceToVM(d, ownerId))
    // Fan out each workspace's projects AND mariuses so the launcher's project/agent counts
    // are correct and stable from first paint (otherwise they read 0 until a workspace is
    // opened, then flip to the real count — the "ảo ảo" inconsistency). Merge, don't replace,
    // so an already-opened project keeps its detail-level seats.
    const [perWsProjects, perWsMariuses] = await Promise.all([
      Promise.all(dtos.map((d) => api.listProjects(d.id).catch(() => []))),
      Promise.all(dtos.map((d) => api.listMariuses(d.id).catch(() => []))),
    ])
    const incomingProjects = perWsProjects.flat().map(projectToVM)
    // Stamp each agent's WA badge from its workspace's designated-host pointer (#32).
    const hostByWs = new Map(dtos.map((d) => [String(d.id), d.workspace_agent_id ?? null]))
    const incomingMariuses = perWsMariuses
      .flat()
      .map(mariusToVM)
      .map((m) => ({ ...m, isWorkspaceAgent: hostByWs.get(m.workspaceId) === m.id }))
    // Keep the persisted active workspace if it still exists; otherwise fall back to the
    // first workspace (and persist that choice).
    const prevActive = get().activeWorkspaceId
    const activeWorkspaceId =
      prevActive && vms.some((w) => w.id === prevActive) ? prevActive : (vms[0]?.id ?? null)
    saveActiveWorkspace(activeWorkspaceId)
    // Replace the mariuses for the workspaces we just loaded; keep any others intact.
    const loadedWsIds = new Set(dtos.map((d) => String(d.id)))
    set((s) => ({
      workspaces: vms,
      projects: mergeProjects(s.projects, incomingProjects),
      mariuses: [
        ...s.mariuses.filter((m) => !loadedWsIds.has(m.workspaceId)),
        ...incomingMariuses,
      ],
      activeWorkspaceId,
    }))
  },

  hydrateWorkspace: async (workspaceId: string) => {
    if (get().isMock) return
    const [mariuses, projects, skills] = await Promise.all([
      api.listMariuses(workspaceId),
      api.listProjects(workspaceId),
      api.listSkills(workspaceId).catch(() => []),
    ])
    // The designated-host pointer came in with hydrateWorkspaces (boot runs it first).
    const hostId = get().workspaces.find((w) => w.id === workspaceId)?.workspaceAgentId
    // Replace ONLY this workspace's slice — keep other workspaces' data intact. The
    // previous version reassigned the whole array, so opening workspace B wiped A's
    // agents/projects/skills (and made the launcher counts flap back to 0).
    set((s) => ({
      mariuses: [
        ...s.mariuses.filter((m) => m.workspaceId !== workspaceId),
        ...mariuses.map(mariusToVM).map((m) => ({
          ...m,
          isWorkspaceAgent: hostId != null && m.id === hostId,
        })),
      ],
      projects: [
        ...s.projects.filter((p) => p.workspaceId !== workspaceId),
        ...projects.map(projectToVM),
      ],
      skills: [
        ...s.skills.filter((sk) => sk.workspaceId !== workspaceId),
        ...skills.map(skillToVM),
      ],
    }))
  },

  hydrateProject: async (projectId: string) => {
    if (get().isMock) return
    const [detail, taskDtos] = await Promise.all([api.getProject(projectId), api.listTasks(projectId)])
    const project = projectDetailToVM(detail)
    const tasks = taskDtos.map(taskToVM)
    set({
      projects: upsertById(get().projects, project),
      tasks: [...get().tasks.filter((t) => t.projectId !== projectId), ...tasks],
    })
  },

  hydrateTask: async (taskId: string) => {
    if (get().isMock) return
    const [taskDto, comments, artifacts] = await Promise.all([
      api.getTask(taskId),
      api.listComments(taskId),
      api.listArtifacts(taskId),
    ])
    const full: Task = {
      ...taskToVM(taskDto),
      comments: comments.map(commentToVM),
      artifacts: artifacts.map(artifactToVM),
    }
    set({ tasks: upsertById(get().tasks, full) })
  },
}))
