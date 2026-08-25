// Real API client (Sprint 6 golden-path scope).
//
// Typed fetch wrapper that injects the Bearer token, handles 401→refresh→retry, and exposes
// every endpoint the golden-path needs: auth/me, workspaces, projects (list/create/get),
// roster (detail/grant), mariuses, labels, skills, tasks (CRUD + comments + artifacts),
// and the two SSE routes (for URL construction only; the stream itself lives in sse.ts).
//
// Error responses raise an `ApiError` carrying the server's cause code and parameters
// (FR-084a). Callers put it on screen through `errorText`, which words it in the patron's
// language; `ApiError.message` is the server's English rendering, kept as the fallback.

import { getToken, logout, refreshAccessToken, type UserDTO } from './auth'
import { ApiError, throwApiError } from './errors'
import { API_BASE } from './env'

// The refusal type and the body reader both live in `./errors`, below this module and
// below `auth.ts`, so the login screen gets the same coded refusals every other page does.
export { ApiError } from './errors'

// Single-flight token refresh. When several authenticated requests 401 at once (common on an
// F5 that fans out many GETs after the access token expired), they must all await the SAME
// refresh and then retry — not race. A boolean guard let the first request refresh while the
// rest skipped it and returned the stale 401 (spurious failures / logout). A shared promise
// makes every 401'd caller wait for one refresh, then each retries once.
let refreshPromise: Promise<boolean> | null = null

function refreshOnce(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      try {
        return await refreshAccessToken()
      } finally {
        refreshPromise = null
      }
    })()
  }
  return refreshPromise
}

async function fetchWithAuth(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  let token = getToken()

  const headers: Record<string, string> = {
    ...((init?.headers as Record<string, string>) ?? undefined),
    Accept: 'application/json',
  }
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }
  if (init?.body && !(init.body instanceof FormData) && !(init.body instanceof URLSearchParams)) {
    headers['Content-Type'] = 'application/json'
  }

  let res = await fetch(`${API_BASE}${input}`, {
    ...init,
    headers,
  })

  // 401 → refresh once (shared across concurrent callers), then retry the original request.
  if (res.status === 401 && token) {
    const ok = await refreshOnce()

    if (ok) {
      token = getToken()
      if (token) {
        headers.Authorization = `Bearer ${token}`
      }
      res = await fetch(`${API_BASE}${input}`, {
        ...init,
        headers,
      })
    } else {
      // Refresh failed → logged out; clear local state and surface the 401.
      logout()
      // The one refusal the client raises on its own behalf: no server said this, the
      // refresh simply did not come back. Coded all the same, so it is worded like the
      // rest instead of being the one English sentence on a Vietnamese screen.
      throw new ApiError('Session expired. Please log in again.', 401, 'session_expired')
    }
  }

  return res
}

async function get<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(path)
  if (!res.ok) {
    await throwApiError(res)
  }
  return (await res.json()) as T
}

