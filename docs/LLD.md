# Armarius — Low-Level Design (LLD)

> Status: **Design draft** (2026-06-26). Build-level detail for the wave described in
> `HLD.md` / `API_CONTRACT.md`. All paths are relative to repo root. References to existing code
> cite `file:line` as of the `94d6f9e` commit.

---

## 1. File map (what changes)

### Backend
| Area | File(s) | Change |
|---|---|---|
| Entities | `domain/entities/{workspace,project(→split),role,seat_grant,task,task_participant,checklist_item,task_dependency,label,onboarding_session,artifact}.py` | Add new entities; extend Project/Task/Workspace/Artifact. |
| Use cases | `application/use_cases/{workspaces,projects(NEW),roster(NEW),tasks,onboarding(extend),artifacts,participants(NEW)}.py` | New services; extend task/artifact/onboarding. |
| Repos | `infrastructure/repositories/*.py` + `domain/repositories/*.py` (ports) | New repos for roles/grants/labels/participants/checklist/deps/onboarding. |
| ORM | `infrastructure/database/models.py` | New `*Model` classes; new columns. |
| Migrations | `alembic/` (NEW) + `alembic.ini` + env wiring | Introduce Alembic. |
| Artifact store | `infrastructure/artifacts/store.py` (NEW) + `domain/services/artifact_store.py` (port) | FS-backed store. |
| Schemas | `presentation/schemas.py` | New/changed pydantic schemas. |
| API | `presentation/api/{workspaces,projects(NEW),tasks,agent,artifacts}.py` | New routers; changed task/artifact endpoints. |
| Builtins | `application/use_cases/skills.py` + `static/skills/armarius-onboarder/SKILL.md` (NEW) | Add onboarder builtin. |
| Config | `config.py` (Settings) | `ARTIFACT_STORE_DIR`, `WORKSPACE_AGENT_SKILL_*`. |

### Frontend
| Area | File(s) | Change |
|---|---|---|
| Routing | `App.tsx` | Insert project layer routes. |
| Pages | `pages/{ProjectLanding(NEW),ProjectBoard(NEW),Onboarding(NEW),SkillEditor,Directory,Board→folds into ProjectBoard,Room→CollaborationRoom}.tsx` | New + rework. |
| Components | `components/{RosterPanel,ParticipantBar,Checklist,NestedFileTree,SeatDialog}.tsx` (NEW) | New building blocks. |
| API | `api.ts` | New endpoints. |
| i18n | `i18n.tsx` | New keys (EN/VI) for projects/roles/onboarding/collaboration. |

---

## 2. Domain entities (field-level)

### 2.1 Workspace — extend
```python
@dataclass
class Workspace:
    id: UUID
    name: str
    slug: str
    owner_user_id: str | None
    workspace_agent_id: UUID | None = None   # NEW: designated Workspace Agent (FK Marius)
    created_at / updated_at
```

### 2.2 Project — extend (split out of `workspace.py`)
```python
class ProjectStatus(str, Enum):
    SETUP = "setup"; ACTIVE = "active"; ARCHIVED = "archived"

@dataclass
class Project:
    id: UUID
    workspace_id: UUID
    name: str; slug: str; description: str | None
    objective: str | None                     # NEW
    success_metrics: dict | None              # NEW (JSON)
    target_date: datetime | None              # NEW
    context: str | None                       # NEW (patron-pasted free text)
    settings: dict                            # NEW (JSON): require_review_before_done, require_approval_for_done, comment_required_for_review
    status: ProjectStatus = ProjectStatus.SETUP  # NEW
    created_by_user_id: str | None
    created_at / updated_at
```
`ensure_default_project` / `ensure_personal_workspace` **stop creating "General"**. `ensure_personal_workspace`
keeps seeding builtin skills only.

### 2.3 Role (seat definition) — NEW
```python
@dataclass
class Role:
    id: UUID
    project_id: UUID
    key: str           # stable slug, e.g. "backend", "leader"
    title: str         # "Backend"
    seats: int         # seat count
    is_leader: bool = False
    description: str = ""
    created_at: datetime
```
Constraint (enforced in `ProjectService.create`): exactly one role has `is_leader and seats>=1`;
≥1 other role has `seats>=1`.

