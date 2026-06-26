# Armarius — High-Level Design (HLD)

> Status: **Design draft v2** (2026-06-26). Companion to [API_CONTRACT.md](./API_CONTRACT.md)
> (interface) and [LLD.md](./LLD.md) (build detail); see [ARCHITECTURE.md](./ARCHITECTURE.md) for the
> visual, use-case-driven overview. This doc covers **architecture, data model, and key flows** for
> the "multi-project + onboarding + richer task + collaboration" wave.

---

## 1. Purpose & guiding principle

Armarius ("Agents Are MARIUS") is a provisioner for **cross-team autonomous-agent collaboration**.
A human **Patron** tasks; agents **collaborate**; the Patron **traces**. The north-star line, from
the design file (`ARMARIUS Design/`):

> **"You task. They collaborate. You trace."**

Three pillars:

1. **Multi-project workspaces.** A workspace holds **many projects**, each a self-contained unit of
   work with its own **roster** (roles/seats) and onboarding.
2. **Collaboration is first-class.** A task is worked by **multiple participants** co-working in a
   messaging thread; the Patron watches a live **trace**.
3. **Output always lands in the shared store.** The fatal failure of other multi-agent systems —
   *the agent finishes but leaves the output locally* — is **structurally prevented**: a task cannot
   be marked done until its output artifact is published to the Shared Artifact Store (MinIO).

---

## 2. Architecture (Clean Architecture — unchanged shape)

```
presentation/  FastAPI routers + pydantic schemas          ← API_CONTRACT.md
application/   use_cases: workspaces, projects, roster,    ← new: roster, onboarding, participants
                tasks, skills, onboarding, artifacts
domain/        entities + value objects (pure, no I/O)      ← new: Role/SeatGrant, TaskParticipant,
                                                            Checklist, Label, OnboardingSession
infrastructure/ SQLAlchemy models/repos, MinIO store,       ← new: MinIO artifact store, Alembic
                Alembic, clock
```

Composition root (`presentation/container.py`) wires use-cases with repos. **Domain stays pure**;
all framework/IO in infrastructure; all HTTP in presentation.

**Vendor-neutral runtime.** Armarius does not bind to one agent vendor. Every runtime is wrapped in a
single bounded `MariusAdapter.execute(ctx)` contract (`application/ports/adapter.py`); the
`AdapterRegistry` resolves a Marius's `adapter_type` to its implementation
(`hermes_gateway` — reference/verified, `openclaw_gateway`, `claude_local`, `echo` for tests). The
wake engine **owns the wake loop** and always drives the runtime **through an adapter → that runtime's
gateway**, never calling a gateway directly. See [ARCHITECTURE.md](./ARCHITECTURE.md) §2.

**Stack**: Python 3.12 · FastAPI · SQLAlchemy 2 (async) · pydantic-settings · `uv` + ruff. Local
dev = SQLite + aiosqlite; Docker = Postgres + **MinIO** (artifact/media store, bucket `armarius`).
Frontend = React 18 + Vite + react-router, self-contained i18n (EN/VI), nginx reverse-proxy with
relative API URLs.

---

## 3. Data model

```
User 1──* Workspace *──1 (workspace_agent) Marius
Workspace 1──* Project *──* Role(seat) *──1 SeatGrant *──1 Marius
Workspace 1──* Label            │
Workspace 1──* Skill            *──1 Task *──1 TaskParticipant *──1 Marius
OnboardingSession 1──1 Project  Task *──* Dependency(blocked_by)
                                Task 1──* ChecklistItem
                                Task 1──* Artifact (Shared Store: MinIO)
                                Task 1──* Comment   Task 1──* Run(Trace)
```

### 3.1 New / changed entities

