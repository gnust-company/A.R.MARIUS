# Armarius — Development Plan

> Status: **v3 — FE-first mock-data → BE Clean-Architecture TDD** (2026-06-27; FE in progress as of
> 2026-06-28). Supersedes v2 (BE-centric A–G). Source of truth for behavior:
> [ARCHITECTURE.md](./ARCHITECTURE.md) / [HLD.md](./HLD.md) / [LLD.md](./LLD.md) /
> [API_CONTRACT.md](./API_CONTRACT.md).
>
> **Where we are (2026-06-28):** the FE was rebuilt as a pure mock SPA on **React 19 / Vite 7 /
> Tailwind 3 / shadcn** (one `src/store/mockStore.ts` seam). All UC1–UC8 surfaces exist; the
> simulated Hybrid SSE (liveness decay + per-task live trace) and the setup→active gate are now
> wired. Remaining before **FE freeze**: full EN/VI string audit, reduced-motion/a11y pass, and a
> states/QA sweep (FE-3). BE track (BE-1…BE-7) **not started** per owner.

## 1. New ordering and why

The owner reset the build order: **lock the UX with a fully-interactive mock-data frontend FIRST,
then build the backend against it.**

- **FE-first** — the mock-data app *is* the spec. Every screen, flow, and real-time behavior
  (liveness decay, leader commission, live trace) is demonstrated with simulated data *before* a line
  of backend is written. UX problems surface when they are cheap to fix.
- **Scriptorium aesthetic (refined)** — the *current* "Modern Scriptorium" implementation is being
  **re-tuned**, not scrapped (owner: the existing implementation wasn't right). Direction: a warm,
  editorial **Scriptorium** — parchment, terracotta + manuscript gold, classical high-contrast serifs,
  and ornamental medieval details — matched to the owner's reference image. (A cyberpunk direction was
  tried first and set aside.) Defined fully in the design doc produced by FE-0.
- **BE second** — Clean Architecture + strict TDD, phased so each phase ships green and maps to the
  approved architecture. The mock-data contract (TS types + fixtures + simulated SSE) becomes the
  acceptance bar the real API must satisfy.

The previously-approved **architecture** (enroll-and-wait invite, system-only seat grants,
leader-mediated commission, Hybrid SSE, system-probe liveness, file|link DONE gate) is **unchanged**.
Only the build *sequence* and the *visual layer* change.

## 2. Decisions baked into this plan (owner, 2026-06-27)

1. **Build order** — FE mock-data app first; BE after FE freeze.
2. **Aesthetic** — warm editorial **Scriptorium** (parchment + terracotta + manuscript gold,
   classical serif: Fraunces / Spectral / UnifrakturMaguntia-initial), matched to the reference image.
   (Cyberpunk was tried and set aside.)
3. **FE stack** — rebuilt 2026-06-28 on **React 19 + Vite 7 + TS + Tailwind 3 + shadcn/radix +
   React Router**. (The original plan kept React 18 + Tailwind v4; the owner rebuilt fresh instead.
   Still a clean, mock-swappable structure: a single `mockStore.ts` is the only data source.)
4. **Mock fidelity** — fully interactive: every flow clickable, real-time behaviors *simulated* (fake
   SSE streams, scripted liveness decay, scripted leader replies) so the demo feels alive.
5. **BE method** — Clean Architecture + TDD (red→green→refactor per phase); domain pure; Alembic
   revisions for all schema changes after the first.
6. **Architecture unchanged** — the four approved docs stand; DEV_PLAN/ROADMAP now sequence around them.

## 3. Track FE — Mock-data Scriptorium app (FIRST)

Each FE sub-phase ships `tsc --noEmit` + `vite build` clean, EN+VI strings, and a commit. The mock
data layer is the contract the BE will later satisfy.

### FE-0 — Design system + interaction language  *(no deps)*
**Goal:** the Scriptorium design doc that governs everything after.
- New doc **[docs/FE_DESIGN.md](./FE_DESIGN.md)**: design tokens (warm parchment palette, terracotta +
  manuscript gold, aged borders, classical + ornamental type), component primitives (Button, Panel/Card,
  Chip, Input, Modal, Avatar, LivenessDot, StatusBadge, DropCap), and a named **interaction/motion
  language** — *quill-in* reveal, *scroll-unfurl* modals, *gilt-hover*, *wax-seal* press, *pulse*,
  *drop-cap*.