### 2.4 SeatGrant — NEW
```python
@dataclass
class SeatGrant:
    id: UUID
    project_id: UUID
    role_key: str
    marius_id: UUID
    status: str        # "pending" (applicant) | "granted" | "revoked"
    granted_at: datetime | None
    created_at: datetime
```
`grant` sets status `granted`; filling the leader seat flips `Project.status → active`.

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
    priority: TaskPriority = TaskPriority.MEDIUM  # NEW
    parent_id: UUID | None = None             # NEW: subtask
    due_date: datetime | None = None          # NEW
    definition_of_done: str | None = None     # NEW
    # assigned_marius_id kept for back-compat; superseded by TaskParticipant (primary)
```
New relations: `labels` (M2M via `task_labels`), `checklist` (O2M), `dependencies` (blocked_by via
`task_dependencies`), `participants` (O2M).

### 2.7 TaskParticipant — NEW
```python
@dataclass
class TaskParticipant:
    id: UUID; task_id: UUID; marius_id: UUID
    is_primary: bool = False   # the "assignee" for back-compat display
    joined_at: datetime
    unique (task_id, marius_id)
```
Wake (§API 5.2) targets any participant. The old single-assign wake becomes "wake primary" by default.

### 2.8 ChecklistItem — NEW
```python
@dataclass
class ChecklistItem:
    id: UUID; task_id: UUID; text: str; done: bool = False; order: int
```
Lightweight on-task todos (distinct from subtask *issues* via `parent_id`).

### 2.9 TaskDependency — NEW
```python
@dataclass
class TaskDependency:
    task_id: UUID          # the blocked task
    blocks_task_id: UUID   # the task it's waiting on
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
    collected: dict          # accumulating plan: name/objective/roles[]/context/…
    created_project_id: UUID | None
    created_at / updated_at
```

### 2.11 Artifact — extend (content now server-stored)
```python
@dataclass
class Artifact:
    # existing: id, project_id, task_id, marius_id, name, kind, uri, content_sha256, size_bytes, created_at
    stored: bool = True   # NEW: True ⇒ bytes live in the Shared Store
```
`publish(kind=file|patch)` requires `content_b64`; the service decodes, verifies sha256, writes bytes
via `ArtifactStore`, sets `stored=True` and `uri` to the store-relative path. `kind=link|note` may
have `stored=False`.

---

## 3. State machines

### 3.1 Project
```
setup ──(leader seat granted)──► active ──(archive)──► archived
```
Tasks may be commissioned only while `active`.

### 3.2 Task (status) — keep existing transitions, tighten the DONE gate
Existing map (`task.py:32-54`) is preserved. **Addition**: transition into `in_review` or `done` is
rejected (`409`) unless the task has ≥1 artifact with `kind in {file,patch}` and `stored=True`.
**Addition**: if a task has unmet `blocked_by` dependencies, transitioning to `todo`/`in_progress`
is rejected (`409`) — it must stay `backlog`/`blocked` until blockers are `done`.

### 3.3 SeatGrant
```
pending(applicant) ──(grant)──► granted ──(revoke)──► revoked
```

---

## 4. Use-case logic (key methods)

```python
# ProjectService
async def create(self, ws_id, *, name, description, mode, objective, success_metrics,
                 target_date, context, roles: list[RoleIn], settings) -> Project:
    validate_roles(roles)           # exactly one leader seat≥1; ≥1 worker seat≥1 (hard rule)
    project = Project(status=SETUP, ...)
    persist project + roles
    if mode == "agent": link onboarding_session.collected
    return project

async def grant_seat(self, project_id, marius_id, role_key) -> SeatGrant:
    ensure seat not full (count granted < role.seats)
    grant; add marius as project participant
    if role.is_leader and first leader grant: project.status = ACTIVE
    return grant

# TaskService
async def create(self, project_id, *, title, description, priority, label_ids,
                 parent_id, blocked_by, checklist, definition_of_done, due_date) -> Task:
    assert project.status == ACTIVE       # cannot commission into a setup project
    assign identifier (project-scoped seq)
    persist + link labels/checklist/deps/participants
async def transition(self, task_id, to_status, actor) -> Task:
    if to_status in {IN_REVIEW, DONE}: require_stored_output(task_id)   # §5.3 gate
    if to_status in {TODO, IN_PROGRESS}: assert_dependencies_met(task_id)
    apply existing allowed-transition check
async def add_participant(self, task_id, marius_id) -> wakes marius with task context

