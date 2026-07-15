# Armarius — Low-Level Design (LLD)

> Status: **Design draft v3** (2026-06-27). Build-level detail for the wave in [HLD.md](./HLD.md) /
> [API_CONTRACT.md](./API_CONTRACT.md), aligned with the approved [ARCHITECTURE.md](./ARCHITECTURE.md).
> Paths relative to repo root. Existing-code references cite `file:line` as of commit `94d6f9e`.

---

## 1. File map (what changes)

### Backend
| Area | File(s) | Change |
|---|---|---|
| Entities | `domain/entities/{workspace,project,role,seat_grant,task,task_participant,checklist_item,task_dependency,label,onboarding_session,artifact,commission_session}.py` | New entities; extend Project/Task/Workspace/Artifact/Marius (enrollment + liveness fields). |
| Use cases | `application/use_cases/{workspaces,projects(NEW),roster(NEW),tasks,onboarding(extend),artifacts,participants(NEW),enrollment(NEW),commission(NEW)}.py` | New services; extend task/artifact/onboarding. `mariuses.register` becomes invite-and-enroll (no token printed). |
| Liveness | `application/liveness/engine.py` (NEW) + `domain/services/clock.py` | Recency + probe engine; exponential-backoff retry; reset on signal. §10. |
| Events/SSE | `application/events/bus.py` (NEW) + `presentation/api/events.py` (NEW) | **Two** Web-App-only SSE channels — workspace control-plane (`/v1/workspaces/{ws}/events`) + per-task trace (`/v1/tasks/{id}/stream`). §11. |
| Repos | `infrastructure/repositories/*.py` + `domain/repositories/*.py` | New repos (roles/grants/labels/participants/checklist/deps/onboarding/commission). |
| ORM | `infrastructure/database/models.py` | New `*Model` classes; new columns (enrollment_code, liveness timers, commission sessions). |
| Migrations | `alembic/` (NEW) + `alembic.ini` + env wiring | Introduce Alembic. |
| Artifact store | `domain/services/artifact_store.py` (port) + `infrastructure/artifacts/store.py` (**MinIO/S3**) | MinIO-backed store, bucket `armarius`. |
| Schemas | `presentation/schemas.py` | New/changed pydantic schemas. |
| API | `presentation/api/{workspaces(+approve, lock adapter_type),projects(NEW),tasks,agent(+enroll/claim; rename task `/claim`→`/join`),artifacts,events(NEW),commission(NEW)}.py` | New routers; changed task/artifact/agent endpoints. `agent.py:70` `/tasks/{id}/claim` → `/tasks/{id}/join` (frees the word "claim" for enrollment recovery). |
| Builtins | `application/use_cases/skills.py` + `static/skills/armarius-onboarder/SKILL.md` (NEW) | Add onboarder builtin. |
| Config | `config.py` | `MINIO_*`, `LIVENESS_*` (§10), `WORKSPACE_AGENT_SKILL_*`. |
| Compose | `docker-compose.yml` | Add `minio` service + persistent volume; create bucket on boot. |

### Frontend
| Area | File(s) | Change |
|---|---|---|
| Routing | `App.tsx` | Insert project-layer routes. |
| Pages | `pages/{ProjectLanding,ProjectBoard,Onboarding,SkillEditor,Directory,CollaborationRoom}.tsx` | New + rework. |
| Components | `components/{RosterPanel,ParticipantBar,Checklist,NestedFileTree,SeatDialog}.tsx` | New building blocks. |
| API / i18n | `api.ts`, `i18n.tsx` | New endpoints; EN/VI keys for projects/roles/onboarding/collaboration. |

---

## 2. Domain entities (field-level)

### 2.1 Workspace — extend
```python
@dataclass
class Workspace:
    id: UUID; name: str; slug: str; owner_user_id: str | None
    workspace_agent_id: UUID | None = None   # NEW: designated Workspace Agent (FK Marius)
    created_at / updated_at
```

### 2.2 Project — extend (split out of `workspace.py`)
```python
class ProjectStatus(str, Enum):
    SETUP = "setup"; ACTIVE = "active"; ARCHIVED = "archived"

@dataclass
class Project:
    id: UUID; workspace_id: UUID; name: str; slug: str; description: str | None
    objective: str | None                     # NEW
    success_metrics: dict | None              # NEW (JSON)
    target_date: datetime | None              # NEW
    github_url: str | None                    # NEW — optional repo link
    context: str | None                       # NEW (patron-pasted free text)
    settings: dict                            # NEW (JSON): require_review_before_done, require_approval_for_done, comment_required_for_review
    status: ProjectStatus = ProjectStatus.SETUP
    created_by_user_id: str | None
    created_at / updated_at
```
`ensure_personal_workspace` / `register` **stop creating "General"**; `ensure_default_project` is
removed. Builtin-skill seeding stays.

### 2.3 Role (seat definition) — NEW
```python
@dataclass
class Role:
    id: UUID; project_id: UUID
    key: str           # stable slug, e.g. "backend", "leader"
    title: str         # "Backend"
    seats: int         # seat count — the leader role is ALWAYS seats == 1
    is_leader: bool = False
    description: str = ""
    responsibilities: str = ""   # leader only — extra duties (default leader behavior TBC)
    skill_ids: list[str] = field(default_factory=list)  # optional skills this role should carry
    created_at: datetime
```
Constraint (`ProjectService.create`): exactly ONE `is_leader` role **and** it must have
`seats == 1`; ≥1 non-leader role with `seats >= 1`. The leader's agent may be supplied now or empty.

