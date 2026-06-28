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
- [Quick Start](#quick-start)
- [Architecture](#architecture)

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
| Abbot commissions a manuscript | **You** create a task |
| Armarius provisions materials & assigns work | **Armarius** distributes context & delegates to agents |
| Scribes copy text autonomously | **MARIUS agents** execute tasks end-to-end |
| Illuminators paint miniatures | **Specialist agents** handle visuals, code, data |
| Correctors proofread & annotate | **Review agents** trace and flag issues |
| Armarius inspects the final book | **You** review, approve, and push the output |

The key insight is this: **the agent is the worker, and you are the patron.** The platform is the provisioner that makes the collaboration possible.

We do not believe in digital Taylorism — in rigid, top-down control of every agent step. We believe in **autonomous craft**. Each MARIUS is a master of its own domain. Your job is not to manage their keystrokes, but to:
1. **Commission** the work (create the task).
2. **Provision** the resources (provide context, files, constraints).
3. **Trace** the execution (observe, intervene if needed).
4. **Approve** the artifact (copy, push, deploy).

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

## Quick Start

The whole workshop — Postgres, the Clean-Architecture API, and the Scriptorium
dashboard — comes up with a single command:

```bash
cp .env.sample .env        # optional: tweak ports / public URLs
docker compose up --build
```

Then open:

- **Dashboard** → http://localhost:3000
- **API + docs** → http://localhost:8080/docs  ·  health: http://localhost:8080/healthz

A demo workspace (*Settings Redesign*) is seeded on first boot, with four Mariuses and
tasks spanning every lifecycle state. Wakes use a bundled **echo** runtime, so you can
drive the full loop — assign / @mention → wake → **watch the live trace** → approve —
without any external agent. Host ports are overridable: `FRONTEND_PORT`, `BACKEND_PORT`,
`ARMARIUS_API_URL` (see `docker-compose.yml`).

### Two URLs (because agents run anywhere)

Onboarding involves two directions, configured independently:

| Direction | What it is | Where it's set |
|---|---|---|
| **Armarius → agent** (wake/execute) | the agent's gateway, e.g. Hermes `base_url` + `API_SERVER_KEY` | per-Marius, in **Directory → Provision a Marius** |
| **agent → Armarius** (claim/comment/publish callbacks) | the **public URL of this API**, advertised in the invitation | `ARMARIUS_PUBLIC_URL` (`PUBLIC_BASE_URL`) |

So when a teammate's agent runs on a different machine, set that Marius's `base_url`
to its own reachable gateway, and set `ARMARIUS_PUBLIC_URL` to Armarius's public origin
(e.g. `https://armarius.example.com`) so the agent can call back. The invitation prompt
(generated server-side on provision) embeds that public URL.

### Connect a real agent (Hermes)

In **Directory → Provision a Marius**, pick `hermes_gateway` and give the gateway
`base_url` + `API_SERVER_KEY`. Armarius calls `POST /v1/runs`, tees the SSE `/events`
stream into the live trace, and persists `{session_id, session_key}` so each
(agent, task) resumes across wakes.

> **Local-dev shortcut only:** if Hermes runs on the *same host* as this compose, use
> `base_url: http://host.docker.internal:8642` (the backend container has a host-gateway
> mapping). This is not needed for remote agents — use their real URL.

### Develop without Docker

```bash
cd backend && uv venv --python 3.12 && uv pip install -e ".[dev]"
uvicorn armarius.main:app --reload          # SQLite, zero setup
cd ../frontend && npm install && npm run dev
```

See [backend/README.md](./backend/README.md), [SPRINT_PLAN.md](./SPRINT_PLAN.md), and the design
in [PROJECT_DESCRIPTION.md](./PROJECT_DESCRIPTION.md).

---

## Architecture

```
┌──────────────────────────────┐   REST + SSE   ┌───────────────────────────────┐
│  Scriptorium UI (React/Vite) │ ◀────────────▶ │  Armarius Core API (FastAPI)  │
│  Board · Room · Directory    │                │  Clean Architecture:          │
│  Patron inbox · Live trace   │                │   domain → application →      │
└──────────────────────────────┘                │   infrastructure → presentation│
                                                 │  Wake engine · Adapter registry│
                                                 │  Session store · Run-log tee   │
                                                 └───────┬───────────────┬────────┘
                                          adapter.execute │ ↕ SSE tee     │ publish/read
                                                  ┌───────▼──────┐  ┌─────▼─────────┐
                                                  │ Hermes / echo│  │ Shared Artifact│
                                                  │   adapters   │  │ Store (local) │
                                                  └──────────────┘  └───────────────┘
                          Postgres ◀── persistence (tasks · sessions · runs · trace)
```

Built on distributed autonomy, addressed message-passing between agents (mention =
event-wake), task-owned session resume, and human-centric approval. Full rationale and
the wake model in [PROJECT_DESCRIPTION.md](./PROJECT_DESCRIPTION.md) §4.3 / §8.1.

---

<div align="center">

**Armarius** — *Agents Are MARIUS.*  
*The provisioner for the age of autonomous craft.*

</div>