# ArtifactService
async def publish(self, task_id, marius_id, *, name, kind, content_b64=None, uri=None,
                  content_sha256=None, size_bytes=None) -> Artifact:
    if kind in {FILE, PATCH}:
        if not content_b64: raise ValueError("content required for file/patch artifacts")
        raw = b64decode(content_b64)
        if content_sha256: verify sha256(raw)==content_sha256
        rel = await self.store.write_bytes(raw, name)   # store assigns <sha>/<name>
        uri = rel; stored = True; size_bytes = len(raw)
    else:  # link/note
        stored = False
    persist Artifact(...)
```

`require_stored_output(task)` ⇒ `any(a.kind in {FILE,PATCH} and a.stored for a in artifacts)`.

---

## 5. Database / migrations (introduce Alembic)

Today: no migrations; `create_all()` on startup. That cannot add columns to existing tables, so the
schema deltas in §2 would silently no-op on an existing DB.

**Plan**:
1. Add `alembic` to deps; `alembic init alembic` (async template pointing at `DATABASE_URL`).
2. `env.py` imports `infrastructure.database.models.Base.metadata` for `target_metadata`.
3. Baseline migration `0001_baseline` stamps the **current** schema (autogenerate against existing
   models) with `stamp` on existing DBs — no data move.
4. `0002_projects_roster_tasks` adds: `projects.status/objective/success_metrics/target_date/context/
   settings`, `workspaces.workspace_agent_id`, `roles`, `seat_grants`, `labels`, `task_labels`,
   `tasks.identifier/priority/parent_id/due_date/definition_of_done`, `task_participants`,
   `checklist_items`, `task_dependencies`, `artifacts.stored`. All `ADD COLUMN … NULL` / new tables —
   non-destructive, backfills defaults.
5. Seed migration step: insert `armarius-onboarder` builtin skill row into existing workspaces
   (idempotent, like the existing `seed_builtins`).
6. Local dev: `alembic upgrade head`; CI runs migrations against a fresh Postgres.

`create_all()` is kept **only** for the very first bootstrap of an empty DB; thereafter Alembic owns
the schema.

---

## 6. Shared Artifact Store (infra)

```python
# domain/services/artifact_store.py — port (protocol)
class ArtifactStore(Protocol):
    async def write_bytes(self, raw: bytes, name: str) -> str: ...   # returns store-relative path
    async def read_bytes(self, rel: str) -> bytes: ...
    async def open_stream(self, rel: str) -> AsyncIterator[bytes]: ...

# infrastructure/artifacts/store.py — FS impl
class FsArtifactStore:
    def __init__(self, root: Path): self.root = root
    # write_bytes: sha = sha256(raw); path = root/sha[:2]/sha/name; mkdir parents; write; return rel
    # read/open_stream: resolve root/rel, stream
