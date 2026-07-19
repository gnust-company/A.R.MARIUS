import { create } from 'zustand'
import type { SetStateAction } from 'react'

import { clearTokens } from '@/lib/auth'
import * as api from '@/lib/api'
import type { OnboardingCollected, OnboardingDraft, OnboardingQuestion } from '@/lib/api'
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

/** Load a project's tasks and attach each task's `blocked_by` edges (#91) so the board can
 * flag blocked cards and the detail panel can list blockers — one place, two consumers. */
async function loadProjectTasksWithDeps(projectId: string): Promise<Task[]> {
  const [taskDtos, edges] = await Promise.all([
    api.listTasks(projectId),
    api.listProjectDependencies(projectId),
  ])
  const byTask = new Map<string, string[]>()
  for (const e of edges) {
    const arr = byTask.get(e.task_id) ?? []
    arr.push(e.blocks_task_id)
    byTask.set(e.task_id, arr)
  }
  return taskDtos.map((dto) => ({ ...taskToVM(dto), dependencies: byTask.get(dto.id) ?? [] }))
}

/** Merge incoming list-level projects into the store without clobbering richer
 * detail-level entries (e.g. a project already opened via `hydrateProject`, which
 * carries seats). Existing entries win; incoming ones are added. */
function mergeProjects(existing: Project[], incoming: Project[]): Project[] {
  const map = new Map(existing.map((p) => [p.id, p]))
  for (const p of incoming) if (!map.has(p.id)) map.set(p.id, p)
  return [...map.values()]
}

/** Refresh ONE workspace's project slice from a list-level fetch while preserving any
 * detail-level fields already loaded via `hydrateProject`. A bare list refresh must NOT blank
 * an opened project's `seats` array — doing so re-triggered the Roster loading gate forever
 * and reset the project card to 0/0 (#70). List-level fields (name/status/objective/counts)
 * take the fresh value; `seats`/`githubUrl` are kept from the existing detail entry. */
function mergeWorkspaceProjects(
  existing: Project[],
  workspaceId: string,
  incoming: Project[],
): Project[] {
  const byId = new Map(existing.map((p) => [p.id, p]))
  const refreshed = incoming.map((p) => {
    const prev = byId.get(p.id)
    return prev?.seats
      ? { ...p, seats: prev.seats, githubUrl: prev.githubUrl ?? p.githubUrl }
      : p
  })
  return [...existing.filter((p) => p.workspaceId !== workspaceId), ...refreshed]
}

