# Armarius — API Contract

> Status: **Design draft v3** (2026-06-27). Aligned with the approved [ARCHITECTURE.md](./ARCHITECTURE.md):
> enroll-and-wait invite lifecycle, system-only seat grants, leader-mediated commission, a
> workspace-events SSE bus, and a recency-based liveness model. **[NEW]** not yet implemented;
> **[CHANGED]** alters existing; untagged exists. Companion to [HLD.md](./HLD.md) · [LLD.md](./LLD.md) ·
> [DEV_PLAN.md](./DEV_PLAN.md) · [ARCHITECTURE.md](./ARCHITECTURE.md).
>
> Conventions: routes relative to the API base (nginx reverse-proxy). Human routes need a bearer JWT;
> agent routes need an agent token. Every resource is **scoped to the caller's workspace** —
> cross-workspace access is 404. Errors: `{ "detail": "…" }`. The Web App (browser) is the **only** SSE
> consumer — agents never use SSE (they use request/response + adapter wakes).

---

## 0. Naming

| Term | Meaning |
|---|---|
| **Workspace** | Top-level tenant owned by one user. Holds projects, agents, skills. |
| **Project** | A unit of work inside a workspace; has a **roster** of required **roles/seats**. Optionally linked to a GitHub repo (`github_url`). |
| **Role / Seat** | A named position on a project (e.g. `Backend`, `Project Leader`) with a seat count. The Patron **grants** agents into seats — a **system-only** action; agents never self-apply. |
| **Project Leader** | The single leader seat (always `seats = 1`). Drives the project: pushes agents, drives tasks, reports status, and is the agent every **task is commissioned through** (§5.3). |
| **Marius** | An agent in a workspace. May be designated the **Workspace Agent** (onboarding conductor). |
| **enrollment_code** | A per-Marius code (not a token) returned at invite time. The agent uses it once on `/agent/enroll`; the real `agent_token` is minted **on approval** and returned as the enroll response (`/agent/claim` is a recovery fallback). |
| **Liveness** | "Online" is **signal recency**, not a sticky flag. Any contact from the agent (a heartbeat, `/agent/me`, a task response) marks it ONLINE and resets the watchdog; silence decays ONLINE → CHECKING → OFFLINE. See ARCHITECTURE.md §5. |
| **Task** | A unit of work inside a project. Has **participants** (co-work), a **checklist**, **dependencies**, and an **output-artifact** gate. Created **only** through a leader-mediated commission chat (§5.3). |
| **Artifact** | A published output in the **Shared Artifact Store** (MinIO bucket `armarius`). Two kinds: **file** (uploaded content) and **link** (external URL). A task cannot be `done` until ≥1 file/link artifact is published. |
| **Workspace-events SSE** | A server→browser push stream (`GET /v1/workspaces/{ws}/events`) the Web App holds open. Carries liveness/status/approval/task events and the live trace. **Web-App-only.** |

UX north-star (from `ARMARIUS Design/`): **"You task. They collaborate. You trace."**

---

## 1. Auth (unchanged)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Register; auto-provisions the personal workspace (seeds builtin skills, **no** auto project). |
| POST | `/auth/login` | Login. |
| POST | `/auth/refresh` | Refresh JWT. |
| GET  | `/auth/me` | Current user. |

---

