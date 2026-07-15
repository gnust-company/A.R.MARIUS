// Real API client (Sprint 6 golden-path scope).
//
// Typed fetch wrapper that injects the Bearer token, handles 401→refresh→retry, and exposes
// every endpoint the golden-path needs: auth/me, workspaces, projects (list/create/get),
// roster (detail/grant), mariuses, labels, skills, tasks (CRUD + comments + artifacts),
// commission, and the two SSE routes (for URL construction only; the stream itself lives in sse.ts).
//
// Error responses raise an `ApiError` with a `detail` string (the server‑sent `detail` field
// or a fallback message). Callers can display it as a toast or inline alert.

import { getToken, logout, refreshAccessToken, type UserDTO } from './auth'
import { API_BASE } from './env'

export class ApiError extends Error {
  status?: number
  constructor(detail: string, status?: number) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
  }
}

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
      throw new ApiError('Session expired. Please log in again.', 401)
    }
  }

  return res
}

async function get<T>(path: string): Promise<T> {
  const res = await fetchWithAuth(path)
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
    } catch {
      // non-JSON error body — keep the status-line fallback
    }
    throw new ApiError(detail, res.status)
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
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
    } catch {
      // non-JSON error body — keep the status-line fallback
    }
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as T
}

async function patch<T>(path: string, body: unknown): Promise<T> {
  const res = await fetchWithAuth(path, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
    } catch {
      // non-JSON error body — keep the status-line fallback
    }
    throw new ApiError(detail, res.status)
  }
  return (await res.json()) as T
}

// DELETE that tolerates a 204 (no body). Surfaces the server `detail` on 4xx so callers
// can toast the constraint message (e.g. "Built-in skills can't be deleted.").
async function del(path: string): Promise<void> {
  const res = await fetchWithAuth(path, { method: 'DELETE' })
  if (!res.ok && res.status !== 204) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
    } catch {
      // non-JSON error body — keep the status-line fallback
    }
    throw new ApiError(detail, res.status)
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
  adapter_type: string
  liveness: string
  /** Invite lifecycle: invited → pending_review → approved (#51). */
  invite_status?: string | null
  last_seen_at?: string | null
  created_at?: string | null
}

// POST /workspaces/{id}/mariuses response (backend `MariusCreatedOut`). Under operator-invite
// (#63) the token is minted at invite time and pushed to the agent over its gateway — it is
// NEVER returned (a secret). `send_status` tells the UI whether the setup prompt landed.
export interface MariusCreatedDTO extends MariusDTO {
  send_status: 'sent' | 'send_failed'
}

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
  title: string
  description?: string | null
  status: string
  status_reason?: string | null
  assigned_marius_id?: string | null
  next_action?: string | null
  created_at?: string | null
  updated_at?: string | null
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
export interface RunDTO {
  id: string
  task_id?: string | null
  marius_id?: string | null
  adapter_type: string
  wake_source: string
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

export interface CommissionDTO {
  id: string
  project_id?: string | null
  leader_marius_id?: string | null
  task_id?: string | null
  status: string
  leader_state: string
  transcript: Array<{ role: string; text: string }>
  created_at?: string | null
  updated_at?: string | null
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

// ── Projects ───────────────────────────────────────────────────────────────────────────

export interface CreateProjectBody {
  name: string
  description?: string
  objective?: string
  leader?: { marius_id?: string | null; responsibilities?: string }
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
    let detail = `${res.status} ${res.statusText}`
    try {
      const data = await res.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
    } catch {
      // non-JSON error body — keep the status-line fallback
    }
    throw new ApiError(detail, res.status)
  }
}

// ── Mariuses ───────────────────────────────────────────────────────────────────────────

export async function listMariuses(workspaceId: string): Promise<MariusDTO[]> {
  return get<MariusDTO[]>(`/v1/workspaces/${workspaceId}/mariuses`)
}

export interface InviteMariusBody {
  name: string
  skills?: string[]
  skill_ids?: string[]
  adapter_type?: string
  /** The agent's gateway address + key (operator-invite, #63) — stored as adapter_config. */
  gateway_url: string
  api_key: string
  /** Seat the newcomer as Workspace Agent on invite; a sitting host is demoted (#32). */
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

/** Result of linking more skills to an already-invited agent + pushing an install prompt (#74). */
export interface InstallSkillsDTO {
  marius_id: string
  /** The full merged skill-id list after the install (de-duped). */
  skill_ids: string[]
  /** Slugs of the newly linked skills (the ones the install prompt covers). */
  installed: string[]
  /** Best-effort push status: "sent" | "send_failed". */
  send_status: string
}

/** Link additional skills to an invited agent and push a one-time install prompt (#74). */
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

export async function createTask(projectId: string, title: string, description?: string): Promise<TaskDTO> {
  return post<TaskDTO>(`/v1/projects/${projectId}/tasks`, { title, description })
}

export async function updateTaskStatus(taskId: string, status: string, reason?: string): Promise<TaskDTO> {
  return post<TaskDTO>(`/v1/tasks/${taskId}/status`, { status, reason })
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

// ── Commission ───────────────────────────────────────────────────────────────────────────

export interface CommissionStartBody {
  project_id: string
  message: string
  title?: string
}

export async function startCommission(body: CommissionStartBody): Promise<CommissionDTO> {
  return post<CommissionDTO>('/v1/commissions', body)
}

export interface CommissionRefineBody {
  message: string
}

export async function refineCommission(sessionId: string, body: CommissionRefineBody): Promise<CommissionDTO> {
  return post<CommissionDTO>(`/v1/commissions/${sessionId}/refine`, body)
}

export async function confirmCommission(sessionId: string): Promise<CommissionDTO> {
  return post<CommissionDTO>(`/v1/commissions/${sessionId}/confirm`, {})
}

export async function getCommission(sessionId: string): Promise<CommissionDTO> {
  return get<CommissionDTO>(`/v1/commissions/${sessionId}`)
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

export interface SeatGrantDTO {
  id: string
  project_id?: string | null
  role_key: string
  marius_id?: string | null
  status: string
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
