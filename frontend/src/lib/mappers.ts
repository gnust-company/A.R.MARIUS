// Bidirectional mappers: DTO ↔ view‑model (the existing `appStore` interfaces).
//
// Central enum mapping so the frontend can speak the same language as the backend without
// scattering `|| 'unknown'` and `String(foo)` across components. The backend `StrEnum` values
// are already lowercase, so the heavy lifting is merging the frontend unions (e.g. `AgentStatus`,
// `TaskStatus`) with the narrower backend enums. For liveness, we map `checking`/`hung` into a
// conservative online/offline bucket.
//
// The store uses these mappers on hydration and mutation responses: every entity comes
// through these functions before entering Zustand.

import type {
  ArtifactDTO,
  CommentDTO,
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
} from '@/store/appStore'

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
  // Backend does NOT expose priority in `TaskOut`; default to the board's lowest tier.
  // Must be a key the board understands (P0/P1/P2) — a 'normal' value has no entry in the
  // board's PRIORITY_BADGE/PRIORITY_BORDER maps and crashed the whole board (#70).
  // (Future: if `TaskDTO` grows `priority`, map critical/high/medium/low → P0/P1/P2.)
  return 'P2'
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
  // List-level projects carry `status` + seat *counts* (backend `ProjectOut`) so the grid
  // shows a real status chip and roster fill without opening the detail. The full `seats`
  // array stays detail-only (filled by `projectDetailToVM` when a project is opened); the
  // counts are the list-view fallback the card uses when no detail is loaded yet.
  return {
    id: dto.id,
    name: dto.name,
    key: dto.key ?? undefined,
    description: dto.description ?? undefined,
    workspaceId: dto.workspace_id ?? '',
    status: dto.status === 'active' ? 'active' : dto.status === 'archived' ? 'archived' : 'setup',
    objective: dto.objective ?? undefined,
    seatsTotal: dto.seats_total ?? 0,
    seatsFilled: dto.seats_filled ?? 0,
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
    key: dto.key ?? undefined,
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

/** Pre-approval, the invite lifecycle wins — an invited/pending agent has no
 *  meaningful liveness yet. Once approved, its status follows liveness (#51). */
function agentStatusFor(dto: MariusDTO): AgentStatus {
  switch (dto.invite_status) {
    case 'invited':
      return 'invited'
    case 'pending_review':
      return 'pending'
    case 'revoked':
      return 'revoked'
    default: // 'approved' or unset → follow liveness
      return livenessToAgentStatus(dto.liveness)
  }
}

export function mariusToVM(dto: MariusDTO): Marius {
  return {
    id: dto.id,
    name: dto.name,
    role: dto.role,
    status: agentStatusFor(dto),
    workspaceId: dto.workspace_id ?? '',
    projectIds: [], // populated by the frontend from roster grants
    skills: dto.skills,
    skillInstalls: dto.skill_installs ?? {},
    adapterType: dto.adapter_type,
    lastSeen: dto.last_seen_at ?? undefined,
  }
}

// ── Task ────────────────────────────────────────────────────────────────────────────────

export function taskToVM(dto: TaskDTO): Task {
  return {
    id: dto.id,
    identifier: dto.identifier ?? undefined,
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
    slug: dto.slug,
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

// ── Onboarding (agent-driven, question-window project setup · #61) ─────────────────────

export function onboardingToVM(dto: OnboardingDTO): OnboardingSessionVM {
  const collected = dto.collected ?? {}
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
    collected,
    phase: collected.phase === 'complete' ? 'complete' : 'asking',
    pendingQuestion: collected.pending_question ?? null,
    draft: collected.draft ?? null,
    createdProjectId: dto.created_project_id ?? undefined,
  }
}

// ── Trace event (SSE payload) ─────────────────────────────────────────────────────────────

/** Normalize either the internal `{used,total,prompt,completion}` shape or the gateway's
 *  `{input_tokens,output_tokens,total_tokens}` usage shape into the VM token counts. */
function normalizeTokens(raw: unknown): TraceEvent['tokens'] | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const t = raw as Record<string, unknown>
  const num = (v: unknown): number | undefined =>
    v === undefined || v === null ? undefined : Number(v)
  const prompt = num(t.prompt ?? t.input_tokens ?? t.input)
  const completion = num(t.completion ?? t.output_tokens ?? t.output)
  const total = num(t.total ?? t.total_tokens) ?? (prompt !== undefined || completion !== undefined ? (prompt ?? 0) + (completion ?? 0) : undefined)
  const used = num(t.used) ?? total
  if (prompt === undefined && completion === undefined && total === undefined && used === undefined) return undefined
  return { prompt, completion, total, used }
}

/**
 * Parse a run event (live SSE `data:` JSON, or a backfilled `RunEventDTO`) into a
 * `TraceEvent` view‑model — or `null` to DROP it.
 *
 * Maps the real gateway/wake vocabulary (`assistant.message`, `tool.started`, `tool.completed`,
 * `run.completed`, …) — not the guessed `assistant.tool`/`assistant.complete` names the old
 * mapper expected, which is why tool calls and agent text never rendered (#113). Pure lifecycle
 * events with nothing to show (`run.started`, `message.started`, `assistant.completed`,
 * `run.queued`, `run.finished`, `tool.completed` acks) are dropped so the Room shows no empty
 * bubbles.
 *
 * `meta` lets the caller pin a stable identity + timestamp: backfill passes `${run_id}:${seq}`
 * and the durable `created_at`; live tee events carry `(_run_id,_seq)` in the payload, so both
 * paths yield the SAME id and de-duplicate on overlap.
 */
export function traceEventFromVM(
  eventData: unknown,
  meta?: { id?: string; timestamp?: string; taskId?: string },
): TraceEvent | null {
  if (!eventData || typeof eventData !== 'object') return null
  const d = eventData as Record<string, unknown>

  const type = String(d.event_type ?? d.type ?? '')
  const payload = d.payload
  if (!payload || typeof payload !== 'object') return null
  const p = payload as Record<string, unknown>

  const content = String(p.content ?? p.text ?? p.delta ?? p.message ?? p.error ?? '')
  const agentId = p.marius_id ? String(p.marius_id) : undefined
  const model = p.model ? String(p.model) : undefined
  const toolName = (p.tool_name ?? p.name ?? p.tool) ? String(p.tool_name ?? p.name ?? p.tool) : undefined
  const rawArgs = p.args ?? p.arguments ?? p.input
  const args = rawArgs && typeof rawArgs === 'object' ? (rawArgs as Record<string, unknown>) : undefined
  const tokens = normalizeTokens(p.tokens ?? p.usage)

  // Classify into the FE union, or leave null to decide-then-drop.
  let vmType: TraceEvent['type'] | null = null
  if (type === 'assistant.delta' || type === 'run.delta' || type === 'assistant.message') vmType = 'run.delta'
  else if (type === 'assistant.tool' || type === 'run.tool' || type === 'tool.started' || type === 'tool.call' || type === 'tool_call') vmType = 'run.tool'
  else if (type === 'tool.completed' || type === 'tool.result' || type === 'tool_result') {
    // A completion ack with no textual result is redundant with the call bubble → drop it.
    if (!content) return null
    vmType = 'run.tool'
  } else if (type === 'assistant.usage' || type === 'run.usage' || type === 'run.completed') vmType = 'run.usage'
  else if (type === 'assistant.error' || type === 'run.error') vmType = 'run.error'
  else if (type === 'agent.comment' || type === 'comment') vmType = 'agent.comment'
  else if (type === 'agent.status' || type === 'status_change') vmType = 'agent.status'
  else if (type === 'thought') vmType = 'thought'

  // Kill empty bubbles: an event with nothing renderable is dropped whatever its type
  // (this is what silences the lifecycle noise: run.started/queued/finished, …).
  const hasBody = Boolean(content || toolName || tokens || args)
  if (!hasBody) return null
  if (vmType === null) vmType = 'message' // renderable but unknown → generic bubble

  // Stable identity: live tee payload carries (_run_id,_seq); else use meta.id; else random.
  const runId = p._run_id ? String(p._run_id) : undefined
  const seq = typeof p._seq === 'number' ? p._seq : undefined
  const id = meta?.id
    ?? (runId && seq !== undefined ? `${runId}:${seq}` : `tr_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`)

  return {
    id,
    taskId: meta?.taskId ?? '',
    type: vmType,
    agentId,
    content,
    timestamp: meta?.timestamp ?? new Date().toISOString(),
    model,
    toolName,
    args,
    tokens,
  }
}

/**
 * Parse a workspace SSE `data:` JSON into a synthetic store event the UI can react to.
 *
 * The backend publishes `marius.status_changed` with `{marius_id, status}`. We surface
 * this as a `StoreEvent` the workspace-events hook reconciles into the store.
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