// Like `get`, but a 404 resolves to `null` instead of throwing — for "may not exist yet"
// lookups (e.g. the active onboarding chat before one is opened).
async function getOrNull<T>(path: string): Promise<T | null> {
  try {
    return await get<T>(path)
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null
    throw e
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAuth(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    await throwApiError(res)
  }
  return (await res.json()) as T
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAuth(path, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    await throwApiError(res)
  }
  return (await res.json()) as T
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAuth(path, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    await throwApiError(res)
  }
  return (await res.json()) as T
}

// DELETE that tolerates a 204 (no body). Surfaces the server `detail` on 4xx so callers
// can toast the constraint message (e.g. "Built-in skills can't be deleted.").
async function del(path: string): Promise<void> {
  const res = await fetchWithAuth(path, { method: 'DELETE' })
  if (!res.ok && res.status !== 204) {
    await throwApiError(res)
  }
}

// ── DTOs (golden-path only — a thin typed contract over the backend schemas) ─────────────

export interface WorkspaceDTO {
  id: string
  name: string
  slug: string
  /** The designated host Marius (Workspace Agent) — null until one is seated (#32). */
  workspace_agent_id?: string | null
  created_at?: string | null
}

export interface ProjectDTO {
  id: string
  workspace_id?: string | null
  name: string
  slug: string
  /** JIRA-style KEY — prefix of task identifiers "{key}-{n}". */
  key?: string | null
  description?: string | null
  status?: string | null
  objective?: string | null
  // Roster fill for the project card (filled / total) — list-level, no detail fetch needed.
  seats_total?: number | null
  seats_filled?: number | null
  created_at?: string | null
}

export interface ProjectDetailDTO {
  id: string
  workspace_id?: string | null
  name: string
  slug: string
  /** JIRA-style KEY — prefix of task identifiers "{key}-{n}". */
  key?: string | null
  description?: string | null
  status: string
  objective?: string | null
  github_url?: string | null
  created_at?: string | null
  updated_at?: string | null
  roster: RosterRoleDTO[]
}

export interface RosterRoleDTO {
  key: string
  title: string
  seats: number
  is_leader: boolean
  description: string
  skill_ids: string[]
  filled: number
  seated: SeatDTO[]
}

export interface SeatDTO {
  marius_id: string
  name: string
  role_key: string
  liveness: string
  is_primary: boolean
}

export interface MariusDTO {
  id: string
  workspace_id?: string | null
  name: string
  role: string
  skills: string[]
  skill_ids: string[]
  /** What the agent is told to be. Sent to it on every run (FR-007i). */
  instructions?: string
  /** What the team calls it. Never sent to the agent (FR-007j). */
  description?: string
  /** Per-skill install state (#74): slug → pending|installed. */
  skill_installs?: Record<string, string>
  adapter_type: string
  liveness: string
  /** Invite lifecycle: invited → pending_review → approved (#51). */
  invite_status?: string | null
  last_seen_at?: string | null
  created_at?: string | null
}

// POST /workspaces/{id}/mariuses response (backend `MariusCreatedOut`). The agent's token is
// never returned — it is a secret, and nothing on this side has any use for it. There is no
// send to report either: the machine the agent runs on asks for work rather than being
// called, so creating one sends nothing anywhere (FR-007g).
export type MariusCreatedDTO = MariusDTO

export interface LabelDTO {
  id: string
  workspace_id?: string | null
  name: string
  color: string
  created_at?: string | null
}

export interface SkillDTO {
  id: string
  workspace_id?: string | null
  slug: string
  name: string
  description?: string
  source: string
  source_url: string
  files: Record<string, string>
  created_at?: string | null
}

export interface TaskDTO {
  id: string
  project_id?: string | null
  /** Human-readable code "{project.key}-{seq}", e.g. "CALC-7". */
  identifier?: string | null
  title: string
  description?: string | null
  status: string
  status_reason?: string | null
  priority?: string
  due_date?: string | null
  definition_of_done?: string | null
  /** The approved plan item this task belongs to (spec 001 FR-027); null = out of scope. */
  plan_item_id?: string | null
  /** What is going to move this task forward (FR-056); null on a closed task. */
  drive?: string | null
  /** The system dropped this task — every door into `done` is sealed (FR-058). */
  stalled?: boolean
  /** The server's English rendering of the stall verdict — for agents and raw readers. */
  stalled_reason?: string | null
  /** The verdict as a code; the screen words it (see `lib/stall.ts`). */
  stalled_reason_code?: string | null
  /** Filled by the two-signature rule; empty until that ships. */
  signatures?: Record<string, unknown>[]
  assigned_marius_id?: string | null
  next_action?: string | null
  created_at?: string | null
  updated_at?: string | null
}

/** One acceptance criterion — a checkable true/false statement (FR-019). */
export interface CriterionDTO {
  id: string
  task_id?: string | null
  text: string
  order: number
  result: 'unrated' | 'passed' | 'failed'
  evidence_artifact_id?: string | null
}

export interface CommentDTO {
  id: string
  task_id?: string | null
  author_kind: string
  author_marius_id?: string | null
  author_user_id?: string | null
  body: string
  mentions: string[]
  created_at?: string | null
}

export interface ArtifactDTO {
  id: string
  project_id?: string | null
  task_id?: string | null
  marius_id?: string | null
  name: string
  kind: string
  uri: string
  stored?: boolean
  size_bytes?: number | null
  created_at?: string | null
}

// One system→agent dispatch (backend `RunOut`). The agent-detail view lists these as the
// system↔agent interaction log; `RunEventOut` is the per-run trace, fetched on expand.
export interface WakeCauseDTO {
  code: string
  params?: Record<string, string>
}

export interface RunDTO {
  id: string
  task_id?: string | null
  marius_id?: string | null
  adapter_type: string
  wake_source: string
  /**
   * Why the run was woken, as data: a code from the server's closed list plus its
   * parameters. Rendered here through i18n so the line follows the reader's language —
   * the server cannot word it for us, because the same wake also goes to an agent and
   * that copy is always English (Hiến pháp VII).
   */
  trigger_causes?: WakeCauseDTO[]
  /** The English rendering the agent's packet carried. Only shown for runs recorded
   * before the codes existed, which have no causes to render. */
  trigger_detail?: string | null
  status: string
  external_run_id?: string | null
  error?: string | null
  next_action?: string | null
  continuation_attempt?: number
  usage_json?: Record<string, unknown>
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
}

export interface RunEventDTO {
  seq: number
  type: string
  payload: Record<string, unknown>
  created_at?: string | null
}


// ── Auth ─────────────────────────────────────────────────────────────────────────────

export async function getMe(): Promise<UserDTO> {
  return get<UserDTO>('/auth/me')
}

// ── Workspaces ─────────────────────────────────────────────────────────────────────────

export async function listWorkspaces(): Promise<WorkspaceDTO[]> {
  return get<WorkspaceDTO[]>('/v1/workspaces')
}

export async function createWorkspace(name: string): Promise<WorkspaceDTO> {
  return post<WorkspaceDTO>('/v1/workspaces', { name })
}

export async function updateWorkspace(workspaceId: string, name: string): Promise<WorkspaceDTO> {
  return patch<WorkspaceDTO>(`/v1/workspaces/${workspaceId}`, { name })
}

export async function deleteWorkspace(workspaceId: string): Promise<void> {
  return del(`/v1/workspaces/${workspaceId}`)
}

// ── Machines (spec 002) ────────────────────────────────────────────────────────────────

/** A machine waiting to be let into a workspace.
 *
 *  `hostname`, `platform` and `daemon_version` are what the machine *said about itself* at
 *  the start of the link — not a verified identity. They exist so a person can recognise
 *  their own box, and the screen has to say so. */
export interface PendingMachineLinkDTO {
  code: string
  hostname: string
  platform: string
  daemon_version: string
  expires_at: string | null
}

export async function getMachineLink(code: string): Promise<PendingMachineLinkDTO> {
  return get<PendingMachineLinkDTO>(`/v1/machines/link/${encodeURIComponent(code)}`)
}

/** Let the machine in. This is the only door a machine ever enters a workspace through —
 *  there is no path by which one admits itself. */
export async function approveMachineLink(
  code: string,
  workspaceId: string,
): Promise<PendingMachineLinkDTO> {
  return post<PendingMachineLinkDTO>(`/v1/machines/link/${encodeURIComponent(code)}/approve`, {
    workspace_id: workspaceId,
  })
}

// ── Projects ───────────────────────────────────────────────────────────────────────────

export interface CreateProjectBody {
  name: string
  description?: string
  objective?: string
  /** JIRA-style project KEY (2–10 uppercase chars). Omitted/blank → server suggests from name. */
  key?: string
  leader?: { marius_id?: string | null; description?: string }
  roles?: Array<{
    title: string
    seats: number
    description?: string
    skill_ids?: string[]
    marius_ids?: (string | null)[]
  }>
}

export async function listProjects(workspaceId: string): Promise<ProjectDTO[]> {
  return get<ProjectDTO[]>(`/v1/workspaces/${workspaceId}/projects`)
}

export async function createProject(workspaceId: string, body: CreateProjectBody): Promise<ProjectDetailDTO> {
  return post<ProjectDetailDTO>(`/v1/workspaces/${workspaceId}/projects`, body)
}

export async function getProject(projectId: string): Promise<ProjectDetailDTO> {
  return get<ProjectDetailDTO>(`/v1/projects/${projectId}`)
}

export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetchWithAuth(`/v1/projects/${projectId}`, { method: 'DELETE' })
  if (!res.ok && res.status !== 204) {
    await throwApiError(res)
  }
}

