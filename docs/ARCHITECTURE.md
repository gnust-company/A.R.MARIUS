# Architecture — Armarius (A.R.MARIUS)

> **High-level (target) architecture** for the "multi-project + onboarding + rich task +
> collaboration" wave. Lower-level detail lives in [HLD.md](./HLD.md) · [LLD.md](./LLD.md) ·
> [API_CONTRACT.md](./API_CONTRACT.md) · [DEV_PLAN.md](./DEV_PLAN.md) — if they disagree, **those win**.
> Diagrams favor Mermaid; the system is presented **by use case** — how the system runs for each one.

Armarius is a **provisioner for cross-team multi-agent collaboration**. Core philosophy (from
`ARMARIUS Design/`):

> **"You task. They collaborate. You trace."** — the Patron tasks, agents collaborate, the Patron traces.

Two distinct planes:

1. **Provisioning / orchestration (synchronous, REST)** — create a project → staff its roster →
   commission tasks → wake agents.
2. **Execution (real-time, via an adapter → the runtime's gateway + SSE)** — agents run a task,
   collaborate in the thread, publish output, and the Patron watches the live trace.

---

## 1. Component overview

```mermaid
flowchart TB
  subgraph Patron["Patron (human)"]
    UI["Web SPA<br/>React + Vite"]
  end

  subgraph Edge["nginx reverse-proxy"]
    NX["relative API URLs"]
  end

  subgraph App["FastAPI app (armarius.presentation)"]
    H["Human API (JWT)"]
    A["Agent API (agent token)"]
    WAKE["Wake engine"]
    SSE["SSE live run trace"]
  end

  subgraph Reg["Adapter Registry (one bounded execute contract)"]
    AD1["hermes_gateway"]
    AD2["openclaw_gateway"]
    AD3["claude_local"]
    AD4["echo (test)"]
  end

  subgraph Runtime["Agent runtime (a Marius instance)"]
    AGENT["Agent worker<br/>via its own gateway"]
  end

  subgraph Stores
    PG[("PostgreSQL<br/>metadata, roster, tasks, thread, trace-log")]
    MN[("MinIO bucket 'armarius'<br/>per-project artifact folders + media")]
  end

  UI --> NX --> H
  H --> PG
  H --> MN
  WAKE --> Reg
  Reg --> AGENT
  AGENT -- "claim / comment / status / publish / accept (token)" --> NX --> A
  A --> PG
  A --> MN
  AGENT -- "streamed events" --> WAKE
  WAKE --> SSE --> UI
```

- **Web SPA** talks to FastAPI through nginx (relative URLs; nothing host-specific baked into the bundle).
- **Human API** (JWT): workspaces, projects, roster, tasks, thread, artifacts, skills — everything the Patron does.
- **Agent API** (agent token): the agent's own actions — claim a task, comment, change status,
  publish an artifact, accept a seat.
- **Wake engine → Adapter Registry**: Armarius **owns the wake loop**; to run a bounded turn it
  resolves the agent's `adapter_type` to an adapter and calls `execute(ctx)`. The adapter bridges to
  that runtime's gateway and tees streamed events back for the live trace.
- **PostgreSQL** is the source of truth for metadata, roster, tasks, thread, trace-log.
- **MinIO** (bucket `armarius`) is the Shared Artifact Store — a **folder per project** holding task
  outputs, plus media (agent avatars). A task **cannot reach done** until its output is here.

---

## 2. Adapters — one contract, many runtimes

Armarius does **not** bind to a single agent vendor. Every runtime is wrapped in the same bounded
`MariusAdapter.execute(ctx)` contract (`application/ports/adapter.py`); the `AdapterRegistry` resolves
a Marius's `adapter_type` to its implementation. **The backend always calls through the adapter** — it
never special-cases a vendor.

```mermaid
flowchart LR
  WAKE["Wake engine"] --> REG["AdapterRegistry.get(adapter_type)"]
  REG --> H["HermesGatewayAdapter"]
  REG --> O["OpenClawGatewayAdapter"]
  REG --> C["ClaudeLocalAdapter"]
  REG --> E["EchoAdapter (test)"]
  H -- "POST /v1/runs + tee /events" --> HGW["Hermes gateway"]
  O -- "gateway invoke" --> OGW["OpenClaw gateway"]
  C -- "CLI / local session" --> CLI["Claude Code CLI"]
  HGW --> RT["Agent runtime"]
  OGW --> RT
  CLI --> RT
```

| `adapter_type` | Runtime | Transport | Resumable | Status |
|---|---|---|---|---|
| `hermes_gateway` | Hermes gateway | HTTP + tee SSE `/events` | yes (state.db) | **reference, verified** |
| `openclaw_gateway` | OpenClaw gateway | gateway invoke | yes | planned |
| `claude_local` | Claude Code CLI | local session | yes (native `session_id`) | planned |
| `echo` | fake runtime | in-process | n/a | tests/demo |

Each adapter returns the runtime's **native session handle** (`ExecResult.session_params`) so the
next wake on the same task can **resume**. Non-resumable runtimes (`capabilities.resumable=false`)
get a cold start with a transcript replay injected into the prompt.

---

## 3. Service topology (Docker)

The agent runtime is a **single block** reached **through its gateway via an adapter**. Armarius never
calls a gateway directly from the backend — it goes through the registry/adapter. The same agent block
calls **back** into the Agent API (token) for its task actions.

```mermaid
flowchart LR
  Browser([":3000 browser"]) --> NX

  subgraph compose["docker compose"]
    NX["nginx"]
    FE["frontend (Vite)"]
    BE["backend (uvicorn)<br/>+ Adapter Registry"]
    PG[("postgres:5432")]
    MN[("minio:9000<br/>bucket armarius / console :9001")]
  end

  NX --> FE
  NX -- "/v1, /agent, /static" --> BE
  BE --> PG
  BE --> MN

  subgraph agent["Agent runtime (one block)"]
    AG["Marius worker"]
  end

  BE -- "execute() via adapter -> runtime gateway" --> AG
  AG -- "Agent API (token) via nginx" --> NX
```

| Service | Role | Port |
|---|---|---|
| `nginx` | reverse-proxy, relative URLs | 3000 |
| `frontend` | React SPA | (internal) |
| `backend` | FastAPI + Adapter Registry + Wake engine | 8080 |
| `postgres` | metadata | 5432 |
| `minio` | object store, bucket `armarius` | 9000 / console 9001 |
| Agent runtime | external; reached through its gateway via an adapter | (vendor) |

> The bucket `armarius` is created on backend startup if missing. The Agent runtime is one logical
> block: Armarius drives it **through an adapter → its gateway** (`execute()`), and the agent reports
> task actions **back** through the Agent API.

---

## 4. Source layout (target)

```
backend/armarius/
├── domain/entities/        Workspace, Project, Role, SeatGrant, Marius, Skill,
│                           Task, TaskParticipant, ChecklistItem, TaskDependency,
│                           Label, OnboardingSession, Artifact, Comment, Run, Session
├── application/
│   ├── ports/adapter.py    MariusAdapter / AdapterRegistry (execute contract)
│   └── use_cases/          workspaces, projects(NEW), roster(NEW), tasks, skills,
│                           onboarding, participants(NEW), artifacts
├── infrastructure/
│   ├── database/models.py  ORM (*Model)
│   ├── repositories/       SQLAlchemy repos
│   ├── artifacts/store.py  MinIO (S3) store (NEW)
│   ├── adapters/           registry + hermes_gateway + echo (+ openclaw, claude planned)
│   └── alembic/            migrations (NEW)
├── presentation/
│   ├── api/                auth, workspaces, projects(NEW), tasks, agent, artifacts
│   ├── schemas.py          pydantic DTOs
│   └── container.py        composition root (DI)
└── shared/                 config, clock, logging

frontend/src/
├── pages/    ProjectLanding, ProjectBoard, Onboarding, CollaborationRoom,
│             Skills, SkillEditor, Directory, Approvals, Workspaces, Auth
├── components/  NestedFileTree, RosterPanel, ParticipantBar, Checklist, SeatDialog, Modal…
├── api.ts, store.tsx, auth.tsx, i18n.tsx, ui.tsx, App.tsx
```

---

## 5. Use cases — how the system runs

Ordered along the natural journey: **auth → people → skills → project → staffing → work → output →
advanced onboarding**. Agent-side steps show what the runtime (Hermes / OpenClaw / Claude, via its
adapter) does.

### UC1 — Register & Login

```mermaid
sequenceDiagram
  participant U as User
  participant API as Human API
  participant DB as PostgreSQL

  U->>API: POST /auth/register (email, password)
  API->>DB: insert User
  API->>DB: ensure_personal_workspace (name Personal, seed builtin skills)
  API-->>U: JWT + user
  Note over U,DB: No auto project. User lands on the project list (empty).
  U->>API: POST /auth/login
  API-->>U: JWT
```

### UC2 — Invite an agent into the workspace

```mermaid
sequenceDiagram
  participant P as Patron
  participant API as Human API
  participant DB as PostgreSQL
  participant AG as Agent runtime via adapter

  P->>API: POST /workspaces/WS/mariuses (name, role, adapter_type, skills)
  API->>DB: insert Marius (+ agent_token)
  API-->>P: invite prompt (credentials, skill installs, API base)
  Note over P,AG: Patron hands the invite prompt to the agent runtime
  AG->>API: GET /agent/me (token)
  API-->>AG: profile + directory
  Note over AG: Agent saves its token, installs listed skills, goes online
```

### UC3 — Designate the Workspace Agent role to a specific agent

```mermaid
sequenceDiagram
  participant P as Patron
  participant API as Human API
  participant DB as PostgreSQL
  participant AG as Agent runtime

  P->>API: PUT /workspaces/WS/workspace-agent (marius_id)
  API->>DB: set workspace_agent_id
  API->>DB: add armarius-onboarder skill to that Marius
  API-->>P: updated invite prompt (now lists the onboarder skill)
  Note over P,AG: Patron re-sends the invite; the agent installs armarius-onboarder
  AG->>API: GET /agent/me (token)
  API-->>AG: profile now carries the onboarder duty
```

### UC4 — Author or import a skill (nested file tree)

```mermaid
flowchart LR
  P["Patron"] -->|"POST /skills/manual (name)"| API["Human API"]
  P -->|"POST /skills/import (github_url)"| API
  API -->|"manual: generate SKILL.md template"| DB[("Skill.files {path:content}")]
  API -->|"import: GitHub Contents API, only the SKILL.md folder"| GH["github.com"]
  GH --> DB
  P --> UI["NestedFileTree (VSCode-style collapsible folders)"]
  UI -->|"PUT /skills/ID (edited tree)"| API
```

- A skill is a file tree rooted at `SKILL.md`; name/description come from the YAML frontmatter.
- The **nested tree** is a frontend concern — the backend already stores `files: {path: content}`.

### UC5 — Create a project + staff the roster (the only setup→active difference is task-assignment)

```mermaid
sequenceDiagram
  participant P as Patron
  participant API as Human API
  participant DB as PostgreSQL

  P->>API: POST /workspaces/WS/projects (leader, roles[], github_url, context)
  API->>API: validate hard rule (exactly one leader seats=1, at least one worker role)
  API->>DB: insert Project status=setup + Roles
  Note over API,DB: MinIO project folder armarius/<project-slug>/ is provisioned
  API-->>P: 201 project (setup)
  Note over P: In setup the Patron can do everything EXCEPT assign tasks
```

- **Hard rule**: exactly one **Project Leader** (`seats = 1`; pick an existing agent now or leave it
  empty for later) plus at least one worker role (name, description, optional skills, seat count).
- **The only behavioral difference between `setup` and `active`**: tasks can be **assigned/commissioned
  only when the project is `active`**. Everything else (view the board, build the roster, vet seats)
  works in `setup` too.

### UC6 — Agent applies for and accepts a seat (vetting → active)

```mermaid
sequenceDiagram
  participant AG as Agent runtime
  participant API as Agent / Human API
  participant P as Patron
  participant DB as PostgreSQL

  AG->>API: POST /projects/P/apply (role_key)
  API->>DB: SeatGrant status=pending
  P->>API: POST /projects/P/grant (marius_id, role_key)
  API->>DB: SeatGrant status=granted (agent is now a participant)
  AG->>API: POST /projects/P/accept (token) — online and accepts
  API->>DB: SeatGrant status=acknowledged
  API->>API: recompute_active (all seats acknowledged?)
  API->>DB: Project status=active
  Note over P: Now the Patron may assign tasks
```

### UC7 — Commission a task, agents co-work, Patron traces

```mermaid
sequenceDiagram
  participant P as Patron
  participant API as Human API
  participant DB as PostgreSQL
  participant WAKE as Wake engine
  participant ADP as Adapter by adapter_type
  participant AG as Agent runtime

  P->>API: POST /projects/P/tasks (priority, checklist, DoD, deps)
  API->>API: assert project.status == active
  API->>DB: insert Task ARM-n + checklist + deps + labels
  P->>API: POST /tasks/T/participants add A then add B
  API->>WAKE: wake A and B with task context
  WAKE->>ADP: execute(ctx) per agent
  ADP->>AG: run one bounded turn via the runtime gateway
  AG-->>ADP: streamed events (deltas, tool calls, usage)
  ADP-->>WAKE: tee events
  WAKE-->>P: SSE /tasks/T/stream (live trace)
  AG->>API: POST /agent/tasks/T/comment and mention B (token)
  AG->>API: POST /agent/tasks/T/next-action
```

### UC8 — Publish output, then the DONE gate (no local-only output)

```mermaid
flowchart LR
  AG["Agent"] -->|"POST /artifact kind=file (content_b64)"| SVC["ArtifactService"]
  AG -->|"POST /artifact kind=link (uri)"| SVC
  SVC -->|"file: decode + verify sha256"| MN[("MinIO armarius/&lt;project&gt;/&lt;task&gt;/&lt;name&gt;")]
  SVC -->|"link: external URL (PR / deploy)"| EXT["external location"]
  MN --> DB[("Artifact row uri=key stored=true")]
  EXT --> DB2[("Artifact row uri stored=false")]
  AG -->|"POST /tasks/T/status done"| GATE{"has a file or link artifact?"}
  GATE -->|no| X["409 — publish first"]
  GATE -->|yes| OK["done"]
```

- A **file** artifact must **upload content** (stored under the project folder in MinIO); a **link**
  points to an external location (a merged PR). A task **cannot** reach `in_review`/`done` without at
  least one — output never stays on the agent's local disk.

### UC9 — Agent-assisted onboarding (Phase G, last / optional)

```mermaid
sequenceDiagram
  participant P as Patron
  participant API as Human API
  participant WA as Workspace Agent
  participant DB as PostgreSQL

  P->>API: POST /onboarding/sessions (mode agent)
  API-->>P: session id
  loop structured Q and A
    WA->>P: question (goal, leader, worker roles, counts, context)
    P->>API: POST /sessions/ID/messages (answer)
  end
  WA->>API: POST /sessions/ID/finalize (roles, leader, context)
  API->>API: ProjectService.create (same hard rule as manual)
  API->>DB: Project status=setup + Roles
  API-->>P: project created
```

---

## 6. Data model

```mermaid
erDiagram
  workspace ||--o{ project : owns
  workspace ||--o{ marius : has
  workspace ||--o{ label : has
  workspace ||--o{ skill : has
  workspace ||--o| onboarding_session : runs
  project ||--o{ role : declares
  project ||--o{ task : contains
  role ||--o{ seat_grant : seats
  seat_grant }o--|| marius : fills
  task ||--o{ task_participant : has
  task_participant }o--|| marius : works
  task ||--o{ checklist_item : has
  task ||--o{ task_dependency : blocks
  task ||--o{ artifact : outputs
  task ||--o{ comment : threads
  task ||--o{ run : traces
  task }o--o{ label : tagged
  task ||--o{ task : parent_subtask

  project {
    uuid id PK
    uuid workspace_id FK
    string status "setup-active-archived"
    string github_url "optional"
    string objective
    json settings
  }
  role {
    uuid id PK
    string key
    int seats "leader=1"
    bool is_leader
    string responsibilities
  }
  seat_grant {
    uuid id PK
    string status "pending-granted-acknowledged-revoked"
    datetime acknowledged_at
  }
  task {
    uuid id PK
    string identifier "ARM-n"
    string status
    string priority
    string definition_of_done
  }
  artifact {
    uuid id PK
    string kind "file-link"
    string uri "MinIO key or external URL"
    bool stored
  }
```

> Field/enum detail: [LLD.md](./LLD.md) §2.

### Shared store layout (MinIO bucket `armarius`)

The store follows the project: each project owns a top-level folder; each task with output writes
under it, keyed by task id (or slug). Media lives apart.

```
armarius/                              (bucket)
├── <project-slug>/                    one folder per project (created at project creation)
│   ├── <task-id-or-slug>/             one folder per task that produced output
│   │   ├── login-impl.txt             a file artifact (content-stored)
│   │   └── ...
│   └── <task-id-or-slug>/...
└── _media/
    └── avatars/<marius_id>.<ext>      agent avatars and other media
```

---

## 7. Phase roadmap (A→F is the main flow; G trails)

```mermaid
flowchart LR
  A["A. Alembic + MinIO"] --> C["C. Project + roster"]
  A --> E["E. Rich task + artifact gate"]
  B["B. Skill nested tree"]
  C --> D["D. Manual onboarding + Workspace Agent"]
  C --> E
  E --> F["F. Collaboration Room"]
  D --> G["G. Agent onboarding (last)"]
  F --> G
```

| Phase | Work | Depends on |
|---|---|---|
| A | Alembic + MinIO (bucket `armarius`) | — |
| B | Skill nested file tree (frontend) | — |
| C | Project layer + roster (roles/seats, ack→active) | A |
| D | Manual onboarding + designate Workspace Agent | C |
| E | Rich task schema + Output-Artifact gate (MinIO) | A, C |
| F | Collaboration Room (participants + thread + trace) | E |
| G | Agent-assisted onboarding chat | D, F (last) |

---

## 8. Key design decisions

1. **Vendor-neutral via adapters** — every runtime (Hermes, OpenClaw, Claude CLI, echo) is wrapped in
   one bounded `execute()` contract resolved through the `AdapterRegistry`. Armarius **owns the wake
   loop**; the runtime is just an executor reached through its gateway via an adapter.
2. **Roster/seats are the backbone** — a project has exactly one **Project Leader** (pick now or leave
   empty) plus worker roles (optional skills + seat counts). It becomes `active` only when **every seat
   is acknowledged**; the **sole** active-vs-setup difference is being allowed to assign tasks.
3. **Collaboration is first-class** — a task has **multiple participants** co-working in the thread, not
   a lone assignee.
4. **Shared store prevents local-only output** — a `file` artifact must upload content into the
   project's MinIO folder; a `link` points outward; a task **cannot reach done** without one. This is
   the decisive difference from other multi-agent systems.
5. **"You trace"** — the **live run trace** (SSE) is retained in the Collaboration Room; it is an
   Armarius signature.
6. **Workspace Agent** — onboarding may be driven by a designated agent via chat, but it is a
   nice-to-have shipped **last (Phase G)**.
7. **Clean Architecture** — pure domain; all IO/HTTP in infrastructure/presentation; a single
   composition root.
8. **Alembic** — replaces `create_all()` so schema changes ship without nuking data.

---

## 9. Run & health

```bash
# Docker (recommended)
docker compose up --build
# UI: http://localhost:3000   API (via nginx): /v1, /agent   MinIO console: :9001

# Backend (local dev)
cd backend && uv run uvicorn armarius.presentation.main:app --reload --port 8080
cd frontend && npm run dev

# Migrations
cd backend && uv run alembic upgrade head
```

Health (after Phase A): `GET /health` → `{ "status": "ok", "db": "up", "minio": "up" }`.