### 2.4 SeatGrant — NEW (system-only)
```python
@dataclass
class SeatGrant:
    id: UUID; project_id: UUID; role_key: str; marius_id: UUID
    status: str        # "granted" (Patron grants — system-only) | "revoked"
    granted_at: datetime | None
    created_at: datetime
```
There is **no applicant/acknowledged** state — agents never apply and there is no accept step. A grant
is `granted` immediately (system-only); the only transition out is `revoked`. The role's skill install
is tracked separately (a queued job, not a grant state). Activation keys off **liveness**, not grant
state: `active` = every seat `granted` **and** every seated agent `ONLINE` (§4).

### 2.5 Label — NEW (workspace-scoped)
```python
@dataclass
class Label:
    id: UUID; workspace_id: UUID; name: str; color: str
```

### 2.6 Task — extend
```python
class TaskPriority(str, Enum):
    CRITICAL="critical"; HIGH="high"; MEDIUM="medium"; LOW="low"

@dataclass
class Task:
    # existing…
    identifier: str | None = None             # NEW: "ARM-<seq>", project-scoped
    priority: TaskPriority = TaskPriority.MEDIUM
    parent_id: UUID | None = None             # subtask
    due_date: datetime | None = None
    definition_of_done: str | None = None
    # assigned_marius_id kept for back-compat; superseded by TaskParticipant (primary)
```
Relations: `labels` (M2M via `task_labels`), `checklist` (O2M), `dependencies` (blocked_by via
`task_dependencies`), `participants` (O2M).

### 2.7 TaskParticipant — NEW
```python
@dataclass
class TaskParticipant:
    id: UUID; task_id: UUID; marius_id: UUID
    is_primary: bool = False
    joined_at: datetime
    unique (task_id, marius_id)
```

### 2.8 ChecklistItem — NEW
```python
@dataclass
class ChecklistItem:
    id: UUID; task_id: UUID; text: str; done: bool = False; order: int
```

### 2.9 TaskDependency — NEW
```python
@dataclass
class TaskDependency:
    task_id: UUID          # blocked task
    blocks_task_id: UUID   # the task it waits on
    unique (task_id, blocks_task_id); no self-loops
```

### 2.10 OnboardingSession — NEW
```python
class OnboardingStatus(str, Enum):
    OPEN="open"; FINALIZED="finalized"; ABANDONED="abandoned"

@dataclass
class OnboardingSession:
    id: UUID; workspace_id: UUID; status: OnboardingStatus
    transcript: list[dict]   # [{role:"agent"|"patron", text, ts}]
    collected: dict          # accumulating plan: name/objective/leader/roles[]/context/…
    created_project_id: UUID | None
    created_at / updated_at
```

### 2.11 Artifact — extend (MinIO; kinds file|link)
```python
@dataclass
class Artifact:
    # existing: id, project_id, task_id, marius_id, name, kind, uri, content_sha256, size_bytes, created_at
    stored: bool = False   # True ⇒ bytes live in the MinIO bucket `armarius` (file only)
```
Supported kinds: **`file`** (content **must** be uploaded → MinIO; `uri` = bucket key) and **`link`**
(external `uri`, e.g. a merged PR; `stored = False`). `patch`/`note` dropped.

### 2.12 Marius — extend (enrollment + liveness)
The existing `Marius` (`domain/entities/marius.py`) gains the invite/lifecycle fields. The token is
**not** set at invite time; it is minted on approval.
```python
class InviteStatus(StrEnum):
    INVITED = "invited"; PENDING_REVIEW = "pending_review"; APPROVED = "approved"; REVOKED = "revoked"

@dataclass
class Marius:
    # existing: id, workspace_id, name, role, skills, skill_ids, adapter_type, adapter_config,
    #           owner_user_id, agent_token, liveness, last_seen_at, created_at, updated_at
    invite_status: InviteStatus = InviteStatus.INVITED
    enrollment_code: str | None = None     # issued at invite; agent uses it ONCE on /agent/enroll
    approved_at: datetime | None = None
    # liveness engine bookkeeping (§10): driven by LivenessEngine, not hand-set
    liveness: Liveness = Liveness.OFFLINE       # ONLINE|CHECKING|OFFLINE|WORKING|HUNG (+IDLE legacy)
    last_seen_at: datetime | None = None
    probe_attempts: int = 0                     # within a CHECKING cycle (≤3)
    backoff_step: int = 0                       # OFFLINE retry cycle; R << backoff_step
```
- `agent_token` is `None` until `approve`; `build_invite_prompt` is rewritten to print the
  `enrollment_code` (and per-skill source URLs) — **never** the token.
- `Liveness` already exists in code; `CHECKING` is the "waking" display state (rename `IDLE`→`CHECKING`
  or map it in the schema layer — see §10).

