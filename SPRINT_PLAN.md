# Armarius — Sprint Plan & Build Log

> **Single source for sequencing + history.** Merged from the former `docs/DEV_PLAN.md`
> (the v3 FE-first → BE-TDD plan) and `ROADMAP.md` (the dated build log) on 2026-06-28.
> **Behavior source of truth stays the four design docs** — [docs/ARCHITECTURE.md](./docs/ARCHITECTURE.md) ·
> [docs/HLD.md](./docs/HLD.md) · [docs/LLD.md](./docs/LLD.md) · [docs/API_CONTRACT.md](./docs/API_CONTRACT.md).
> If this plan disagrees with them, **those win**. Convention: after every large update, append a dated
> entry to the Build log, then commit + push.

---

## 1. Locked decisions

### Architecture (locked)

| Decision | Choice | Why |
|---|---|---|
| Backend language | **Python 3.12** | Clean-architecture fit; aligns with the OpenClaw MC reference and Hermes' stack |
| Style | **Clean Architecture** (domain / application / infrastructure / presentation) | Owner requirement; keep domain pure & runtime-agnostic |
| Web framework | **FastAPI** + `sse-starlette` | Async, first-class SSE for the live-trace tee (API_CONTRACT §8) |
| Persistence | **SQLAlchemy 2 (async)**, SQLite for dev, Postgres for prod | Zero-setup local dev; swap `DATABASE_URL` for prod |
| Migrations | **Alembic** (replaces `create_all`) | Ship schema deltas without nuking data (ARCHITECTURE §8 #12) |
| Shared store | **MinIO** (S3-compatible), bucket `armarius` | The file\|link DONE-gate; one folder per project + `_media/` |
| Tooling | **uv**, ruff, mypy, pytest | Fast, reproducible |
| Reference adapter | **`hermes_gateway`** first | Verified HTTP+SSE gateway; cleaner than OpenClaw's WS |

### Build-order & UX (locked, 2026-06-27)

| Decision | Choice | Why |
|---|---|---|
| Build order | **FE-first (mock data) → BE** | Lock UX before backend cost; the mock app is the spec the BE implements to |
| Aesthetic | **Scriptorium (refined)** — warm parchment + terracotta + manuscript gold, classical serif (Fraunces/Spectral) | Re-tuned to the owner's reference image; cyberpunk tried and set aside |
| FE stack | **React 19 + Vite 7 + TS + Tailwind 3 + shadcn/radix + Router** (rebuilt 2026-06-28) | Pure mock SPA; one `mockStore.ts` swap-seam |
| BE method | **Clean Architecture + strict TDD** (red→green→refactor per sprint) | Domain pure; owner requirement |
| Architecture | **Unchanged** (enroll-and-wait, system-only seats, leader commission, Hybrid SSE, probe liveness, file\|link gate) | Already approved in ARCHITECTURE/HLD/LLD/API_CONTRACT |

---

## 2. Layer map (`backend/armarius/`)

```
domain/          pure entities + domain services (no I/O, no ORM)
application/     ports (interfaces) + use cases (orchestration) + dtos
infrastructure/  SQLAlchemy models/repos, adapter registry, Hermes adapter, event bus, stores
presentation/    FastAPI routers + pydantic schemas + DI wiring (composition root)
shared/          config, logging, clock
```

Dependency rule: `presentation → application → domain`; `infrastructure` implements
`application.ports` / `domain.repositories` and is wired in at `presentation` only.

## 3. Task lifecycle (from API_CONTRACT §5)

`draft → todo → in_progress → in_review → done`  (+ `backlog`, `blocked`, `cancelled`).
`draft` is created only by a leader commission chat; `draft → todo` only on `/commission/confirm`.
A task may reach `in_review`/`done` only with ≥1 artifact of kind **`file` or `link`** (DONE-gate).

---

## 4. Current state (2026-06-28) — where the BE actually is

The FE is **frozen** and implements the full target on mock data — so **`mockStore.ts` is the acceptance
contract** every BE sprint must satisfy. The backend is **not greenfield**: a real Clean-Arch FastAPI app
exists from the pre-architecture-wave build (commits `d7fbb8c` → `94d6f9e`), but it predates the
multi-project / roster / commission wave.

| Already on disk (old model) | Missing vs the four docs (all `[NEW]`) |
|---|---|
| Auth JWT (register/login/refresh/me) | **Project / Role / SeatGrant** layer (UC5/6): entities, use cases, routes |
| Workspaces, invite (old form), Skills (list + manual/import) | **Leader-mediated Commission** + `CommissionSession`/`leader_state` (UC7) |
| Task **single-assignee** (`/assign`, `/claim`) | **Rich Task**: `draft`, `identifier`, priority, DoD, checklist, deps, labels, **participants** |
| Comments, next-action, wake | **Liveness watchdog** (system-probe, backoff R→2R→4R, **no heartbeat**) |
| **Hermes + echo** adapter + AdapterRegistry + WakeEngine | **Hybrid SSE**: workspace control-plane `/events` (only per-run trace exists today) |
| Per-run trace SSE | **MinIO** store + DONE-gate (file\|link) — today is `local_store.py` (filesystem) |
| Ports present: `artifact_store`, `event_bus`, `unit_of_work`; composition root `container.py` | **Alembic** (today `create_all`); **Workspace Agent** + onboarder; **Onboarding session** (UC9) |

**⚠ Baseline is RED — 8/32 tests fail.** Cause: the suite runs against a non-reset SQLite DB (register →
`409` because the seed user already exists). Fixing test isolation is **Sprint 0a** — nothing else can
claim "ships green" until the baseline is green.

**Leverage:** the `artifact_store` / `event_bus` / `unit_of_work` ports + composition root already exist,
so `local_store → MinIO` and the control-plane bus are **adapter additions**, not a rewrite.

---

## 5. Sprint plan (0 → 7)

Each sprint: **TDD red→green→refactor**, domain pure, `pytest` green + `ruff` clean, schema change = one
Alembic revision, then commit + push. This plan is **review-first** (owner approves before commit).
Sprints map to ARCHITECTURE phases A–G, the former DEV_PLAN BE-1…BE-7, and API_CONTRACT sections.

### Sprint 0 — Foundation & green baseline  · ARCH Phase A · BE-1
- **0a** Fix test isolation (fresh DB per run; stop testing against the seeded on-disk DB) → suite **green**.
- **0b** Alembic init + baseline migration replacing `create_all()` (ARCH §8 #12).
- **0c** MinIO compose service + create bucket `armarius` on boot; swap `local_store` → S3/MinIO store
  **behind the existing `artifact_store` port**; `GET /health` → `{status, db, minio}`.
- **DoD:** `pytest` green; `alembic upgrade head` runs on fresh Postgres *and* the existing SQLite; bucket reachable.

### Sprint 1 — Domain core (rich, pure)  · ARCH §6, Phase C/E · BE-2
- New/extended entities: `Project(setup/active/archived)`, `Role`, `SeatGrant`, `Task(+draft, identifier,
  priority, DoD, due_date, parent_id)`, `TaskParticipant`, `ChecklistItem`, `TaskDependency`, `Label`,
  `OnboardingSession`, `CommissionSession(+leader_state)`, `Artifact(file|link)`.
- Pure rules (no I/O): task lifecycle (LLD §3), **DONE-gate**, dependency-gate, `recompute_active`,
  invite FSM, **liveness FSM** (ONLINE→CHECKING→OFFLINE + backoff).
- **DoD:** unit tests green covering activation rule, DONE-gate, dep-gate, invite & liveness FSM.

### Sprint 2 — Application: ports + use cases  · ARCH UC2/3/5/6 · BE-3
- `ProjectService` (create with **hard rule** 1 leader + ≥1 worker, `grant_seat` system-only,
  `recompute_active`, roster CRUD); `EnrollmentService` (**enroll-and-wait** → approve completes the held
  call; `claim` is recovery-only); `LivenessEngine` (system-probe, **no heartbeat**); Workspace Agent
  designation + onboarder skill link.
- **DoD:** use-case tests green on fake ports (enroll-and-wait returns token on approve; liveness decay +
  backoff + signal-reset; system-only grant; skill tree).

### Sprint 3 — Infrastructure: repos + adapters + migration 0002  · BE-4
- SQLAlchemy models + mappers + async repos for all new tables; **Alembic `0002`** (all new
  tables/columns incl. commission + liveness timers); AdapterRegistry/`execute` (hermes + echo);
  in-process EventBus for control-plane.
- **DoD:** integration round-trips on Postgres; migration up/down; adapter execute echoes; MinIO put/get.

### Sprint 4 — Presentation: routers + Hybrid SSE  · API_CONTRACT §2–8 · BE-5
- Routers to contract: projects, roster + grant, mariuses (invite/approve), labels, rich tasks
  (CRUD/status/checklist/participants), artifacts (file\|link + **409 DONE-gate**), skills.
- **Workspace control-plane SSE** `/workspaces/{ws}/events` + **per-task trace SSE** `/tasks/{id}/stream`,
  `Last-Event-ID` resume.
- **DoD:** contract-conformance tests (status codes, 409 gates); SSE framing + resume.

### Sprint 5 — Commission runtime + Wake engine + Liveness watchdog  · ARCH UC7 · BE-6
- WakeEngine (bounded turns, session resume, skill-install on grant, **tee trace** to per-task SSE);
  `CommissionService` async (commission/refine/confirm/edit, `leader_state`, `commission_jobs` drains on
  online); liveness watchdog loop (probe on idle).
- **DoD:** integration — commission `draft → todo` wakes workers; leader-offline queues then drains;
  liveness decays over time.

### Sprint 6 — Integration: FE mock → real API  · BE-7
- Flip `MOCK=off`; HTTP seam in `api.ts`; bind the frozen FE; full `docker compose`
  (Postgres + MinIO + backend + frontend + nginx; ports 3000/8080); add real loading/error states
  (the FE carry-forward).
- **DoD:** the exact FE journey plays end-to-end on the real stack; one-command compose green.

### Sprint 7 — Agent-assisted onboarding (last, optional)  · ARCH UC9, Phase G
- `OnboardingSession.finalize` → `ProjectService.create`; Workspace Agent chat (agent-surface messages).
- **DoD:** finalize creates a project + roster; the agent-mode tab works end-to-end.

**Dependency:** `0 → 1 → 2 → 3 → 4 → 5 → 6`, with `7` trailing `2` (domain) + `5` (wake). Sprint 0 blocks all.

**GitHub issues** (synced 2026-06-28): Sprint 0 → [#3](https://github.com/gnust-company/A.R.MARIUS/issues/3) ·
1 → [#4](https://github.com/gnust-company/A.R.MARIUS/issues/4) · 2 → [#5](https://github.com/gnust-company/A.R.MARIUS/issues/5) ·
3 → [#6](https://github.com/gnust-company/A.R.MARIUS/issues/6) · 4 → [#7](https://github.com/gnust-company/A.R.MARIUS/issues/7) ·
5 → [#8](https://github.com/gnust-company/A.R.MARIUS/issues/8) · 6 → [#9](https://github.com/gnust-company/A.R.MARIUS/issues/9) ·
7 → [#10](https://github.com/gnust-company/A.R.MARIUS/issues/10).

---

## 6. FE track — done & frozen (2026-06-28)

The mock-data Scriptorium SPA is the frozen UX spec. All sub-phases shipped green (`tsc` + `vite build`).

- [x] **FE-0** Design system + interaction language → [docs/FE_DESIGN.md](./docs/FE_DESIGN.md)
- [x] **FE-1** Mock data layer + simulated Hybrid SSE (liveness decay + per-task trace; setup→active gate)
- [x] **FE-2a** Shell + Auth + Workspaces
- [x] **FE-2b** Project landing + Roster + Onboarding manual form + Profile page
- [x] **FE-2c** Board + Commission (leader-mediated, async / `leader_state`)
- [x] **FE-2d** Collaboration Room (context + thread + per-task trace + publish + DONE-gate)
- [x] **FE-2e** Agent Directory (enroll-and-wait) + Skill Shop (nested tree) + Patron Inbox
- [x] **FE-3** Polish: EN/VI i18n (full, diacritic-correct), reduced-motion, a11y → **FE freeze**

## 7. Rules
- **FE** — `tsc` + `vite build` clean per change; mock layer = the API_CONTRACT contract; EN+VI every string.
- **BE** — TDD per sprint; domain pure; new behavior = use-case + repo (+ entity); `pytest` green +
  `ruff` clean; all schema changes after Sprint 0 are Alembic revisions (review, never edit a stamped one).
- **Both** — commit + push to `main` per sprint. This plan's updates are **review-first, commit on owner approval**.
- i18n — every new string lands EN **and** VI in the same commit.

## 8. Out of scope (carried forward)
- MCP server + MCP skill (GitHub issue #1).
- `openclaw_gateway` / `claude_local` / websocket adapters beyond registry stubs (after Sprint 6).
- Board drag-and-drop + advanced grouping (after Sprint 6).

---

## Build log

### 2026-06-29 — **Sprint 2 done**: application ports + use cases (Project/Roster/Enroll/Liveness) · issue #5
> Owner approved continuing ("Oke và tiếp tục sprint 2") + two new rules: **use CodeGraph to navigate**, and
> **`codegraph sync` after every sprint**. Application layer only, exercised on **fake in-memory ports** —
> no SQL/HTTP wiring (those are later infra/presentation sprints). Behaviour bound to LLD §3/§4/§10/§12.
- **New ports.** `domain/repositories` gains `RoleRepository` + `SeatGrantRepository`; both wired into the
  `UnitOfWork` port. New `application/ports/liveness_probe.py::LivenessProbe` (bounded "are you there?" — no
  heartbeat). The SQLAlchemy UoW keeps satisfying the ABC (annotations, not abstract methods); real repos
  land in the infra sprint.
- **ProjectService** (`application/use_cases/projects.py`) — `create_project` enforces the hard roster rule
  via `validate_plan` (1 leader seats==1 + ≥1 worker) and is born in SETUP; `grant_seat`/`revoke_seat` are
  **system-only** (`SystemOnlyOperation` otherwise); roster CRUD (`add/list/update/remove_role`);
  `recompute_active` flips SETUP→ACTIVE once (all seats granted AND all seated ONLINE), never rolls back.
- **EnrollmentService** (`enrollment.py`) — **enroll-and-wait**: `enroll` flips PENDING_REVIEW, commits, then
  awaits a per-Marius `asyncio.Future` (DB tx not held); `approve` mints the token once and completes the
  held call; `claim` is recovery-only (token iff approved). Bad code / illegal step → `EnrollmentError`.
- **LivenessEngine** (`liveness.py`) — wraps the pure §10 FSM with the clock + `LivenessProbe` + persistence:
  `record_signal` (any contact → ONLINE+reset), `begin_turn` (→WORKING), `tick`/`advance` (plan → register
  the attempt → fire one probe outside the tx → fold the result back). Decay→OFFLINE, backoff R→2R, signal
  reset all verified.
- **WorkspaceAgentService** (`workspace_agent.py`) — idempotently designates the host **Workspace Agent**
  Marius and materialises + links the built-in **`armarius-onboarder`** skill (skill-tree round-trip).
- **TDD.** New `tests/support/fakes.py` (shared-store `FakeUnitOfWork` + `FakeLivenessProbe`) and
  `test_project_service.py` (10), `test_enrollment_service.py` (7), `test_liveness_engine.py` (6),
  `test_workspace_agent.py` (4). **DoD covered**: enroll-and-wait returns token on approve; liveness decay +
  backoff + signal reset; system-only grant; skill tree round-trip.
- **Verify** — `pytest` **103 passed** (was 76, +27); `ruff` clean; `codegraph sync` (303 nodes). No
  infra/ORM/HTTP touched. Paused for owner review of issue #5 before Sprint 3.

### 2026-06-28 — **Sprint 1 done**: domain core (rich, pure entities + lifecycle rules, TDD) · issue #4
> Owner approved continuing to the next sprint ("tiếp tục sprint và issue tiếp theo, nhớ luôn đồng bộ").
> Pure domain only — **no I/O, no ORM** (ports + use cases are Sprint 2). Behaviour bound to LLD §2/§3/§10.
- **Entities (rich, pure dataclasses).** Split `Project` out of `workspace.py` → `project.py` with
  `ProjectStatus(setup/active/archived)` + objective/success_metrics/target_date/github_url/context/settings;
  `workspace.py` gains `workspace_agent_id` and re-exports `Project` (back-compat). New: `Role`,
  `SeatGrant(+SeatGrantStatus, revoke)`, `Label`, `TaskParticipant`, `ChecklistItem`,
  `TaskDependency(self-loop guard)`, `OnboardingSession(+FSM)`, `CommissionSession(+LeaderState)`. Extended:
  `Task` (`DRAFT` status, `TaskPriority`, identifier/parent_id/due_date/definition_of_done),
  `Artifact` (`stored`, kinds file|link via `ArtifactKind`), `Marius` (`InviteStatus` + enrollment_code/
  approved_at + liveness `CHECKING` + probe bookkeeping).
- **Pure rules.** `domain/services/project_rules.py` — `validate_plan` (exactly 1 leader seats==1 + ≥1
  worker) and `recompute_active` (setup→active once: all seats granted AND all seated ONLINE; never rolls
  back). `domain/services/liveness_fsm.py` — the §10 FSM as pure functions (`plan_tick`/`register_probe`/
  `on_probe_result`/`go_offline`/`on_signal`): ONLINE→CHECKING→OFFLINE, 3 probes spaced ~T2, backoff
  R→2R→4R capped, signal-reset, WORKING→HUNG. Invite FSM as pure `Marius` methods (`begin_enroll`/
  `approve`/`revoke`/`token_for_claim`); task DONE-gate + dependency-gate enforced in `Task.transition_to`.
- **TDD.** New `test_project_rules.py`, `test_invite_fsm.py`, `test_liveness_fsm.py`; extended
  `test_task_rules.py` (draft + dep-gate). **DoD covered**: activation rule, DONE-gate, dep-gate, invite
  FSM, liveness FSM (incl. first-wait-R + probe-spacing + cap).
- **Verify** — `pytest` **76 passed** (was 34, +42); `ruff` clean. No infra/ORM touched (Sprint 3). Paused
  for owner review of issue #4 before Sprint 2.

### 2026-06-28 — Plan consolidation: SPRINT_PLAN.md + GitHub-issue sync; **Sprint 0 done**
> Owner: "FE đã oke; lên plan bám sát ARCHITECT + design docs, chia sprint, báo cáo." Merged
> `docs/DEV_PLAN.md` + `ROADMAP.md` into this **SPRINT_PLAN.md**; reconciled the plan with the
> **already-existing** pre-wave backend (the old DEV_PLAN said "BE not started" — true only of the
> *new wave*; a real Clean-Arch app is on disk). Recut BE-1…BE-7 into **Sprint 0–7**; synced to GitHub
> issues #3–#10. Workflow: one sprint/issue at a time, **review-first** before the next.
- **Sprint 0a — green baseline.** Root cause of the RED suite (8/32): HTTP tests drove the global app
  whose engine read the persisted `./armarius.db` (leftover rows → register 409). Fix in
  `tests/conftest.py`: pin all global I/O (DB, artifact root) to a throwaway temp dir **before** importing
  `armarius`, and drop+create the schema per test. Stray dev DB + artifact store now gitignored. → **green**.
- **Sprint 0b — Alembic.** Added `alembic`; `env.py` wired to `settings.database_url` + `Base.metadata`;
  baseline revision `a40098b66ac7` (all 12 tables). Boot replaced `create_all()` with
  `migrations.ensure_schema()` — fresh DB → `upgrade head`; managed DB → apply pending; **legacy**
  create_all DB (no `alembic_version`) → `stamp head` then upgrade. Verified on fresh + legacy SQLite.
- **Sprint 0c — MinIO.** Added `minio`; `MinioArtifactStore` behind the existing `artifact_store` port
  (bucket `armarius` created on boot, with boot-retry); container selects local|minio via
  `ARTIFACT_STORE_BACKEND`; `GET /health` → `{status, db, minio}`. Compose gains an internal-only `minio`
  service (no host ports → no 9000/9001 clash). Real-MinIO roundtrip verified (bucket create + put + readback).
- **Verify** — `pytest` **34 passed**; `ruff` clean; `docker compose --profile backend config` valid;
  real Postgres fresh `upgrade head` → 13 tables; MinIO bucket `armarius` auto-created; `/health` →
  `{status:ok, db:up, minio:up}`. Shipped as commit `abf08e0` (BE) + `362a7c7` (FE i18n).

### 2026-06-28 — i18n pass complete (issue #2 resolved)
> Owner picked "close i18n first" over starting BE. The deferred full EN/VI pass is now done; the FE
> stays frozen on everything else.
- **All 6 hardcoded surfaces wired** — Workspaces, Directory, Skills, SkillEditor, Inbox, Account now
  call `t()`; the ~25 CollaborationRoom leftovers (LIVE, status options, Add-Artifact modal, wake-control
  titles, empty states) are translated too. No user-facing English remains on the in-app surfaces.
- **Dictionaries grew 224 → 351 leaf keys**, EN/VI **key-for-key in sync** (parity-checked, 0 asymmetry).
  New `account` + `inbox` namespaces; `directory`/`skills` extended (status/adapter/role labels, editor).
  Status labels reuse `tasks.status.*`. Adapter/role **values stay English** (persisted data); only
  labels translate.
- **Intentionally still EN:** Landing (marketing), the generated enrollment-prompt payload (machine text),
  `A.R.MARIUS — v1.0.0` version string, the `WA` badge abbreviation.
- **Verify** — 165 distinct static `t()` keys all resolve; `tsc --noEmit` clean; `vite build` clean.

> Subsequent fix (same day): the VI dictionary was rewritten with **full, correct diacritics** (an earlier
> pass had shipped ASCII-stripped VI to `main`); all in-app chrome (Navbar/TopBar/Modal/ProjectBoard
> tooltip/Roster/Directory/Commission) wired to `t()`; EN/VI parity 366/366. Kanban tags, Landing, the
> mock AI demo script, and generated SKILL.md content stay English by owner decision.

### 2026-06-28 — FE-3 reviewed, trimmed, and **FE FROZEN**
> Owner: "I'm very happy with the FE, only a few small things left — check whether FE-3 actually gains
> anything; if not, fix the plan." A per-item audit showed FE-3 as written gains almost nothing on a
> pure mock, so it was trimmed instead of run as a phase, and the FE is frozen.
- **reduced-motion — done.** A single global `<MotionConfig reducedMotion="user">` at the app root → every
  framer-motion animation (16 files) honors the OS "reduce motion" setting.
- **i18n — measured & deferred** at the time (later resolved above).
- **Loading/error states — moot** in a synchronous mock; deferred to Sprint 6 (when data is async).
- **FE FREEZE.** The mock-data SPA is the frozen UX spec; the BE implements to match it.
- **Verify** — `tsc --noEmit` clean; `vite build` clean. Pushed to `main`.

### 2026-06-28 — FE-1 simulated Hybrid SSE actually wired (liveness decay · live trace · setup→active gate)
> The rebuilt SPA had every surface but the **simulated real-time layer was inert**. This change makes the
> mock feel alive — the FE-1 DoD.
- **Workspace control-plane channel** — new `useMockSimulator()` hook decays one agent's liveness ONLINE →
  checking → offline → back on a ~4.5s tick, emitting `marius.liveness` (honours `prefers-reduced-motion`).
- **Per-task trace channel** — the Collaboration Room streams scripted `run.delta`/`run.tool`/`run.usage`
  into the open `in_progress` task while wake control is "running" (bounded, pause/stop aware).
- **setup→active gate** — `grantSeat` recomputes status: `setup` flips to **active** once every seat is
  filled, emitting `project.active` (unlocks Commission).
- **Verify** — `tsc --noEmit` clean; `vite build` clean. Pushed to `main`.

### 2026-06-28 — FE rebuilt as a pure mock SPA (React 19 / Vite 7 / Tailwind 3 / shadcn) + docker compose (`1345088`)
> The owner re-implemented the whole frontend on a new stack. It is now a **pure mock SPA** — no `fetch`,
> no API client; one in-memory **`src/store/mockStore.ts`** (zustand) is the only data source and the
> single swap-seam the BE will later satisfy.
- **Stack** — React 19 + Vite 7 + TypeScript 5.9 + Tailwind CSS 3 + shadcn/radix-ui + framer-motion +
  gsap + react-router. Every UC1–UC8 surface present.
- **Docker** — root `docker-compose.yml` builds the FE by default (Node 22 → nginx, SPA fallback); `db` +
  `backend` gated behind `profiles: ["backend"]`. Lockfile regenerated off the public registry;
  `network: host` on the build (this host's BuildKit has no DNS); `Cache-Control: no-cache` on `index.html`.
- **Verify** — `tsc --noEmit` clean; `vite build` clean. Pushed to `main`.

### 2026-06-27 — FE track complete: every surface rebuilt in Scriptorium + new Profile page (`cebeec9`)
- Clean warm ivory parchment material (no burn); every surface rebuilt fresh sharing one grammar
  (illuminated vellum header, `.panel` cards with gilt hover + quill-in stagger, mono for data).
- Shell / Auth / Workspaces / Board / Room / Directory / Skills+Editor / Inbox / **Profile (NEW)**.
- Icon family extended; emoji removed; `profile.*` + inbox groups added EN+VI.
- **Verify** — `tsc --noEmit` + `vite build` clean. **FE freeze (this was the React 18/Tailwind v4 build,
  later superseded by the React 19 rebuild above).**

### 2026-06-27 — Plan v3: FE-first mock-data → BE Clean-Architecture TDD (planning; pre-impl)
> Owner reset the build order. Plan + design charter only.
- **New order** — build a fully-interactive **mock-data frontend FIRST**, then the backend against it.
  Supersedes the v2 BE-centric A–G ordering (preserved as the BE track, TDD-reframed).
- **Aesthetic — Scriptorium (refined)**; cyberpunk tried and set aside. Charter → FE-0 (`docs/FE_DESIGN.md`).
- **BE method** — Clean Architecture + strict TDD; 7 phases BE-1…BE-7 mapping the approved architecture
  (all decisions unchanged).

### 2026-06-26 — DESIGN: multi-project + onboarding + rich task + collaboration (pre-impl)
> **Design milestone — no code.** Learning from `openclaw-mission-control` (workspace/project UX) and
> `paperclip` (task schema + task detail). Four needs folded into a new `docs/` design set.
- **New design docs** — `docs/API_CONTRACT.md`, `docs/HLD.md`, `docs/LLD.md`, `docs/DEV_PLAN.md`.
- **Skill nested tree** (frontend rendering; backend stores `files:{path}`).
- **Multi-project workspaces** — no more auto "General"; land on a project list; each project has a
  **roster of roles/seats**. Hard rule: created only with a complete seat plan; `setup → active`.
- **Two onboarding modes** — manual form; agent-assisted via a designated **Workspace Agent**.
- **Rich task schema** — Paperclip fields (priority, labels, parent/subtask, deps, due, DoD) + checklist
  + the **Output-Artifact shared-store gate**.
- **Collaboration Room** — participants co-working + live run trace + artifacts + DoD/checklist.
- **Infra** — adopt Alembic; sequencing A–G (each phase ships green + commits).

#### 2026-06-26 (refined) — design v2: MinIO, file|link gate, ack-activation, github, ARCHITECTURE doc
- **Resolved** — hard rule (1 leader seats=1, pick-now-or-empty, ≥1 worker role); DONE-gate = `file`|`link`
  only; Phase G (agent onboarding) is **last**.
- **Additions** — project `github_url`; **MinIO** Shared Artifact Store (bucket `armarius`, also media).
- **New doc** — `docs/ARCHITECTURE.md` (use-case-driven, Mermaid-heavy).

#### 2026-06-26 (architecture review) — ARCHITECTURE.md fixes + EN-only docs
- All docs English-only; **AdapterRegistry made first-class** (hermes/openclaw/claude/echo behind one
  bounded `execute()`); topology fixed to one agent-runtime block; UCs reordered to follow the journey;
  `setup` vs `active` clarified (only difference = task commission); shared store follows the project.

### 2026-06-23 — Skill authoring (manual + GitHub import + editor) + UX fixes
- Skill Shop became an authoring surface: a skill is a file tree rooted at `SKILL.md` (manual template or
  GitHub-folder import via the Contents API). Editor at `/skills/:id`; PUT re-derives name/description.
- Patron Inbox made bilingual; Commission modal takes a description; sidebar back affordance.
- **Verify** — 32 backend tests pass; ruff clean; FE typecheck + build clean; live GitHub import tested.

### 2026-06-23 — Quality pass: i18n audit, skill listbox, skill preview, workspace UX
- Rewrote `i18n.tsx` (151 keys × EN/VI + interpolation) wired through every page; skill field → listbox;
  skill preview modal; login lands on the Workspaces overview; "Personal" workspace; lazy "General" project.
- **Verify** — 32 backend tests pass; ruff clean; FE build clean; live UI driven with headless Chrome.

### 2026-06-23 — Skill Shop + multi-workspace + agent editing + onboarding fixes
- Registration by email (auto-derived handle); **Skill Shop** (workspace-scoped `Skill` entity + repo;
  every workspace seeded with builtin **armarius-http**); agent skill linking → per-skill invite steps;
  multi-workspace switcher + overview; fixed a `build_invite_prompt` crash; static-asset COPY bug fixed.
- **Verify** — 32 backend tests pass (5 new); ruff clean; FE build clean; live end-to-end smoke green.

### 2026-06-23 — Human-user auth (JWT) + i18n (EN/VI) + design alignment
- **User auth (JWT)** — `User` entity + `UserRole`; `JWTService` (python-jose) + `PasswordService` (bcrypt);
  `AuthService` (register/login/refresh); `/auth/{register,login,refresh,me}` + Bearer dependency.
- **i18n** — lightweight `i18n.tsx` provider (EN/VI, auto-detect, persisted); language switcher.
- **Frontend auth flow** — token storage, transparent refresh + retry on 401; auth gating in `App.tsx`.
- **Verify** — 7 new auth tests; full suite 27 passing.

### 2026-06-23 — Enhanced onboarding with credential file + HTTP skill + MCP deferred
- Enhanced invitation prompt (credential file → confirm online → install skills); HTTP API skill
  (`backend/static/skills/armarius-http/SKILL.md`); `/static` mount; **MCP deferred to issue #1**.

### 2026-06-23 — Public URL config + server-side invitations + `.env.sample`
- Separated Armarius→agent (per-Marius gateway `base_url`) from agent→Armarius (one public callback URL);
  `PUBLIC_BASE_URL` + `GET /v1/meta`; server-side invitation prompt; root `.env.sample` + parameterised compose.

### 2026-06-22 — Postgres + Docker Compose + Scriptorium frontend
- One-command stack (Postgres + backend + frontend); backend `Dockerfile` + healthcheck; the original
  "Modern Scriptorium" frontend (Board, Collaboration Room, Directory, Patron inbox).
- The user's real Hermes instance is up on :8642 — `hermes_gateway` adapter ready to point at it.

### 2026-06-22 — Backend walking skeleton (Clean Architecture)
- Full clean-arch backend under `backend/armarius/` (domain → application → infrastructure → presentation):
  entities + task-lifecycle rules + wake policy/prompt; ports (`MariusAdapter`/`EventBus`/`ArtifactStore`/
  `UnitOfWork`); use cases (workspaces, mariuses, tasks, threads, artifacts, runs) + **WakeEngine**;
  SQLAlchemy async repos + UoW; in-memory event bus; local artifact store; AdapterRegistry +
  **HermesGatewayAdapter** + **echo**; FastAPI app + composition root + routers + demo seed.
- Verified end-to-end (HTTP smoke + 20 pytest): assign/mention → wake → echo run → durable trace + resume.

### 2026-06-22 — Bootstrap
- Locked stack & clean-architecture layout; created the roadmap; began the Phase 0 scaffold.
