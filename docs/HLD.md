# Armarius — High-Level Design (HLD)

> Status: **Design draft** (2026-06-26). Companion to `API_CONTRACT.md` (interface) and
> `LLD.md` (build detail). This doc covers **architecture, data model, and the key flows** changed
> by the "multi-project + onboarding + richer task + collaboration" wave.

---

## 1. System purpose & guiding principle

Armarius ("Agents Are MARIUS") is a provisioner for **cross-team autonomous-agent collaboration**.
A human **Patron** tasks; agents **collaborate**; the Patron **traces**. The north-star UX line,
lifted from the design file (`ARMARIUS Design/`), is:

> **"You task. They collaborate. You trace."**

Three design pillars follow from it:

1. **Multi-project workspaces.** A workspace is the Patron's workshop; it holds **many projects**,
   each a self-contained unit of work with its own **roster** (roles/seats) and onboarding.
2. **Collaboration is first-class.** A task is worked by **multiple participants** co-working in a
   messaging thread, not a lone assignee. The Patron watches a live **trace** of what agents do.
3. **Output always lands in the shared store.** The fatal failure of other multi-agent systems —
   *the agent finishes but leaves the output file locally* — is **structurally prevented**: a task
   cannot be marked done until its output artifact is published to the Shared Artifact Store.

---

## 2. Architecture (Clean Architecture — unchanged shape, new contents)

The layering is unchanged from the existing codebase; this wave adds entities/use-cases/schemas,
not new layers.

```
presentation/  (FastAPI routers + pydantic schemas)   ← API_CONTRACT.md lives here
application/   (use_cases: workspaces, projects,      ← new: roster, onboarding, participants
                tasks, skills, onboarding, artifacts)
domain/        (entities + value objects; pure)        ← new: Role/Seat, TaskParticipant,
                no I/O, no framework                    Checklist, Label, OnboardingSession
infrastructure/(SQLAlchemy models, repos, clock,       ← new: artifact store FS impl, Alembic
                artifact store)
```

Composition root (`presentation/container.py`) wires use-cases with repos. **Domain stays pure**;
all framework/IO in infrastructure; all HTTP in presentation.

**Stack**: Python 3.12 · FastAPI · SQLAlchemy 2 (async) · pydantic-settings · `uv` + ruff.
Local dev = SQLite + aiosqlite; Docker = Postgres. Frontend = React 18 + Vite + react-router,
self-contained i18n (EN/VI), nginx reverse-proxy with relative API URLs.

---

## 3. Data model (entities & relationships)

```
User 1──* Workspace *──1 (workspace_agent) Marius
Workspace 1──* Project *──* Role(seat) *──1 SeatGrant *──1 Marius
Workspace 1──* Label            │
Workspace 1──* Skill            *──1 Task *──1 TaskParticipant *──1 Marius
                               Task *──* Dependency(blocked_by)
OnboardingSession 1──1 Project  Task 1──* ChecklistItem
                                Task 1──* Artifact (Shared Store)
                                Task 1──* Comment   Task 1──* Run(Trace)
```

### 3.1 New / changed entities

| Entity | Status | Notes |
|---|---|---|
| **Workspace** | CHANGED | + `workspace_agent_id` (nullable FK→Marius). |
| **Project** | CHANGED | + `status` (`setup`/`active`/`archived`), `objective`, `success_metrics` (json), `target_date`, `context`, `settings` (json). Drops the "auto General" provisioning. |
| **Role** (seat definition) | NEW | `project_id`, `key`, `title`, `seats` (int), `is_leader` (bool), `description`. |
| **SeatGrant** | NEW | `project_id`, `role_key`, `marius_id`, `granted_at`. (An applicant is a pending grant.) |
| **Label** | NEW | `workspace_id`, `name`, `color`. |
| **Task** | CHANGED | + `identifier`, `priority`, `parent_id`, `due_date`, `definition_of_done`, + checklist/deps/labels as relations. `assigned_marius_id` superseded by participants. |
| **TaskParticipant** | NEW | `task_id`, `marius_id`, `joined_at`, `is_primary`. |
| **ChecklistItem** | NEW | `task_id`, `text`, `done`, `order`. |
| **TaskDependency** | NEW | `task_id` blocked_by `blocks_task_id`. |
| **OnboardingSession** | NEW | `workspace_id`, `status`, `transcript` (json messages), `collected` (json plan), `created_project_id`. |
| **Artifact** | CHANGED | content now **server-stored** for `file`/`patch` (see §6); `uri` is the store-relative path assigned by the store. |