### 2.13 CommissionSession — NEW (leader-mediated commission)
```python
class CommissionStatus(str, Enum):
    OPEN="open"; CONFIRMED="confirmed"; ABANDONED="abandoned"

class LeaderState(str, Enum):                  # surfaced to the Patron while a turn runs
    THINKING="thinking"; WAITING="waiting"; LEADER_OFFLINE="leader_offline"

@dataclass
class CommissionSession:
    id: UUID; project_id: UUID
    leader_marius_id: UUID
    task_id: UUID                       # the Task the Leader is shaping: a fresh draft (new task)
                                        # OR an existing confirmed task (edit, §4 edit())
    session_params: dict                # native Leader session handle (for resume across refine turns)
    transcript: list[dict]              # [{role:"patron"|"leader", text, ts}]
    status: CommissionStatus = CommissionStatus.OPEN
    leader_state: LeaderState = LeaderState.THINKING   # async progress for GET /commission/{id}
    created_at / updated_at
```
A commission chat targets **one Task** — a fresh draft (`Task.status == "draft"`) for a new task, or
an existing **confirmed** task for an edit (§4 `edit`). Refine turns resume `session_params`; `confirm`
flips a draft `draft → todo`, fixes participants = Leader-picked workers, and wakes them (an edit
re-applies the proposal in place without a status flip). The draft is hidden from the board list unless
the caller owns the commission. Because the Leader is an agent, every turn is **async** — the API
returns `202` immediately and the reply/preview arrive over the workspace SSE (`commission.*`, §11).

---

## 3. State machines

### 3.1 Project
```
setup ──(every seat granted AND every seated agent ONLINE)──► active ──(archive)──► archived
```
Reached **once**; **stays active** (a worker going offline later does not roll back). **The only
behavioral gate is task commission**: tasks may be commissioned **only while `active`** and only
through the Project Leader. Everything else (board view, roster CRUD, granting seats) works in `setup`.

### 3.2 Task status — keep existing transitions, add `draft`, tighten two gates
Existing map (`task.py:32-54`) preserved, **plus a new entry point**:
- **`draft`** — created by a commission chat (Leader proposal); `draft → todo` only on
  `/commission/…/confirm`. Drafts are hidden from the board list unless the caller owns the commission.
- → `in_review`/`done` rejected (`409`) unless the task has ≥1 artifact of kind `file` or `link`.
- → `todo`/`in_progress` rejected (`409`) if any `blocked_by` dependency is not `done` (stays
  `backlog`/`blocked`).

### 3.3 SeatGrant — system-only
```
granted ──(revoke)──► revoked
```
No `pending`/`acknowledged`: agents never apply and there is no accept step. A grant is `granted`
immediately; revoke is the only exit. Activation is decided by **liveness**, not grant state (§3.1).

### 3.4 Marius invite — enroll-and-wait
```
invited ──(agent /enroll, held open)──► pending_review ──(Patron approve)──► approved
                                                              │
                                            mint agent_token ONCE, returned AS the enroll response
invited/pending_review ──(revoke)──► revoked
recovery (enroll session lost): approved + /agent/claim(enrollment_code) ──► token
```
The first authenticated `/agent/me` after approval flips `liveness → ONLINE` (§10) and emits
`marius.online` on the workspace-events SSE.

---

## 4. Use-case logic (key methods)