// Persist the active workspace across reloads so a hard refresh on `/projects` (whose URL
// carries no workspace id) doesn't drop the user out of context.
const ACTIVE_WS_KEY = 'armarius.activeWorkspace'
function loadActiveWorkspace(): string | null {
  try {
    return localStorage.getItem(ACTIVE_WS_KEY)
  } catch {
    return null
  }
}
function saveActiveWorkspace(id: string | null): void {
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
  /** The agent's gateway URL (operator-invite, #63) — shown in details; the key is never kept. */
  gatewayUrl?: string
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
  collected: OnboardingCollected
  /** 'asking' while the agent is interviewing; 'complete' once a draft is ready to confirm. */
  phase: 'asking' | 'complete'
  /** The current tick-select question, or null when none is pending. */
  pendingQuestion: OnboardingQuestion | null
  /** The proposed project + roster, present once the interview is complete. */
  draft: OnboardingDraft | null
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
  /** JIRA-style KEY — prefix of task identifiers "{key}-{n}". */
  key?: string
  description?: string
  workspaceId: string
  seatIds?: string[]
  seats?: ProjectSeat[]
  // List-view seat fill (from `ProjectOut`) — the card's fallback when no detail `seats`
  // array is loaded. Detail hydration (`seats`) is authoritative when present.
  seatsTotal?: number
  seatsFilled?: number
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

interface AppStoreState {
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

  // Actions
  /** Invite a new agent into the active workspace (operator-invite, #63): the backend mints
   * the token at invite time and pushes the setup prompt to the agent's gateway. Returns the
   * new agent + whether the push landed (`send_status`) — the token is never exposed. */
  inviteNewAgent: (input: {
    name: string
    adapterType: string
    gatewayUrl: string
    apiKey: string
    skillIds: string[]
    /** Seat the newcomer as Workspace Agent; a sitting host is demoted, kept (#32). */
    isWorkspaceAgent?: boolean
  }) => Promise<{ agent: Marius; sendStatus: 'sent' | 'send_failed' }>
  /** Link additional skills to an already-invited agent and push a one-time install prompt
   *  (#74). Returns the send_status of the push (best-effort — the links persist regardless). */
  installAgentSkills: (
    mariusId: string,
    skillIds: string[],
  ) => Promise<{ installedSlugs: string[]; sendStatus: 'sent' | 'send_failed' }>
  /** Hand the Workspace Agent seat to this Marius (real endpoint in API mode, #32). */
  designateWorkspaceAgent: (mariusId: string) => Promise<void>
  /** Internal: stamp WA flags + the workspace pointer after a designation (#32). */
  applyDesignation: (workspaceId: string, mariusId: string) => void
  emitEvent: (event: Omit<StoreEvent, 'id' | 'timestamp'>) => void
  setCurrentUser: (user: User | null) => void
  logout: () => void
  setSidebarCollapsed: (collapsed: boolean) => void
  setSseConnected: (connected: boolean) => void
  updateTask: (taskId: string, updater: SetStateAction<Task>) => Promise<void>
  /** Add a blocked_by edge (this task waits on blocksTaskId), then refresh its blocker list. */
  addTaskDependency: (taskId: string, blocksTaskId: string) => Promise<void>
  /** Remove a blocked_by edge. */
  removeTaskDependency: (taskId: string, blocksTaskId: string) => Promise<void>
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
    key?: string
    description?: string
    objective?: string
    workspaceId?: string
    leaderId?: string
    leaderDescription?: string
    seats?: Array<{ roleKey: string; roleLabel: string; mariusId: string | null; skillsRequired: string[] }>
  }) => Promise<Project>
  createTask: (task: Partial<Task> & { title: string; status: TaskStatus; priority: Priority; projectId: string }) => Promise<Task>
  deleteProject: (projectId: string) => Promise<void>
  grantSeat: (projectId: string, mariusId: string, role: string) => Promise<void>

  // ── Onboarding (agent-driven, question-window project setup · #61) ─────────────────
  /** Open a FRESH agent-setup chat and ask the first question (never rejoins stale history). */
  startOnboarding: () => Promise<OnboardingSessionVM>
  /** Answer the pending tick-select question; the agent asks the next (or emits the draft). */
  answerOnboarding: (answer: string, otherText?: string) => Promise<OnboardingSessionVM>
  /** Confirm the draft → creates a real project + roster. */
  finalizeOnboarding: () => Promise<OnboardingSessionVM>
  /** Drop the active chat. */
  abandonOnboarding: () => Promise<void>
  /** Rehydrate the active chat on mount, if one is open. */
  hydrateActiveOnboarding: () => Promise<void>

  // ── API hydration thunks ───────────────────────────────────────
  hydrateMe: () => Promise<void>
  hydrateWorkspaces: () => Promise<void>
  hydrateWorkspace: (workspaceId: string) => Promise<void>
  hydrateProject: (projectId: string) => Promise<void>
  hydrateTask: (taskId: string) => Promise<void>
}

// ── Store ───────────────────────────────────────────

