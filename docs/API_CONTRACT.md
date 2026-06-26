# Armarius — API Contract

> Status: **Design draft** (2026-06-26). This document captures the agreed interface for the
> "multi-project + onboarding + richer task + collaboration" wave. Items tagged **[NEW]** are
> not yet implemented; **[CHANGED]** alter an existing endpoint/schema; untagged already exist.
>
> Conventions: all routes are relative to the API base (served behind the nginx reverse-proxy,
> see `docker-compose.yml`). Human routes require a bearer JWT (`Authorization: Bearer …`).
> Agent routes require an agent token. Every resource is **scoped to the calling user/agent's
> workspace** — cross-workspace access returns 404. Errors: `{ "detail": "…" }` (FastAPI).

---

## 0. Naming

| Term | Meaning |
|---|---|
| **Workspace** | Top-level tenant owned by one user. Holds projects, agents, skills. |
| **Project** | A unit of work inside a workspace. Has a **roster** of required **roles/seats**. |
| **Role / Seat** | A named position on a project (e.g. `Backend`, `Project Leader`) with a seat count. Agents are **granted** a seat after vetting. |
| **Marius** | An agent in a workspace. May be designated the **Workspace Agent** (onboarding conductor). |
| **Task** | A unit of work inside a project. Has **participants** (co-work), a **checklist**, **dependencies**, and an **output artifact** gate. |
| **Artifact** | A published output in the **Shared Artifact Store**. A task cannot be `done` until its output is published there. |

Guiding UX principle (from `ARMARIUS Design/`): **"You task. They collaborate. You trace."**

---

## 1. Auth (unchanged)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Register; auto-provisions the personal workspace. |
| POST | `/auth/login` | Login. |
| POST | `/auth/refresh` | Refresh JWT. |
| GET  | `/auth/me` | Current user. |

---

## 2. Workspaces (minor change)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces` | List workspaces owned by the caller. |
| POST | `/v1/workspaces` | Create a workspace (seeds builtin skills + **no** auto "General" project — see §3 note). |
| GET  | `/v1/workspaces/{ws}` | Workspace detail, incl. `workspace_agent_id`. **[NEW]** |

**[CHANGED] Onboarding side-effect**: a fresh workspace is created **empty of projects**. The old
behavior of auto-creating a "General" project and dropping the user onto the board is **removed**.
The user lands on a **project list / landing** (`GET /v1/workspaces/{ws}/projects`) and creates a
project through onboarding (§3).

**[NEW] Workspace Agent designation** (the workspace may have at most one):

| Method | Path | Purpose |
|---|---|---|
| PUT  | `/v1/workspaces/{ws}/workspace-agent` | Body `{ "marius_id": "<uuid>" \| null }`. Sets/clears the workspace agent. When set, the designated Marius receives the **armarius-onboarder** skill install step (its `skill_ids` gains the builtin skill id) and a re-issued invite prompt describing its onboarding duty. |

---