> Entity field-level detail, enums, and constraints are in `LLD.md` §2.

### 3.2 The roster model (roles → seats → participants → tasks)

This is the backbone of "1 leader + N workers" and the user's "roles + worker counts":

1. A **project** declares **Roles** (e.g. `Project Leader` ×1, `Backend` ×2, `Frontend` ×1). One role
   is `is_leader`. **Creating a project requires this plan to be complete** (hard rule, HLD §5.2).
2. Agents **apply** for a seat; the Patron **vets & grants** it (`SeatGrant`). A granted agent is a
   **project participant**.
3. A project moves `setup → active` when its **leader seat** is granted.
4. A **task's participants** are drawn from the project's granted agents. Any participant can be
   woken to work the task (co-work).

This is exactly the *"Required roles · agents must qualify for a seat"* / *"Vet & grant seat"* /
*"Project roster"* language in the design file.

---

## 4. Key flows

### 4.1 Register → empty workspace → project landing

```
register ──► ensure_personal_workspace (named "Personal", seeds builtin skills)
          ──► [NO auto project] ──► UI lands on /workspaces/{ws} (project list / landing)
```

The Patron creates a project through onboarding (manual or agent-assisted). The board is reached
*inside* a project, not at workspace entry.

### 4.2 Create project — manual onboarding

```
Patron ─► "New project" modal (mode = manual)
        │  fills: name, objective, target_date, context,
        │         roles[] (title + seats + description, one is_leader),
        │         settings (review/approve gates)
        └─► POST /projects  ── validates hard composition rule ──► project status=setup (seats empty)
Patron invites/grants agents to seats ──► leader seat filled ──► project status=active
Patron commissions tasks (only while active)
```

### 4.3 Create project — agent-assisted onboarding (Workspace Agent)

```
Patron (once) ─► designates a Marius as Workspace Agent
              └─► that Marius gets armarius-onboarder skill install step (invite prompt lists it)
Patron ─► "New project" ▸ agent mode ─► starts an OnboardingSession
Workspace Agent asks structured questions (goal → roles → per-role counts → context)
              └─► patron answers in the chat
Workspace Agent ─► finalize ─► POST /projects (roles/plan) ─► project created (status=setup)
```

The agent-assisted path is the OpenClaw-style chat; the manual path is a form. Both converge on the
same `POST /projects` payload and the same hard composition rule. (Agent-assisted is a later phase —
see DEV_PLAN.)

### 4.4 Commission + collaborate + trace + publish

```
Patron ─► commission task (rich schema: priority/labels/checklist/DoD/due_date/parent/deps)
        └─► add participants (≥1 from project roster) ──► each is woken with task context
Participants co-work: comment thread (@mention), update status/next-action, tick checklist
        └─► Patron watches Live run trace (SSE: assistant deltas, tool calls, usage)
A participant publishes output ─► POST /artifact (content uploaded → Shared Store)
Task ─► in_review ─► Patron approves ─► done   (gated: no stored output ⇒ cannot leave in_progress)
```

The "You task / They collaborate / You trace" loop closes when the output is in the shared store.

---

## 5. Cross-cutting rules

### 5.1 Multi-tenancy
Every read/write is scoped to the caller's workspace (user JWT or agent token). Cross-workspace
access is 404. Projects/roles/labels/skills/tasks all carry `workspace_id` (directly or via
project/workspace). No shared data across workspaces.