```python
# ProjectService
async def create(self, ws_id, *, name, description, mode, objective, success_metrics,
                 target_date, github_url, context, leader: LeaderIn, roles: list[RoleIn],
                 settings) -> Project:
    validate_plan(leader, roles)    # exactly one leader (seats=1); ≥1 worker role seats≥1
    project = Project(status=SETUP, github_url=github_url, ...)
    persist project + leader role + worker roles
    pre-seat supplied agents (leader.marius_id / role.marius_ids) as `granted` grants (system-only)
    store.ensure_prefix("<project-slug>/")          # MinIO project folder
    recompute_active()              # active only if all granted AND online (not yet)
    if mode == "agent": link onboarding_session.collected
    return project

async def grant_seat(self, project_id, marius_id, role_key) -> SeatGrant:
    # SYSTEM-ONLY — no applicant, no agent touchpoint unless the role has skills.
    ensure seat not full (count(status=granted) < role.seats)
    grant = SeatGrant(status=GRANTED, granted_at=now); add marius as project participant
    if role.skill_ids:
        if marius.liveness == ONLINE:
            wake_engine.queue_skill_install(marius_id, role.skill_ids)   # adapter wake now
        else:
            skill_jobs.enqueue(marius_id, role.skill_ids)               # queued; resumes on next signal
    recompute_active()
    events.emit("seat.skills_installed", {...}) if installed else None
    return grant

async def recompute_active(self, project_id):
    seats_ok = every role seat is granted
    online_ok = every seated marius.liveness == ONLINE
    if seats_ok and online_ok and project.status == SETUP:
        project.status = ACTIVE                      # reached ONCE; never rolls back
        events.emit("project.active", {project_id})

# EnrollmentService (invite lifecycle) — replaces token-in-prompt
async def invite(self, ws_id, *, name, role, adapter_type, skill_ids, adapter_config) -> Marius:
    marius = Marius(invite_status=INVITED, enrollment_code=secrets.token_urlsafe(24),
                    agent_token=None, ...)
    return marius                                    # prompt is built WITHOUT the token (§6)

async def enroll(self, enrollment_code, capabilities, adapter_config) -> HeldEnroll:
    marius = resolve by enrollment_code; assert invite_status in {INVITED, PENDING_REVIEW}
    marius.invite_status = PENDING_REVIEW; events.emit("marius.status_changed", {...})
    held = HeldEnroll(marius_id=marius.id)          # the HTTP response is DEFERRED until approve
    held_sessions.put(held)                          # or: a short-lived completion token + SSE wait
    return held                                      # caller awaits — returns {agent_token} on approve

async def approve(self, marius_id) -> None:         # Patron-side
    assert invite_status == PENDING_REVIEW
    marius.agent_token = secrets.token_urlsafe(32)   # minted ONCE
    marius.invite_status = APPROVED; approved_at = now
    events.emit("marius.status_changed", {status: approved})
    held_sessions.complete(marius_id, {agent_token}) # unblocks the enroll call with the token

async def claim(self, enrollment_code) -> str:      # RECOVERY FALLBACK only
    marius = resolve by enrollment_code; assert invite_status == APPROVED
    return marius.agent_token                         # returns token if the enroll session was lost

def mark_online(self, marius_id):                    # called from GET /agent/me (first contact after approval)
    first = (marius.liveness != ONLINE and marius.invite_status == APPROVED)
    liveness_engine.record_signal(marius_id)         # §10 is the SINGLE funnel: ONLINE + reset timer/backoff
                                                     # + emit marius.liveness{online}. No duplicate bookkeeping here.
    if first:
        events.emit("marius.online", {marius_id})    # one-time "agent is live" milestone for the Directory

# MariusService.update — adapter_type is LOCKED after approval
async def update(self, marius_id, *, name=None, role=None, skills=None, avatar=None,
                 adapter_type=None, adapter_config=None) -> Marius:
    if adapter_type is not None and marius.invite_status == APPROVED and adapter_type != marius.adapter_type:
        raise Conflict("adapter_type is locked after approval; re-invite to change runtime")
    # name/role/skills/avatar/adapter_config remain editable (e.g. rotated gateway creds)

# CommissionService — leader-mediated, no manual form. Every turn is ASYNC:
# the public methods persist the session and SCHEDULE _run_turn, then return at once
# (the API layer maps that to 202). The actual reply + preview arrive over SSE.
async def start(self, project_id, message) -> CommissionSession:        # NEW task
    assert project.status == ACTIVE
    leader = project.leader_marius()
    draft = TaskService.new_draft(project_id)        # status=draft, identifier ARM-n assigned
    sess = CommissionSession(leader_marius_id=leader.id, task_id=draft.id,
                             transcript=[{patron, msg}], leader_state=THINKING)
    persist(sess)
    background.spawn(self._run_turn, sess.id, message, resume=False)
    return sess                                       # → API returns 202 {commission_id, task_id, leader_state}

async def refine(self, commission_id, message) -> CommissionSession:    # iterate the draft
    sess = load(commission_id); append transcript; sess.leader_state = THINKING; persist(sess)
    background.spawn(self._run_turn, sess.id, message, resume=True)
    return sess                                       # → 202

async def edit(self, task_id, message) -> CommissionSession:            # EDIT a confirmed task
    task = TaskService.get(task_id); assert task.status != DRAFT
    leader = task.project.leader_marius()
    sess = CommissionSession(leader_marius_id=leader.id, task_id=task_id,   # targets the EXISTING task
                             transcript=[{patron, msg}], leader_state=THINKING)
    persist(sess)
    background.spawn(self._run_turn, sess.id, message, resume=False)
    return sess                                       # → 202; POST /v1/tasks/{id}/commission

async def _run_turn(self, commission_id, message, *, resume):
    sess = load(commission_id); leader = Marius.get(sess.leader_marius_id)
    if leader.liveness == OFFLINE:                    # wait/retry, NOT a hard 409 (ARCHITECTURE §5)
        sess.leader_state = LEADER_OFFLINE; persist(sess)
        events.emit("commission.leader_offline", {commission_id})
        commission_jobs.enqueue(commission_id, message, resume)   # drained when the leader is ONLINE
        return                                          # (liveness re-probes per backoff §10; record_signal drains)
    sess.leader_state = WAITING; persist(sess)
    ctx = leader_commission_ctx(project, roster, TaskService.get(sess.task_id), message)
    result = await wake_engine.execute(leader, resume=sess.session_params if resume else None, ctx=ctx)
    TaskService.apply_proposal(sess.task_id, result.proposal)   # leader-filled fields + picked workers
    sess.session_params = result.session_params; sess.leader_state = WAITING; persist(sess)
    events.emit("commission.turn",  {commission_id, leader_reply, task_preview})
    events.emit("commission.ready", {commission_id})  # draft awaits Patron confirm/refine

async def confirm(self, commission_id) -> Task:        # synchronous (no agent turn)
    sess = load(commission_id); task = TaskService.get(sess.task_id)
    if task.status == DRAFT:                            # new task → publish; edits already live
        task.status = TODO; events.emit("task.created", {task_id})
    task.participants = leader-picked workers
    for w in task.participants: wake_engine.wake(w, task_context=task)   # each woken with context
    sess.status = CONFIRMED; persist(sess)
    return task

# TaskService (no Patron-facing manual create — commission owns task creation)
async def new_draft(self, project_id) -> Task:      # internal; called by CommissionService
    assign identifier (project-scoped seq); status = DRAFT; persist
async def transition(self, task_id, to_status, actor) -> Task:
    if to_status in {IN_REVIEW, DONE}: require_output(task_id)      # §5.3 gate
    if to_status in {TODO, IN_PROGRESS}: assert_dependencies_met(task_id)
    apply existing allowed-transition check
async def add_participant(self, task_id, marius_id) -> wakes marius with task context

# ArtifactService
async def publish(self, task_id, marius_id, *, name, kind, content_b64=None, uri=None,
                  content_sha256=None, size_bytes=None) -> Artifact:
    if kind == FILE:
        if not content_b64: raise ValueError("content required for a file artifact")
        raw = b64decode(content_b64)
        if content_sha256: verify sha256(raw) == content_sha256
        # The store follows the project: <project-slug>/<task-id-or-slug>/<name>
        key = await self.store.put_object(raw, f"{project_slug}/{task_ref}/{name}")
        uri = key; stored = True; size_bytes = len(raw)
    elif kind == LINK:
        if not uri: raise ValueError("uri required for a link artifact")
        stored = False
    else:
        raise ValueError(f"unsupported kind {kind}")   # only file|link
    persist Artifact(...)
```

