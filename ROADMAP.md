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

## Task lifecycle (from §4.3 wake model)

`backlog → todo → in_progress → in_review → done`  (+ `blocked`, `cancelled`).
A task may only reach `in_review`/`done` when a **published artifact** is linked (§3.4).

---

## Phase plan (mirrors PROJECT_DESCRIPTION §12)

### Phase 0 — Walking skeleton  ◀ backend complete
- [x] Decide stack + clean-arch layout + ROADMAP
- [x] Workspace / Project / Marius / Task / Thread CRUD
- [x] Session store (agent_task_sessions) keyed by (marius, adapter, task) — §4
- [x] Event-wake (assign / mention / on_demand) — §4.3 family 1
- [x] Self/liveness-wake policy (status × run table) + bounded continuation/nudge — §4.3 family 2
- [x] `hermes_gateway` adapter: `POST /v1/runs` + tee SSE `/events` → run-log + live bus — §8.1
- [x] `echo` adapter (fake runtime) so the loop is demoable without a gateway
- [x] Shared Artifact Store (local) + `publish_artifact` + "done needs artifact" rule
- [x] Agent-facing API (claim/update/comment/mention/publish/read_directory) with per-Marius token
- [x] Live trace SSE endpoint + durable run-event store
- [x] Demo seed (Settings Redesign scenario) + 20 passing tests
- [x] Docker Compose (Postgres + backend + frontend) — out-of-the-box `docker compose up`
- [x] Frontend dashboard (Scriptorium UI: Board, Collaboration Room w/ live trace, Directory, Patron inbox)

### Phase 1 — Real collaboration
- [ ] Agent Directory injected into every wake prompt — §3.1
- [ ] `@mention` → event-wake of the mentioned Marius — §3.2
- [ ] Self/liveness-wake: watchdog + continuation + status-gating + coalescing — §4.3 / §7
- [ ] Invite + skill install flow — §6.1/6.2

### Phase 2 — Governance & multi-runtime
- [ ] Roster / role gate + vetting — §6.3
- [ ] `openclaw_gateway` adapter
- [ ] Approval engine + patron inbox, wired to Hermes `/v1/runs/{id}/approval` — §8

### Phase 3 — Advanced
- [ ] `gateway_ws` streaming adapter + session broker
- [ ] Capability probe, per-gateway backpressure

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