### 5.2 Hard team-composition rule (at creation)
`POST /projects` rejects a plan that does not have **exactly one** `is_leader` role with `seats≥1`
**and** ≥1 non-leader role with `seats≥1`. This is the user's "Hard — chặn lúc tạo" decision:
the seat *plan* is enforced at creation (agents fill seats afterward via vetting).

### 5.3 The shared-store DONE gate (anti-local-output)
- An artifact of kind `file`/`patch` **must upload content** (`content_b64`); bytes are sha256-verified
  and written under `ARTIFACT_STORE_DIR`. A bare local `uri` is no longer accepted for these kinds.
- Status transition to `in_review` or `done` is **rejected (409)** unless the task has ≥1 stored
  `file`/`patch` artifact. This is the structural guarantee that output never stays local.

### 5.4 Leader vs participant permissions (mirrors OpenClaw `task_permission.py`)
- **Leader** may reassign participants, set status (subject to the gate), edit DoD/checklist.
- **Worker/participant** may update status of tasks they're on, comment, tick their checklist, and
  publish artifacts — but not change the roster or reassign peers.
- Patron overrides all.

### 5.5 i18n
All user-facing strings (incl. the Patron Inbox and onboarding) flow through the `t()`/`tEn()`
helpers with EN/VI dictionaries. No hardcoded display strings (per prior audit).

---

## 6. The Shared Artifact Store (component view)

```
agent ──POST /artifact {kind:file, content_b64}──► ArtifactService.publish
        ArtifactService: decode, verify sha256, ArtifactStore.write_bytes ──► ARTIFACT_STORE_DIR/<sha>/<name>
        Artifact row {uri: store-relative path, size, sha}
GET /artifacts/{id}/content ──► ArtifactStore.read_bytes ──► stream
```

`ArtifactStore` is an infrastructure port (`write_bytes/read_bytes`) with an FS implementation. This
keeps the domain pure (the domain reasons about an uploaded artifact; the store is IO). In Docker the
store is a mounted volume; locally a `./artifact-store/` dir.

---

## 7. Frontend structure (high level)

```
/workspaces                     outer launcher (full-screen, no app chrome)
/workspaces/{ws}                [NEW] project landing (list + create + workspace-agent designate)
/workspaces/{ws}/onboarding     [NEW] agent-assisted chat (modal/route)
/workspaces/{ws}/projects/{p}   [NEW] project board (tasks by status) + roster panel
/workspaces/{ws}/projects/{p}/tasks/{t}   [CHANGED] Collaboration Room (participants + thread + trace + artifacts + DoD/checklist)
/workspaces/{ws}/skills         skill shop (unchanged)
/workspaces/{ws}/skills/{id}    [CHANGED] nested file-tree editor
/workspaces/{ws}/directory      agent directory (add: workspace-agent badge)
/workspaces/{ws}/approvals      Patron Inbox (bilingual; unchanged surface)
```

The current routes use the **in-workspace Shell** (sidebar with a *back-to-launcher* button). The
project layer is inserted between the workspace and the board, matching OpenClaw's depth.

> The existing `ARMARIUS Design/Armarius.dc.html` is the visual north-star. The Collaboration Room
> in particular should follow its "Collaboration" view (participants roster + thread + trace +
> linked artifacts + "published to the shared store"). The current Room already has 3 of these; the
> redesign adds the participants roster + DoD/checklist + shared-store publish affordance.

---

## 8. What is explicitly OUT of scope for this wave

- MCP server + MCP skill (deferred to the standing GitHub issue).
- A full Alembic migration history retrofit beyond what this wave needs; we adopt Alembic **now** to
  ship the schema deltas in §3.1 safely (see LLD §5).
- Re-skinning every page to pixel-match `ARMARIUS Design/` (the user noted a later pass for that).
  This wave aligns **structure** (project layer, roster, collaboration room) to the design; the
  broader visual reflow is a follow-up.