`require_output(task)` ⇒ `any(a.kind in {FILE, LINK} for a in artifacts)`.

---

## 5. Database / migrations (introduce Alembic)

Today: no migrations; `create_all()` on startup (can't add columns to existing tables).

1. Add `alembic`; `alembic init alembic` (async `env.py` → `DATABASE_URL`, `target_metadata = Base.metadata`).
2. Baseline `0001_baseline` = autogenerate of **current** models; `stamp` on existing DBs.
3. `0002_projects_roster_tasks`: `projects.status/objective/success_metrics/target_date/context/
   github_url/settings`, `workspaces.workspace_agent_id`, `roles`, `seat_grants` (status
   `granted`/`revoked` only), `labels`, `task_labels`,
   `tasks.identifier/priority/parent_id/due_date/definition_of_done` (status enum gains `draft`),
   `task_participants`, `checklist_items`, `task_dependencies`, `artifacts.stored`,
   `mariuses.invite_status/enrollment_code/approved_at/probe_attempts/backoff_step/next_probe_at/
   offline_since`,
   `commission_sessions` (`project_id`, `leader_marius_id`, `task_id`, `session_params`, `transcript`,
   `status`, `leader_state`). All additive (NULL/new tables/new enum value) — non-destructive.
4. Seed step: insert `armarius-onboarder` builtin into existing workspaces (idempotent).
5. Local: `alembic upgrade head`; CI runs migrations against fresh Postgres.

`create_all()` kept only for the very first bootstrap of an empty DB; thereafter Alembic owns schema.

---

## 6. Shared Artifact Store (MinIO infra)

```python
# domain/services/artifact_store.py — port (protocol)
class ArtifactStore(Protocol):
    async def put_object(self, raw: bytes, key: str) -> str: ...           # returns key
    async def get_object(self, key: str) -> bytes: ...
    async def open_stream(self, key: str) -> AsyncIterator[bytes]: ...
    async def presign_get(self, key: str, expires: int) -> str: ...        # optional time-limited URL

# infrastructure/artifacts/store.py — MinIO (S3) impl
class MinioArtifactStore:
    def __init__(self, endpoint, access_key, secret_key, bucket, secure):
        self._client = minio-async client; self.bucket = bucket   # "armarius"
    # put_object: ensure bucket exists; put bytes at key
    # get/open_stream: get_object / streaming body
```
- Config: `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET` (default
  `armarius`), `MINIO_SECURE`. Bucket created on startup if absent.
- **The store follows the project.** A project's folder is provisioned at project creation
  (`<project-slug>/`); each task that produces output writes under it keyed by task id/slug:
  ```
  armarius/
  ├── <project-slug>/<task-id-or-slug>/<name>   # file artifacts (content-stored)
  └── _media/avatars/<marius_id>.<ext>          # media (agent avatars, …)
  ```
  e.g. a file for task `ARM-7` in project `acme-web` → `armarius/acme-web/ARM-7/<name>`;
  `Artifact.uri` holds that key. Agent avatars upload via `POST /workspaces/{ws}/media` → `_media/`.
- Downloads stream via `open_stream`; optionally `presign_get` for direct browser fetch.
- `ProjectService.create` calls `store.ensure_prefix("<project-slug>/")` (or simply relies on the
  first object write — MinIO has no real directories; the per-project prefix is logical).

---

## 7. Frontend — components & pages

### 7.1 Nested file tree (`components/NestedFileTree.tsx`) — replaces flat list
- Build a tree from the flat `files: {path: content}` map (split each path on `/`).
- Folder node: chevron `▸/▾` + name (collapsible; state in component + `localStorage` per skill id).
  File node: icon + name; click selects for the editor. SKILL.md pinned at top.
- Folder actions: new file here / new folder / delete folder (removes `folder/*`). Root: same.
- `Skills.tsx` preview reuses the tree read-only (select to view content) — replaces the single `<pre>`.

### 7.2 Project landing (`pages/ProjectLanding.tsx`)
- Header: workspace name + "designate Workspace Agent" control (picker from the directory; shows the
  current designee + badge).
- Project cards: name, status (`setup`/`active`), roster fill (`leader ✓ · backend 1/2`), ack state,
  task counts. Empty-state CTA → "New project".

### 7.3 Onboarding modal (`components/ProjectOnboardingModal.tsx`)
- Mode toggle: **Manual** | **Agent** (Agent disabled until a Workspace Agent is designated, with a hint).
- **Manual** (single scrolling form): name, objective, target_date, **github_url (optional)**, context;
  a **Project Leader** block (responsibilities textarea + picker to **seat an existing agent now or
  leave empty**); a **worker-roles editor** (repeatable: title, **seats** (number), description,
  **optional skills** multi-pick like inviting an agent, optional pre-seated agents); settings toggles.
  Create disabled until the hard rule passes; on submit `POST /projects`. Success → project board.
- **Agent** (Phase G): the onboarding chat — transcript + collected-plan preview + Finalize.

### 7.4 Project board (`pages/ProjectBoard.tsx`) — `route …/projects/{p}`
- Existing kanban moves under the project (columns unchanged). A **RosterPanel** (rail/tab) shows
  roles, seat fill, liveness, and a **Grant seat** action (pick agent + role; **system-only** — no
  apply/accept). Activation status (`setup`/`active`) reflects granted + online, updated over SSE.
- "Commission task" opens a **leader chat** (`components/CommissionChat.tsx`) — **no form**. The Patron
  types a request; the Leader's replies + the task preview stream in over the workspace-events SSE;
  the Patron refines or confirms. Card click → Collaboration Room (§7.5).

### 7.5 Collaboration Room (`pages/CollaborationRoom.tsx`, reworks `Room.tsx`)
3-column skeleton realigned to the design's Collaboration view:
- **Left/Context**: editable title/description, **Definition of Done**, **Checklist** (add/toggle),
  status pill, priority, labels, due_date, dependencies (blocked-by pills), linked artifacts + "publish
  to shared store".
- **Center/Thread**: comment thread (@mentions, author kinds) + composer (the co-work surface); a
  **Participants bar** shows who's on the task + per-participant "wake".
- **Right/Trace**: existing live run trace (SSE) — retained ("you trace").
- Publish flow: upload file → stored artifact card + download; transitions to in_review/done disabled
  with a tooltip until a file/link output exists.

### 7.6 Directory — invite flow + liveness dot + Workspace Agent badge
- "Add agent" opens a **type-picker** (adapter type, name, role, skills[]); on submit the backend
  returns the copyable prompt (`enrollment_code`, **no token**). The card transitions
  `invited → pending_review → approved`, driven by the workspace-events SSE; an **Approve** action is
  shown for `pending_review`.
- Each agent shows a **liveness dot** (ONLINE/CHECKING/OFFLINE) updated over SSE. Avatar upload →
  MinIO `_media/avatars/`. Workspace-Agent badge + the designation action also live here and in
  `ProjectLanding`.

---

## 8. i18n additions (EN/VI, via `t()`/`tEn()`)

- `project.*` — title, new, status.setup/active/archived, roster, roles, seats, leader, worker,
  responsibilities, githubUrl, grant, revoke, leaveEmpty, preseat, context, objective, targetDate,
  successMetrics, settings.*, grantSeat.
- `invite.*` — addAgent, chooseType, invited, pendingReview, approved, approve, copyPrompt,
  promptCopied, enrollWaiting. (No applicant/accept/acknowledged keys.)
- `liveness.*` — online, checking (a.k.a. "waking"), offline, working, hung, lastSeen.
- `commission.*` — title, placeholder, refine, confirm, leaderReply, preview, leaderOffline.
- `onboarding.*` — manual, agent, modeHint, finalize, needWorkspaceAgent, askGoal/askRoles/askContext.
- `task.*` — priority.*, status.draft, checklist.*, definitionOfDone, dueDate, blockedBy, blocks,
  participant(s), wake, publishOutput, gateNeedOutput.
- `artifact.*` — sharedStore, publish, download, contentRequired, kindFile/kindLink.

---

## 9. Tests (backend, httpx)

- `test_project_requires_leader_and_worker_roles` — no leader → 422; leader seats≠1 → 422; no worker
  role → 422; leader left empty → 201 (`setup`); valid → 201 (`setup`).
- `test_project_activates_when_all_seats_granted_and_online` — grant all + bring all ONLINE →
  `active`; grant-all-but-one-offline → `setup`; grant-then-online-then-offline-after-active → **stays**
  `active`.
- `test_no_tasks_in_setup_project` and `commission_in_setup_rejected` (409).
- `test_seat_grant_is_system_only` — no `/apply`/`/accept` routes; grant → `granted`; grant again past
  seat count → 409; revoke → `revoked`; granting a role with skills on an offline agent **queues** the
  install (no wake fired), and on an online agent **fires** the wake.
- `test_invite_enroll_and_wait` — `POST /mariuses` returns `enrollment_code`, **no** token; agent
  `POST /agent/enroll` is held open and flips `pending_review`; Patron `approve` mints the token and
  **completes the enroll call with it**; the first `/agent/me` flips `ONLINE` + emits `marius.online`.
- `test_claim_is_recovery_only` — `/agent/claim` returns the token only after approval; before approval
  → 409; after a lost enroll session → 200.
- `test_token_never_in_prompt` — assert the invite prompt text does not contain `agent_token`.
- `test_commission_leader_chat` — `POST /commission` creates a `draft` task; leader fills fields +
  picks workers; `/refine` resumes the session; `/confirm` → `todo` + wakes workers; draft hidden from
  the board list for non-owners.
- `test_task_rich_schema` — commission-produced task carries priority/labels/checklist/deps/parent/DoD;
  PATCH edits; filters.
- `test_dependency_blocks_progress` — blocked task can't go in_progress until blocker done.
- `test_artifact_file_requires_content_and_link_requires_uri` — file without `content_b64` → 400;
  file with → stored in MinIO, downloadable; link without `uri` → 400; link with → ok.
- `test_done_gate_requires_output` — in_review/done rejected (409) without a file/link artifact; ok after.
- `test_liveness_decay_and_reset` — idle past T1 + 3 failed probes → OFFLINE; any signal resets to
  ONLINE and zeroes backoff; OFFLINE retry interval doubles each failed cycle (R→2R→4R) up to the cap.
- `test_onboarding_manual_creates_project`.
- `test_workspace_agent_designation_adds_onboarder_skill` (direct adapter wake when online; queued
  when offline).

Frontend: typecheck + build; Playwright for Collaboration Room + nested tree + commission chat in a
follow-up.

---

## 10. Liveness engine (`application/liveness/engine.py`) **[NEW]**

Owns the recency+probe model for every Marius. It is the **only** writer of `Marius.liveness`; all
signals funnel through `record_signal(marius_id)`, and a single background loop advances the state
machine off the clock. See [ARCHITECTURE.md](./ARCHITECTURE.md) §5 for the state diagram.

```python
@dataclass
class LivenessConfig:
    idle_timeout: timedelta        = timedelta(seconds=90)    # T1 — no signal ⇒ start probing
    probe_window: timedelta        = timedelta(seconds=30)    # T2 — gap BETWEEN probe attempts (and per-probe timeout)
    max_probe_attempts: int        = 3                        # 3 misses ⇒ OFFLINE
    retry_base: timedelta          = timedelta(seconds=60)    # R  — FIRST OFFLINE re-probe wait
    retry_max: timedelta           = timedelta(minutes=30)    # cap on the doubling backoff
    retry_factor: float            = 2.0                      # R → 2R → 4R …
    hung_after: timedelta          = timedelta(minutes=20)    # WORKING turn watchdog

# Marius liveness bookkeeping (persisted): liveness, last_seen_at, probe_attempts,
# backoff_step, next_probe_at, offline_since, turn_started_at.

class LivenessEngine:
    async def record_signal(self, marius_id):        # ANY contact: probe reply, /agent/me, task reply, enroll reply
        m.liveness = ONLINE; m.last_seen_at = now
        m.probe_attempts = 0; m.backoff_step = 0; m.next_probe_at = None   # RESET timer + backoff
        events.emit("marius.liveness", {marius_id, "online"})
        drain_offline_jobs(marius_id)                 # resume work queued while offline: skill installs
                                                       # (grant_seat) + commission turns (commission_jobs)
    async def begin_turn(self, marius_id):           # wake engine calls this when a turn starts
        m.liveness = WORKING; m.turn_started_at = now
    async def end_turn(self, marius_id):
        await self.record_signal(marius_id)          # turn done ⇒ counts as a signal (reset)

    async def tick(self):                            # background loop, e.g. every 5s — TIME-DRIVEN, never blocks
        for m in mariuses.all():
            if m.liveness == WORKING:
                if now - m.turn_started_at > hung_after: m.liveness = HUNG
                continue                                                  # a turn IS a signal; don't probe
            # ONLINE gone quiet past T1 → enter CHECKING and schedule the FIRST probe now
            if m.liveness == ONLINE and now - m.last_seen_at > T1:
                m.liveness = CHECKING; m.probe_attempts = 0; m.next_probe_at = now
            # OFFLINE waiting out its backoff → when the interval elapses, re-enter CHECKING
            if m.liveness == OFFLINE and now >= m.next_probe_at:
                m.liveness = CHECKING; m.probe_attempts = 0; m.next_probe_at = now
            # CHECKING: fire at most ONE probe per due time, spaced by T2
            if m.liveness == CHECKING and now >= m.next_probe_at:
                await self._probe(m)                                      # awaits ≤ T2; sets next_probe_at = now + T2
                if m.liveness == CHECKING and m.probe_attempts >= max_probe_attempts:
                    self._go_offline(m)

    async def _probe(self, m):
        # one light "reply OK" turn in a throwaway session via the adapter; bounded by T2
        m.probe_attempts += 1
        m.next_probe_at = now + probe_window          # the NEXT attempt waits a full T2 (no burst)
        result = await wake_engine.execute(m, ctx=probe_ctx, timeout=int(T2.total_seconds()))
        if result.status == COMPLETED:
            await self.record_signal(m.id)            # success ⇒ reset (cancels the CHECKING cycle)

    def _retry_interval(self, m):
        # backoff_step is the count of FAILED offline cycles so far: 0 ⇒ R, 1 ⇒ 2R, 2 ⇒ 4R … capped
        return min(retry_base * (retry_factor ** m.backoff_step), retry_max)

    def _go_offline(self, m):
        m.liveness = OFFLINE; m.offline_since = now
        m.next_probe_at = now + self._retry_interval(m)   # schedule re-probe BEFORE bumping the step
        m.backoff_step += 1                               # so the FIRST offline wait is exactly R, then 2R, 4R …
        events.emit("marius.liveness", {marius_id, "offline"})
```

Two correctness points the prior draft got wrong (reviewer-flagged), now fixed:

- **Probe spacing (`T2` between attempts).** `tick` fires **at most one probe per Marius per due
  time**, and `_probe` sets `next_probe_at = now + probe_window`, so the 3 attempts are spaced ~`T2`
  apart — not blasted within one 5-second tick. `tick` itself never blocks the loop on the 3-probe
  sequence; it advances each Marius by time.
- **Backoff starts at `R`, not `2R`.** `_go_offline` computes `next_probe_at` with the **current**
  `backoff_step` (0 ⇒ interval `R`) and **then** increments it. So the first OFFLINE wait is exactly
  `R`, the next `2R`, then `4R` … capped at `retry_max` — matching ARCHITECTURE §5.

Other notes:

- **`record_signal` is the universal reset.** Any contact — mid-probe, or while OFFLINE — snaps the
  agent to ONLINE and zeroes `probe_attempts`/`backoff_step`/`next_probe_at`. Activation (§4
  `recompute_active`) re-evaluates on the resulting `marius.online` event.
- **No heartbeat endpoint.** The probe is the primary mechanism; the agent is never asked to self-report
  (ARCHITECTURE §5). Incidental agent calls just route through `record_signal` opportunistically.
- The `IDLE` enum value from the current code is **deprecated**; `CHECKING` replaces it (map `IDLE→
  CHECKING` in the schema layer, or rename). `HUNG` and `WORKING` are surfaced to the UI liveness dot.
- The probe is a real adapter `execute()` (so the runtime must answer); `echo` answers instantly
  (useful for tests). Probe turns carry `task_id=None` and a throwaway session so they never pollute a
  task transcript.
- Concurrency: one outstanding probe per Marius; a late signal arriving during a probe simply resets and
  cancels the failure count (the in-flight `_probe` result is then ignored because state is ONLINE).

## 11. SSE channels — Hybrid (`application/events/bus.py` + `presentation/api/events.py`) **[NEW]**

**Two** server→browser SSE channels, both `StreamingResponse` with `text/event-stream`, both
**Web-App-only** (agents never read SSE), both honoring `Last-Event-ID` for gap-free resume:

1. **Workspace control-plane** — `GET /v1/workspaces/{ws}/events` (JWT). Always-on; the Web App holds
   it open on workspace mount. Carries light events that belong to no single task.
2. **Per-task trace** — `GET /v1/tasks/{task_id}/stream` (JWT). Opened by the Collaboration Room only
   while the task is on screen and closed on leave. Carries that task's heavy run trace.

```python
class EventBus:                                     # in-process pub/sub
    async def emit_workspace(self, ws_id, type: str, data: dict, event_id=None): ...
    async def emit_task(self, task_id, type: str, data: dict, event_id=None): ...   # trace channel
    async def subscribe_workspace(self, ws_id, after=None) -> AsyncIterator[SSEFrame]: ...
    async def subscribe_task(self, task_id, after=None) -> AsyncIterator[SSEFrame]: ...

# events.py — one helper renders both
def _sse(gen):  # id:/event:/data: framing
    return StreamingResponse(gen, media_type="text/event-stream")

@router.get("/workspaces/{ws_id}/events")
async def workspace_events(ws_id, user, bus: EventBus):
    async def gen():
        async for f in bus.subscribe_workspace(ws_id, after=last_event_id()):
            yield f"id: {f.id}\nevent: {f.type}\ndata: {json.dumps(f.data)}\n\n"
    return _sse(gen())

@router.get("/tasks/{task_id}/stream")
async def task_trace(task_id, user, bus: EventBus):
    async def gen():
        async for f in bus.subscribe_task(task_id, after=last_event_id()):
            yield f"id: {f.id}\nevent: {f.type}\ndata: {json.dumps(f.data)}\n\n"
    return _sse(gen())
```

- **Workspace-channel producers**: `EnrollmentService`, `ProjectService.grant_seat`/`recompute_active`,
  `LivenessEngine`, `CommissionService`. Event types: `marius.status_changed`, `marius.online`,
  `marius.liveness`, `seat.skills_installed`, `project.active`,
  `commission.turn`/`commission.leader_offline`/`commission.ready`, `task.created`, approvals.
  (The §4/§10 pseudocode writes these as `events.emit(...)` — shorthand for `emit_workspace` on the
  agent's workspace; only the trace tee uses `emit_task`.)
- **Task-channel producer**: the **wake-engine trace tee** — the adapter's `on_event` callback fans
  `run.delta`/`run.tool`/`run.usage` (each carrying `task_id`/`run_id`) onto `emit_task`.
- **Why two channels (Hybrid), not one.** The trace is heavy and only relevant while a room is open;
  control-plane events must arrive even with no room open. Splitting keeps the always-on connection cheap
  (the browser does not download every agent's trace at once) while still streaming each task in
  real-time. This is distinct from the **agent runtime session** (one per task/run, backend↔agent,
  unchanged): the wake engine **tees** each session's events onto that task's trace channel. So the
  browser holds **one** always-on connection plus **at most one** trace connection (the focused task).
- In a multi-worker deploy both channels need a shared broker (Redis pub/sub); for the single-uvicorn
  compose setup an in-process bus is sufficient and is what Phase A ships.

## 12. Invite lifecycle — holding the enroll call **[NEW]**

`POST /agent/enroll` must stay open until the Patron approves, then return the token as its response.
Two equivalent implementations (pick per adapter transport):

1. **Deferred HTTP response (Hermes/Claude-local).** `enroll` registers a pending `HeldEnroll` keyed
   by `marius_id`, then `await`s an `asyncio.Future`. `approve` mints the token and
   `future.set_result({"agent_token": …})`; the held request returns it. A `enroll_timeout` (e.g. 10m)
   resolves the future with `408` so the agent can re-enroll.
2. **Run-result completion (OpenClaw gateway).** The gateway's run is held open; `approve` posts the
   token as the run's completion payload; the agent reads it from the run result. Same timeout story.

Recovery: if the held session is lost (agent restart, gateway timeout) **before** approval completes,
the agent calls `POST /agent/claim(enrollment_code)`; the backend returns the token **iff**
`invite_status == APPROVED` (else `409 pending`). Claim is therefore a fallback, never the happy path.

`build_invite_prompt` (`application/use_cases/onboarding.py`) is rewritten to:
- print the **`enrollment_code`** and the per-skill **source URLs** (full file tree install);
- **omit** `agent_token` entirely;
- instruct the agent to `POST /agent/enroll` and wait, then store the returned token to
  `~/.armarius/tokens/…`, install skills, and call `GET /agent/me` (which flips ONLINE, §10).