```
- Config: `ARTIFACT_STORE_DIR` (default `./artifact-store`; Docker mounts a volume).
- Content path is content-addressed (`sha256`), so identical re-publishes are cheap and dedup'd.
- Download endpoint streams via `open_stream` with the right content-type by `kind`/`name` ext.

---

## 7. Frontend — components & pages

### 7.1 Nested file tree (`components/NestedFileTree.tsx`) — replaces flat list in SkillEditor/preview
- Build a tree from the flat `files: {path: content}` map: split each path on `/`.
- Node render: folder = chevron `▸/▾` + name (collapsible, state in component state); file = icon +
  name; click file selects it for the editor.
- Actions: on a folder → "New file here" (prefills `<folder>/`), "New folder" (creates a marker —
  represented implicitly by a path), "Delete folder" (removes all `folder/*` keys after confirm). On
  root → same. SKILL.md pinned at top.
- Collapse state persisted to `localStorage` per skill id.
- Preview modal (`Skills.tsx`) reuses `NestedFileTree` in read-only mode (select to view content on
  the right), replacing the single-`<pre>` blob.

### 7.2 Project landing (`pages/ProjectLanding.tsx`) — `route /workspaces/{ws}`
- Header: workspace name + "designate Workspace Agent" control (opens a picker from the directory;
  shows current designee + badge).
- Grid of project cards: name, status (`setup`/`active`), roster fill (`leader ✓ · backend 1/2`),
  task counts. Empty state CTA → "New project".
- "New project" button → onboarding modal (§7.3).

### 7.3 Onboarding modal (`components/ProjectOnboardingModal.tsx`)
- Mode toggle: **Manual** | **Agent** (Agent disabled if no Workspace Agent designated, with a hint).
- **Manual**: a single scrolling form — name, objective, target_date, context; a **roles editor**
  (repeatable rows: title, seats (number), description; one row marked `is_leader` — enforced to
  exactly one); settings toggles. The Create button is disabled until the hard rule passes; on
  submit, `POST /projects`. Success → navigate to the project board.
- **Agent**: opens the onboarding chat — a thread UI backed by `OnboardingSession`; the Workspace
  Agent posts questions, patron answers; a "Finalize" surfaces the collected plan for confirm →
  `POST …/finalize`. (Implemented in a later phase per DEV_PLAN.)

### 7.4 Project board (`pages/ProjectBoard.tsx`) — `route /workspaces/{ws}/projects/{p}`
- Existing `Board.tsx` kanban moves under the project. Columns unchanged (Backlog…Done).
- New: a **RosterPanel** (collapsible right rail or a tab) showing roles, seat fill, applicants to
  vet (grant/revoke), project participants.
- Commission task modal now collects the full schema (priority, labels, due_date, DoD, checklist
  seed, parent, blocked_by) — not just title/description.
- Clicking a card → Collaboration Room (§7.5).

### 7.5 Collaboration Room (`pages/CollaborationRoom.tsx`, reworks `Room.tsx`)
Keep the 3-column skeleton but realign to the design's Collaboration view:
- **Left — Context**: editable title/description, **Definition of Done**, **Checklist** (add/toggle),
  status pill, priority, labels, due_date, dependencies (blocked-by pills), linked artifacts with a
  "publish to shared store" affordance.
- **Center — Thread**: the existing comment thread (@mentions, author kinds) + composer; this *is*
  the co-work surface. A **Participants bar** at the top shows who is on the task + "wake" per
  participant.
- **Right — Trace**: the existing live run trace (SSE) — retained (it's the "you trace" pillar and is
  in the design as "Live run trace").
- Publish flow: participant uploads file → stored artifact appears under "Linked artifacts" with a
  download link; status can then move to in_review/done (the gate is enforced server-side; the UI
  disables those transitions with a tooltip until a stored output exists).

### 7.6 Directory — add Workspace Agent badge
`Directory.tsx` shows a "Workspace Agent" badge on the designated Marius; the designation action also
lives here (or in ProjectLanding). Provisioning an agent unchanged.

---

## 8. i18n additions (EN/VI)

New key groups (all with both languages, via `t()`/`tEn()`):
- `project.*` — title, new, status.setup/active/archived, roster, roles, seats, leader, worker, grant, revoke, applicant, vetting, context, objective, targetDate, successMetrics, settings.*.
- `onboarding.*` — manual, agent, modeHint, finalize, needWorkspaceAgent, askGoal/askRoles/askContext.
- `task.*` — priority.*, checklist.*, definitionOfDone, dueDate, blockedBy, blocks, participant(s), wake, publishOutput, gateNeedOutput.
- `artifact.*` — sharedStore, publish, download, contentRequired, kind.file/patch/link/note.

No hardcoded display strings; reuse the audit pattern from the prior i18n pass.

---

## 9. Tests (backend, httpx)

- `test_project_requires_leader_and_worker_seats` — hard rule: missing leader → 422; missing worker → 422; valid → 201 setup.
- `test_project_activates_when_leader_seat_granted`; `test_no_tasks_in_setup_project`.
- `test_seat_grant_vetting` — apply (pending) → grant (granted) → revoke.
- `test_task_rich_schema` — create with priority/labels/checklist/deps/parent/DoD; PATCH edits; list filters.
- `test_dependency_blocks_progress` — blocked task cannot go in_progress until blocker done.
- `test_artifact_must_upload_content_for_file_kind` — `kind=file` without `content_b64` → 400; with → stored, downloadable.
- `test_done_gate_requires_stored_output` — in_review/done rejected (409) without a stored file/patch artifact; accepted after.
- `test_onboarding_manual_creates_project`; `test_onboarding_agent_finalize` (mock the workspace agent's calls).
- `test_workspace_agent_designation_adds_onboarder_skill`.

Frontend: typecheck + build (existing pipeline); consider Playwright for the Collaboration Room + nested tree in a follow-up.
