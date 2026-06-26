# Armarius — Low-Level Design (LLD)

> Status: **Design draft v2** (2026-06-26). Build-level detail for the wave in [HLD.md](./HLD.md) /
> [API_CONTRACT.md](./API_CONTRACT.md). Paths relative to repo root. Existing-code references cite
> `file:line` as of commit `94d6f9e`.

---

## 1. File map (what changes)

### Backend
| Area | File(s) | Change |
|---|---|---|
| Entities | `domain/entities/{workspace,project,role,seat_grant,task,task_participant,checklist_item,task_dependency,label,onboarding_session,artifact}.py` | New entities; extend Project/Task/Workspace/Artifact. |
| Use cases | `application/use_cases/{workspaces,projects(NEW),roster(NEW),tasks,onboarding(extend),artifacts,participants(NEW)}.py` | New services; extend task/artifact/onboarding. |
| Repos | `infrastructure/repositories/*.py` + `domain/repositories/*.py` | New repos (roles/grants/labels/participants/checklist/deps/onboarding). |
| ORM | `infrastructure/database/models.py` | New `*Model` classes; new columns. |
| Migrations | `alembic/` (NEW) + `alembic.ini` + env wiring | Introduce Alembic. |
| Artifact store | `domain/services/artifact_store.py` (port) + `infrastructure/artifacts/store.py` (**MinIO/S3**) | MinIO-backed store, bucket `armarius`. |
| Schemas | `presentation/schemas.py` | New/changed pydantic schemas. |
| API | `presentation/api/{workspaces,projects(NEW),tasks,agent,artifacts}.py` | New routers; changed task/artifact endpoints. |
| Builtins | `application/use_cases/skills.py` + `static/skills/armarius-onboarder/SKILL.md` (NEW) | Add onboarder builtin. |
| Config | `config.py` | `MINIO_*`, `WORKSPACE_AGENT_SKILL_*`. |
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

### 2.4 SeatGrant — NEW
```python
@dataclass
class SeatGrant:
    id: UUID; project_id: UUID; role_key: str; marius_id: UUID
    status: str        # "pending" (applicant) | "granted" (patron vetted) | "acknowledged" (agent accepted) | "revoked"
    granted_at: datetime | None
    acknowledged_at: datetime | None
    created_at: datetime
```

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
    # assigned_marius_id kept for back-comat; superseded by TaskParticipant (primary)
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

---

## 3. State machines

### 3.1 Project
```
setup ──(every seat filled + acknowledged)──► active ──(archive)──► archived
```
**The only behavioral gate is task assignment**: tasks may be commissioned/assigned **only while
`active`**. Everything else (board view, roster CRUD, seat vetting) works in `setup` too.

### 3.2 Task status — keep existing transitions, tighten two gates
Existing map (`task.py:32-54`) preserved. **Additions**:
- → `in_review`/`done` rejected (`409`) unless the task has ≥1 artifact of kind `file` or `link`.
- → `todo`/`in_progress` rejected (`409`) if any `blocked_by` dependency is not `done` (stays
  `backlog`/`blocked`).

### 3.3 SeatGrant
```
pending(applicant) ──(grant)──► granted ──(accept)──► acknowledged ──(revoke)──► revoked
```

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
    pre-seat supplied agents (leader.marius_id / role.marius_ids) as `granted` grants
    recompute_active()              # active only if all seats acknowledged (not yet)
    if mode == "agent": link onboarding_session.collected
    return project

async def grant_seat(self, project_id, marius_id, role_key) -> SeatGrant:
    ensure seat not full (count granted < role.seats)
    create `granted` grant; add marius as project participant
    return grant

async def accept_seat(self, project_id, marius_id) -> SeatGrant:   # agent online + accepts
    grant.status = ACKNOWLEDGED; grant.acknowledged_at = now
    recompute_active()
    return grant

async def recompute_active(self, project_id):
    if every seat across all roles is `acknowledged`: project.status = ACTIVE

# TaskService
async def create(self, project_id, *, title, description, priority, label_ids,
                 parent_id, blocked_by, checklist, definition_of_done, due_date) -> Task:
    assert project.status == ACTIVE
    assign identifier (project-scoped seq)
    persist + link labels/checklist/deps/participants
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
   github_url/settings`, `workspaces.workspace_agent_id`, `roles`, `seat_grants`, `labels`,
   `task_labels`, `tasks.identifier/priority/parent_id/due_date/definition_of_done`,
   `task_participants`, `checklist_items`, `task_dependencies`, `artifacts.stored`. All additive
   (NULL/new tables) — non-destructive.
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
  roles, seat fill, ack state, applicants to vet (apply → grant → accept → acknowledged).
- Commission modal collects the full schema (priority, labels, due_date, DoD, checklist seed, parent,
  blocked_by). Card click → Collaboration Room (§7.5).

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

### 7.6 Directory — add Workspace Agent badge + avatar upload (MinIO `avatars/`).
Provisioning unchanged; designation action also lives in `ProjectLanding`.

---

## 8. i18n additions (EN/VI, via `t()`/`tEn()`)

- `project.*` — title, new, status.setup/active/archived, roster, roles, seats, leader, worker,
  responsibilities, githubUrl, grant, revoke, applicant, vetting, accept, seatState.pending/granted/
  acknowledged, leaveEmpty, preseat, context, objective, targetDate, successMetrics, settings.*.
- `onboarding.*` — manual, agent, modeHint, finalize, needWorkspaceAgent, askGoal/askRoles/askContext.
- `task.*` — priority.*, checklist.*, definitionOfDone, dueDate, blockedBy, blocks, participant(s),
  wake, publishOutput, gateNeedOutput.
- `artifact.*` — sharedStore, publish, download, contentRequired, kindFile/kindLink.

---

## 9. Tests (backend, httpx)

- `test_project_requires_leader_and_worker_roles` — no leader → 422; leader seats≠1 → 422; no worker
  role → 422; leader left empty → 201 (`setup`); valid → 201 (`setup`).
- `test_project_activates_only_when_all_seats_acknowledged` — grant all + accept all → `active`;
  partial → `setup`.
- `test_no_tasks_in_setup_project`.
- `test_seat_grant_vetting` — apply (pending) → grant → accept → revoke.
- `test_task_rich_schema` — create with priority/labels/checklist/deps/parent/DoD; PATCH edits; filters.
- `test_dependency_blocks_progress` — blocked task can't go in_progress until blocker done.
- `test_artifact_file_requires_content_and_link_requires_uri` — file without `content_b64` → 400;
  file with → stored in MinIO, downloadable; link without `uri` → 400; link with → ok.
- `test_done_gate_requires_output` — in_review/done rejected (409) without a file/link artifact; ok after.
- `test_onboarding_manual_creates_project`.
- `test_workspace_agent_designation_adds_onboarder_skill`.

Frontend: typecheck + build; Playwright for Collaboration Room + nested tree in a follow-up.
