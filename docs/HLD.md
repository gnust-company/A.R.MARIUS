> ⚠️ **ĐÃ LỖI THỜI (ARCHIVED).** Nguồn sự thật hiện tại là [`spec/`](../spec/) (tiếng Việt). Xem [docs/README.md](README.md).

# Armarius — High-Level Design (HLD)

> Status: **Design draft v3** (2026-06-27). Aligned with the approved [ARCHITECTURE.md](./ARCHITECTURE.md):
> enroll-and-wait invite, system-only seat grants, leader-mediated commission, a workspace-events SSE
> bus, and a recency-based liveness model. Companion to [API_CONTRACT.md](./API_CONTRACT.md) (interface)
> and [LLD.md](./LLD.md) (build detail); see [ARCHITECTURE.md](./ARCHITECTURE.md) for the visual,
> use-case-driven overview. This doc covers **architecture, data model, and key flows** for the
> "multi-project + onboarding + richer task + collaboration" wave.

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

**Two SSE channels, both server→browser (Hybrid).** Both are **Web-App-only** — agents never read SSE.
(1) The **workspace control-plane stream** (`GET /v1/workspaces/{ws}/events`) is **always-on**: the
browser holds it open and the backend pushes light events that belong to no single task —
liveness/status/approval/commission-preview/`project.active`/`task.created`. (2) A **per-task trace
stream** (`GET /v1/tasks/{task_id}/stream`) is opened **only while a Collaboration Room is on screen**
and carries that task's heavy live run trace (`run.delta`/`run.tool`/`run.usage`), teed by the adapter
through the wake engine. Keeping the trace off the always-on stream means the browser never downloads
every agent's trace at once. See [ARCHITECTURE.md](./ARCHITECTURE.md) §1 and §5.7.

**Liveness is recency, not a flag.** "Online" means *a signal was received recently*. The backend
**probes** an idle agent (a light "reply OK" turn in a throwaway session) — the agent never self-reports,
so there is **no heartbeat endpoint**; incidental agent calls (`/agent/me`, a task response) count as
signals too. Silence decays ONLINE → CHECKING → OFFLINE (probed 3×), and OFFLINE re-probes on a timeout
that **doubles each failed cycle**; **any signal resets everything**. This is what lets activation key
off "online" without a separate ack handshake. Full model: [ARCHITECTURE.md](./ARCHITECTURE.md) §5;
timers in [LLD.md](./LLD.md) §10.

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
Workspace 1──* OnboardingSession 1──0..1 Project   (a session creates 0 or 1 project)
Project 1──* CommissionSession 1──1 Task(draft)    Task *──* Dependency(blocked_by)
                                Task 1──* ChecklistItem
                                Task 1──* Artifact (Shared Store: MinIO)
                                Task 1──* Comment   Task 1──* Run(Trace)