// ── Mariuses ───────────────────────────────────────────────────────────────────────────

export async function listMariuses(workspaceId: string): Promise<MariusDTO[]> {
  return get<MariusDTO[]>(`/v1/workspaces/${workspaceId}/mariuses`)
}

/** A workplace an agent may be put on — one agent CLI on one of the patron's machines.
 *  Only ready ones are ever returned, so there is nothing to filter here (FR-007f). */
export interface WorkplaceChoiceDTO {
  id: string
  cli_kind: string
  /** The machine's own name. Without it, the same CLI on two machines is two identical rows. */
  machine_name: string
}

export async function listWorkplaces(workspaceId: string): Promise<WorkplaceChoiceDTO[]> {
  return get<WorkplaceChoiceDTO[]>(`/v1/workspaces/${workspaceId}/workplaces`)
}

export interface InviteMariusBody {
  name: string
  /** What the agent is told to be. Goes down with every run (FR-007i). */
  instructions?: string
  /** What the team calls it among themselves. Never reaches the agent (FR-007j). */
  description?: string
  skills?: string[]
  skill_ids?: string[]
  adapter_type?: string
  /** Where this agent will work. Required and fixed for life — an agent is never moved
   *  to another workplace afterwards (FR-007, FR-007f). */
  workplace_id: string
  /** Seat the newcomer as Workspace Agent on creation; a sitting host is demoted (#32). */
  is_workspace_agent?: boolean
}

/** Editable fields on an existing Marius (backend `UpdateMariusIn`). */
export interface UpdateMariusBody {
  name?: string
  role?: string
  skills?: string[]
  skill_ids?: string[]
  adapter_type?: string
  adapter_config?: Record<string, unknown>
}

