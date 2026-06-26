# Armarius — Development Plan

> Status: **Design draft v2** (2026-06-26). Sequencing for the wave in [HLD.md](./HLD.md) /
> [LLD.md](./LLD.md) / [API_CONTRACT.md](./API_CONTRACT.md). Phases ship in order; each ships green
> and commits to `main`. Phase **G trails last** (optional nice-to-have); the main flow is **A→F**.

## The four user asks map here
- **Skill nested tree** → Phase B (frontend-only).
- **Multi-project + onboarding** → Phases C (project/roster) + D (manual onboarding + Workspace Agent).
- **Rich task schema (Paperclip) + Output-Artifact gate** → Phase E.
- **Collaboration Room task detail** → Phase F.
- **Agent-assisted onboarding** → Phase G (last).

## Resolved decisions (from the owner)
1. **Hard rule (Phase C)**: a project declares exactly **one Project Leader** (`seats = 1`, pick an
   existing agent **or leave empty** for later) + a `responsibilities` field (default leader behavior
   TBC), and **≥1 worker role** with name/description/optional skills/seat count. The project goes
   `active` only when **all** seats are filled **and acknowledged** (agent came online + accepted).
2. **DONE-gate (Phase E)**: supported artifact kinds are **`file`** (upload content → MinIO) and
   **`link`** (external URL); DONE requires ≥1 file/link. `patch`/`note` dropped.
3. **Phase G (agent onboarding)** is **last** — manual is the priority path; the main flow must run first.
4. **Add**: project `github_url` (optional); **MinIO** as the Shared Store (bucket `armarius`) holding
   artifacts **and media** (agent avatars). The store **follows the project**: one folder per project
   (`<project-slug>/`), each task with output writes under it (`<project-slug>/<task-id-or-slug>/<name>`);
   media under `_media/`.
5. **`setup` vs `active`**: the **only** behavioral difference is **task assignment** — tasks are
   assignable only when `active`; the board/roster/vetting all work in `setup`.

## Rules
- Clean Architecture: domain pure; new behavior = new use-case + repo (+ entity if needed).
- Each phase: backend `pytest` green, `ruff` clean; frontend `tsc --noEmit` + `vite build` clean.
- Each phase: update `ROADMAP.md` build-log + commit + push to `main`.
- i18n: every new string lands EN **and** VI in the same commit.
- After Phase A, all schema changes ship as Alembic revisions (autogenerate, review, never edit a stamped one).

---

## Phase A — Infra: Alembic + MinIO  *(blocks C, E)*
**Goal:** safe schema evolution + the object store, ready before they're needed. No app behavior.
- Add `alembic`; `alembic init alembic` (async `env.py` → `DATABASE_URL`, `target_metadata`).
- Baseline `0001_baseline` = autogenerate of current models; `alembic stamp head` on existing DBs.
- Wire startup to `alembic upgrade head` (keep `create_all` only for empty bootstrap).
- **MinIO**: add `minio` service to `docker-compose.yml` + persistent volume; create bucket `armarius`
  on boot; per-project folders are logical prefixes (`<project-slug>/<task>/<name>`, media under
  `_media/`); add `MINIO_*` settings; `backend/README.md` note (run + make/apply migrations + MinIO).
**DoD:** fresh Postgres + existing SQLite both `upgrade head`; MinIO reachable, bucket `armarius`
exists; app boots; existing tests pass.

## Phase B — Skill nested file tree  *(no deps; frontend-only)*
**Goal:** imported/manual skills render as a VSCode/GitHub-style tree (add folder/file in structure).
- `components/NestedFileTree.tsx` — tree from flat `files` map; collapsible folders; SKILL.md pinned;
  collapse state in `localStorage`.
- Folder actions: new file here / new folder / delete folder. Rewire `pages/SkillEditor.tsx` (left =
  tree, right = editor; keep dirty/save).
- `pages/Skills.tsx` preview → reuse the tree read-only. i18n: `skill.newFolder/deleteFolder/emptyFolder`.
**DoD:** import `anthropics/skills/algorithmic-art` → collapsible `templates/`; add a file under it;
save persists; typecheck/build clean.

## Phase C — Project layer + roster (roles/seats)  *(deps: A)*
**Goal:** workspace holds many projects; project landing; create-project with a complete seat plan;
no auto "General".
- Domain/ORM/migration `0002a`: `Project` new fields + status; `Role`, `SeatGrant` (with `acknowledged`
  state); `Workspace.workspace_agent_id`.
- Remove auto-"General": `ensure_personal_workspace`/`register` stop creating the default project.
- `ProjectService`: `create` (validates hard rule: 1 leader `seats=1` + ≥1 worker role; leader may be
  empty), `grant_seat`, `accept_seat`, `revoke_seat`, `apply_seat`, role CRUD;
  `recompute_active()` → `active` only when all seats `acknowledged`.
- API: `projects.py` router (§API 3) + roster/grant/accept endpoints.
- Frontend: `pages/ProjectLanding.tsx` (project list + "New project"); insert `/workspaces/{ws}` route;
  `Board.tsx` → `pages/ProjectBoard.tsx` under `…/projects/{p}`; minimal create form (name + leader +
  worker roles + seats). Full onboarding UI is Phase D.
- Tests: `test_project_requires_leader_and_worker_roles`,
  `test_project_activates_only_when_all_seats_acknowledged`, `test_no_tasks_in_setup_project`,
  `test_seat_grant_vetting`. i18n: `project.*`, `role.*`.