## 3. Projects + Roster (roles/seats) + Onboarding

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces/{ws}/projects` | List projects in the workspace. |
| GET  | `/v1/projects/{project_id}` | Project detail: roster, seat fill state, status. **[NEW]** |
| POST | `/v1/workspaces/{ws}/projects` | Create a project **with a complete seat plan** (see below). **[CHANGED]** |
| PATCH | `/v1/projects/{project_id}` | Edit project fields (objective, success metrics, target date, settings). **[NEW]** |
| DELETE | `/v1/projects/{project_id}` | Delete a project (owner only). **[NEW]** |

### 3.1 Create project — `POST /v1/workspaces/{ws}/projects`

A project is created in one of two onboarding modes. Both write to the same endpoint.

```jsonc
// request
{
  "name": "Acme Web Platform",
  "description": "Public marketing site relaunch.",
  "mode": "manual",                 // "manual" | "agent"
  "objective": "Ship a new marketing site by Q3.",
  "success_metrics": { "kpi": "…" },// free-form json, optional
  "target_date": "2026-09-30",      // optional
  "context": "Brand guidelines in the shared store…", // free text the patron pastes in
  "roles": [
    { "key": "leader",  "title": "Project Leader", "seats": 1, "is_leader": true,
      "description": "Plans and sequences work, vets output." },
    { "key": "backend", "title": "Backend",        "seats": 2,
      "description": "API + data layer." },
    { "key": "frontend","title": "Frontend",       "seats": 1,
      "description": "UI implementation." }
  ],
  "settings": {
    "require_review_before_done": true,
    "require_approval_for_done": true,
    "comment_required_for_review": false
  },
  "onboarding_session_id": null     // present only in "agent" mode (§3.4)
}
```

**Hard composition rule (enforced here — see LLD §2):** the `roles` plan must contain **exactly
one** role with `is_leader: true` and `seats >= 1`, **and** at least one non-leader role with
`seats >= 1`. If not, `422 { "detail": "A project needs exactly one leader seat and at least one worker seat." }`.

On success the project is created in status **`setup`** with all seats empty. The patron then
fills seats (§3.3); when the **leader seat is granted**, status flips to **`active`**. Tasks may be
commissioned only while `active` (or later).

### 3.2 Project status

`setup` → `active` (leader seat filled) → `archived`. (Tombstone states: `deleted`.)

### 3.3 Roster — roles, seats, applicants, grants **[NEW]**

| Method | Path | Purpose |
|---|---|---|
| GET    | `/v1/projects/{project_id}/roster` | Roles with `seats`, `filled`, and the granted agents. |
| POST   | `/v1/projects/{project_id}/roles` | Add a role/seat to an existing project. |
| PATCH  | `/v1/projects/{project_id}/roles/{role_key}` | Change title/seats/description. |
| DELETE | `/v1/projects/{project_id}/roles/{role_key}` | Remove a role (only if no agent holds it). |
| GET    | `/v1/projects/{project_id}/applicants` | Agents who applied for a seat (pending vetting). |
| POST   | `/v1/projects/{project_id}/apply` | Agent-side: `{ "role_key": "backend" }` — apply for a seat. |
| POST   | `/v1/projects/{project_id}/grant` | Patron-side: `{ "marius_id": "…", "role_key": "backend" }` — vet & grant a seat. Adds the agent as a project **participant**. |
| DELETE | `/v1/projects/{project_id}/grant` | Revoke a granted seat (`{ "marius_id", "role_key" }`). |

A granted agent becomes a **project participant** and is eligible to be added to task participants (§5.2).

### 3.4 Onboarding session (agent-assisted mode) **[NEW]**

When `mode: "agent"`, the request is opened by the **Workspace Agent** after a chat. The session is
persisted so the conversation can resume and the final plan is auditable.

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/workspaces/{ws}/onboarding/sessions` | Start a session; returns `{ id }`. The workspace agent drives it. |
| GET  | `/v1/workspaces/{ws}/onboarding/sessions/{id}` | Session state: status, transcript, collected fields. |
| POST | `/v1/workspaces/{ws}/onboarding/sessions/{id}/messages` | Append a message (patron answer or agent question). |
| POST | `/v1/workspaces/{ws}/onboarding/sessions/{id}/finalize` | Materialize the collected plan → creates the project via §3.1. Body carries the same `roles`/`objective`/`context`. Returns the created project. |

The Workspace Agent is instructed (via the **armarius-onboarder** skill, §6) to ask a structured set
of questions (goal → roles → per-role counts → context), mirroring OpenClaw's chat onboarding, then
call `finalize`.

---

