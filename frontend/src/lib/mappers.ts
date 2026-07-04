// Bidirectional mappers: DTO ↔ view‑model (the existing `mockStore` interfaces).
//
// Central enum mapping so the frontend can speak the same language as the backend without
// scattering `|| 'unknown'` and `String(foo)` across components. The backend `StrEnum` values
// are already lowercase, so the heavy lifting is merging the frontend unions (e.g. `AgentStatus`,
// `TaskStatus`) with the narrower backend enums. For liveness, we map `checking`/`hung` into a
// conservative online/offline bucket.
//
// The store uses these mappers on hydration and mutation responses. Under MOCK the data stays
// as-is; under the real API every entity comes through these functions before entering Zustand.

import type {
  ArtifactDTO,
  CommentDTO,
  CommissionDTO,
  LabelDTO,
  MariusDTO,
  OnboardingDTO,
  ProjectDTO,
  ProjectDetailDTO,
  SkillDTO,
  TaskDTO,
  WorkspaceDTO,
} from './api'
import type {
  AgentStatus,
  Artifact,
  CommissionSession as CommissionSessionVM,
  Marius,
  OnboardingSessionVM,
  Priority,
  Project,
  ProjectSeat,
  Skill,
  Task,
  TaskComment,
  TaskStatus,
  TraceEvent,
  Workspace,
} from '@/store/mockStore'

// ── Enums ─────────────────────────────────────────────────────────────────────────────

export function livenessToAgentStatus(liveness: string): AgentStatus {
  switch (liveness) {
    case 'offline':
    case 'hung':
      return 'offline'
    case 'checking':
      return 'idle' // conservative: probing → idle/online bucket
    case 'online':
    case 'working':
    case 'idle':
      return 'online' // working/idle → online (the "available" bucket)
    default:
      return 'offline'
  }
}

export function taskStatusFromDTO(status: string): TaskStatus {
  // Backend enum is a subset of the frontend union; pass through known values,
  // fallback to a safe default.
  const known: Record<string, TaskStatus> = {
    draft: 'draft',
    backlog: 'backlog',
    todo: 'todo',
    in_progress: 'in_progress',
    in_review: 'in_review',
    blocked: 'blocked',
    done: 'done',
    cancelled: 'cancelled',
  }
  return known[status] ?? 'todo'
}

export function priorityFromDTO(): Priority {
  // Backend does NOT expose priority in `TaskOut`; default the view-model to normal.
  // (Future: if `TaskDTO` grows `priority`, map critical/high/medium/low.)
  return 'normal'
}

// ── Workspace ───────────────────────────────────────────────────────────────────────────

export function workspaceToVM(dto: WorkspaceDTO, ownerId = ''): Workspace {
  return {
    id: dto.id,
    name: dto.name,
    ownerId, // not exposed by the backend; populated from the user context on hydration
    description: dto.slug, // backend has no description field – repurpose slug as a stopgap
    workspaceAgentId: dto.workspace_agent_id ?? undefined,
  }
}

// ── Project ─────────────────────────────────────────────────────────────────────────────

export function projectToVM(dto: ProjectDTO): Project {
  // List-level projects now carry `status` (backend `ProjectOut`); map it through so the
  // projects grid shows a real status chip instead of an undefined one. Roster/seats stay
  // detail-only (filled by `projectDetailToVM` when a project is opened).
  return {
    id: dto.id,
    name: dto.name,
    description: dto.description ?? undefined,
    workspaceId: dto.workspace_id ?? '',
    status: dto.status === 'active' ? 'active' : dto.status === 'archived' ? 'archived' : 'setup',
    objective: dto.objective ?? undefined,
    createdAt: dto.created_at ?? undefined,
  }
}

export function projectDetailToVM(dto: ProjectDetailDTO): Project {
  const seats: ProjectSeat[] = []
  for (const role of dto.roster) {
    for (const seat of role.seated) {
      seats.push({
        id: `${dto.id}-${seat.marius_id}-${role.key}`,
        projectId: dto.id,
        mariusId: seat.marius_id,
        role: role.key,
      })
    }
    // Unfilled seats appear as empty slots with the role key (no mariusId).
    for (let i = role.filled; i < role.seats; i++) {
      seats.push({
        id: `${dto.id}-${role.key}-${i}-empty`,
        projectId: dto.id,
        mariusId: null,
        role: role.key,
      })
    }
  }
  return {
    id: dto.id,
    name: dto.name,
    description: dto.description ?? undefined,
    workspaceId: dto.workspace_id ?? '',
    status: dto.status === 'setup' ? 'setup' : dto.status === 'active' ? 'active' : 'archived',
    objective: dto.objective ?? undefined,
    githubUrl: dto.github_url ?? undefined,
    createdAt: dto.created_at ?? undefined,
    seats,
  }
}