**DoD:** new workspace lands on the project list (empty); create a project → `setup`; grant + accept
all seats → `active`; only then reach the board.

## Phase D — Manual onboarding + Workspace Agent designation  *(deps: C)*
**Goal:** full manual onboarding (goal, leader {pick-or-empty + responsibilities}, worker roles w/
counts + descriptions + optional skills, context, settings, github_url) + designate Workspace Agent.
- `components/ProjectOnboardingModal.tsx` replaces Phase C's minimal form (leader block + responsibilities +
  pick-or-empty; worker-roles editor with skills + counts; github_url; context; settings). Create
  disabled until the hard rule passes.
- Workspace Agent: `PUT /workspaces/{ws}/workspace-agent`; designation adds `armarius-onboarder`
  builtin to the marius's skills + rebuilds the invite prompt. Add
  `static/skills/armarius-onboarder/SKILL.md` (structured question script + `finalize`).
- Frontend: designate control in `ProjectLanding` + `Directory` badge; the "Agent" mode tab is
  disabled with a hint until a Workspace Agent exists (chat itself is Phase G).
- Tests: `test_workspace_agent_designation_adds_onboarder_skill`,
  `test_onboarding_manual_creates_project`. i18n: `onboarding.*` (manual side).
**DoD:** create a project via the full manual form (leader + 2 worker roles + counts + context +
github_url); designate a Marius as Workspace Agent (invite lists the onboarder skill install).

## Phase E — Rich task schema + Output-Artifact gate  *(deps: A, C)*
**Goal:** Paperclip-style task fields + the anti-local-output guarantee, backed by MinIO.
- **MinIO store**: `domain/services/artifact_store.py` port + `infrastructure/artifacts/store.py`
  (MinIO/S3); `MINIO_*` config; `GET /artifacts/{id}/content` stream; `POST /workspaces/{ws}/media`.
- **Artifact**: `publish(kind=file)` requires `content_b64` → decode/verify/`put_object` under
  `<project-slug>/<task-id-or-slug>/<name>`/`stored=True`; `publish(kind=link)` requires `uri`. Kinds
  limited to file|link.
- Task fields / migration `0002c`: `identifier`, `priority`, `parent_id`, `due_date`,
  `definition_of_done`; `Label`, `task_labels`, `TaskParticipant`, `ChecklistItem`, `TaskDependency`.
- `TaskService`: `create` (project `active`; assign identifier), `transition` (DONE-gate +
  dependency-gate), participants add/remove + wake(participant), checklist/deps/labels helpers.
- API: `PATCH /tasks/{id}`, labels/participants/checklist endpoints, tightened `POST /tasks/{id}/status`.
- Tests: `test_task_rich_schema`, `test_dependency_blocks_progress`,
  `test_artifact_file_requires_content_and_link_requires_uri`, `test_done_gate_requires_output`.
  i18n: `task.priority.*`, `task.checklist.*`, `task.definitionOfDone`, `task.dueDate`, `task.blockedBy`,
  `task.publishOutput`, `task.gateNeedOutput`, `artifact.*`.
**DoD:** commission a task with priority+labels+checklist+DoD+deps; add participants; a participant
publishes a file (uploaded, downloadable from MinIO) and/or a link; DONE blocked (409) until a
file/link output exists; a blocked task can't go in_progress until its blocker is done.

## Phase F — Collaboration Room (task detail)  *(deps: E; frontend-led)*
**Goal:** task detail follows the design's Collaboration view — co-work thread + participants + trace + shared-store publish.
- Rework `pages/Room.tsx` → `pages/CollaborationRoom.tsx`:
  - **Left/Context**: editable title+desc, Definition of Done, Checklist (add/toggle),
    status/priority/labels/due/deps, linked artifacts + "publish to shared store".
  - **Center/Thread**: existing comment thread + composer + **Participants bar** (who's on the task,
    per-participant "wake").
  - **Right/Trace**: existing live run trace (SSE) — retained.
- Publish affordance: upload file → stored artifact card + download; transitions to in_review/done
  disabled with tooltip until a file/link output exists. i18n: `task.participants/wake/publishedToStore`.
**DoD:** open a task → see participants co-working in the thread, tick the checklist, watch the live
trace, publish a stored output, then move it to done; visually close to the design's Collaboration view.

## Phase G — Agent-assisted onboarding (chat)  *(deps: D; LAST, optional)*
**Goal:** the Workspace Agent runs OpenClaw-style project onboarding via a chat. Nice-to-have; only
after the main flow runs end-to-end.
- Domain/migration: `OnboardingSession` entity/repo/model.
- API: onboarding-session endpoints (§API 3.4); agent appends messages; `finalize` → `ProjectService.create`.
- Frontend: chat UI in the onboarding modal's Agent tab; transcript + collected-plan preview + Finalize.
- `armarius-onboarder SKILL.md`: concrete question script (goal → leader → worker roles → counts →
  context) + the `finalize` payload shape.
- Tests: `test_onboarding_agent_finalize` (drive session + finalize → project with correct roster).
**DoD:** with a designated Workspace Agent, start an onboarding chat, answer the agent, finalize → a
project is created with the agreed roster.

---

## Out of scope (carried forward)
- MCP server + MCP skill (standing issue).
- Full visual reflow of all pages to match `ARMARIUS Design/` pixel-for-pixel (after this wave lands).
- Drag-and-drop kanban + board grouping (Paperclip-style) — nice-to-have after F.