## 4. Mariuses / Agents

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces/{ws}/mariuses` | Directory of agents in the workspace. |
| POST | `/v1/workspaces/{ws}/mariuses` | Provision a Marius (builds invite prompt; skills listed). |
| PATCH| `/v1/workspaces/{ws}/mariuses/{marius_id}` | Edit name/role/skills/liveness. |
| GET  | `/v1/projects/{project_id}/agents` | Project participants + their role/liveness. **[NEW]** |

---

## 5. Tasks (rich schema — fields inherited from Paperclip + Armarius additions)

### 5.1 Task object

```jsonc
{
  "id": "…", "project_id": "…",
  "identifier": "ARM-7",                 // [NEW] human id, project-scoped sequence
  "title": "Implement /login",
  "description": "…",                    // markdown
  "status": "todo",                      // backlog|todo|in_progress|in_review|blocked|done|cancelled
  "priority": "high",                    // [NEW] critical|high|medium|low
  "label_ids": ["…"],                    // [NEW] see §5.4
  "parent_id": null,                     // [NEW] subtask link
  "blocked_by": ["<task_id>"],           // [NEW] dependency links (read view)
  "blocks":     ["<task_id>"],           // [NEW] (read view)
  "checklist": [                         // [NEW] lightweight on-task todos
    { "id": "c1", "text": "Write tests", "done": false }
  ],
  "definition_of_done": "Branch merges, tests green, artifact published.", // [NEW]
  "due_date": "2026-07-15",             // [NEW]
  "leader_marius_id": "…",              // [NEW] project leader of this task's project (denormalized)
  "created_by_user_id": "…", "created_by_marius_id": null,
  "in_progress_at": null, "completed_at": null,
  "created_at": "…", "updated_at": "…"
}
```

> Note on participants: the old single `assigned_marius_id` is superseded by the **participants**
> collection (§5.2). For back-compat, `assigned_marius_id` is exposed as the first/primary
> participant but new code uses participants.

### 5.2 Task participants (co-work) **[NEW]**

A task is worked by **one or more** participants (the "co-work" in the tagline), drawn from the
project roster.

| Method | Path | Purpose |
|---|---|---|
| GET    | `/v1/tasks/{task_id}/participants` | List participants with their project role + liveness. |
| POST   | `/v1/tasks/{task_id}/participants` | Body `{ "marius_id": "…" }`. The participant is woken with task context. |
| DELETE | `/v1/tasks/{task_id}/participants` | `{ "marius_id": "…" }` — remove. |
| POST   | `/v1/tasks/{task_id}/wake` | Wake a specific participant (`{ "marius_id": "…" }`). (Replaces the old single-assign wake.) |

### 5.3 Task CRUD / lifecycle

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/projects/{project_id}/tasks` | Create task. Body now accepts **all new fields** (priority, labels, parent_id, blocked_by, checklist, definition_of_done, due_date). **[CHANGED]** |
| GET  | `/v1/projects/{project_id}/tasks` | List tasks (filter by status/label/assignee; groupable). |
| GET  | `/v1/tasks/{task_id}` | Task detail (incl. participants, checklist, deps). |
| PATCH | `/v1/tasks/{task_id}` | Edit any writable field (priority, labels, checklist, description…). **[NEW]** (replaces several narrow endpoints). |
| POST | `/v1/tasks/{task_id}/status` | Transition status (state machine, LLD §4). **`in_review`/`done` require a published output artifact (§7 gate).** **[CHANGED]** |
| POST | `/v1/tasks/{task_id}/checklist` | Append/toggle checklist items (also available via PATCH). **[NEW]** |

### 5.4 Labels **[NEW]**

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces/{ws}/labels` | List labels. |
| POST | `/v1/workspaces/{ws}/labels` | Create `{ name, color }`. |

Labels are **workspace-scoped** and referenced by `label_ids` on tasks.

---

## 6. Skills (unchanged surface; tree is a frontend concern)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/workspaces/{ws}/skills` | List skills. |
| GET  | `/v1/workspaces/{ws}/skills/{id}` | Skill detail (`files: {path: content}`). |
| POST | `/v1/workspaces/{ws}/skills/manual` | Create from template. |
| POST | `/v1/workspaces/{ws}/skills/import` | Import from GitHub folder URL. |
| PUT  | `/v1/workspaces/{ws}/skills/{id}` | Save edited file tree. |