| Entity | Status | Notes |
|---|---|---|
| **Workspace** | CHANGED | + `workspace_agent_id` (nullable FK→Marius). |
| **Project** | CHANGED | + `status` (`setup`/`active`/`archived`), `objective`, `success_metrics` (json), `target_date`, `context`, **`github_url`** (optional), `settings` (json). Drops auto-"General". |
| **Role** (seat definition) | NEW | `project_id`, `key`, `title`, `seats` (int; **leader always 1**), `is_leader`, `description`, `responsibilities` (leader), `skill_ids` (optional). |
| **SeatGrant** | NEW | `project_id`, `role_key`, `marius_id`, `status` (`pending`→`granted`→`acknowledged`→`revoked`), granted/acknowledged timestamps. |
| **Label** | NEW | `workspace_id`, `name`, `color`. |
| **Task** | CHANGED | + `identifier`, `priority`, `parent_id`, `due_date`, `definition_of_done`; + checklist/deps/labels relations. `assigned_marius_id` superseded by participants. |
| **TaskParticipant** | NEW | `task_id`, `marius_id`, `joined_at`, `is_primary`. |
| **ChecklistItem** | NEW | `task_id`, `text`, `done`, `order`. |
| **TaskDependency** | NEW | `task_id` blocked_by `blocks_task_id`. |
| **OnboardingSession** | NEW | `workspace_id`, `status`, `transcript`, `collected`, `created_project_id`. |
| **Artifact** | CHANGED | kinds narrowed to **`file` \| `link`**; `file` content **stored in MinIO** (bucket `armarius`); `link` carries an external `uri`. |

> Field-level detail, enums, constraints: [LLD.md](./LLD.md) §2.

### 3.2 The roster model (roles → seats → participants → tasks)

The backbone of "1 leader + N workers" and the user's "roles + worker counts":

1. A **project** declares **Roles** (e.g. `Project Leader` ×1, `Backend` ×2, `Frontend` ×1). Exactly
   one role is the **Project Leader** (`seats = 1`). Worker roles carry an optional `description`,
   optional `skill_ids`, and a seat count. **Creating a project requires this plan to be complete**
   (hard rule, §5.2).
2. The leader's agent may be **chosen now** (existing workspace agent) or **left empty** for later;
   worker seats may likewise be pre-seated or left empty.
3. Agents **apply**; the Patron **vets & grants** (`granted`); the agent **accepts** (`acknowledged`
   — came online + accepted the seat). A granted agent is a **project participant**.
4. The project moves `setup → active` **only when every seat is filled and acknowledged**.
5. A **task's participants** are drawn from the project's granted agents; any participant can be
   woken to co-work the task.

This is the *"Required roles · agents must qualify for a seat"* / *"Vet & grant seat"* /
*"Project roster"* language in the design file.

---

## 4. Key flows

### 4.1 Register → empty workspace → project landing

```
register ──► ensure_personal_workspace (named "Personal", seeds builtin skills)
          ──► [NO auto project] ──► lands on /workspaces/{ws} (project list / landing)
```

### 4.2 Create project — manual onboarding

```
Patron ─► "New project" (mode = manual)
        │  name, objective, target_date, github_url(optional), context,
        │  leader {responsibilities, pick-existing-agent | leave-empty},
        │  worker roles[] {title, seats, description, skills(optional)},
        │  settings
        └─► POST /projects ── validates hard rule ──► project status=setup
                              (supplied agents pre-seated as granted; rest empty)
Agents accept seats (online + ack) ──► ALL seats filled+acknowledged ──► status=active
Patron commissions tasks (only while active)
```

### 4.3 Create project — agent-assisted onboarding (Workspace Agent) — *Phase G, last*

```
Patron (once) ─► designates a Marius as Workspace Agent
              └─► that Marius gets armarius-onboarder skill install step
Patron ─► "New project" ▸ agent mode ─► starts an OnboardingSession
Workspace Agent asks structured questions (goal → leader → worker roles → counts → context)
              └─► patron answers in the chat
Workspace Agent ─► finalize ─► POST /projects ─► project created (status=setup)
```

### 4.4 Commission + collaborate + trace + publish

```
Patron ─► commission task (priority/labels/checklist/DoD/due_date/parent/deps; project must be active)
        └─► add participants (≥1 from roster) ──► each woken with task context
Participants co-work: comment thread (@mention), update status/next-action, tick checklist
        └─► Patron watches Live run trace (SSE: deltas, tool calls, usage)
A participant publishes output ─► POST /artifact
        ├─ file  → content uploaded, sha256-verified, stored in MinIO
        └─ link  → external URL (a merged PR)
Task ─► in_review ─► Patron approves ─► done   (gate: no file/link output ⇒ cannot leave in_progress)
```

---

## 5. Cross-cutting rules

### 5.1 Multi-tenancy
Every read/write is scoped to the caller's workspace. Cross-workspace access is 404. Projects,
roles, labels, skills, tasks all carry `workspace_id` (directly or transitively). No shared data.

### 5.2 Hard team-composition rule (at creation)
`POST /projects` rejects a plan without **exactly one** Project Leader (`seats = 1`) **and** ≥1 worker
role with `seats ≥ 1`. The leader's agent may be chosen now or left empty. The seat *plan* is
enforced at creation; agents fill seats afterward, and the project only goes `active` once **all**
seats are granted **and acknowledged** (§3.2).

