# Armarius — Development Plan

> Status: **Design draft** (2026-06-26). Sequencing for the wave defined in
> `HLD.md` / `LLD.md` / `API_CONTRACT.md`. Phases are ordered for **independent value** + minimal
> rework: each phase ships, tests green, commits to `main`. Dependencies are called out explicitly.
>
> The four user asks map here:
> - **Skill nested tree** → Phase B (frontend-only).
> - **Multi-project + onboarding (manual leader+workers / agent)** → Phases C, D, E.
> - **Rich task schema (Paperclip-style) + Output-Artifact shared-store gate** → Phase F.
> - **Collaboration Room task detail** → Phase G.

---

## Guiding rules
- Clean Architecture: domain pure, no IO; new behavior = new use-case + repo + (optional) entity.
- Every phase: backend `pytest` green, `ruff` clean; frontend `tsc --noEmit` + `vite build` clean.
- Every phase: update `ROADMAP.md` build-log + commit + push to `main`.
- i18n: every new string lands EN **and** VI in the same commit.
- Migrations: after Phase A, **all** schema changes ship as Alembic revisions (autogenerate, review the diff, never edit a stamped migration).

---

## Phase A — Infra: introduce Alembic  *(blocks C, F)*
**Goal:** safe, additive schema evolution. No behavior change.
**Backend only.**
- Add `alembic` dep; `alembic init alembic` (async `env.py` → `DATABASE_URL`, `target_metadata = Base.metadata`).
- Baseline `0001_baseline` = autogenerate of **current** models; `alembic stamp head` on existing DBs.
- Wire `docker-compose`/startup to `alembic upgrade head` before app boot (keep `create_all` only for empty bootstrap).
- Doc note in `backend/README.md`: how to make/apply a migration.
**DoD:** fresh Postgres + existing SQLite both `upgrade head` cleanly; app boots; existing tests pass.

---

## Phase B — Skill nested file tree  *(no deps; frontend-only)*
**Goal:** the imported/manual skill shows as a VSCode/GitHub-style tree, not a flat list. Add folder/file within structure.
**Frontend only** (backend already stores `files: {path: content}`).
- `components/NestedFileTree.tsx` — build tree from flat map; collapsible folders; SKILL.md pinned; collapse state in `localStorage`.
- Folder actions: new file here / new folder / delete folder. File actions: select / delete. Add-file input prefills the parent path.
- Rewire `pages/SkillEditor.tsx` to use it (left pane = tree, right = editor). Keep dirty/save logic.
- `pages/Skills.tsx` preview → reuse tree in read-only (select to view content), replacing the single `<pre>`.
- i18n keys: `skill.newFolder`, `skill.deleteFolder`, `skill.emptyFolder`, …
**DoD:** import `anthropics/skills/algorithmic-art` → tree shows `templates/` collapsible with its files; add a file under `templates/`; save persists; typecheck/build clean.

---

## Phase C — Project layer + roster (roles/seats)  *(deps: A)*
**Goal:** workspace holds many projects; project landing; create-project with a complete seat plan; no auto "General".
- **Domain/ORM/migration `0002a`**: `Project` new fields + status enum; `Role`, `SeatGrant` entities/repos/models; `Workspace.workspace_agent_id`.
- Remove auto-"General": `ensure_personal_workspace`/`register` stop creating the default project; `ensure_default_project` deleted (or kept internal-only, unused).
- **ProjectService**: `create` (validates hard rule), `get`, `list`, `grant_seat`, `revoke_seat`, `apply_seat`, `add_role/update_role/remove_role`; status `setup→active` on leader grant.
- **API**: `projects.py` router (§API 3), `roster`/`grant` endpoints; `GET /workspaces/{ws}/projects`.
- **Frontend**: `pages/ProjectLanding.tsx` (project list + "New project"); insert `/workspaces/{ws}` route; `pages/Board.tsx` becomes `pages/ProjectBoard.tsx` under `/workspaces/{ws}/projects/{p}`; workspace shell routes updated.
- **Frontend**: `components/RosterPanel.tsx`, roles editor in the create modal (Phase D ships the modal; here ship a minimal create form: name + roles[] + seats + leader flag).
- Tests: `test_project_requires_leader_and_worker_seats`, `test_project_activates_when_leader_seat_granted`, `test_no_tasks_in_setup_project`, `test_seat_grant_vetting`.
- i18n: `project.*`, `role.*`.
**DoD:** new workspace lands on project list (empty); create a project → it's `setup`; grant the leader seat → `active`; only then can you reach the board.

---