- Re-tune `src/index.css` tokens + `src/ui.tsx` primitives to the reference (parchment/terracotta/serif).
- One **style playground** page (`/style`) rendering every token + primitive + motion.
**DoD:** FE_DESIGN.md approved; `/style` renders the full token + primitive + motion set; tsc+build clean.

### FE-1 — Mock data layer + simulated real-time  *(deps: FE-0)*
**Goal:** swap the backend for an in-browser mock that serves the API_CONTRACT shapes and simulates SSE.
- Keep `src/api.ts` signatures + TS interfaces; back them with an in-memory mock store seeded from
  fixtures grounded in API_CONTRACT (a demo workspace, a project w/ roster, several tasks across
  statuses incl. a `draft`, agents in each liveness state, skills, artifacts).
- **Simulated Hybrid SSE** — a fake event emitter that streams workspace control-plane events
  (`marius.online`, `marius.liveness` decay ONLINE→CHECKING→OFFLINE, `project.active`, `task.created`,
  `commission.*`) and a per-task trace stream (`run.delta`/`run.tool`/`run.usage`).
- A `MOCK` on/off switch so the same screens later bind to the real API unchanged.
**DoD:** app boots with zero backend; demo seed visible; liveness dots decay live; a task trace streams
fake run events; `MOCK=off` still compiles.
**Status — done (2026-06-28):** pure mock store seeded per §7; `useMockSimulator()` decays liveness on
the workspace channel; the Collaboration Room streams per-task `run.*` trace events; setup→active gate
recomputes on seat grant. (No `MOCK` *toggle* yet — the app is mock-only; the toggle/HTTP seam lands
with BE-7.)

### FE-2 — Rebuild every surface (Scriptorium styling + motion), in 5 sub-phases
Old Scriptorium components are re-tuned under the new system. Each sub-phase is one commit.

- **FE-2a Shell + Auth + Workspaces** — App shell (Scriptorium nav); login/register (*quill-in*
  reveal on success); Workspaces overview (create, "enter" transition).
- **FE-2b Project landing + Roster + Onboarding** — project list + "New project"; onboarding modal:
  **manual** form (goal, leader pick-or-empty + responsibilities, worker roles + counts + optional
  skills, context, github_url, settings) and the **agent-assisted** tab (Workspace Agent chat —
  simulated, scripted). Roster: roles/seats, system-only grants, liveness dots.
- **FE-2c Board + Commission chat** — kanban by status (`backlog/todo/in_progress/in_review/done`;
  `draft` hidden unless owner); "Commission task" opens the **leader-mediated** chat (async feel:
  `leader_state` thinking→waiting, draft preview, refine/confirm, `commission.leader_offline`).
- **FE-2d Collaboration Room** — task detail: context (title/desc, DoD, checklist, deps, labels,
  participants, status/priority/due), co-work thread (@mention), **per-task live trace** (simulated
  SSE, gilt/ink timeline), publish artifact (file→MinIO mock card / link), DONE-gate enforcement.
- **FE-2e Agent Directory + Skill Shop + Patron Inbox** — Directory: Marius cards, **enroll-and-wait**
  invite (enrollment_code, NO token; approve → token), adapter_type-lock note; Skill Shop +
  **nested file-tree** editor (manual + GitHub import); Patron Inbox approval queue.

**DoD (FE-2):** all surfaces demonstrable end-to-end on mock data; the full journey
(register → workspace → onboard project → roster active → commission task → co-work + trace → publish
→ done → approve) plays through in the Scriptorium style + motion; tsc+build clean.

### FE-3 — Polish + i18n + accessibility  *(deps: FE-2)*
**Goal:** a production-feel mock demo.
- Full EN+VI string coverage; motion tuning (honor `prefers-reduced-motion`); loading/empty/error
  states; keyboard nav + focus rings; responsive breakpoints; QA pass + screenshots.
**DoD:** both languages complete; reduced-motion honored; no console errors; demo screenshotted.

> **FE freeze.** After FE-3 the mock-data app is the frozen UX spec. BE phases implement to match it.

## 4. Track BE — Clean Architecture + TDD (AFTER FE freeze)

Each BE phase: **red→green→refactor** (tests first), domain pure, `pytest` green + `ruff` clean, an
Alembic revision for schema, then commit + push. Phases ordered by the approved dependency graph.