**The only behavioral difference between `setup` and `active` is task assignment.** In `setup` the
Patron can do everything else — view the board, build/edit the roster, vet and grant seats — but
**tasks may be commissioned/assigned only when the project is `active`** (all seats acknowledged).

### 5.3 The shared-store DONE gate (anti-local-output)
- An artifact of kind **`file`** must **upload content** (`content_b64`); bytes are sha256-verified
  and written to the MinIO bucket `armarius`. A bare local path is no longer accepted.
- A **`link`** artifact points at an external location (a merged PR, a deploy) — no upload.
- Transition to `in_review`/`done` is **rejected (409)** unless the task has ≥1 `file` or `link`
  artifact. Output never stays local.

### 5.4 Leader vs participant permissions (mirrors OpenClaw `task_permission.py`)
- **Leader** may reassign participants, set status (subject to the gate), edit DoD/checklist.
- **Worker/participant** may update status of tasks they're on, comment, tick their checklist,
  publish artifacts — but not change the roster or reassign peers.
- Patron overrides all.

### 5.5 i18n
All user-facing strings flow through `t()`/`tEn()` (EN/VI). No hardcoded display strings.

---

## 6. The Shared Artifact Store (MinIO)

```
agent ──POST /artifact {kind:file, content_b64}──► ArtifactService.publish
        ArtifactService: decode, verify sha256, ArtifactStore.put_object
            ──► MinIO bucket `armarius` @ <project-slug>/<task-id-or-slug>/<name>
        Artifact row {uri: object key, size, sha}
GET /artifacts/{id}/content ──► ArtifactStore.get_object ──► stream
POST /workspaces/{ws}/media  ──► ArtifactStore.put_object @ _media/avatars/…  (agent avatars, …)
```

`ArtifactStore` is an infrastructure port (`put_object`/`get_object`/`open_stream`) with an
**S3/MinIO** implementation (async client). In Docker, MinIO is a compose service with a persistent
volume; the bucket `armarius` is created on startup if absent.

**The store follows the project.** Each project owns a top-level folder in the bucket, provisioned at
project creation; each task that produces output writes under it, keyed by task id (or slug). Media
(agent avatars, …) lives apart under `_media/`:

```
armarius/                              (bucket)
├── <project-slug>/                    one folder per project (created at project creation)
│   └── <task-id-or-slug>/             one folder per task that produced output
│       ├── login-impl.txt             a file artifact (content-stored)
│       └── ...
└── _media/avatars/<marius_id>.<ext>   agent avatars and other media
```

So a `file` artifact for task `ARM-7` in project `acme-web` is written to
`armarius/acme-web/ARM-7/<name>`; `Artifact.uri` holds that object key.

---

## 7. Frontend structure

```
/workspaces                     outer launcher (full-screen, no app chrome)
/workspaces/{ws}                [NEW] project landing (list + create + designate Workspace Agent)
/workspaces/{ws}/onboarding     [NEW] agent-assisted chat (Phase G)
/workspaces/{ws}/projects/{p}   [NEW] project board (tasks by status) + roster panel
/workspaces/{ws}/projects/{p}/tasks/{t}   [CHANGED] Collaboration Room (participants + thread + trace + artifacts + DoD/checklist)
/workspaces/{ws}/skills         skill shop (unchanged)
/workspaces/{ws}/skills/{id}    [CHANGED] nested file-tree editor
/workspaces/{ws}/directory      agent directory (+ Workspace Agent badge)
/workspaces/{ws}/approvals      Patron Inbox (bilingual; surface unchanged)
```

The in-workspace Shell keeps the *back-to-launcher* button; the project layer is inserted between
the workspace and the board (OpenClaw depth). The existing `ARMARIUS Design/` is the visual
north-star; this wave aligns **structure** (project layer, roster, collaboration room) to it; a
broader pixel-match pass is a follow-up.

---

## 8. Scope & phasing (summary — see DEV_PLAN.md)

A) Alembic + MinIO · B) skill nested tree · C) project layer + roster · D) manual onboarding +
Workspace Agent designation · E) rich task + Output-Artifact gate · F) Collaboration Room ·
**G) agent-assisted onboarding (LAST, optional nice-to-have).** The main flow is A→F; G trails.

**Out of scope**: MCP server + skill (standing issue); full visual reflow to match the design
pixel-for-pixel; drag-and-drop kanban/grouping.