## Phase D — Manual onboarding + Workspace Agent designation  *(deps: C)*
**Goal:** full manual onboarding (goal, roles + per-role counts + descriptions, context, settings) and the "designate Workspace Agent" control.
- **Onboarding (manual)**: `components/ProjectOnboardingModal.tsx` replaces Phase C's minimal form — objective, target_date, context, full roles editor, settings toggles; Create disabled until hard rule satisfied.
- **Workspace Agent**: `PUT /workspaces/{ws}/workspace-agent`; designation adds `armarius-onboarder` builtin to the marius's skills + rebuilds invite prompt. Add `static/skills/armarius-onboarder/SKILL.md` (instructs the agent on the structured question set + `finalize` call).
- **Frontend**: designate control in `ProjectLanding` (and/or `Directory` badge); "Agent" mode in onboarding modal is **disabled with a hint** until a Workspace Agent exists (the chat itself ships in Phase E).
- Tests: `test_workspace_agent_designation_adds_onboarder_skill`; `test_onboarding_manual_creates_project`.
- i18n: `onboarding.manual/agent/modeHint/needWorkspaceAgent/objective/targetDate/context/…`.
**DoD:** create a project via the full manual form with a 2-role plan (leader + backend×2 + context); designate a Marius as Workspace Agent (invite now lists the onboarder skill install).

---

## Phase E — Agent-assisted onboarding (chat)  *(deps: D; can trail)*
**Goal:** the Workspace Agent runs OpenClaw-style project onboarding via a chat.
- **Domain/migration `0002b`**: `OnboardingSession` entity/repo/model.
- **API**: onboarding-session endpoints (§API 3.4); agent can append messages; `finalize` calls `ProjectService.create`.
- **Frontend**: chat UI in the onboarding modal's Agent tab; transcript + collected-plan preview + Finalize.
- **armarius-onboarder SKILL.md**: concrete question script (goal → roles → counts → context) + the `finalize` payload shape.
- Tests: `test_onboarding_agent_finalize` (drive the session + finalize, assert project created with correct roles).
**DoD:** with a designated Workspace Agent, start an onboarding chat, answer the agent, finalize → a project is created with the agreed roster.

---

## Phase F — Rich task schema + Output-Artifact shared-store gate  *(deps: A, C)*
**Goal:** Paperclip-style task fields + the anti-local-output guarantee.
- **Shared Artifact Store**: `domain/services/artifact_store.py` port + `infrastructure/artifacts/store.py` FS impl; `ARTIFACT_STORE_DIR` config; `GET /artifacts/{id}/content` stream.
- **Artifact change**: `publish(kind=file|patch)` requires `content_b64`; decode/verify/write/stored=True. `Artifact.stored` column.
- **Task fields / migration `0002c`**: `identifier`, `priority`, `parent_id`, `due_date`, `definition_of_done`; `Label`, `task_labels`, `TaskParticipant`, `ChecklistItem`, `TaskDependency`.
- **TaskService**: `create` (project must be `active`; assign identifier), `transition` (DONE-gate + dependency-gate), `add_participant`/`remove_participant`, `wake(participant)`, checklist/deps/labels helpers.
- **API**: `PATCH /tasks/{id}` (replaces narrow endpoints), labels endpoints, participants endpoints, checklist endpoints; tightened `POST /tasks/{id}/status` gate.
- Tests: `test_task_rich_schema`, `test_dependency_blocks_progress`, `test_artifact_must_upload_content_for_file_kind`, `test_done_gate_requires_stored_output`.
- i18n: `task.priority.*`, `task.checklist.*`, `task.definitionOfDone`, `task.dueDate`, `task.blockedBy`, `task.publishOutput`, `task.gateNeedOutput`, `artifact.*`.
**DoD:** commission a task with priority+labels+checklist+DoD+deps; add participants; a participant publishes a file (uploaded, downloadable); DONE is blocked (409) until a stored output exists; a blocked task can't go in_progress until its blocker is done.

---

## Phase G — Collaboration Room (task detail)  *(deps: F; frontend-led)*
**Goal:** task detail follows the design's Collaboration view — co-work thread + participants + trace + shared-store publish.
- Rework `pages/Room.tsx` → `pages/CollaborationRoom.tsx`:
  - **Left/Context**: editable title+desc, Definition of Done, Checklist (add/toggle), status/priority/labels/due/deps, Linked artifacts + "publish to shared store".
  - **Center/Thread**: existing comment thread + composer + **Participants bar** (who's on the task, per-participant "wake").
  - **Right/Trace**: existing live run trace (SSE) — retained.
- Publish affordance: upload file → stored artifact card + download; transitions to in_review/done disabled with tooltip until stored output exists.
- i18n: `task.participants`, `task.wake`, `task.publishedToStore`, etc.
**DoD:** open a task → see participants co-working in the thread, tick the checklist, watch the live trace, publish a stored output, then move it to done; visual matches the design's Collaboration view closely enough to ship (full pixel-match is a later pass).

---

## Out of scope (carried forward)
- MCP server + MCP skill (standing issue).
- Full visual reflow of all pages to match `ARMARIUS Design/` pixel-for-pixel (after this wave lands structurally).
- Drag-and-drop kanban + board grouping (Paperclip-style) — nice-to-have after G.

## Suggested order for the user to review
1. Confirm **Phase C hard rule** (leader seat + ≥1 worker seat at creation; `setup→active` on leader grant) matches intent.
2. Confirm **Phase F DONE-gate** (file/patch must upload content; no bare local `uri`) is the right anti-local-output enforcement.
3. Confirm **Phase E (agent onboarding)** can trail manual onboarding (Phase D) — i.e., manual is the priority path.