## 2. Workspaces

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces` | List workspaces owned by the caller. |
| POST | `/v1/workspaces` | Create a workspace (seeds builtin skills; **no** auto project). |
| GET  | `/v1/workspaces/{ws}` | Workspace detail, incl. `workspace_agent_id`. **[NEW]** |
| PUT  | `/v1/workspaces/{ws}/workspace-agent` | Body `{ "marius_id": "<uuid>" \| null }`. Designate/clear the **Workspace Agent**. When set, that Marius receives the **armarius-onboarder** skill install step (a direct adapter wake if it is online; queued otherwise). **[CHANGED]** |
| SSE  | `/v1/workspaces/{ws}/events` | **Workspace-events stream** — the Web App holds this open (JWT). Server→browser push for `marius.online`, `marius.status_changed`, `marius.liveness`, `project.active`, `task.created`, `commission.*`, approvals, and the live run trace. **[NEW — Web-App-only]** |

**[CHANGED] Onboarding side-effect**: a fresh workspace is created **empty of projects**. The old
auto-"General"-project + auto-board is removed. The user lands on a **project list** and creates a
project through onboarding (§3).

**Workspace-events SSE (§2).** The Web App opens `/v1/workspaces/{ws}/events` on workspace mount and
keeps it open. The backend pushes JSON event frames down it so the UI **never polls**. Representative
events (envelope `{ "type": "…", "data": {…} }`):

| Event | When | Web App effect |
|---|---|---|
| `marius.status_changed` | invite/enroll/approve transitions | Directory badge flips (`invited` → `pending_review` → `approved`) |
| `marius.online` / `marius.liveness` | any agent signal, or watchdog decay | liveness dot flips `ONLINE`/`CHECKING`/`OFFLINE` |
| `seat.skills_installed` | role-skill install completes | roster row re-renders |
| `project.active` | last seat granted + online | board unlocks task commission |
| `task.created` / `commission.*` | leader proposes/confirms a task | board card appears, commission modal updates |
| `run.delta` / `run.tool` / `run.usage` | agent turn streams | Collaboration Room trace panel appends |

`Last-Event-ID` is honored for resume; a dropped stream is reconnected by the Web App. Agents never
read this stream — they learn of their own changes from the request/response they make.

---

## 3. Projects + Roster + Onboarding

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces/{ws}/projects` | List projects. |
| GET  | `/v1/projects/{project_id}` | Project detail: roster, seat fill, ack state, status. **[NEW]** |
| POST | `/v1/workspaces/{ws}/projects` | Create a project **with a complete seat plan** (§3.1). **[CHANGED]** |
| PATCH | `/v1/projects/{project_id}` | Edit project fields (objective, success_metrics, target_date, `github_url`, settings). **[NEW]** |
| DELETE | `/v1/projects/{project_id}` | Delete (owner only). **[NEW]** |

### 3.1 Create project — `POST /v1/workspaces/{ws}/projects`

Two onboarding modes (manual is the priority; agent mode is Phase G, **last**). Both write here.

```jsonc
{
  "name": "Acme Web Platform",
  "description": "Public marketing site relaunch.",
  "mode": "manual",                          // "manual" | "agent"
  "objective": "Ship a new marketing site by Q3.",
  "success_metrics": { "kpi": "…" },         // optional json
  "target_date": "2026-09-30",               // optional
  "github_url": "https://github.com/acme/web", // NEW — optional repo link
  "context": "Brand guidelines in the shared store…", // free text
  "leader": {                                // exactly one Project Leader (seats = 1)
    "responsibilities": "Push agents, sequence tasks, report project status. (default behavior TBC)",
    "marius_id": "<uuid>" | null             // pick an existing agent now, OR null to add later
  },
  "roles": [                                 // 0+ worker roles, each with a seat count
    { "title": "Backend",  "seats": 2, "description": "API + data layer.",
      "skill_ids": ["<skill-uuid>"],         // optional — skills this role should carry
      "marius_ids": ["<uuid>", null] },       // optional — pre-seat existing agents (len ≤ seats)
    { "title": "Frontend", "seats": 1, "description": "UI implementation." }
  ],
  "settings": {
    "require_review_before_done": true,
    "require_approval_for_done": true,
    "comment_required_for_review": false
  },
  "onboarding_session_id": null              // present only in "agent" mode (§3.4)
}
```

**Hard composition rule (LLD §2.3):** the plan must include **exactly one** Project Leader (always
`seats = 1`) **and** ≥1 worker role with `seats >= 1`. The leader's agent may be chosen now
(`leader.marius_id`) or left `null`. Otherwise
`422 { "detail": "A project needs one Project Leader and at least one worker role." }`.