export const useAppStore = create<AppStoreState>((set, get) => ({
  currentUser: null,
  workspaces: [],
  projects: [],
  mariuses: [],
  tasks: [],
  skills: [],
  messages: [],
  comments: [],
  events: [],
  traceEvents: [],
  activeWorkspaceId: loadActiveWorkspace(),
  activeOnboarding: null,
  sseConnected: false,
  sidebarCollapsed: false,

  inviteNewAgent: async ({ name, adapterType, gatewayUrl, apiKey, skillIds, isWorkspaceAgent }) => {
    const workspaceId = get().activeWorkspaceId || 'w1'
    const skillNames = get()
      .skills.filter((s) => skillIds.includes(s.id))
      .map((s) => s.name)

    // Operator-invite (#63): the backend probes the gateway, mints the token at invite time,
    // and pushes the setup prompt. Send skill_ids — that is what the prompt resolves for the
    // install step. The api_key is sent once and never persisted client-side. Role is NOT set
    // at invite — it is a project-roster concept, assigned later (#63).
    const dto = await api.inviteMarius(workspaceId, {
      name,
      skills: skillNames,
      skill_ids: skillIds,
      adapter_type: adapterType,
      gateway_url: gatewayUrl,
      api_key: apiKey,
      is_workspace_agent: isWorkspaceAgent ?? false,
    })
    const agent: Marius = {
      ...mariusToVM(dto),
      // A newly invited agent is live (approved) but not yet online — it flips to ONLINE
      // once it calls /agent/me with the token the setup prompt handed it.
      status: 'offline',
      displayName: name,
      gatewayUrl: gatewayUrl,
      isWorkspaceAgent: isWorkspaceAgent === true,
    }
    set({ mariuses: [...get().mariuses, agent] })
    if (isWorkspaceAgent) get().applyDesignation(workspaceId, agent.id)
    return { agent, sendStatus: dto.send_status }
  },

  installAgentSkills: async (mariusId, skillIds) => {
    const marius = get().mariuses.find((m) => m.id === mariusId)
    const workspaceId = marius?.workspaceId || get().activeWorkspaceId || 'w1'
    const dto = await api.installSkills(workspaceId, mariusId, skillIds)
    // Refresh this workspace's slice from server truth so the agent's skill pills
    // reflect the freshly linked names — instead of guessing id→name from a skills
    // list that may not be loaded on the page the call was made from.
    await get().hydrateWorkspace(workspaceId).catch(() => {})
    return {
      installedSlugs: dto.installed,
      sendStatus: dto.send_status === 'sent' ? 'sent' : 'send_failed',
    }
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
    await api.designateWorkspaceAgent(workspaceId, mariusId)
    get().applyDesignation(workspaceId, mariusId)
    get().emitEvent({ type: 'workspace_agent.designated', payload: { mariusId } })
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

  logout: () => {
    clearTokens()
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
    if (newTask.status !== prev.status) {
      try {
        await api.updateTaskStatus(taskId, newTask.status)
      } catch (e) {
        set({ tasks: get().tasks.map((t) => (t.id === taskId ? prev : t)) })
        console.error('updateTask status failed, reverted:', e)
      }
    }
  },

  addTaskDependency: async (taskId, blocksTaskId) => {
    // Server rejects self-loop/duplicate/cross-project/cycle (422) — let it bubble so the
    // caller can surface the message; the store only updates on success.
    await api.addTaskDependency(taskId, blocksTaskId)
    set({
      tasks: get().tasks.map((t) =>
        t.id === taskId
          ? { ...t, dependencies: [...(t.dependencies || []), blocksTaskId] }
          : t,
      ),
    })
  },

  removeTaskDependency: async (taskId, blocksTaskId) => {
    await api.removeTaskDependency(taskId, blocksTaskId)
    set({
      tasks: get().tasks.map((t) =>
        t.id === taskId
          ? { ...t, dependencies: (t.dependencies || []).filter((d) => d !== blocksTaskId) }
          : t,
      ),
    })
  },

  addComment: async (taskId, comment) => {
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
    const kind = artifact.type === 'link' ? 'link' : 'file'
    const name = artifact.name || artifact.title || 'artifact'
    const dto = await api.publishArtifact(taskId, name, kind, artifact.url)
    const full = artifactToVM(dto)
    set({ tasks: get().tasks.map((t) => (t.id === taskId ? { ...t, artifacts: [...(t.artifacts || []), full] } : t)) })
  },

  createSkill: async (input) => {
    const workspaceId = input.workspaceId || get().activeWorkspaceId || undefined
    if (!workspaceId) throw new Error('createSkill: no active workspace')
    // Persist manual skills through the backend so they survive an F5 and carry a real id
    // (the detail route resolves against it). GitHub imports go through the dedicated
    // importSkill() path — the backend clones + persists them there.
    const dto = await api.createManualSkill(workspaceId, {
      name: input.name,
      description: input.description,
    })
    const vm = skillToVM(dto)
    set({ skills: [...get().skills, vm] })
    return vm
  },

  importSkill: async (url: string, workspaceId?: string) => {
    const wsId = workspaceId || get().activeWorkspaceId || undefined
    if (!wsId) throw new Error('importSkill: no active workspace')
    // The backend actually clones the GitHub folder (detects SKILL.md, pulls that folder)
    // and persists the skill — so it survives F5 and carries a real id. A bad URL / missing
    // SKILL.md throws here (the modal surfaces the message); we never fabricate a
    // placeholder skill (issues #41, #42).
    const dto = await api.importSkill(wsId, url)
    const vm = skillToVM(dto)
    set({ skills: [...get().skills, vm] })
    return vm
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
    if (workspaceId) {
      await api.deleteSkill(workspaceId, skillId)
    }
    set({ skills: get().skills.filter((s) => s.id !== skillId) })
  },

  createWorkspace: async (workspace: Workspace) => {
    const dto = await api.createWorkspace(workspace.name)
    const ownerId = get().currentUser?.id ?? ''
    const vm = workspaceToVM(dto, ownerId)
    set({ workspaces: [...get().workspaces, vm] })
    return vm
  },

  updateWorkspace: async (workspaceId: string, name: string) => {
    await api.updateWorkspace(workspaceId, name)
    set({
      workspaces: get().workspaces.map((w) => (w.id === workspaceId ? { ...w, name } : w)),
    })
  },

  deleteWorkspace: async (workspaceId: string) => {
    await api.deleteWorkspace(workspaceId)
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
    if (workspaceId) {
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
    if (workspaceId) {
      await api.deleteMarius(workspaceId, mariusId)
    }
    set({
      mariuses: get().mariuses.filter((x) => x.id !== mariusId),
      // If the deleted agent held the Workspace Agent seat, vacate the pointer so the
      // WA badge clears immediately — the backend does the same on its side (#50).
      workspaces: get().workspaces.map((w) =>
        w.workspaceAgentId === mariusId ? { ...w, workspaceAgentId: undefined } : w,
      ),
    })
  },

  setActiveWorkspace: (workspaceId: string) => {
    saveActiveWorkspace(workspaceId)
    set({ activeWorkspaceId: workspaceId })
  },

  grantSeat: async (projectId: string, mariusId: string, role: string) => {
    const project = get().projects.find((p) => p.id === projectId)
    if (!project) return

    // The backend grants the seat (system-only) and recomputes setup→active.
    await api.grantSeat(projectId, { marius_id: mariusId, role_key: role })
    await get().hydrateProject(projectId)
    if (get().projects.find((p) => p.id === projectId)?.status === 'active') {
      get().emitEvent({ type: 'project.active', payload: { projectId } })
    }
  },

  createTask: async (task) => {
    const dto = await api.createTask(task.projectId, {
      title: task.title,
      description: task.description,
    })
    const newTask = taskToVM(dto)
    set({ tasks: [...get().tasks, newTask] })
    return newTask
  },

  deleteProject: async (projectId: string) => {
    // Drop the project + its tasks locally either way; the backend cascade
    // (tasks/artifacts/comments/seats/roles) is triggered in real mode.
    await api.deleteProject(projectId)
    set({
      projects: get().projects.filter((p) => p.id !== projectId),
      tasks: get().tasks.filter((t) => t.projectId !== projectId),
    })
  },

  createProject: async (input) => {
    const workspaceId = input.workspaceId || get().activeWorkspaceId || ''
    // Reconstruct role specs from the flat seat list the wizard emits (one entry per
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
      key: input.key,
      description: input.description,
      objective: input.objective,
      leader: { marius_id: input.leaderId || undefined, description: input.leaderDescription?.trim() || '' },
      roles: [...roleMap.values()].map((r) => ({ title: r.title, seats: r.seats, skill_ids: r.skill_ids })),
    }
    const dto = await api.createProject(workspaceId, body)
    const project = projectDetailToVM(dto)
    set({ projects: upsertById(get().projects, project) })
    return project
  },

  // ── Onboarding (agent-driven, question-window project setup · #61) ─────────────────
  startOnboarding: async () => {
    const workspaceId = get().activeWorkspaceId || ''
    // Always open a FRESH session — the backend abandons any prior open chat, so re-entering
    // the agent flow never resurrects stale history (#61).
    const dto = await api.startOnboarding(workspaceId)
    const vm = onboardingToVM(dto)
    set({ activeOnboarding: vm })
    return vm
  },

  answerOnboarding: async (answer: string, otherText?: string) => {
    const session = get().activeOnboarding
    if (!session) throw new Error('no active onboarding session')
    const dto = await api.answerOnboarding(session.id, answer, otherText)
    const vm = onboardingToVM(dto)
    set({ activeOnboarding: vm })
    return vm
  },

  finalizeOnboarding: async () => {
    const session = get().activeOnboarding
    if (!session) throw new Error('no active onboarding session')
    const dto = await api.finalizeOnboarding(session.id)
    const vm = onboardingToVM(dto)
    set({ activeOnboarding: vm })
    return vm
  },

  abandonOnboarding: async () => {
    const session = get().activeOnboarding
    if (!session) return
    await api.abandonOnboarding(session.id)
    set({ activeOnboarding: null })
  },

  hydrateActiveOnboarding: async () => {
    const workspaceId = get().activeWorkspaceId || ''
    if (!workspaceId) return
    const dto = await api.getActiveOnboarding(workspaceId)
    set({ activeOnboarding: dto ? onboardingToVM(dto) : null })
  },

  // ── API hydration thunks ───────────────────────────────────────────────────────────
  hydrateMe: async () => {
    try {
      const user = await api.getMe()
      set({ currentUser: { id: user.id, name: user.full_name, email: user.email } })
    } catch {
      // Not logged in (401) — leave currentUser null; the auth guard redirects to Landing.
    }
  },

  hydrateWorkspaces: async () => {
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
      projects: mergeWorkspaceProjects(s.projects, workspaceId, projects.map(projectToVM)),
      skills: [
        ...s.skills.filter((sk) => sk.workspaceId !== workspaceId),
        ...skills.map(skillToVM),
      ],
    }))
  },

  hydrateProject: async (projectId: string) => {
    const [detail, tasks] = await Promise.all([
      api.getProject(projectId),
      loadProjectTasksWithDeps(projectId),
    ])
    const project = projectDetailToVM(detail)
    set({
      projects: upsertById(get().projects, project),
      tasks: [...get().tasks.filter((t) => t.projectId !== projectId), ...tasks],
    })
  },

  hydrateTask: async (taskId: string) => {
    const [taskDto, comments, artifacts, blockers] = await Promise.all([
      api.getTask(taskId),
      api.listComments(taskId),
      api.listArtifacts(taskId),
      api.listTaskDependencies(taskId),
    ])
    const full: Task = {
      ...taskToVM(taskDto),
      comments: comments.map(commentToVM),
      artifacts: artifacts.map(artifactToVM),
      dependencies: blockers.map((b) => b.id),
    }
    // Ensure the project's sibling tasks are present (so the blocked-by list can resolve
    // titles + the add-dependency picker has candidates) without blanking loaded detail.
    let next = get().tasks
    if (taskDto.project_id) {
      const siblings = await loadProjectTasksWithDeps(taskDto.project_id)
      const known = new Set(next.map((t) => t.id))
      next = [...next, ...siblings.filter((s) => !known.has(s.id) && s.id !== taskId)]
    }
    set({ tasks: upsertById(next, full) })
  },
}))