```

### 3.1 New / changed entities

| Entity | Status | Notes |
|---|---|---|
| **Workspace** | CHANGED | + `workspace_agent_id` (nullable FK→Marius). |
| **Marius** | CHANGED | + `invite_status` (`invited`/`pending_review`/`approved`/`revoked`), `enrollment_code`, `approved_at`; liveness timers `probe_attempts`, `backoff_step`, `next_probe_at`, `offline_since`. **`agent_token` minted once on approve** (not at invite). `adapter_type` locked after approve. |
| **Project** | CHANGED | + `status` (`setup`/`active`/`archived`), `objective`, `success_metrics` (json), `target_date`, `context`, **`github_url`** (optional), `settings` (json). Drops auto-"General". |
| **Role** (seat definition) | NEW | `project_id`, `key`, `title`, `seats` (int; **leader always 1**), `is_leader`, `description`, `responsibilities` (leader), `skill_ids` (optional). |
| **SeatGrant** | NEW | `project_id`, `role_key`, `marius_id`, `status` (`granted`→`revoked`), `granted_at`. **System-only** — agents never apply; there is no accept step (activation keys off liveness instead). |
| **Label** | NEW | `workspace_id`, `name`, `color`. |
| **Task** | CHANGED | + `identifier`, `priority`, `parent_id`, `due_date`, `definition_of_done`; + checklist/deps/labels relations. `assigned_marius_id` superseded by participants. |
| **TaskParticipant** | NEW | `task_id`, `marius_id`, `joined_at`, `is_primary`. |
| **ChecklistItem** | NEW | `task_id`, `text`, `done`, `order`. |
| **TaskDependency** | NEW | `task_id` blocked_by `blocks_task_id`. |
| **OnboardingSession** | NEW | `workspace_id`, `status`, `transcript`, `collected`, `created_project_id`. |
| **CommissionSession** | NEW | `project_id`, `leader_marius_id`, `task_id` (draft or existing task), `session_params`, `transcript`, `status` (`open`/`confirmed`/`abandoned`), `leader_state` (`thinking`/`waiting`/`leader_offline`). Leader-mediated task authoring (§5.3 API). |
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
3. The Patron **grants** agents into seats — a **system-only** action (no agent applies, no accept
   step). A granted agent is a **project participant**. The agent is contacted **only** if its new role
   carries skills it must install; that install is **queued** if the agent is offline and resumes on its
   next signal.
4. The project moves `setup → active` **once**, when **every seat is granted *and* every seated agent is
   ONLINE** (liveness reused from the invite handshake). It **stays active** — a worker going offline
   later does not roll it back.
5. A **task's participants** are picked by the Project Leader during commission (§4.4); any participant
   can be woken to co-work the task.

---

## 4. Key flows

### 4.1 Register → empty workspace → project landing

```
register ──► ensure_personal_workspace (named "Personal", seeds builtin skills)
          ──► [NO auto project] ──► lands on /workspaces/{ws} (project list / landing)
```

### 4.2 Invite agents, then create a project — manual onboarding

```
Invite (UC2, enroll-and-wait):
Patron ─► "Add agent" (choose adapter type only; name, role, skills[])
        └─► POST /mariuses ── Marius status=invited + enrollment_code (NO token printed)
Agent  ─► POST /agent/enroll (code) ── held open ── status=pending_review
Patron ─► approve ── mint agent_token ONCE, returned AS the enroll response
Agent  ─► store token, install skill file-trees, GET /agent/me ── ONLINE + SSE marius.online

Create project (manual):
Patron ─► "New project" (mode = manual)
        │  name, objective, target_date, github_url(optional), context,
        │  leader {responsibilities, pick-existing-agent | leave-empty},
        │  worker roles[] {title, seats, description, skills(optional)},
        │  settings
        └─► POST /projects ── validates hard rule ──► project status=setup
                              (supplied agents pre-seated as granted; rest empty)
Patron grants seats (system-only) ── role-skill install queued if agent offline
ALL seats granted + seated agents ONLINE ──► status=active  (once; stays active)
Patron commissions tasks through the Leader (only while active) ── §4.4
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

### 4.4 Commission (through the Leader) + collaborate + trace + publish