**Project Leader behavior** (default TBC): it pushes agents, drives tasks, and reports project
status — hence always exactly one seat.

On success the project is **`setup`** with any supplied agents pre-seated as **`granted`** (a
system-only grant — there is no agent apply/accept step) and the rest of the seats empty. The project
becomes **`active`** **once**, when **every seat is granted *and* every seated agent is ONLINE**
(liveness is already tracked from the invite handshake — §4.1). **The only thing `active` unlocks is
task commission** — tasks may be commissioned only while `active` (and only through the Project Leader,
§5.3); the board, roster CRUD, and seat grants all work in `setup` too. A per-project folder
`<project-slug>/` is provisioned in the MinIO bucket at creation (§7).

### 3.2 Project status

`setup` → `active` (every seat **granted and online**, reached **once** — it then **stays active**; a
worker going offline later does not revoke activation) → `archived`. Tombstone: `deleted`.

### 3.3 Roster — roles, seats, grants **[CHANGED — system-only; no apply, no accept]**

A seat grant is a **pure system action** controlled by the Patron. Agents **never self-apply** and
there is **no agent "accept"** step — being granted is the whole record, and the agent is contacted
**only** if its new role carries skills it must install (queued if the agent is offline).

| Method | Path | Purpose |
|---|---|---|
| GET    | `/v1/projects/{project_id}/roster` | Roles with `seats`, fill counts, and granted agents + liveness. |
| POST   | `/v1/projects/{project_id}/roles` | Add a role/seat to an existing project. |
| PATCH  | `/v1/projects/{project_id}/roles/{role_key}` | Change title/seats/description/skills. |
| DELETE | `/v1/projects/{project_id}/roles/{role_key}` | Remove a role (only if no agent holds it). |
| POST   | `/v1/projects/{project_id}/grant` | `{ "marius_id", "role_key" }` — Patron **grants a seat**. Creates a `granted` grant; the agent becomes a project participant (system-only). If the role carries skills and the agent is ONLINE, an adapter wake installs them; if offline, the install is **queued** and resumes on the agent's next signal. Emits `seat.skills_installed` over SSE. |
| DELETE | `/v1/projects/{project_id}/grant` | Revoke a granted seat (`{ "marius_id", "role_key" }`). |

After each grant the backend recomputes activation: **`active` when every seat is granted and every
seated agent is ONLINE** (liveness from §4.1). The transition is pushed over SSE as
`project.active`. An agent going offline **after** the project is already active does **not** roll it
back to `setup` — that is an operational matter (wake/report), not an activation gate.

### 3.4 Onboarding session (agent-assisted mode) **[NEW — Phase G, last]**

When `mode: "agent"`, the request is opened by the **Workspace Agent** after a chat.

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/workspaces/{ws}/onboarding/sessions` | Start a session; returns `{ id }`. |
| GET  | `/v1/workspaces/{ws}/onboarding/sessions/{id}` | Session state: status, transcript, collected plan. |
| POST | `/v1/workspaces/{ws}/onboarding/sessions/{id}/messages` | Append a message (patron answer / agent question). |
| POST | `/v1/workspaces/{ws}/onboarding/sessions/{id}/finalize` | Materialize the plan → creates the project (§3.1 payload). |

---

## 4. Mariuses / Agents

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces/{ws}/mariuses` | Directory of agents (with liveness). |
| POST | `/v1/workspaces/{ws}/mariuses` | Invite a Marius — Patron picks the **type** only. Returns `enrollment_code` + a copyable prompt; **no token is printed**. **[CHANGED]** |
| PATCH| `/v1/workspaces/{ws}/mariuses/{marius_id}` | Edit name/role/skills/avatar/adapter. |
| POST | `/v1/workspaces/{ws}/mariuses/{marius_id}/approve` | Patron **approves** a pending enrollment → mints `agent_token` once and **completes the held `/agent/enroll` call with it**. **[NEW]** |
| GET  | `/v1/projects/{project_id}/agents` | Project participants + role/liveness. **[NEW]** |