// ── Marius ──────────────────────────────────────────────────────────────────────────────

export function mariusToVM(dto: MariusDTO): Marius {
  return {
    id: dto.id,
    name: dto.name,
    role: dto.role,
    status: livenessToAgentStatus(dto.liveness),
    workspaceId: dto.workspace_id ?? '',
    projectIds: [], // populated by the frontend from roster grants
    skills: dto.skills,
    adapterType: dto.adapter_type,
    lastSeen: dto.last_seen_at ?? undefined,
  }
}

// ── Task ────────────────────────────────────────────────────────────────────────────────

export function taskToVM(dto: TaskDTO): Task {
  return {
    id: dto.id,
    title: dto.title,
    description: dto.description ?? undefined,
    status: taskStatusFromDTO(dto.status),
    priority: priorityFromDTO(),
    projectId: dto.project_id ?? '',
    assigneeId: dto.assigned_marius_id ?? undefined,
    createdAt: dto.created_at ?? new Date().toISOString(),
    updatedAt: dto.updated_at ?? undefined,
    trace: [],
    comments: [],
    artifacts: [],
    checklist: [],
    participants: [],
    dependencies: [],
  }
}

// ── Comment ─────────────────────────────────────────────────────────────────────────────

export function commentToVM(dto: CommentDTO): TaskComment {
  return {
    id: dto.id,
    taskId: dto.task_id ?? '',
    authorId: dto.author_marius_id ?? dto.author_user_id ?? 'unknown',
    authorName: undefined, // populated by joining mariuses
    content: dto.body,
    timestamp: dto.created_at ?? new Date().toISOString(),
  }
}

// ── Artifact ────────────────────────────────────────────────────────────────────────────

export function artifactToVM(dto: ArtifactDTO): Artifact {
  return {
    id: dto.id,
    taskId: dto.task_id ?? '',
    type: dto.kind === 'link' ? 'link' : 'file',
    title: dto.name,
    name: dto.name,
    url: dto.uri ?? undefined,
  }
}

// ── Label ───────────────────────────────────────────────────────────────────────────────

export function labelToVM(dto: LabelDTO): { id: string; name: string; color: string; workspaceId?: string } {
  return {
    id: dto.id,
    name: dto.name,
    color: dto.color,
    workspaceId: dto.workspace_id ?? undefined,
  }
}

// ── Skill ───────────────────────────────────────────────────────────────────────────────

export function skillToVM(dto: SkillDTO): Skill {
  return {
    id: dto.id,
    name: dto.name,
    description: dto.description ?? undefined,
    workspaceId: dto.workspace_id ?? undefined,
    type: dto.source === 'builtin' ? 'builtin' : dto.source === 'imported' ? 'github' : 'custom',
    files: Object.entries(dto.files).map(([name, content]) => ({
      id: `${dto.id}-${name}`,
      name,
      path: name,
      language: name.endsWith('.md') ? 'markdown' : 'typescript',
      description: '',
      content,
      workspaceId: dto.workspace_id ?? undefined,
    })),
  }
}

// ── Commission ───────────────────────────────────────────────────────────────────────────

export function commissionToVM(dto: CommissionDTO): CommissionSessionVM {
  return {
    id: dto.id,
    projectId: dto.project_id ?? '',
    leaderMariusId: dto.leader_marius_id ?? undefined,
    taskId: dto.task_id ?? undefined,
    status: dto.status === 'open' ? 'open' : dto.status === 'confirmed' ? 'confirmed' : 'abandoned',
    leaderState:
      dto.leader_state === 'thinking'
        ? 'thinking'
        : dto.leader_state === 'waiting'
          ? 'waiting'
          : 'leader_offline',
    transcript: dto.transcript as CommissionSessionVM['transcript'],
    messages: dto.transcript as CommissionSessionVM['messages'],
    draftTask: dto.task_id
      ? {
          id: dto.task_id,
          title: '',
          description: '',
          priority: 'normal',
          assigneeId: undefined,
          checklist: [],
          dependencies: [],
        }
      : null,
  }
}

