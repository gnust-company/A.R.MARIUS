# Armarius — Roadmap & Build Log

> Living log of large updates. Source design: [PROJECT_DESCRIPTION.md](./PROJECT_DESCRIPTION.md).
> Convention: after every large update we append a dated entry here, then commit + push.

## Architecture decisions (locked)

| Decision | Choice | Why |
|---|---|---|
| Backend language | **Python 3.12** | Clean-architecture fit; aligns with the OpenClaw MC reference and Hermes' own stack |
| Style | **Clean Architecture** (domain / application / infrastructure / presentation) | Required by product owner; keep domain pure & runtime-agnostic |
| Web framework | **FastAPI** + `sse-starlette` | Async, first-class SSE for the live trace tee (§8.1) |
| Persistence | **SQLAlchemy 2 (async)**, SQLite by default, Postgres-ready | Zero-setup local dev; swap `DATABASE_URL` for prod |
| Tooling | **uv**, ruff, mypy, pytest | Fast, reproducible |
| Reference adapter | **`hermes_gateway`** first | Verified HTTP+SSE gateway (§5.3); cleaner than OpenClaw's WS |

## Build-order & UX decisions (locked, 2026-06-27)

| Decision | Choice | Why |
|---|---|---|
| Build order | **FE-first (mock data) → BE** | Lock UX before any backend cost; the mock app is the spec the BE implements to |
| Aesthetic | **Scriptorium (refined)** — warm parchment + terracotta + manuscript gold, classical serif (Fraunces/Spectral) | Re-tuned toward the owner's reference image; cyberpunk was tried and set aside |
| FE stack | **React 19 + Vite 7 + TS + Tailwind 3 + shadcn/radix + Router** (rebuilt 2026-06-28) | The mock SPA was rebuilt fresh on this stack; cleanly structured + mock-swappable (single `mockStore.ts` seam). Earlier plan said "keep React 18 + Tailwind v4"; superseded by the rebuild. |
| Mock fidelity | **Fully interactive, simulated real-time** | Every flow clickable; fake SSE, scripted liveness decay + leader replies |
| BE method | **Clean Architecture + strict TDD** | Domain pure; red→green→refactor per phase; required by owner |
| Architecture | **Unchanged** (enroll-and-wait, system-only seats, leader commission, Hybrid SSE, probe liveness, file\|link gate) | Already approved in ARCHITECTURE/HLD/LLD/API_CONTRACT |

## Layer map (`backend/armarius/`)

```
domain/          pure entities + domain services (no I/O, no ORM)
application/     ports (interfaces) + use cases (orchestration) + dtos
infrastructure/  SQLAlchemy models/repos, adapter registry, Hermes adapter, event bus
presentation/    FastAPI routers + pydantic schemas + DI wiring
shared/          config, logging, clock
```

Dependency rule: `presentation → application → domain`; `infrastructure` implements
`application.ports` / `domain.repositories` and is wired in at `presentation` only.

## Task lifecycle (from API_CONTRACT §5)

`draft → todo → in_progress → in_review → done`  (+ `backlog`, `blocked`, `cancelled`).
`draft` is created only by a leader commission chat; `draft → todo` only on `/commission/confirm`.
A task may reach `in_review`/`done` only with ≥1 artifact of kind **`file` or `link`** (DONE-gate).

---

## Build plan (v3 — FE-first → BE-TDD; mirrors [DEV_PLAN.md](./docs/DEV_PLAN.md))

> Ordering changed 2026-06-27: lock the UX with a mock-data **Scriptorium** frontend first, then build
> the backend (Clean Architecture + TDD). The architecture is unchanged; only the sequence + visual
> layer change. Full detail in [DEV_PLAN.md](./docs/DEV_PLAN.md).

**Already shipped (backend walking skeleton — the old "Phase 0"):** workspace/project/marius/task/
thread CRUD, session store, event-wake + self/liveness-wake, `hermes_gateway` + `echo` adapters, local
artifact store, agent API, live-trace SSE, demo seed, docker-compose, and the (now-to-be-replaced)
Scriptorium frontend. All `[x]`.

### Track FE — Mock-data Scriptorium app (FIRST)
- [x] **FE-0** Design system + interaction language → [docs/FE_DESIGN.md](./docs/FE_DESIGN.md)
      (parchment + terracotta + gilt tokens, Fraunces/Spectral, quill-in / scroll-unfurl / gilt-hover / wax-seal motion)
- [x] **FE-1** Mock data layer + simulated Hybrid SSE (in-memory store seeded from API_CONTRACT
      shapes; fake liveness decay + per-task trace stream; `MOCK` on/off switch)