### 4.1 Invite lifecycle — enroll-and-wait (no token in the prompt) **[CHANGED]**

Modeled on Paperclip's openclaw-gateway invite: the Patron only **chooses the agent type**; Armarius
prepares everything and produces a single **copyable prompt** that carries the `enrollment_code` —
**never the token**. The agent enrolls and **waits on that call**; on approval the backend **returns
the token as the enroll response**, so the agent receives it on the same session it opened. A separate
`/agent/claim` exists only as a recovery fallback.

```
POST /v1/workspaces/{ws}/mariuses
  → { name, role, adapter_type, skill_ids?, adapter_config? }
  ← { id, enrollment_code, status:"invited", invite:"<copyable prompt>" }   // NO token

POST /agent/enroll          (agent, held open)   §9
  { enrollment_code, capabilities, adapter_config }
  → status "pending_review"  +  SSE marius.status_changed  →  Directory shows "pending review"
  … Patron reviews …

POST /v1/workspaces/{ws}/mariuses/{id}/approve   (Patron)
  → mint agent_token ONCE
  → COMPLETE the held enroll call, returning { agent_token } on that same response
  +  SSE marius.status_changed "approved"

# agent stores the token, installs skills (full file tree per skill), then:
GET  /agent/me            (Bearer token)   §9
  → marks liveness=ONLINE, last_seen=now   +   SSE marius.online   →  Directory dot turns ONLINE
```

- **Where the token comes from**: it does **not** exist at invite time and is **never printed in the
  prompt**. It is minted on approval and handed back **as the enroll call's response** (HTTP body for
  `hermes_gateway` / `claude_local`; the run result for `openclaw_gateway`). `/agent/claim` is a
  **fallback** for when the enroll session was lost (restart/timeout) before approval completed.
- **How the Patron knows it worked**: that first authenticated `/agent/me` callback marks the agent
  ONLINE and the backend emits `marius.online` on the workspace-events SSE (§2) — the Directory dot
  flips in real time, no polling.
- The prompt also lists each linked skill's **source URL** so the agent can fetch the full file tree
  (`SKILL.md` plus siblings) and install it. Builtin `armarius-http` teaches API calls.

---

## 5. Tasks (rich schema — Paperclip-inherited + Armarius additions)

### 5.1 Task object

```jsonc
{
  "id": "…", "project_id": "…",
  "identifier": "ARM-7",                 // [NEW] project-scoped sequence
  "title": "Implement /login",
  "description": "…",                    // markdown
  "status": "todo",                      // draft|backlog|todo|in_progress|in_review|blocked|done|cancelled
  "priority": "high",                    // [NEW] critical|high|medium|low
  "label_ids": ["…"],                    // [NEW] §5.4
  "parent_id": null,                     // [NEW] subtask link
  "blocked_by": ["<task_id>"], "blocks": ["<task_id>"], // [NEW] deps (read view)
  "checklist": [ {"id":"c1","text":"Write tests","done":false} ], // [NEW]
  "definition_of_done": "Branch merges, tests green, artifact published.", // [NEW]
  "due_date": "2026-07-15",             // [NEW]
  "created_by_user_id": "…", "created_by_marius_id": null,
  "in_progress_at": null, "completed_at": null,
  "created_at": "…", "updated_at": "…"
}
```

> The old single `assigned_marius_id` is superseded by **participants** (§5.2); kept as the primary
> participant for back-compat display.

### 5.2 Task participants (co-work) **[NEW]**