```
Commission (no manual form — a chat with the Project Leader):
Patron ─► "Commission task" (project must be active) ─► opens a chat to the Leader
Patron ─► POST /projects/P/commission {message}
Backend ─► wake Leader in a FRESH session (ctx = project + roster + workers)
Leader  ─► analyze / ask if >1 option / break down / fill ALL fields / pick workers ─► preview (Task draft)
Patron  ─► refine (resume Leader session)  OR  confirm ─► Task draft→todo, wake chosen workers
Participants co-work: comment thread (@mention), update status/next-action, tick checklist
        └─► Patron watches Live run trace (per-task SSE /tasks/T/stream: deltas, tool calls, usage)
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
enforced at creation; seats are filled by the Patron **granting** agents afterward, and the project
goes `active` **once** when **all seats are granted *and* every seated agent is ONLINE** (§3.2).

**The only behavioral difference between `setup` and `active` is task commission.** In `setup` the
Patron can do everything else — view the board, build/edit the roster, grant seats — but **tasks may be
commissioned only when the project is `active`**, and only **through the Project Leader** (no manual
form, §4.4). Activation is reached once and **stays**: a worker going offline later does not roll the
project back to `setup`; it is an operational (wake/report) matter.

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

### 5.6 Liveness — "online" is recency + probe, not a sticky flag **[NEW]**
"Online" means **a signal was received recently**. The **deciding mechanism is a system probe**: when
an agent has been idle, the backend opens a **light throwaway session** asking it to reply "OK" — the
reply is a signal, then the session is discarded. The agent is **never required to self-report**, so
**there is no heartbeat endpoint**. Incidental calls the agent makes while working (comment, status,
`/agent/me`, the enroll reply) are *also* counted as signals — they reset the idle timer and let the
backend skip a probe. The backend watches the time since the **last signal** and probes on idle:

- **Idle timeout `T1`** → send a **light probe** ("reply OK" in a throwaway session); wait short `T2`.
- **Retry 3×** → no answer flips the agent to `CHECKING` (a "waking" display) for up to 3 probes.
- **OFFLINE** after all 3 fail; then a **retry timeout `R`** re-runs the whole probe loop, and **`R`
  doubles each failed cycle** (R → 2R → 4R, capped) so a busy agent or overloaded LLM isn't hammered.
- **Reset on any signal**: any contact — mid-probe, from OFFLINE, or a real task response — resets
  state to `ONLINE`, restarts the idle timer, and resets backoff to base `R`.
- A turn in flight ⇒ `WORKING`; a turn overrunning `hung_after` ⇒ `HUNG` (watchdog).

This is what makes activation robust: an agent invited today and never heard from again is **OFFLINE**
by the time a project is staffed weeks later — the UI never shows a stale ONLINE. Timer defaults
(`T1`, `T2`, `R`, `hung_after`, max-backoff cap) are pinned in [LLD.md](./LLD.md) §10. Full state
machine: [ARCHITECTURE.md](./ARCHITECTURE.md) §5.

### 5.7 SSE — two channels (Hybrid), push not polling **[NEW]**
**Channel 1 — workspace control-plane (always-on).** The Web App opens **one** `GET
/v1/workspaces/{ws}/events` on workspace mount and keeps it open. The backend pushes light events that
belong to no single task: `marius.online`, `marius.status_changed`, `marius.liveness`,
`seat.skills_installed`, `project.active`, `task.created`, `commission.*`, approvals. The UI needs these
even with no task on screen, so it is one persistent connection.

**Channel 2 — per-task trace (on demand).** When a Collaboration Room opens, the Web App also opens
`GET /v1/tasks/{task_id}/stream` for that task; it carries the heavy live run trace
(`run.delta`/`run.tool`/`run.usage`) and is **closed when the room is left**. At most one is open (the
focused task). `Last-Event-ID` is honored for resume on both channels.

Both channels are **Web-App-only** — agents never use SSE (they use request/response + adapter wakes);
so any `API → SSE → WEB` step is the backend telling the UI about a change the UI did not itself
trigger.

**Why split (Hybrid), and how it relates to sessions.** Control-plane events must arrive even with no
room open, while a task's trace is only interesting while you watch it; keeping the trace off the
always-on stream means the browser never downloads every agent's trace at once. The browser therefore
holds **one** always-on connection plus **at most one** trace connection. This is **not** the same as
the agent runtime session: the backend↔agent side still runs **one session per task/run** (unchanged);
the wake engine **tees** that session's streamed events onto the task's trace channel. So "two browser
SSE channels" and "one runtime session per task" are different layers and do not conflict.

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

## 8. Scope & phasing (summary — see ../SPRINT_PLAN.md)

A) Alembic + MinIO · B) skill nested tree · C) project layer + roster · D) manual onboarding +
Workspace Agent designation · E) rich task + Output-Artifact gate · F) Collaboration Room ·
**G) agent-assisted onboarding (LAST, optional nice-to-have).** The main flow is A→F; G trails.

**Out of scope**: MCP server + skill (standing issue); full visual reflow to match the design
pixel-for-pixel; drag-and-drop kanban/grouping.