- [x] **FE-2a** Shell + Auth + Workspaces
- [x] **FE-2b** Project landing + Roster (Board) + Onboarding manual form (Directory provision)
      + **Profile page** ("trang cá nhân", added per owner). *Agent-assisted onboarding chat
      deferred to the BE runtime (BE-6 finalize).*
- [x] **FE-2c** Board + Commission (leader-mediated, async / `leader_state`)
- [x] **FE-2d** Collaboration Room (context + thread + per-task trace + publish + DONE gate)
- [x] **FE-2e** Agent Directory (enroll-and-wait) + Skill Shop (nested tree) + Patron Inbox
- [x] **FE-3** Polish: EN/VI i18n, reduced-motion, a11y, empty/loading/error states → **FE freeze**

### Track BE — Clean Architecture + TDD (after FE freeze)
- [ ] **BE-1** Infra: Alembic + MinIO
- [ ] **BE-2** Domain core (entities + lifecycle rules — pure, TDD)
- [ ] **BE-3** Application (ports + use cases + Enrollment + Liveness engine)
- [ ] **BE-4** Infrastructure (SQLAlchemy repos + adapters + MinIO + migration `0002`)
- [ ] **BE-5** Presentation (FastAPI routers + composition root + Hybrid SSE)
- [ ] **BE-6** Commission runtime + Wake engine + Onboarding finalize
- [ ] **BE-7** Integration: `MOCK=off` → real API; docker-compose full-stack end-to-end

---

## Build log

### 2026-06-22 — Bootstrap
- Locked stack & clean-architecture layout (table above).
- Created ROADMAP; began Phase 0 scaffold (backend package, config, domain entities).

### 2026-06-22 — Backend walking skeleton (Clean Architecture)
- Full clean-arch backend under `backend/armarius/` (domain → application → infrastructure → presentation).
- Domain: entities + task lifecycle rules (artifact gate) + wake policy + wake-prompt builder + repo ports.
- Application: `MariusAdapter`/`EventBus`/`ArtifactStore`/`UnitOfWork` ports; use cases for
  workspaces, mariuses, tasks, threads, artifacts, runs; and the **WakeEngine** (event-wake,
  coalescing, SSE tee, session resume, self-wake policy).
- Infrastructure: SQLAlchemy async models + mappers + repositories + UoW; in-memory event bus;
  local artifact store; adapter registry; **HermesGatewayAdapter** (POST /v1/runs + SSE tee) and
  an **echo** adapter for offline demos.
- Presentation: FastAPI app, composition root, error handling, routers (workspaces/projects/
  mariuses/tasks/threads/artifacts/trace+SSE/agent-API), demo seed.
- Verified end-to-end (HTTP smoke + 20 pytest): assign/mention → wake → echo run → durable trace
  (`run.started … tool.* … run.completed`) + persisted session for resume.
- Next: Postgres + Docker Compose stack, then the Scriptorium frontend.

### 2026-06-22 — Postgres + Docker Compose + Scriptorium frontend
- **One-command stack**: root `docker-compose.yml` brings up Postgres + backend + frontend;
  `docker compose up --build` → dashboard on :3000, API on :8080 (host ports overridable).
- Backend `Dockerfile` (installs `.[postgres]`/psycopg) + healthcheck; default prod DB = Postgres.
- **Frontend** (Vite + React + TS + Tailwind v4, "Modern Scriptorium" theme):
  - Board (kanban by status + agent directory rail + commission task)
  - **Collaboration Room** — task context (status/assign/next-action/DoD/artifacts) · thread with
    @mention highlighting + composer · **live trace via SSE** (run tabs, streaming deltas, tool
    chips, usage) · approval bar when `in_review`
  - Directory (Marius cards + "Provision a Marius" → generated token + invite prompt)
  - Patron inbox (only items needing a human: in_review / blocked)
- Verified: full stack healthy on Postgres; seed present; wake → echo run → durable trace through
  the containerised backend. Frontend typechecks + builds clean.
- The user's real Hermes instance is up on :8642 — `hermes_gateway` adapter ready to point at it.

### 2026-06-23 — Public URL config + server-side invitations + `.env.sample`
- Separated the two onboarding directions (was conflated): **Armarius→agent** = per-Marius
  gateway `base_url` (user-supplied, works for remote agents); **agent→Armarius** = a single
  public callback URL.