| Method | Path | Purpose |
|---|---|---|
| GET    | `/v1/tasks/{task_id}/participants` | Participants with role + liveness. |
| POST   | `/v1/tasks/{task_id}/participants` | `{ "marius_id": "…" }` — wakes the agent with task context. |
| DELETE | `/v1/tasks/{task_id}/participants` | `{ "marius_id": "…" }`. |
| POST   | `/v1/tasks/{task_id}/wake` | Wake a specific participant (`{ "marius_id": "…" }`). |

### 5.3 Task lifecycle — commission through the Project Leader (no manual form) **[CHANGED]**

There is **no manual task form**. Because every project has a **Project Leader** agent, "Commission
task" opens a **chat with the Leader**. The Patron states what they want; the Leader analyzes, asks
back when there is more than one option, breaks the work down if too large, **fills every task field**
(priority, DoD, checklist, deps, due date), **picks the workers** from the roster, and produces a
**preview** (a Task row in `draft` status). The Patron then asks the Leader to refine, or confirms.

| Method | Path | Purpose |
|---|---|---|
| POST  | `/v1/projects/{project_id}/commission` | `{ "message": "…" }` — wakes the **Project Leader in a fresh session** seeded with project + roster + workers. Returns `{ commission_id, task_id (draft), leader_reply }` and streams the leader's chat + task preview over SSE (`commission.*`). Project must be `active`. **[NEW]** |
| POST  | `/v1/commission/{commission_id}/refine` | `{ "message": "…" }` — resume the Leader session; it revises the draft task. Streamed over SSE. **[NEW]** |
| POST  | `/v1/tasks/{task_id}/confirm` | Patron accepts the preview → Task `draft → todo`, participants = Leader-picked workers, each woken with task context. Emits `task.created`. **[NEW]** |
| GET   | `/v1/projects/{project_id}/tasks` | List (filter by status/label/assignee; groupable; `draft` hidden unless the caller owns the commission). |
| GET   | `/v1/tasks/{task_id}` | Detail (participants, checklist, deps). |
| PATCH | `/v1/tasks/{task_id}` | Edit any writable field (priority, labels, checklist, description…). **[NEW]** |
| POST  | `/v1/tasks/{task_id}/status` | Transition (LLD §3). **`in_review`/`done` require a published file/link artifact (§7 gate).** Blocked-by deps must be `done` to leave `backlog`/`blocked`. **[CHANGED]** |
| POST  | `/v1/tasks/{task_id}/checklist` | Append/toggle checklist items. **[NEW]** |

- The Patron **never fills task fields** — that is the Leader's job. "You task" is literal.
- Commission is **not gated on per-worker liveness**: it only needs the project to be `active`. If a
  chosen worker is offline, that is resolved at run time by the wake/report machinery — only the
  **Leader** must be reachable (the chat is with it). The Leader may also **edit a confirmed task**
  later the same way (Patron messages a change → Leader revises).

### 5.4 Labels **[NEW]** (workspace-scoped)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces/{ws}/labels` | List. |
| POST | `/v1/workspaces/{ws}/labels` | Create `{ name, color }`. |

---

## 6. Skills (surface unchanged; tree is frontend-only)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces/{ws}/skills` | List. |
| GET  | `/v1/workspaces/{ws}/skills/{id}` | Detail (`files: {path: content}`). |
| POST | `/v1/workspaces/{ws}/skills/manual` | From template. |
| POST | `/v1/workspaces/{ws}/skills/import` | From GitHub folder URL. |
| PUT  | `/v1/workspaces/{ws}/skills/{id}` | Save edited file tree. |

Builtin skills: `armarius-http` (existing) + **`armarius-onboarder` [NEW]** (issued to the Workspace
Agent; its `SKILL.md` runs the agent-assisted onboarding, §3.4). The **nested file tree** is
frontend-only (backend already stores `files: {path: content}`).

---

## 7. Shared Artifact Store (MinIO bucket `armarius`)

The fatal failure we prevent: *an agent finishes the task but leaves the output file locally.*
Armarius **requires** every actionable task to publish its output into the Shared Store before it can
leave `in_progress`. **Backing store: MinIO (S3-compatible), bucket `armarius`** — a new compose
service. The same bucket holds task outputs **and media** (agent avatars, …). See LLD §6.