// ── Onboarding (agent-assisted project setup · Sprint 7) ───────────────────────────────

export function onboardingToVM(dto: OnboardingDTO): OnboardingSessionVM {
  return {
    id: dto.id,
    workspaceId: dto.workspace_id ?? '',
    status:
      dto.status === 'finalized' ? 'finalized' : dto.status === 'abandoned' ? 'abandoned' : 'open',
    transcript: (dto.transcript ?? []).map((t, i) => ({
      id: `${dto.id}-${i}`,
      role: t.role === 'patron' ? 'patron' : t.role === 'agent' ? 'agent' : 'system',
      text: t.text,
      timestamp: t.ts ?? new Date().toISOString(),
    })),
    collected: dto.collected ?? {},
    createdProjectId: dto.created_project_id ?? undefined,
  }
}

// ── Trace event (SSE payload) ─────────────────────────────────────────────────────────────

/**
 * Parse a per‑task SSE `data:` JSON into a `TraceEvent` view‑model fragment.
 *
 * The backend wakes → runs → publishes events to the task topic. We only care about the
 * shapes the UI already renders: `run.delta`, `run.tool`, `run.usage`. Legacy event types
 * (`thought`, `tool_call`, etc.) are kept for back‑compat with frozen demo fixtures.
 */
export function traceEventFromVM(eventData: unknown): TraceEvent | null {
  if (!eventData || typeof eventData !== 'object') return null
  const d = eventData as Record<string, unknown>

  // The backend `wake_engine.py` tee sends `event_type` + `payload`.
  const type = String(d.event_type ?? d.type ?? '')
  const payload = d.payload

  if (!payload || typeof payload !== 'object') return null
  const p = payload as Record<string, unknown>

  // Map the event type to the frontend union.
  let vmType: TraceEvent['type'] = 'message'
  if (type === 'assistant.delta' || type === 'run.delta') vmType = 'run.delta'
  else if (type === 'assistant.tool' || type === 'run.tool') vmType = 'run.tool'
  else if (type === 'assistant.usage' || type === 'run.usage') vmType = 'run.usage'
  else if (type === 'assistant.complete' || type === 'run.complete') vmType = 'run.complete'
  else if (type === 'assistant.error' || type === 'run.error') vmType = 'run.error'
  else if (type === 'agent.comment') vmType = 'agent.comment'
  else if (type === 'agent.status') vmType = 'agent.status'
  else if (type === 'thought' || type === 'tool_call' || type === 'tool_result' || type === 'comment' || type === 'status_change')
    vmType = type

  const content = String(p.content ?? p.delta ?? p.text ?? '')
  const agentId = p.marius_id ? String(p.marius_id) : undefined
  const model = p.model ? String(p.model) : undefined
  const toolName = p.tool_name ? String(p.tool_name) : undefined
  const args = p.args
  const tokens = p.tokens
    ? {
        used: Number((p.tokens as Record<string, unknown>)?.used ?? 0),
        total: Number((p.tokens as Record<string, unknown>)?.total ?? 0),
        prompt: Number((p.tokens as Record<string, unknown>)?.prompt ?? 0),
        completion: Number((p.tokens as Record<string, unknown>)?.completion ?? 0),
      }
    : undefined

  return {
    id: `tr_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`,
    taskId: '', // set by the caller from the subscription context
    type: vmType,
    agentId,
    content,
    timestamp: new Date().toISOString(),
    model,
    toolName,
    args: args as Record<string, unknown> | undefined,
    tokens,
  }
}

/**
 * Parse a workspace SSE `data:` JSON into a synthetic store event the UI can react to.
 *
 * The backend publishes `marius.status_changed` with `{marius_id, status}`. We surface
 * this as a `StoreEvent` so the existing `use-mock-simulator` logic stays intact.
 */
export function workspaceEventFromVM(eventData: unknown): { type: string; payload: Record<string, unknown> } | null {
  if (!eventData || typeof eventData !== 'object') return null
  const d = eventData as Record<string, unknown>
  const type = String(d.type ?? d.event_type ?? '')
  const payload = d.payload

  if (!payload || typeof payload !== 'object') return null

  // Known workspace event types from the backend.
  if (type === 'marius.status_changed' || type === 'marius.online' || type === 'marius.liveness') {
    return { type: 'marius.liveness', payload: payload as Record<string, unknown> }
  }

  return { type, payload: payload as Record<string, unknown> }
}
