# Armarius — API Contract

> Status: **Design draft v2** (2026-06-26). Interface for the "multi-project + onboarding + richer
> task + collaboration" wave. **[NEW]** not yet implemented; **[CHANGED]** alters existing; untagged
> exists. Companion to [HLD.md](./HLD.md) · [LLD.md](./LLD.md) · [DEV_PLAN.md](./DEV_PLAN.md) ·
> [ARCHITECTURE.md](./ARCHITECTURE.md).
>
> Conventions: routes relative to the API base (nginx reverse-proxy). Human routes need a bearer JWT;
> agent routes need an agent token. Every resource is **scoped to the caller's workspace** —
> cross-workspace access is 404. Errors: `{ "detail": "…" }`.

---

## 0. Naming

| Term | Meaning |
|---|---|
| **Workspace** | Top-level tenant owned by one user. Holds projects, agents, skills. |
| **Project** | A unit of work inside a workspace; has a **roster** of required **roles/seats**. Optionally linked to a GitHub repo (`github_url`). |
| **Role / Seat** | A named position on a project (e.g. `Backend`, `Project Leader`) with a seat count. Agents fill seats after vetting + acknowledgment. |
| **Project Leader** | The single leader seat (always `seats = 1`). Drives the project: pushes agents, drives tasks, reports status (default behavior TBC). |
| **Marius** | An agent in a workspace. May be designated the **Workspace Agent** (onboarding conductor). |
| **Task** | A unit of work inside a project. Has **participants** (co-work), a **checklist**, **dependencies**, and an **output-artifact** gate. |
| **Artifact** | A published output in the **Shared Artifact Store** (MinIO bucket `armarius`). Two kinds: **file** (uploaded content) and **link** (external URL). A task cannot be `done` until ≥1 file/link artifact is published. |

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
| PUT  | `/v1/workspaces/{ws}/workspace-agent` | Body `{ "marius_id": "<uuid>" \| null }`. Designate/clear the **Workspace Agent**. When set, that Marius receives the **armarius-onboarder** skill install step. **[NEW]** |

**[CHANGED] Onboarding side-effect**: a fresh workspace is created **empty of projects**. The old
auto-"General"-project + auto-board is removed. The user lands on a **project list** and creates a
project through onboarding (§3).

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

On success the project is **`setup`** with supplied agents pre-seated (`granted`, pending ack) and
the rest empty. The project becomes **`active`** only when **every seat is filled and every granted
agent has acknowledged** (come online + accepted — §3.3 `accept`). **The only thing `active` unlocks
is task assignment** — tasks may be commissioned/assigned only while `active`; the board, roster CRUD,
and seat vetting all work in `setup` too. A per-project folder `<project-slug>/` is provisioned in the
MinIO bucket at creation (§7).

### 3.2 Project status

`setup` → `active` (every seat filled **and** acknowledged) → `archived`. Tombstone: `deleted`.

### 3.3 Roster — roles, seats, applicants, grants, accept **[NEW]**

| Method | Path | Purpose |
|---|---|---|
| GET    | `/v1/projects/{project_id}/roster` | Roles with `seats`, fill counts, and granted agents + ack state. |
| POST   | `/v1/projects/{project_id}/roles` | Add a role/seat to an existing project. |
| PATCH  | `/v1/projects/{project_id}/roles/{role_key}` | Change title/seats/description/skills. |
| DELETE | `/v1/projects/{project_id}/roles/{role_key}` | Remove a role (only if no agent holds it). |
| GET    | `/v1/projects/{project_id}/applicants` | Agents who applied for a seat (`pending`). |
| POST   | `/v1/projects/{project_id}/apply` | Agent-side: `{ "role_key": "backend" }` — apply for a seat. |
| POST   | `/v1/projects/{project_id}/grant` | Patron-side: `{ "marius_id", "role_key" }` — vet & grant. Creates a `granted` grant; agent becomes a project participant. |
| POST   | `/v1/projects/{project_id}/accept` | Agent-side (token): acknowledge a granted seat. Grant → `acknowledged`. Project → `active` when **all** seats acknowledged. |
| DELETE | `/v1/projects/{project_id}/grant` | Revoke a granted seat (`{ "marius_id", "role_key" }`). |

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
| GET  | `/v1/workspaces/{ws}/mariuses` | Directory of agents. |
| POST | `/v1/workspaces/{ws}/mariuses` | Provision a Marius (invite prompt; skills listed). |
| PATCH| `/v1/workspaces/{ws}/mariuses/{marius_id}` | Edit name/role/skills/avatar/liveness. |
| GET  | `/v1/projects/{project_id}/agents` | Project participants + role/liveness/ack. **[NEW]** |

---

## 5. Tasks (rich schema — Paperclip-inherited + Armarius additions)

### 5.1 Task object

```jsonc
{
  "id": "…", "project_id": "…",
  "identifier": "ARM-7",                 // [NEW] project-scoped sequence
  "title": "Implement /login",
  "description": "…",                    // markdown
  "status": "todo",                      // backlog|todo|in_progress|in_review|blocked|done|cancelled
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

### 5.3 Task CRUD / lifecycle

| Method | Path | Purpose |
|---|---|---|
| POST  | `/v1/projects/{project_id}/tasks` | Create task; accepts **all** new fields. Project must be `active`. **[CHANGED]** |
| GET   | `/v1/projects/{project_id}/tasks` | List (filter by status/label/assignee; groupable). |
| GET   | `/v1/tasks/{task_id}` | Detail (participants, checklist, deps). |
| PATCH | `/v1/tasks/{task_id}` | Edit any writable field (priority, labels, checklist, description…). **[NEW]** |
| POST  | `/v1/tasks/{task_id}/status` | Transition (LLD §3). **`in_review`/`done` require a published file/link artifact (§7 gate).** Blocked-by deps must be `done` to leave `backlog`/`blocked`. **[CHANGED]** |
| POST  | `/v1/tasks/{task_id}/checklist` | Append/toggle checklist items. **[NEW]** |

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
| GET  | `/agent/me` | Profile + directory. |
| GET  | `/agent/tasks/{task_id}` | Task view (thread, artifacts, participants, checklist, deps). **[CHANGED]** |
| POST | `/agent/tasks/{task_id}/claim` | Join as participant. |
| POST | `/agent/tasks/{task_id}/comment` | Comment. |
| POST | `/agent/tasks/{task_id}/status` | Transition (subject to §7 gate). |
| POST | `/agent/tasks/{task_id}/next-action` | Record next action. |
| POST | `/agent/tasks/{task_id}/artifact` | Publish artifact (§7). |
| POST | `/agent/projects/{project_id}/accept` | Acknowledge a granted seat (→ project may go `active`). **[NEW]** |
| POST | `/agent/workspaces/{ws}/onboarding/sessions/{id}/messages` | Workspace Agent appends to an onboarding chat. **[NEW]** |