**Supported artifact kinds: `file` | `link`.**

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/tasks/{task_id}/artifacts` | List (human). |
| POST | `/v1/tasks/{task_id}/artifacts` | Publish. **[CHANGED]** |
| POST | `/agent/tasks/{task_id}/artifact` | Agent surface (token). **[CHANGED]** |
| GET  | `/v1/artifacts/{artifact_id}/content` | Download a `file` artifact (streamed from MinIO). **[NEW]** |
| POST | `/v1/workspaces/{ws}/media` | Upload media (e.g. agent avatar) to the bucket; returns object key/url. **[NEW]** |

```jsonc
// file  → content MUST be uploaded (server-stored in MinIO)
{ "name": "login-impl.txt", "kind": "file",
  "content_b64": "LS0t …",              // REQUIRED; decoded, sha256-verified, written to bucket
  "content_sha256": "…", "size_bytes": 1234 }

// link  → external location (e.g. a merged PR), no upload
{ "name": "PR #42", "kind": "link",
  "uri": "https://github.com/acme/web/pull/42" }   // REQUIRED external URL
```

- `file`: decoded, sha256-verified, written under the project's folder
  `<project-slug>/<task-id-or-slug>/<name>`; `uri` = bucket key. (Media e.g. avatars go under
  `_media/`.) The store follows the project: one folder per project, one sub-folder per task with output.
- `link`: external `uri` (PR/deploy); not stored.

**DONE gate** (`POST /tasks/{id}/status` → `in_review`/`done`): rejected with
`409 { "detail": "Publish the output artifact (file or link) first." }` unless the task has ≥1 `file`
or `link` artifact.

---

## 8. Thread, Approvals, Trace (largely unchanged)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/tasks/{task_id}/comments` | Thread (human/agent/system, @mentions). |
| POST | `/v1/tasks/{task_id}/comments` | Comment. |
| POST | `/v1/tasks/{task_id}/next-action` | Record next action. |
| POST | `/v1/tasks/{task_id}/wake` | Wake a participant (§5.2). |
| SSE  | `/v1/tasks/{task_id}/stream` | Live run trace (assistant deltas, tool calls, usage). **[NEW]** (formalize existing CDP/SSE trace). |

---

## 9. Agent-facing surface (token) — deltas

| Method | Path | Purpose |
|---|---|---|
| POST | `/agent/enroll` | `{ enrollment_code, capabilities, adapter_config }` — agent's join-back call. **Held open** until the Patron approves, then the response body carries the minted `agent_token`. **[NEW]** |
| POST | `/agent/claim` | `{ enrollment_code }` — **recovery fallback** only: returns the token if already approved and the enroll session was lost. **[NEW]** |
| GET  | `/agent/me` | Profile + directory. **Also the success signal**: this first authenticated call marks `liveness=ONLINE`, updates `last_seen_at`, and emits `marius.online` on the workspace-events SSE. **[CHANGED]** |
| GET  | `/agent/tasks/{task_id}` | Task view (thread, artifacts, participants, checklist, deps). **[CHANGED]** |
| POST | `/agent/tasks/{task_id}/claim` | Join as participant. |
| POST | `/agent/tasks/{task_id}/comment` | Comment. |
| POST | `/agent/tasks/{task_id}/status` | Transition (subject to §7 gate). |
| POST | `/agent/tasks/{task_id}/next-action` | Record next action. |
| POST | `/agent/tasks/{task_id}/artifact` | Publish artifact (§7, `file`\|`link`). |
| POST | `/agent/workspaces/{ws}/onboarding/sessions/{id}/messages` | Workspace Agent appends to an onboarding chat. **[NEW]** |

> There is **no** `/agent/projects/.../accept` — seat grants are system-only (§3.3); activation keys off
> liveness, not an agent ack.
