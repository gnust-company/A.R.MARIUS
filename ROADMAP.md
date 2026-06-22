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
- [ ] Docker Compose (Postgres + backend + frontend) — out-of-the-box `docker compose up`
- [ ] Frontend dashboard (Scriptorium UI)

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