export async function inviteMarius(workspaceId: string, body: InviteMariusBody): Promise<MariusCreatedDTO> {
  return post<MariusCreatedDTO>(`/v1/workspaces/${workspaceId}/mariuses`, body)
}

export async function designateWorkspaceAgent(
  workspaceId: string,
  mariusId: string,
): Promise<MariusDTO> {
  return post<MariusDTO>(`/v1/workspaces/${workspaceId}/mariuses/${mariusId}/designate`, {})
}

export async function updateMarius(
  workspaceId: string,
  mariusId: string,
  body: Partial<UpdateMariusBody>,
): Promise<MariusDTO> {
  return patch<MariusDTO>(`/v1/workspaces/${workspaceId}/mariuses/${mariusId}`, body)
}

export async function deleteMarius(workspaceId: string, mariusId: string): Promise<void> {
  return del(`/v1/workspaces/${workspaceId}/mariuses/${mariusId}`)
}

/** Result of linking more skills to an agent (#74, FR-011c). */
export interface InstallSkillsDTO {
  marius_id: string
  /** The full merged skill-id list after the link (de-duped). */
  skill_ids: string[]
  /** Slugs of the newly linked skills. The agent installs them on its next run. */
  installed: string[]
}

/** Link additional skills to an agent. Nothing is pushed — they travel with the work. */
export async function installSkills(
  workspaceId: string,
  mariusId: string,
  skillIds: string[],
): Promise<InstallSkillsDTO> {
  return post<InstallSkillsDTO>(
    `/v1/workspaces/${workspaceId}/mariuses/${mariusId}/install-skills`,
    { skill_ids: skillIds },
  )
}

// The agent's run history — the system↔agent interaction log the detail view tracks (#72).
export async function listMariusRuns(workspaceId: string, mariusId: string): Promise<RunDTO[]> {
  return get<RunDTO[]>(`/v1/workspaces/${workspaceId}/mariuses/${mariusId}/runs`)
}

// All runs of a task (every wake/turn), newest history for the Room's trace backfill (#113).
export async function listTaskRuns(taskId: string): Promise<RunDTO[]> {
  return get<RunDTO[]>(`/v1/tasks/${taskId}/runs`)
}

// The durable per-run trace (assistant deltas, tool calls, …) — reused from the §8.1 trace API.
export async function listRunEvents(runId: string): Promise<RunEventDTO[]> {
  return get<RunEventDTO[]>(`/v1/runs/${runId}/events`)
}

// ── Labels ─────────────────────────────────────────────────────────────────────────────

export async function listLabels(workspaceId: string): Promise<LabelDTO[]> {
  return get<LabelDTO[]>(`/v1/workspaces/${workspaceId}/labels`)
}

// ── Skills ─────────────────────────────────────────────────────────────────────────────

export async function listSkills(workspaceId: string): Promise<SkillDTO[]> {
  return get<SkillDTO[]>(`/v1/workspaces/${workspaceId}/skills`)
}

export async function createManualSkill(
  workspaceId: string,
  body: { name: string; description?: string },
): Promise<SkillDTO> {
  return post<SkillDTO>(`/v1/workspaces/${workspaceId}/skills/manual`, body)
}

export async function importSkill(workspaceId: string, sourceUrl: string): Promise<SkillDTO> {
  // The backend clones the GitHub folder (detects SKILL.md, pulls that folder) and
  // persists the skill in one call — throws (404 with a detail message) on a bad URL
  // or a folder with no SKILL.md, so nothing is created unless the fetch succeeded.
  return post<SkillDTO>(`/v1/workspaces/${workspaceId}/skills/import`, { source_url: sourceUrl })
}

export async function deleteSkill(workspaceId: string, skillId: string): Promise<void> {
  return del(`/v1/workspaces/${workspaceId}/skills/${skillId}`)
}

// ── Tasks ───────────────────────────────────────────────────────────────────────────────

export async function listTasks(projectId: string): Promise<TaskDTO[]> {
  return get<TaskDTO[]>(`/v1/projects/${projectId}/tasks`)
}

export async function getTask(taskId: string): Promise<TaskDTO> {
  return get<TaskDTO>(`/v1/tasks/${taskId}`)
}

export async function createTask(
  projectId: string,
  body: {
    title: string
    description?: string
    status?: string
    priority?: string
    due_date?: string
    definition_of_done?: string
    assigned_marius_id?: string
  },
): Promise<TaskDTO> {
  return post<TaskDTO>(`/v1/projects/${projectId}/tasks`, body)
}

/** A seated project agent — the manual add-task assignee dropdown source (#82). */
export interface ProjectAgentDTO {
  marius_id: string
  name: string
  role_key: string
  liveness: string
  is_primary: boolean
}