### BE-1 — Infra: Alembic + MinIO  *(blocks BE-2, BE-5)*
Alembic init + baseline + `upgrade head` on boot; MinIO service + bucket `armarius`; config wiring.
**Tests:** fresh Postgres + existing SQLite both `upgrade head`; bucket reachable; app boots.

### BE-2 — Domain core: entities + value objects + lifecycle rules  *(deps: BE-1)*
**TDD-first.** Pure domain: Project (setup/active/archived), Role/SeatGrant (granted/revoked), Marius
(invite_status, enrollment_code, liveness, timers), Task (+ `draft`, rich fields),
TaskParticipant/Checklist/Dependency/Label, OnboardingSession, CommissionSession (+ leader_state),
Artifact (file|link). Task lifecycle + DONE/dependency gates + `recompute_active` as pure functions.
**Tests (unit, in-memory):** project activation rule, DONE-gate, dependency gate, invite state machine.
*No I/O, no ORM yet.*

### BE-3 — Application: ports + use cases + Enrollment + Liveness engine  *(deps: BE-2)*
Ports (repos, adapter registry, artifact store, event bus, clock, unit-of-work). Use cases:
EnrollmentService (enroll-and-wait), LivenessEngine (system-probe, **no heartbeat**), MariusService
(adapter_type lock), ProjectService (grant_seat system-only, recompute_active), SkillService.
**Tests (fake ports):** enroll-and-wait returns token on approve; claim is recovery-only; liveness
decay ONLINE→CHECKING→OFFLINE + backoff R→2R→4R + signal reset; system-only grant; skill tree.

### BE-4 — Infrastructure: SQLAlchemy repos + adapters + MinIO + Alembic 0002  *(deps: BE-3)*
ORM models + mappers + async repos; migration `0002_*` (all new tables/columns incl. commission,
liveness timers); AdapterRegistry + `hermes_gateway`/`echo` adapters behind `MariusAdapter.execute`;
MinIO ArtifactStore; in-process EventBus.
**Tests (integration, Postgres/MinIO):** repo round-trips; migration up/down; adapter execute echoes;
MinIO put/get.

### BE-5 — Presentation: FastAPI routers + composition root + Hybrid SSE  *(deps: BE-4)*
Composition root wiring; routers per API_CONTRACT (workspaces, projects, roster, tasks, agent
enroll/claim/join, commission, artifacts, skills, events). **Hybrid SSE**: workspace control-plane
(`/workspaces/{ws}/events`) + per-task trace (`/tasks/{id}/stream`); wake-engine trace tee.
**Tests (API, httpx/ASGI):** contract conformance (statuses, 409 gates), SSE event framing + resume,
enroll-and-wait holds-then-completes, leader-offline 202 path.

### BE-6 — Commission runtime + Wake engine + Onboarding finalize  *(deps: BE-5)*
WakeEngine (bounded turns, session resume, skill install on grant, tees trace to SSE);
CommissionService async (start/refine/edit/confirm, leader_state, `commission_jobs` drains on online);
OnboardingSession finalize → `ProjectService.create`.
**Tests (integration):** commission draft→todo wakes workers; leader-offline queues then drains;
onboarding finalize creates project w/ roster.

### BE-7 — Integration: swap FE mock → real API, end-to-end  *(deps: FE-3, BE-6)*
Flip `MOCK=off`; bind the frozen FE to the real backend; `docker compose up` full stack (Postgres +
MinIO + backend + frontend); drive the same journey proven in mock; seed parity.
**DoD:** the exact journey from FE-3 plays on the real stack; docker-compose one-command green.

## 5. Rules
- **FE** — tsc + vite build clean per sub-phase; mock layer = the API_CONTRACT contract; EN+VI every string.
- **BE** — TDD per phase; domain pure; new behavior = use-case + repo (+ entity); `pytest` green +
  `ruff` clean; all schema changes after BE-1 are Alembic revisions (review, never edit a stamped one).
- **Both** — commit + push to `main` per phase (per FE sub-phase after FE-0; per BE phase). This plan
  + the ROADMAP update are **review-first, commit on owner approval.**
- i18n — every new string lands EN **and** VI in the same commit.

## 6. Out of scope (carried forward)
- MCP server + MCP skill.
- `openclaw_gateway` / `claude_local` / websocket adapters beyond registry stubs (after BE-7).
- Board drag-and-drop + advanced grouping (after BE-7).