- Added `PUBLIC_BASE_URL` setting (mirrors OpenClaw MC's `BASE_URL`) + `GET /v1/meta`.
- Invitation prompt now generated **server-side** (`application/use_cases/onboarding.py`) and
  advertises the configured public URL + full agent-skill endpoints — no more browser-guessed
  or `host.docker.internal` URLs baked into invites.
- Root **`.env.sample`** + parameterised `docker-compose.yml` (ports, Postgres creds,
  `ARMARIUS_PUBLIC_URL`, `ARMARIUS_API_URL`, `CORS_ORIGINS`); `host.docker.internal` demoted to a
  documented dev-only shortcut.
- Verified: `/v1/meta` and generated invites reflect a custom `ARMARIUS_PUBLIC_URL` end-to-end.

### 2026-06-23 — Enhanced onboarding with credential file + HTTP skill + MCP deferred
- **Enhanced invitation prompt** (`onboarding.py`):
  - Added **STEP 1**: Credential file storage instruction at `~/.armarius/credentials/<workspace>_<agent>.json`
  - Added **STEP 2**: Online confirmation with `curl /agent/me` to verify token works
  - Added **STEP 3**: Skill installation guidance with known-good curl examples
  - Structured prompt with clear sections (credentials, confirm, install, endpoints, rules)
- **HTTP API skill** (`backend/static/skills/armarius-http/SKILL.md`):
  - OpenClaw MC-style skill template with credential file reader
  - Known-good curl examples for all endpoints (me, task, claim, comment, status, next-action, artifact)
  - Rules that keep this from breaking (no shell variables, literal values, temp files for JSON)
  - Task workflow rules (claim first, artifact required for review/done, @mention, next_action)
- **Static file serving**: Added `/static` mount in `main.py` for skills directory
- **MCP server + skill**: Deferred to GitHub issue #1 (will be implemented separately)
- Auth pattern reviewed: Armarius uses simple bearer token (sufficient for agent use case; JWT upgrade not needed)
- Reference: Innovation Hub auth analyzed — JWT with refresh tokens is overkill for long-lived agent tokens.

### 2026-06-23 — Human-user auth (JWT) + i18n (EN/VI) + design alignment
- **User authentication (Clean Architecture, JWT)** — humans now register/login to access the app:
  - Domain: `User` entity + `UserRole` (`patron`/`member`/`admin`) + `UserRepository` port.
  - Infrastructure: `UserModel` (SQLAlchemy), mapper, `SqlUserRepository`, wired into `UnitOfWork` (+`users`).
  - Security: `JWTService` (python-jose — access + refresh tokens) + `PasswordService` (bcrypt directly;
    dropped passlib due to passlib/bcrypt-5 incompatibility).
  - Application: `AuthService` (register/login/refresh with duplicate + invalid-credential errors + timing-safe login).
  - Presentation: `/auth/{register,login,refresh,me}` endpoints + `get_current_user` Bearer dependency.
  - Config: `JWT_SECRET`/`JWT_ALGORITHM`/`JWT_ACCESS_EXPIRE_MINUTES`/`JWT_REFRESH_EXPIRE_DAYS` in `.env.sample`.
  - 7 new auth tests (register/login/me/duplicate/refresh/401s); full suite = 27 passing.
- **i18n (Vietnamese / English)** — frontend, lightweight self-contained (no extra deps):
  - `i18n.tsx`: `I18nProvider` + `useT()` + EN/VI dictionaries + browser-lang auto-detect + persisted choice.
  - Language switcher on the Auth screen and in the Sidebar.
  - Nav labels, auth copy, validation messages, and task-status labels localized.
- **Frontend auth flow**:
  - `api.ts`: token storage (localStorage), auto-attach `Authorization` header, transparent access-token refresh
    + retry on 401, `register`/`login`/`me` methods. (Also fixed default `API_BASE` → :8080.)
  - `auth.tsx`: `AuthProvider` bootstraps session via `/auth/me`; `signIn`/`signUp`/`signOut`.
  - `pages/Auth.tsx`: single Sign-in / Register screen in the Scriptorium theme.
  - `App.tsx`: gates the app behind auth — logged-out → Auth routes; logged-in → `AppProvider`-wrapped Shell
    with sidebar user card + sign-out.
- **Design alignment**: `ARMARIUS Design/Armarius.dc.html` reviewed — the existing Scriptorium UI already matches
  the spec (board / collaboration room / directory / patron inbox / invite). Auth + language switcher added
  without diverging from the parchment/ink/gold theme.

### 2026-06-23 — Skill Shop + multi-workspace + agent editing + onboarding fixes
- **Registration simplified** — login is by email; the `username` field is gone from the UI.
  - Backend auto-derives a unique internal handle from the email local-part (`AuthService.register`).
  - Register form now asks for a **password confirmation** (compared client-side) instead of a username.
- **Skill Shop (workspace-scoped)** — new first-class concept:
  - Domain `Skill` entity + `SkillRepository` port + `SkillModel` + mapper + `SqlSkillRepository` (wired into UoW).
  - `SkillService`: every workspace is seeded with the built-in **armarius-http** skill (idempotent; seeded on
    workspace create, on personal-workspace provision, and lazily on first `list_skills` — backfills old rows).
    Custom skills can be submitted to a workspace and are **NOT shared** across workspaces.
  - API: `GET/POST /v1/workspaces/{ws}/skills`. Built-in `install_url` is relative (`/static/...`) and resolved
    against the public base URL when advertised to an agent.
  - Frontend: **Skill Shop** page + nav entry below Agent Directory; "Submit a skill" form (built-in vs custom chips).
- **Agent (Marius) editing + skill linking**:
  - `Marius.skill_ids` links Skill-Shop entries to an agent; `MariusService.update` + `PATCH .../mariuses/{id}`.
  - Provision & Edit forms list the workspace's skills as **checkboxes** (built-in armarius-http pre-selected);
    selected skills drive **per-skill install steps** in the invitation prompt.
- **Onboarding prompt fixed & enriched**:
  - Removed a latent crash — `build_invite_prompt` referenced `marius.workspace`/`marius.project` (don't exist);
    it now takes workspace/project names + resolved `Skill`s explicitly.
  - STEP 3 now lists each linked skill with a **resolvable download URL** + notes + the credential-file path.
- **Multi-workspace UX**:
  - Store loads all owned workspaces; **Personal** workspace is the default. Sidebar workspace switcher
    (★ marks Personal) + **Workspaces** overview page (per-workspace project/agent counts, create new).
- **i18n**: EN/VI strings for Workspaces, Skill Shop, agent editing, confirm-password. The **Patron Inbox**
  view stays **English regardless of language** (`tEn()` for its nav label; the page copy is already English).
- **Static-asset bug fixed (BE-URL correctness)**: the backend Docker image never `COPY`d `static/`, so the
  SKILL.md the invite tells agents to download 404'd. Added `COPY static ./static`; verified the advertised
  URL returns **200** both directly (`:8080`) and through the nginx reverse-proxy (`:3000`).
- **Verification**: 32 backend tests pass (5 new: builtin-skill seeding, email→handle derivation, provision-links-
  skill + invite steps, agent edit, custom-skill workspace isolation); ruff clean; FE typecheck + prod build clean;
  Postgres volume wiped + stack rebuilt; live end-to-end smoke (register→workspace→skill→provision→edit→2nd
  workspace→tenant isolation→401→static 200) all green.

### 2026-06-23 — Quality pass: i18n audit, skill listbox, skill preview, workspace UX
Follow-up fixes after direct UI review (every visible string now bilingual; UX friction removed).

- **Full i18n audit (the big one)** — rewrote `i18n.tsx` with **151 keys × 2 languages** (EN/VI) and
  `{n}` interpolation; wired `t()` through **every** page (Board, Room, App, Auth, Directory, Skills,
  Workspaces, store). Task-status & liveness labels and relative time are now translatable
  (`ui.tsx` resolves `status.*` / `liveness.*` / `time.*` via `t`; `relTime` takes the translator).
  Singular/plural handled (e.g. "1 project" / "2 projects"). **Patron Inbox stays English** by design
  (`tEn`). New keys cover Board columns, the entire Collaboration Room (status/assignee/artifacts/
  thread/trace/wake), agent provision/edit, skill shop, workspaces, common verbs.
- **Skill field → listbox** — Provision & Edit agent: the old free-text "Skills, comma-separated"
  field **and** the checkbox grid are gone. Replaced with a native `<select multiple>` **list box**
  listing the workspace's skills (built-in `armarius-http` pre-selected). No more checkboxes.
- **Skill preview** — Skill Shop cards now have a **Preview** button opening a modal that `fetch`es
  the SKILL.md (built-in) or shows inline install notes (custom). Verified rendering the full doc.
- **Skill Shop icon** — replaced the broken/unreadable `⌁` glyph with a clear tools icon (`⚒`).
- **One workspace list, not two** — login now **lands on the Workspaces overview**; the redundant
  sidebar workspace **dropdown switcher is removed** (it was the confusing "second list"). The
  sidebar now shows just the *current* workspace (links to the overview). Project selector in the
  top bar is hidden when the workspace has ≤1 project.
- **"Personal" + no "Getting Started"** — personal workspace is named **"Personal"** (not
  "{name}'s Workspace"). The confusing "Getting Started" starter project is removed; a neutral
  **"General"** project is created lazily (on first board load, and on agent provisioning) so tasks
  always have a home without a confusing seed artefact.
- **Verification**: 32 backend tests pass, ruff clean, FE typecheck + prod build clean, stack rebuilt;
  drove the live UI with headless Chrome (CDP) — screenshotted Workspaces (1 "Personal" card, "1
  project"), Skill Shop (new icon), Provision form (skill **listbox**, no checkboxes/free-text),
  Skill **Preview** modal (renders SKILL.md), and the VI locale (fully translated).

### 2026-06-23 — Skill authoring (manual + GitHub import + editor) + UX fixes
- **Skill Shop is now an authoring surface**, not just a link list. A skill is a small
  file tree rooted at `SKILL.md`; `name`/`description` come from its YAML frontmatter.
  - **Manual**: generates a `SKILL.md` template the author fleshes out; can add sibling
    files/folders (e.g. `scripts/`, `references/`) because some skills need more.
  - **Import from GitHub**: paste a folder URL (e.g. `github.com/owner/repo/tree/branch/skills/x`)
    → the backend detects `SKILL.md`, clones **only that folder** (GitHub Contents API,
    recursive, files only — no `git` needed), and stores the tree.
  - **Editor**: a full page (`/skills/:id`) with a file-tree panel + textarea editor +
    add/delete file + Save (PUT re-derives name/description from the frontmatter).
  - BE: `Skill.files` (JSON), `SkillService.create_manual` / `import_from_url` /
    `update_files` / `get_skill`; endpoints `manual`, `import`, `GET/PUT /skills/{id}`.
    Removed the made-up `http`/`mcp` `kind` (no one asked for it).
- **Sidebar back button**: removed the standalone "Workspaces" tab; replaced with a
  back affordance (shows the current workspace name, exits to the launcher) sitting
  alongside the other tabs.
- **Patron Inbox is now bilingual** (reverses the earlier English-only decision).
- **Commission task** modal now takes a **description**, not just a title.
- **Skill checkbox-dropdown** (agent provision/edit): restyled so it stays crisp after
  unchecking — solid panel, row separators, gold tint on selected rows.
- Verification: 32 backend tests pass (incl. manual-template + edit-rederive +
  workspace scoping), ruff clean, FE typecheck + build clean; live-tested GitHub
  import of `anthropics/skills/algorithmic-art` (cloned SKILL.md + LICENSE.txt +
  templates/*). Headless-Chrome screenshots of sidebar (VI), new-skill modal
  (Manual/Import tabs), skill editor (file tree + editor), commission modal.

### 2026-06-26 — DESIGN: multi-project + onboarding + rich task + collaboration (pre-impl)
> **Design milestone — no code yet.** The user asked to design the next wave *before* building it,
> learning from `openclaw-mission-control` (workspace/project UX) and `paperclip` (task schema +
> task detail). Four needs folded into a new `docs/` design set; full detail there, summary here.

- **New design docs** — [`docs/API_CONTRACT.md`](./docs/API_CONTRACT.md),
  [`docs/HLD.md`](./docs/HLD.md), [`docs/LLD.md`](./docs/LLD.md),
  [`docs/DEV_PLAN.md`](./docs/DEV_PLAN.md). HLD/LLD/API-CONTRACT didn't exist before; they now.
- **Skill nested tree** — imported/manual skills render as a **VSCode/GitHub-style collapsible tree**
  (add folder/file inside structure), not a flat list. Backend unchanged (stores `files:{path}`).
- **Multi-project workspaces** — a workspace holds **many projects**; **no more auto "General"** +
  auto-board. Land on a project list; each project has a **roster of roles/seats** (one leader +
  worker roles with seat counts) matching the design's *"Required roles · agents must qualify for a
  seat"* / *"Vet & grant seat"*. **Hard rule**: a project is created only with a complete seat plan;
  it goes `setup → active` when the leader seat is granted.
- **Two onboarding modes** — (1) **manual** form: goal, roles + per-role counts + descriptions,
  context, settings; (2) **agent-assisted**: a designated **Workspace Agent** (gets an
  `armarius-onboarder` skill) runs an OpenClaw-style chat that finalizes the project plan.
- **Rich task schema** — inherit Paperclip fields (priority, labels, parent/subtask, dependencies,
  due date, DoD) + a lightweight **checklist**, and the **Output-Artifact shared-store gate** that
  structurally prevents the "agent left the output file locally" failure: a `file`/`patch` artifact
  must **upload content** (server-stored), and a task **cannot reach `in_review`/`done`** without one.
- **Collaboration Room** — task detail follows the design's *Collaboration* view: participants
  co-working in the thread + the live run trace + linked artifacts + DoD/checklist
  (keeps the distinctive trace panel; tagline *"You task. They collaborate. You trace."*).
- **Infra**: adopt **Alembic** migrations (none existed) to ship the schema deltas safely.
- **Sequencing** (DEV_PLAN): A) Alembic · B) skill tree · C) project layer + roster · D) manual
  onboarding + Workspace Agent · E) agent-assisted chat (trails) · F) rich task + artifact gate ·
  G) Collaboration Room. Each phase ships green + commits to `main`.
- **Status**: design drafted; the three open confirmations are now **resolved** (see refinement below).

#### 2026-06-26 (refined) — design v2: MinIO, file|link gate, ack-activation, github, ARCHITECTURE doc
> Owner reviewed v1 and refined the design. Docs updated in place (not yet committed).

- **Resolved decisions**
  1. **Hard rule (Phase C)** — exactly one **Project Leader** (`seats = 1`): **pick an existing agent now
     OR leave empty** to add later; a `responsibilities` field (default leader behavior TBC). ≥1 worker
     role with name/description/**optional skills**/seat count. Project goes `active` only when **all**
     seats are filled **and acknowledged** (agent came online + accepted).
  2. **DONE-gate (Phase E)** — supported artifact kinds = **`file`** (upload content → MinIO) **or
     `link`** (external URL); DONE requires ≥1 file/link. `patch`/`note` dropped.
  3. **Phase G (agent onboarding) is LAST** — manual is the priority path; the main flow runs first.
- **Additions**
  - **Project `github_url`** (optional repo link) added to the project model.
  - **MinIO** is the Shared Artifact Store (new compose service, bucket **`armarius`**) — holds task
    output artifacts **and media** (agent avatars, …). Replaces the earlier FS-store design.
- **New doc** — [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md): higher-level, Mermaid-heavy,
  **use-case-driven** (one flow diagram per use case: create-project/roster, commission+co-work+trace,
  publish+DONE-gate, Workspace-Agent onboarding, skill tree), plus component/topology/data-model/phase
  diagrams. Style follows the `chat-with-documents` ARCHITECTURE reference.
- **Phase relabel** (DEV_PLAN) for a contiguous main flow: **A** Alembic+MinIO · **B** skill tree ·
  **C** project+roster · **D** manual onboarding + Workspace Agent · **E** rich task + artifact gate ·
  **F** Collaboration Room · **G** agent onboarding (last). HLD/LLD/API_CONTRACT updated to match.
- **NOT committed** (per owner: "ko commit và push nhé"). Changes live in the working tree only.

#### 2026-06-26 (architecture review) — ARCHITECTURE.md fixes + EN-only docs
> Owner reviewed at the architecture tier; I applied the fixes and propagated the wording down to
> HLD/LLD/API_CONTRACT/DEV_PLAN. Still **not committed**.

- **All docs are English-only** now (no Vietnamese mixed in) — ARCHITECTURE.md rewritten in EN.
- **Adapters made first-class** — the diagrams were Hermes-only; now they show the **AdapterRegistry**
  with `hermes_gateway` (reference), `openclaw_gateway`, `claude_local`, and `echo` (test) behind the
  single bounded `MariusAdapter.execute(ctx)` contract. The backend **always calls through an adapter →
  the runtime's gateway**, never a gateway directly. Added an adapter table + a dedicated §2.
- **Topology fixed** — removed the two-separate-agent-blocks drawing. Now there is **one agent-runtime
  block**: Armarius drives it through an adapter→gateway (`execute()`), and that same block calls
  **back** into the Agent API (token). No standalone agent→nginx box wired oddly.
- **Use cases reordered + expanded** — UCs now follow the journey and number in order: UC1 Register &
  Login, UC2 Invite an agent, UC3 Designate the Workspace-Agent role, UC4 Author/import skill, UC5
  Create project + staff roster, UC6 Apply/accept seat → active, UC7 Commission + co-work + trace, UC8
  Publish + DONE-gate, UC9 Agent-assisted onboarding (last). Agent-side steps show what the runtime
  (Hermes/OpenClaw/Claude via its adapter) does.
- **`setup` vs `active`** — clarified the **only** behavioral difference is **task assignment**;
  everything else works in `setup`. Propagated to HLD §5.2, LLD §3.1, API_CONTRACT §3.1.
- **Shared store follows the project** — artifacts are no longer a flat `artifacts/<task>/…`; each
  **project gets a top-level folder** in the bucket and each task with output writes under it
  (`<project-slug>/<task-id-or-slug>/<name>`); media under `_media/`. Propagated to HLD §6, LLD §6,
  API_CONTRACT §7, DEV_PLAN A/E.
- **UC2 Mermaid parse error fixed** — the `participants {A}; {B}` line used `{}`/`;` that GitHub's
  Mermaid rejects; reworded all sequence messages to plain text (no `{}`, `;`, or parens-as-syntax).
  Scanned every diagram for the same hazard.

### 2026-06-27 — Plan v3: FE-first mock-data → BE Clean-Architecture TDD (planning; pre-impl)
> Owner reset the build order. **No code yet** — plan + design charter only; pending approval.

- **New order** — build a fully-interactive **mock-data frontend FIRST**, then the backend against it.
  The mock app *is* the spec; UX problems surface before backend cost. Supersedes the v2 BE-centric
  A–G ordering (that content is preserved as the BE track, TDD-reframed). Full detail in
  [DEV_PLAN.md](./docs/DEV_PLAN.md) v3.
- **Aesthetic — Scriptorium (refined to the reference)** — the *current* "Modern Scriptorium"
  implementation is re-tuned (not scrapped) toward the owner's reference image: warm parchment,
  terracotta + manuscript-gold accents, high-contrast serifs (Fraunces / Spectral / UnifrakturMaguntia
  initials), ornamental medieval details. (A cyberpunk direction was tried first and set aside.)
  Charter → FE-0 deliverable [docs/FE_DESIGN.md](./docs/FE_DESIGN.md).
- **FE stack kept** (React 18 + Vite + TS + Tailwind v4 + React Router); only the design system,
  components, and theme are rebuilt. An audit confirmed the current FE (`api.ts`, providers, routing)
  is cleanly structured and highly swappable to mock data.
- **Mock fidelity** — every flow clickable; real-time behaviors **simulated** (fake SSE, scripted
  liveness decay, scripted leader commission replies). A `MOCK` toggle lets the same screens later
  bind to the real API unchanged.
- **BE method** — Clean Architecture + strict TDD (red→green→refactor per phase); 7 phases BE-1…BE-7
  mapping the approved architecture (enroll-and-wait, system-only seats, leader commission, Hybrid
  SSE, system-probe liveness, file|link DONE gate — all unchanged).
- **Docs** — [DEV_PLAN.md](./docs/DEV_PLAN.md) rewritten v3; this ROADMAP's phase plan, task
  lifecycle, and locked-decisions table updated. ARCHITECTURE/HLD/LLD/API_CONTRACT untouched (still
  the source of truth).
- **Status** — plan drafted, pending owner approval; **not committed**.

### 2026-06-27 — FE track complete: every surface rebuilt in Scriptorium + new Profile page (`cebeec9`)
- **Material locked (no burn).** Clean warm ivory parchment (#F3EAD4) + fine fiber speckle + faint
  mottling; `.vellum` = subtle hand-torn deckle (SVG turbulence mask, scale 6) + faint rim + soft
  drop-shadow. No singe / charred rim / vignette — matches the owner's crisp reference.
- **Every surface rebuilt fresh** (old layouts deleted), sharing one grammar: illuminated `.vellum`
  header (DropCap + Fraunces title + status chips + action), `.panel`/`.panel-flat` cards with
  `.gilt` hover + `.quill-in` stagger, mono for data, earthy status palette.
  - **Shell** — line-icon nav, terracotta brand, Account/Profile route, icon'd TopBar + sign-out.
  - **Auth** — illuminated vellum card, terracotta brand; fixed an undefined `--surface` var.
  - **Workspaces** — vellum header, folio cards with icon counts.
  - **Board** — illuminated project header + kanban + Scribes roster (committed earlier).
  - **Room** — vellum task header; reskinned 3-pane (context / thread / live trace) with an icon'd
    mono tool/delta/usage timeline; approval bar; wake control.
  - **Directory** — illuminated header, folio agent cards, icon'd skills, copy-feedback invite.
  - **Skills + SkillEditor** — illuminated headers, icon file tree (file / folder / seal).
  - **Inbox** — grouped Awaiting-review / Blocked, illuminated header, icon'd states.
  - **Profile (NEW)** — the Patron's "trang cá nhân": identity + workshop + preferences + session.
- **Icon family** in `ui.tsx` extended (file/folder/link/check/square/quill/copy/eye/trash/bolt/edit +
  accept `style`); all emoji glyphs removed.
- **i18n** — `profile.*`, inbox groups, `agent.copied` added EN+VI; glyph prefixes stripped (icons
  render them now). `prefers-reduced-motion`, focus rings, loading/empty/error states in place.
- **Verify** — `tsc --noEmit` clean; `vite build` clean (52 modules). Review screenshots in
  `docs/preview/04–12` (untracked). **FE freeze.** BE track (BE-1…BE-7) **not started** per owner.

### 2026-06-28 — FE rebuilt as a pure mock SPA (React 19 / Vite 7 / Tailwind 3 / shadcn) + docker compose (`1345088`)
> The owner re-implemented the whole frontend on a new stack (the cebeec9 freeze above was the
> *previous* React 18 / Tailwind v4 build). It is now a **pure mock SPA** — no `fetch`, no
> `import.meta.env`, no API client; one in-memory **`src/store/mockStore.ts`** (zustand) is the only
> data source and the single swap-seam the BE will later satisfy.
- **Stack** — React 19 + Vite 7 + TypeScript 5.9 + Tailwind CSS 3 + shadcn/radix-ui + framer-motion +
  gsap + react-router (BrowserRouter). Every UC1–UC8 surface present: Landing, Workspaces, Projects,
  CreateProject, ProjectBoard, Roster, Commission, Directory, Skills + SkillEditor, Inbox, Account,
  CollaborationRoom.
- **Docker** — root `docker-compose.yml` builds the FE by default (Node 22 → nginx, SPA fallback,
  no API proxy while mock); `db` + `backend` gated behind `profiles: ["backend"]`. Fixes baked in:
  regenerated `package-lock.json` off the public registry (was pinned to a dead build-farm mirror),
  `network: host` on the build (this host's BuildKit has no DNS), and `Cache-Control: no-cache` on
  `index.html` (the "/`→`/workspaces` phantom redirect" was a stale-bundle cache illusion, not a redirect).
- **Branding** — gilt "A" of ARMARIUS as the browser favicon; the workspace launcher + in-app logo use
  a single wordmark (gilt initial **A** + `rmarius`), no duplicated/black A.
- **UI polish** (`6f9b138`) — illuminated **PageTitle** (gilt first letter inline, 56px Fraunces;
  replaces the DropCap + `<h1>` first-letter duplication) across every surface; **sidebar redesign**
  (brand row aligned to the TopBar, workspace-switcher droplist, floating collapse toggle, agent
  mini-bar removed, collapse no longer leaves a header gap — margin tracks `sidebarCollapsed`);
  project cards put title + status chip on one row.
- **Verify** — `tsc --noEmit` clean; `vite build` clean. Pushed to `main`.

### 2026-06-28 — FE-1 simulated Hybrid SSE actually wired (liveness decay · live trace · setup→active gate)
> The rebuilt SPA had every surface but the **simulated real-time layer was inert**: `sseConnected`
> was always false, agent liveness was static, and the signature **"You trace"** pane showed the empty
> state on every task (all seed `trace: []`). This change makes the mock feel alive — the FE-1 DoD.
- **Workspace control-plane channel** — new `useMockSimulator()` hook (mounted once in `App`) marks the
  SSE link connected and, on a ~4.5s tick, decays one agent's liveness ONLINE → idle(checking) →
  offline → back, emitting `marius.liveness` store events (honours `prefers-reduced-motion`). The
  TopBar "connected" badge and Directory dots now move on their own.
- **Per-task trace channel** — the Collaboration Room streams scripted `run.delta`/`run.tool`/`run.usage`
  events into the open `in_progress` task while the wake control is "running" (bounded, pause/stop aware).
  Seeded the three in-progress tasks with realistic trace history so the pane is populated on first view.
- **setup→active gate (F2)** — `grantSeat` now recomputes status: a `setup` project flips to **active**
  once every seat is filled, emitting `project.active` (this unlocks Commission — previously the seats
  filled but the project never activated).
- **Correctness** — `approveAgent` now flips an agent **ONLINE** (+ `marius.online` event) per UC2 (was
  `idle`); Commission confirm creates the task as **`todo`** (was `pending`, which fell off the board);
  `addComment`/`appendTrace` fill `id`/`timestamp` so thread timestamps render (fixes Invalid Date).
- **Store contract** — added `setSseConnected`, `simulateLivenessTick`, `appendTrace`; broadened
  `TraceEvent` to the streamed `run.*` shape. Still a pure mock — the single `mockStore.ts` seam.
- **Verify** — `tsc --noEmit` clean; `vite build` clean. Pushed to `main`.