export async function listProjectAgents(projectId: string): Promise<ProjectAgentDTO[]> {
  return get<ProjectAgentDTO[]>(`/v1/projects/${projectId}/agents`)
}

export async function updateTaskStatus(taskId: string, status: string, reason?: string): Promise<TaskDTO> {
  return post<TaskDTO>(`/v1/tasks/${taskId}/status`, { status, reason })
}

/** The patron rewriting a task after it exists (FR-070a). Takes effect immediately.
 *
 * Send only the keys you mean to change: the server reads which fields were present, so
 * an omitted key is left alone while `due_date: null` clears a deadline entered by
 * mistake. Spreading a whole task object in here would silently rewrite every field. */
export async function editTask(
  taskId: string,
  body: {
    title?: string
    description?: string | null
    priority?: string
    due_date?: string | null
    definition_of_done?: string | null
  },
): Promise<TaskDTO> {
  return patch<TaskDTO>(`/v1/tasks/${taskId}`, body)
}


/** Bring a closed task back. The reason is mandatory — the server refuses without it. */
export async function reopenTask(taskId: string, reason: string): Promise<TaskDTO> {
  return post<TaskDTO>(`/v1/tasks/${taskId}/reopen`, { reason })
}

export async function listTaskCriteria(taskId: string): Promise<CriterionDTO[]> {
  return get<CriterionDTO[]>(`/v1/tasks/${taskId}/criteria`)
}

/** Replace the whole yardstick. Refused (409) once the worker has started (FR-019). */
export async function setTaskCriteria(taskId: string, texts: string[]): Promise<CriterionDTO[]> {
  return put<CriterionDTO[]>(`/v1/tasks/${taskId}/criteria`, {
    items: texts.map((text) => ({ text })),
  })
}

// ── Output acceptance: the two signatures that close a task (spec 001 Story 3) ──
/** One recorded signature. `is_auto` marks one the auto-approval switch supplied. */
export interface ApprovalDTO {
  id: string
  task_id?: string | null
  round: number
  signer_kind: 'leader' | 'patron'
  signer_marius_id?: string | null
  signer_user_id?: string | null
  result: 'approve' | 'reject'
  reason?: string | null
  is_auto: boolean
  signed_at?: string | null
}

export async function listTaskApprovals(taskId: string): Promise<ApprovalDTO[]> {
  return get<ApprovalDTO[]>(`/v1/tasks/${taskId}/approvals`)
}

/**
 * The patron's signature. Refusing needs a reason — it becomes the worker's next action,
 * so an empty one leaves them nothing to fix (FR-040).
 */
export async function signTaskApproval(
  taskId: string,
  approve: boolean,
  reason?: string,
): Promise<TaskDTO> {
  return post<TaskDTO>(`/v1/tasks/${taskId}/approval`, { approve, reason: reason ?? null })
}

/** This patron's own auto-approval switch on one project. Off until they turn it on. */
export interface AutoApprovalDTO {
  project_id?: string | null
  user_id: string
  enabled: boolean
  updated_at?: string | null
}

export async function getAutoApproval(projectId: string): Promise<AutoApprovalDTO> {
  return get<AutoApprovalDTO>(`/v1/projects/${projectId}/auto-approval`)
}

export async function setAutoApproval(
  projectId: string,
  enabled: boolean,
): Promise<AutoApprovalDTO> {
  return put<AutoApprovalDTO>(`/v1/projects/${projectId}/auto-approval`, { enabled })
}

// ── Dependencies (blocked_by edges, #91) ─────────────────────────────────────
/** A task that blocks another (rendered in the blocked-by list). */
export interface BlockerDTO {
  id: string
  identifier?: string | null
  title: string
  status: string
}

/** A raw blocked_by edge — the board flags cards that have an unfinished blocker. */
export interface TaskDependencyEdgeDTO {
  task_id: string
  blocks_task_id: string
}

export async function listTaskDependencies(taskId: string): Promise<BlockerDTO[]> {
  return get<BlockerDTO[]>(`/v1/tasks/${taskId}/dependencies`)
}

/** Add a blocked_by edge (task waits on blocksTaskId); returns the refreshed blocker list. */
export async function addTaskDependency(taskId: string, blocksTaskId: string): Promise<BlockerDTO[]> {
  return post<BlockerDTO[]>(`/v1/tasks/${taskId}/dependencies`, { blocks_task_id: blocksTaskId })
}

export async function removeTaskDependency(taskId: string, blocksTaskId: string): Promise<void> {
  return del(`/v1/tasks/${taskId}/dependencies/${blocksTaskId}`)
}

export async function listProjectDependencies(projectId: string): Promise<TaskDependencyEdgeDTO[]> {
  return get<TaskDependencyEdgeDTO[]>(`/v1/projects/${projectId}/task-dependencies`)
}

