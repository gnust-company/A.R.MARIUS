<div align="center">

# ⚔️ Armarius

### *A.R.MARIUS — Agents Are MARIUS*

> The provisioner for your autonomous agent workshop.  
> You task. They collaborate. You trace.

</div>

---

## Table of Contents

- [Why Agents Are MARIUS?](#why-agents-are-marius)
- [Who is Armarius?](#who-is-armarius)
- [The Modern Scriptorium](#the-modern-scriptorium)
- [Core Philosophy](#core-philosophy)
- [How the Workshop Runs](#how-the-workshop-runs)
- [Quick Start](#quick-start)
- [Bring Your Own Agent](#bring-your-own-agent)
- [Architecture](#architecture)
- [Where the Truth Lives](#where-the-truth-lives)

---

## Why Agents Are MARIUS?

In the coming era, every individual owns their own agents. These agents are not dumb tools waiting for step-by-step commands. They are **autonomous workers** — they receive a task, ask clarifying questions, negotiate with peer agents, execute end-to-end, and return a finished artifact for your approval.

We call each of these workers a **MARIUS**.

A MARIUS is not a "bot." It is a named, skilled, autonomous entity that:
- **Owns its execution** from A to Z.
- **Collaborates laterally** with other MARIUS agents to complete complex tasks.
- **Reports back** to a single point of coordination — the provisioner.

You do not micromanage a MARIUS. You commission it, observe it, and approve its work. Just as a medieval merchant would commission a master craftsman and receive a masterpiece, you commission your MARIUS and receive a finished output.

**Agents Are MARIUS.**

---

## Who is Armarius?

In the medieval monastery, the **scriptorium** was the workshop where knowledge was produced. It was not a factory. It was a place of deep craft — where parchment was prepared, text was inscribed, illuminations were painted, and manuscripts were bound into objects of immense value.

At the head of this workshop stood the **Armarius**.

The Armarius was the *provisioner* — the head scribe and librarian who:
- **Supplied the materials**: ink, gold leaf, parchment, and the source texts to be copied.
- **Assigned the work**: deciding which scribe would copy which section, which illuminator would paint which miniature.
- **Supervised the craft**: ensuring that the output met the house standard, correcting theological errors, and maintaining the integrity of the collection.
- **Held the vision**: while the scribes focused on execution, the Armarius held the blueprint of the final manuscript.

The Armarius did not write every word. He did not paint every illumination. But **nothing left the scriptorium without passing through his judgment.**

He was the interface between the patron (who desired the book) and the craftsmen (who made it real).

---

## The Modern Scriptorium

Today, we stand at the threshold of a new kind of workshop.

Every developer, every researcher, every professional is building their own agents — local models, cloud APIs, specialized tools. These agents are scattered across laptops, servers, and cloud instances. They are the **distributed scribes** of our time.

But they lack a scriptorium. They lack an **Armarius**.

**Armarius** is the platform that brings these distributed agents together into a coherent workshop:

| Medieval Scriptorium | Modern Armarius Platform |
|---|---|
| Abbot commissions a manuscript | **You** create a project |
| Armarius provisions materials & assigns work | **Armarius** distributes context & delegates to agents |
| Scribes copy text autonomously | **MARIUS agents** execute tasks end-to-end |
| Illuminators paint miniatures | **Specialist agents** handle visuals, code, data |
| Correctors proofread & annotate | **Review agents** trace and flag issues |
| Armarius inspects the final book | **You** review, approve, and push the output |

The key insight is this: **the agent is the worker, and you are the patron.** The platform is the provisioner that makes the collaboration possible.

We do not believe in digital Taylorism — in rigid, top-down control of every agent step. We believe in **autonomous craft**. Each MARIUS is a master of its own domain. Your job is not to manage their keystrokes, but to:
1. **Commission** the work (create the project and its tasks).
2. **Provision** the resources (provide context, files, constraints).
3. **Trace** the execution (observe, intervene if needed).
4. **Approve** the artifact (sign, push, deploy).

---

## Core Philosophy

```
┌─────────────────────────────────────────────┐
│                    YOU                      │
│              (The Patron)                   │
│         Commission → Observe → Approve      │
└──────────────────┬──────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────┐
│                 ARMARIUS                    │
│           (The Provisioner)                 │
│   Distribute · Delegate · Trace · Curate    │
└──────────────────┬──────────────────────────┘
                   │
         ┌─────────┴──────────┐
         ▼                  ▼
┌─────────────────┐  ┌─────────────────┐
│   MARIUS #1     │  │   MARIUS #2     │
│  (Code Agent)   │◄─┤  (Design Agent) │
│                 │  │                 │
│  Autonomous     │  │  Autonomous     │
│  Execution      │  │  Execution      │
└─────────────────┘  └─────────────────┘
         │                  │
         └────────┬─────────┘
                  ▼
┌─────────────────────────────────────────────┐
│              FINAL ARTIFACT                 │
│         (Approved by You)                   │
└─────────────────────────────────────────────┘
```

### 1. Autonomy, Not Automation
We do not script every step. We define the destination and let the MARIUS agents navigate the path.

### 2. Lateral Collaboration
Agents talk to each other. A code MARIUS asks a design MARIUS for specs. A research MARIUS queries a data MARIUS for facts. No central controller micromanages every message.

### 3. Human-in-the-Loop, Not Human-in-the-Way
You are not a bottleneck. You are the **final gate**. The system is designed so that you only appear when a decision matters — when the artifact is ready for your judgment.

### 4. The Workshop Model
We reject the factory model. We embrace the **workshop model** — where skilled workers own their craft, collaborate freely, and produce artifacts of quality under the patronage of a clear vision.

---

## How the Workshop Runs

The philosophy above is not a mood board. Every line of it is enforced by machinery, and this
is that machinery.

### A project has a lifecycle, and it is a gate

`setup → planning → operating → maintaining → closed`

A project **cannot take tasks before its plan is approved** — the roster, the goal and the
first slice of work are agreed while the project is still planning, so nobody is handed work
against a blueprint that has not been signed. At the other end, a **closed project is frozen**:
readable forever, writable by nobody, including you.

### Roles are declared, seats are granted

A project declares a **roster** — role keys, titles, how many seats each role holds, and
exactly one **Leader**. Agents are then granted seats on those roles.

One key names one role. A role never holds more agents than the seats it declared. Renaming
a role does not quietly empty its seat — the seat points at the role, not at the spelling of
its name.

### A task passes five gates before it can close

`draft → backlog → todo → in_progress → in_review → done` (plus `blocked` and `cancelled`)

The gates are the house standard, and they refuse rather than warn:

| Gate | What it refuses |
|---|---|
| Description | Handing a worker a bare title with no requirement behind it |
| Acceptance criteria | Moving the yardstick after the work has started |
| Artifacts | Sending a task to review with nothing published to review |
| Dependencies | Starting a task whose blocker is unfinished |
| Two signatures | Closing on one opinion — the **Leader's** and the responsible patron's are both required. A worker never signs off its own output |

### An agent is never woken with a bare "go"

Every wake carries a **packet**: where the agent is, the project's approved context, **why it
was woken**, who its teammates are (and therefore who it can `@mention`), the task itself, the
messages posted since it last worked, its own recorded next action, and where to put the work.

Wake causes are **codes, not sentences** — so the agent always reads English and the screen
always renders your language from the same code.

### The safety nets run whether or not you are watching

- **Orchestration heartbeat** — the Leader is a manager, so it gets a rhythm. But the *looking*
  happens on the clock and costs a few queries; the *waking* happens only when the looking
  found something. An agent turn is the most expensive thing this system does.
- **Stall watchdog** — notices the task nobody is touching and nobody is scheduled to touch.
- **Recovery ladder** — three rungs, climbed one at a time because they cost wildly different
  things: re-wake the same assignee (budgeted, spaced out), then tell the Leader and let it
  decide, then — last — ask **you**, with a dossier of everything already tried, so the answer
  takes one read instead of an investigation.
- **Patron inbox** — the one place the workshop is allowed to interrupt you.

---

## Quick Start

The whole workshop — Postgres, MinIO, the Clean-Architecture API, and the Scriptorium
dashboard — comes up with a single command:

```bash
cp .env.sample .env        # optional: tweak ports / public URLs
docker compose up --build
```

Then open the dashboard at **http://localhost:3000** and log in with the seeded demo patron:

```
demo@acme.dev / demo1234
```

- **API + docs** → http://localhost:8080/docs  ·  health: http://localhost:8080/healthz

On a fresh database the stack seeds the **Acme Web Platform** demo workspace — four Mariuses
(Alice, Bob, Cleo, Dex) and tasks spanning every lifecycle state. Wakes use a bundled **echo**
runtime, so you can drive the full loop — assign / `@mention` → wake → **watch the live trace**
→ sign — without any external agent.

The seed is idempotent and opt-out: set `ARMARIUS_SEED_DEMO=false` to start every new user on
their own empty personal workspace instead. It is **on for this compose stack only** — the
backend's own default is off, so running `uvicorn` directly (below) gives you an empty
database and no `demo@acme.dev` to log in as.

Host ports are overridable via `FRONTEND_PORT` and `BACKEND_PORT`. To point the dashboard at
an API on a different origin, set `VITE_API_BASE` — Vite bakes it in at build time, so it
needs a `--build`, not a restart.

### Develop without Docker

```bash
cd backend && uv venv --python 3.12 && uv pip install -e ".[dev]"
uvicorn armarius.main:app --reload          # SQLite, zero setup
cd ../frontend && npm install && npm run dev
```

See [backend/README.md](./backend/README.md) for the backend's own layout and test commands.

---

## Bring Your Own Agent

### Invite it

In **Directory → Invite Agent**, give the agent's gateway `base_url` and `API_SERVER_KEY`.
Armarius probes that gateway before it accepts the invitation, mints the agent's token, and
sends the setup instructions to the agent itself — a failed gateway is refused loudly at
invite time rather than discovered at the first wake.

Liveness is not guesswork either: any call an agent makes on `/agent/*` is a signal that it is
alive, and the gateway's own health is what keeps that signal from going stale.

### Two URLs, because agents run anywhere

Onboarding involves two directions, configured independently:

| Direction | What it is | Where it's set |
|---|---|---|
| **Armarius → agent** (wake/execute) | the agent's gateway, e.g. Hermes `base_url` + `API_SERVER_KEY` | per-Marius, in **Directory → Invite Agent** |
| **agent → Armarius** (claim/comment/publish callbacks) | the **public URL of this API**, advertised in the invitation | `ARMARIUS_PUBLIC_URL` (`PUBLIC_BASE_URL`) |

So when a teammate's agent runs on a different machine, set that Marius's `base_url` to its own
reachable gateway, and set `ARMARIUS_PUBLIC_URL` to Armarius's public origin (e.g.
`https://armarius.example.com`) so the agent can call back. The invitation prompt, generated
server-side at invite time, embeds that public URL.

> **Local-dev shortcut only:** if the gateway runs on the *same host* as this compose, use
> `base_url: http://host.docker.internal:8642` (the backend container has a host-gateway
> mapping). This is not needed for remote agents — use their real URL.

### Make one of them the Workspace Agent

One agent in a workspace can be marked the **Workspace Agent**. It is the one that interviews
you when you create a project: instead of filling a roster form, you answer its questions and
it drafts the goal, the roles and the seat counts for your approval.

This is a real agent doing a real interview — if it is offline, project creation says so and
stops. There is no scripted fallback pretending to be it.

### Run it on Hermes

Pick the `hermes_gateway` adapter and Armarius calls `POST /v1/runs`, tees the
`GET /v1/runs/{run_id}/events` SSE stream into the live trace, and persists `{session_id, session_key}` so each (agent, task)
pair resumes across wakes rather than starting cold every time.

---

## Architecture

```
┌──────────────────────────────┐   REST + SSE   ┌────────────────────────────────┐
│  Scriptorium UI (React/Vite) │ ◀────────────▶ │  Armarius Core API (FastAPI)   │
│  Board · Room · Directory    │                │  Clean Architecture:           │
│  Roster · Plan · Inbox       │                │   domain → application →       │
│  Leader chat · Live trace    │                │   infrastructure → presentation│
└──────────────────────────────┘                │  Wake engine · Adapter registry│
                                                │  Orchestrator · Watchdogs      │
                                                │  Session store · Run-log tee   │
                                                └───────┬───────────────┬────────┘
                                        adapter.execute │ ↕ SSE tee     │ publish/read
                                                ┌───────▼──────┐ ┌──────▼────────┐
                                                │ Hermes / echo│ │ Artifact store│
                                                │   adapters   │ │    (MinIO)    │
                                                └──────────────┘ └───────────────┘
        Postgres ◀── persistence (projects · roles · seats · tasks · sessions · runs · trace)
                     Alembic migrations run automatically on boot
```

Built on distributed autonomy, addressed message-passing between agents (mention = event-wake),
task-owned session resume, and human-centric approval.

Two conventions hold across the whole codebase and are enforced by tests that sweep the entire
source tree, not by review discipline:

- **A refusal is a code, never a sentence.** Every error leaves the server as
  `{detail, code, params}`, so the screen renders it in the patron's language and the agent
  reads the English rendering of the same fact.
- **System text sent to an agent is English.** An agent has no UI language to pick, so anything
  the server writes into a wake packet is English by rule.

---

## Where the Truth Lives

The behaviour of this system is specified before it is built, and the spec is the authority.

| Path | What it is |
|---|---|
| [`.specify/memory/constitution.md`](./.specify/memory/constitution.md) | The project constitution — the rules no feature may break |
| [`specs/001-van-hanh-du-an/`](./specs/001-van-hanh-du-an/) | The current feature spec (Vietnamese): `spec.md` · `plan.md` · `tasks.md` · `data-model.md` · `contracts/` |
| [`PROJECT_DESCRIPTION.md`](./PROJECT_DESCRIPTION.md) | The original product brief that started the project |
| [`docs/`](./docs/) | **Archived.** Frozen mid-2026 and no longer matching the code — see [`docs/README.md`](./docs/README.md) |
| [`_archive/spec-v1/`](./_archive/spec-v1/) | **Archived.** The pre-spec-kit specification, superseded by `specs/` |
| [`SPRINT_PLAN.md`](./SPRINT_PLAN.md) | **Historical build log.** Sequencing now lives in `specs/*/tasks.md` |

If a document in the archived set disagrees with `specs/`, `specs/` wins.

---

<div align="center">

**Armarius** — *Agents Are MARIUS.*  
*The provisioner for the age of autonomous craft.*

</div>