**Builtin skills** now include two:
- `armarius-http` — call the API (existing).
- **`armarius-onboarder` [NEW]** — issued to the designated Workspace Agent. Its `SKILL.md` instructs
  the agent to run project onboarding by asking the patron the structured question set (§3.4) and
  calling `finalize`. The skill file lives under `backend/static/skills/armarius-onboarder/SKILL.md`.

> The **nested file-tree** the user asked for is a **frontend-only** change (the backend already
> stores `files: {path: content}` with `/`-delimited paths). No new endpoint.

---

## 7. Shared Artifact Store (the anti-local-output guarantee)

The fatal failure mode we prevent: *an agent finishes the task but leaves the output file on its
local disk instead of pushing it up.* Armarius therefore **requires** every actionable task to
publish its output into the server-side Shared Store before it can leave `in_progress`.

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/tasks/{task_id}/artifacts` | List artifacts (human surface). |
| POST | `/v1/tasks/{task_id}/artifacts` | Publish artifact. **[CHANGED]** |
| POST | `/agent/tasks/{task_id}/artifact` | Agent surface (token auth). **[CHANGED]** |
| GET  | `/v1/artifacts/{artifact_id}/content` | Download stored bytes (stream). **[NEW]** |

**[CHANGED] Publish body** — `kind` in `file|patch` now **requires server-stored content**:

```jsonc
{
  "name": "login-impl.patch",
  "kind": "patch",                  // file|patch|link|note
  "content_b64": "LS0t …",          // [NEW] REQUIRED when kind in {file, patch}; decoded + stored
  "uri": null,                      // optional override; if omitted, store assigns a path
  "content_sha256": "…",            // verified against decoded bytes
  "size_bytes": 1234
}
```

- `file`/`patch`: bytes are decoded, sha256-verified, written to the Shared Store
  (`ARTIFACT_STORE_DIR`, see LLD §6). `uri` becomes the store-relative path. **The agent can no
  longer point `uri` at a bare local path and call it done** — content must be uploaded.
- `link`/`note`: content optional (`link` carries an external `uri`; `note` is a short text).

**The DONE gate** (`POST /tasks/{id}/status` → `in_review`/`done`): rejected with
`409 { "detail": "Publish the output artifact to the shared store first." }` unless the task has ≥1
artifact of kind `file` or `patch` with stored content. (Existing artifact-gate logic is tightened
from "any artifact" to "stored-output artifact".)

---

## 8. Thread (comments), Approvals, Trace (largely unchanged)

| Method | Path | Purpose |
|---|---|---|
| GET  | `/v1/tasks/{task_id}/comments` | Thread (human/agent/system authors, @mentions). |
| POST | `/v1/tasks/{task_id}/comments` | Post comment. |
| POST | `/v1/tasks/{task_id}/next-action` | Record next action (used in trace + task cards). |
| POST | `/v1/tasks/{task_id}/wake` | Wake a participant (see §5.2). |
| SSE  | `/v1/tasks/{task_id}/stream` | Live run trace (assistant deltas, tool calls, usage). **[NEW]** (formalize existing CDP/SSE trace as a documented stream). |

> Approvals (Patron Inbox) surface is unchanged; it consumes the `in_review` → approve/publish flow,
  which now terminates in the §7 artifact gate.

---

## 9. Agent-facing surface (token auth) — deltas

| Method | Path | Purpose |
|---|---|---|
| GET  | `/agent/me` | Profile + directory. |
| GET  | `/agent/tasks/{task_id}` | Task view (thread, artifacts, participants, checklist, deps). **[CHANGED]** (adds participants/checklist/deps). |
| POST | `/agent/tasks/{task_id}/claim` | Join as participant (also via §5.2). |
| POST | `/agent/tasks/{task_id}/comment` | Comment. |
| POST | `/agent/tasks/{task_id}/status` | Transition (subject to §7 gate). |
| POST | `/agent/tasks/{task_id}/next-action` | Record next action. |
| POST | `/agent/tasks/{task_id}/artifact` | Publish artifact (§7). |
| POST | `/agent/workspaces/{ws}/onboarding/sessions/{id}/messages` | The Workspace Agent appends to an onboarding chat. **[NEW]** |