/** The tallies a board card draws that are not fields on the task row. Tasks with nothing
 * to report are absent from the list — read a missing task as all zeroes. */
export interface TaskCardCountsDTO {
  task_id: string
  comments: number
  artifacts: number
  criteria_total: number
  criteria_passed: number
}

export async function listTaskCardCounts(projectId: string): Promise<TaskCardCountsDTO[]> {
  return get<TaskCardCountsDTO[]>(`/v1/projects/${projectId}/task-counts`)
}

// ── Comments ───────────────────────────────────────────────────────────────────────────

export async function listComments(taskId: string): Promise<CommentDTO[]> {
  return get<CommentDTO[]>(`/v1/tasks/${taskId}/comments`)
}

export async function postComment(taskId: string, body: string, mentions?: string[]): Promise<CommentDTO> {
  return post<CommentDTO>(`/v1/tasks/${taskId}/comments`, {
    body,
    author_kind: 'human',
    extra_mentions: mentions ?? [],
  })
}

// ── Artifacts ───────────────────────────────────────────────────────────────────────────

export async function listArtifacts(taskId: string): Promise<ArtifactDTO[]> {
  return get<ArtifactDTO[]>(`/v1/tasks/${taskId}/artifacts`)
}

export async function publishArtifact(
  taskId: string,
  name: string,
  kind: 'file' | 'link',
  uri?: string,
): Promise<ArtifactDTO> {
  return post<ArtifactDTO>(`/v1/tasks/${taskId}/artifacts`, { name, kind, uri })
}

// ── Chat with Leader (project-level 1-1 chat · #82) ───────────────────────────────────────

export interface LeaderChatTurn {
  role: string // 'patron' | 'leader' | 'system'
  /**
   * The agent's English copy of the turn. For a `system` turn (a wake the platform
   * delivered) this is NOT what the patron reads — `code` + `params` are, rendered through
   * the phrase table, because the Leader and the patron read the same turn in two
   * different languages (Constitution VII).
   */
  text: string
  /** `system` turns only: the wake cause, as a code from the closed list. */
  code?: string | null
  /** `system` turns only: what fills the cause's placeholders. */
  params?: Record<string, string> | null
  ts?: string | null
}

export interface LeaderChatDTO {
  project_id?: string | null
  leader_marius_id?: string | null
  leader_name?: string | null
  leader_online: boolean
  state: string // 'idle' | 'thinking' | 'failed'
  transcript: LeaderChatTurn[]
  updated_at?: string | null
}

export async function getLeaderChat(projectId: string): Promise<LeaderChatDTO> {
  return get<LeaderChatDTO>(`/v1/projects/${projectId}/leader-chat`)
}

export async function sendLeaderChatMessage(
  projectId: string,
  message: string,
): Promise<LeaderChatDTO> {
  return post<LeaderChatDTO>(`/v1/projects/${projectId}/leader-chat/messages`, { message })
}


export async function listProposedTasks(projectId: string): Promise<TaskDTO[]> {
  return get<TaskDTO[]>(`/v1/projects/${projectId}/proposed-tasks`)
}

export async function approveTask(taskId: string): Promise<TaskDTO> {
  return post<TaskDTO>(`/v1/tasks/${taskId}/approve`, {})
}

export async function rejectTask(taskId: string): Promise<TaskDTO> {
  return post<TaskDTO>(`/v1/tasks/${taskId}/reject`, {})
}

// ── Onboarding (agent‑driven, question-window project setup · #61) ─────────────────────

export interface OnboardingTranscriptTurn {
  role: 'agent' | 'patron' | 'system'
  text: string
  ts?: string | null
}

export interface OnboardingQuestionOption {
  id: string
  label: string
}

/** The pending question the agent is asking — rendered as a tick-select window. */
export interface OnboardingQuestion {
  key?: string
  question: string
  options: OnboardingQuestionOption[]
  multi?: boolean
}

export interface OnboardingRosterRole {
  key?: string
  title: string
  seats?: number
  is_leader?: boolean
  description?: string
  skills?: string[]
}

/** The final project + roster draft the agent proposes once the interview is complete. */
export interface OnboardingDraft {
  name: string
  objective: string
  success_metrics?: Record<string, unknown> | null
  target_date?: string | null
  context?: string | null
  roster: OnboardingRosterRole[]
}

export interface OnboardingCollected {
  phase?: 'asking' | 'complete'
  answers?: Record<string, string>
  pending_question?: OnboardingQuestion | null
  draft?: OnboardingDraft | null
}

export interface OnboardingDTO {
  id: string
  workspace_id?: string | null
  status: 'open' | 'finalized' | 'abandoned'
  transcript: OnboardingTranscriptTurn[]
  collected: OnboardingCollected
  created_project_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export async function startOnboarding(workspaceId: string): Promise<OnboardingDTO> {
  return post<OnboardingDTO>(`/v1/workspaces/${workspaceId}/onboarding`, {})
}

export async function getActiveOnboarding(workspaceId: string): Promise<OnboardingDTO | null> {
  // 404 = no live chat; return null so the caller can open one.
  return getOrNull<OnboardingDTO>(`/v1/workspaces/${workspaceId}/onboarding/active`)
}

export async function getOnboarding(sessionId: string): Promise<OnboardingDTO> {
  return get<OnboardingDTO>(`/v1/onboarding/${sessionId}`)
}

export async function answerOnboarding(
  sessionId: string,
  answer: string,
  otherText?: string,
): Promise<OnboardingDTO> {
  return post<OnboardingDTO>(`/v1/onboarding/${sessionId}/answer`, {
    answer,
    other_text: otherText ?? null,
  })
}

export async function finalizeOnboarding(sessionId: string): Promise<OnboardingDTO> {
  return post<OnboardingDTO>(`/v1/onboarding/${sessionId}/finalize`, {})
}

export async function abandonOnboarding(sessionId: string): Promise<OnboardingDTO> {
  return post<OnboardingDTO>(`/v1/onboarding/${sessionId}/abandon`, {})
}

// ── Roster grant (system‑only) ────────────────────────────────────────────────────────

export interface GrantSeatBody {
  marius_id: string
  role_key: string
}

/** A live seat. A vacated seat is a deleted row, so there is no status to carry. */
export interface SeatGrantDTO {
  id: string
  project_id?: string | null
  role_key: string
  marius_id?: string | null
  granted_at?: string | null
  created_at?: string | null
}

export async function grantSeat(projectId: string, body: GrantSeatBody): Promise<SeatGrantDTO> {
  return post<SeatGrantDTO>(`/v1/projects/${projectId}/grant`, body)
}

// ── SSE URLs (the streams themselves are fetched in sse.ts) ───────────────────────────────

export function workspaceEventsUrl(workspaceId: string): string {
  return `${API_BASE}/v1/workspaces/${workspaceId}/events`
}

export function taskStreamUrl(taskId: string): string {
  return `${API_BASE}/v1/tasks/${taskId}/stream`
}

// ── Task change log · patron inbox · project thresholds (spec 001) ────────────────────────

/** One line of a task's history (spec 001 §10). Follows the task, not a single run. */
export interface TaskLogEntryDTO {
  id: string
  task_id?: string | null
  seq: number
  kind: string
  actor_kind: string
  actor_marius_id?: string | null
  actor_user_id?: string | null
  before?: string | null
  after?: string | null
  reason?: string | null
  detail: Record<string, unknown>
  created_at?: string | null
}

/** A decision waiting on the calling patron (spec 001 §11). */
export interface InboxItemDTO {
  id: string
  workspace_id?: string | null
  project_id?: string | null
  task_id?: string | null
  kind: string
  status: string
  title: string
  body?: string | null
  reminder_tier: number
  attempt_dossier: Record<string, unknown>
  created_at?: string | null
  last_reminded_at?: string | null
  resolved_at?: string | null
}

/** Effective timing thresholds — the system floor with the project's overrides applied. */
export interface ThresholdsDTO {
  hang_suspect_seconds: number
  hang_grace_seconds: number
  orchestration_cadence_seconds: number
  due_soon_hours: number[]
  patron_reminder_hours: number[]
  level1_recovery_attempts: number
  rejection_round_cap: number
  orchestration_wakes_per_hour: number
  orchestration_max_stretch: number
  orchestration_max_interval_seconds: number
  orchestration_min_interval_seconds: number
  level2_handover_attempts: number
}

/** One thing the last orchestration sweep found on the board (spec 001 FR-052).
 *
 * FR-052 names three kinds. `'silent'` is retired and nothing produces it any more; it
 * stays in the union so sweeps recorded before the retirement still render. */
export interface SnagDTO {
  kind: 'silent' | 'due_soon' | 'blocked' | 'awaiting_leader'
  task_id: string
  identifier: string
  title: string
  mark_hours?: number | null
  /**
   * The agent's English copy of this snag, kept for the audit record of what actually went
   * out in the wake packet. NOT for display — the screen builds its own sentence from the
   * fields above so the patron reads it in their language (Constitution VII).
   */
  detail: string
}

/**
 * The Leader's last look at a project's board (spec 001 FR-052 → FR-055).
 *
 * Reports the sweep that actually happened rather than a list computed on read: a
 * recomputed list would look healthy while the loop behind it was dead.
 */
export interface OrchestrationDTO {
  last_swept_at: string | null
  next_sweep_at: string | null
  interval_seconds: number
  woke_leader: boolean
  skipped_reason: string | null
  snags: SnagDTO[]
}

export async function getTaskLog(taskId: string): Promise<TaskLogEntryDTO[]> {
  return get<TaskLogEntryDTO[]>(`/v1/tasks/${taskId}/log`)
}

/** `status` accepts `pending` (default), `resolved`, `void` or `all`.
 *
 * `void` is a letter whose project closed before anyone answered it — off the waiting
 * list, but never claimed as answered. */
export async function getInbox(params?: {
  status?: 'pending' | 'resolved' | 'void' | 'all'
  projectId?: string
}): Promise<InboxItemDTO[]> {
  const query = new URLSearchParams()
  if (params?.status) query.set('status', params.status)
  if (params?.projectId) query.set('project_id', params.projectId)
  const suffix = query.toString() ? `?${query.toString()}` : ''
  return get<InboxItemDTO[]>(`/v1/inbox${suffix}`)
}

export async function resolveInboxItem(itemId: string): Promise<InboxItemDTO> {
  return post<InboxItemDTO>(`/v1/inbox/${itemId}/resolve`, {})
}

/** The patron's answer to a Mức 3 escalation (FR-061a, FR-061e).
 *
 * One call, not "act then close": the answer is a single decision, so the server lands the
 * action and the closing of the letter under one commit. That is also what makes pressing
 * again safe — a letter that is already answered means this call does nothing at all. */
export async function answerInboxItem(
  itemId: string,
  body: { answer: 'reassign' | 'next_action' | 'cancel' | 'handled'; marius_id?: string; text?: string },
): Promise<InboxItemDTO> {
  return post<InboxItemDTO>(`/v1/inbox/${itemId}/answer`, body)
}

export async function getProjectOrchestration(
  projectId: string,
): Promise<OrchestrationDTO> {
  return get<OrchestrationDTO>(`/v1/projects/${projectId}/orchestration`)
}

export async function getProjectThresholds(projectId: string): Promise<ThresholdsDTO> {
  return get<ThresholdsDTO>(`/v1/projects/${projectId}/thresholds`)
}

/** Replace the project's overrides. Omit a field to keep the system floor for it. */
export async function setProjectThresholds(
  projectId: string,
  overrides: Partial<ThresholdsDTO>,
): Promise<ThresholdsDTO> {
  return put<ThresholdsDTO>(`/v1/projects/${projectId}/thresholds`, overrides)
}

// ── Project context · plan · phase (spec 001) ─────────────────────────────────────────────

/** One version of the five-part project brief (spec 001 §2). */
export interface ProjectContextDTO {
  id: string
  project_id?: string | null
  version: number
  objective: string
  background: string
  constraints: string
  scope: string
  principles: string
  approval_status: string
  approved_at?: string | null
  approved_by_user_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

/** The brief in force, plus one awaiting the patron if the Leader submitted a change. */
export interface ProjectContextViewDTO {
  approved: ProjectContextDTO | null
  pending: ProjectContextDTO | null
}

export interface PlanItemDTO {
  id: string
  title: string
  description: string
  order: number
  definition_of_done: string
  depends_on: string[]
}

export interface PlanDTO {
  id: string
  project_id?: string | null
  version: number
  summary: string
  risks: string
  milestones: string
  status: string
  patron_note?: string | null
  submitted_at?: string | null
  decided_at?: string | null
  decided_by_user_id?: string | null
  items: PlanItemDTO[]
  created_at?: string | null
  updated_at?: string | null
}

/** The patron's three choices at the plan gate (FR-013). */
export type PlanDecisionValue = 'duyet' | 'yeu_cau_chinh' | 'hoi_lai'

export async function getProjectContext(projectId: string): Promise<ProjectContextViewDTO> {
  return get<ProjectContextViewDTO>(`/v1/projects/${projectId}/context`)
}

export async function approveProjectContext(
  projectId: string,
  approve: boolean,
  note?: string,
): Promise<ProjectContextDTO> {
  return post<ProjectContextDTO>(`/v1/projects/${projectId}/context/approve`, { approve, note })
}

/** 404 when the Leader has not submitted a plan yet — the caller renders the empty state. */
export async function getProjectPlan(projectId: string): Promise<PlanDTO> {
  return get<PlanDTO>(`/v1/projects/${projectId}/plan`)
}

export async function decideProjectPlan(
  projectId: string,
  decision: PlanDecisionValue,
  note?: string,
): Promise<PlanDTO> {
  return post<PlanDTO>(`/v1/projects/${projectId}/plan/decision`, { decision, note })
}

export async function changeProjectPhase(
  projectId: string,
  targetPhase: string,
  reason?: string,
): Promise<ProjectDetailDTO> {
  return post<ProjectDetailDTO>(`/v1/projects/${projectId}/phase`, {
    target_phase: targetPhase,
    reason,
  })
}
