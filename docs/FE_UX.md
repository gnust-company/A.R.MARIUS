> ⚠️ **ĐÃ LỖI THỜI (ARCHIVED).** Nguồn sự thật hiện tại là [`spec/`](../spec/) (tiếng Việt). Xem [docs/README.md](README.md).

# Armarius — Frontend UX Specification

> Status: **v1** (2026-06-27). The *information architecture, screens, and flows* the mock-data app
> must implement, derived directly from [ARCHITECTURE.md](./ARCHITECTURE.md) UC1–UC8 (UC9 deferred).
> This doc supersedes the earlier "reskin the old FE" approach: the current `frontend/` is treated as
> **deleted** and rebuilt fresh from this spec. Visual language stays the locked **Scriptorium**
> charter ([FE_DESIGN.md](./FE_DESIGN.md)): warm parchment + terracotta + manuscript gold, high-contrast
> serifs, **no burn, subtle deckle only**.
>
> **Locked this round:** (1) scope = UC1–UC8 only; UC9 agent-onboarding chat deferred. (2) Bilingual
> EN/VI kept, but the **language toggle lives only in Account** — not the sidebar.

---

## 0. The correction this doc makes

The previous FE reskinned an old single-project structure and never reflected the architecture. Three
hard gaps prove it:

- **No project creation.** `store.tsx` auto-created a fake "General" project to hide it. UC5 requires
  real project creation (objective + exactly one leader + worker roles + seats).
- **Commission was a manual form** (title + description). UC7 is unambiguous: commissioning is a
  **chat with the Project Leader**, who fills every field and picks the workers.
- **No roster / staffing / active gate** (UC6). No enroll-and-wait approval surface (UC2). No
  multi-participant collaboration with a DONE artifact gate (UC8).

This spec closes all of that.

---

## 1. Design principles

1. **Architecture is the source of truth.** Every screen maps to a Use Case (UC1–UC8). If a screen
   serves no UC, it is not built.
2. **Patron acts on the Web App; agents act on the Agent API.** The UI shows Patron-side actions and
   agent **outcomes** (online, status, artifacts) pushed over (simulated) SSE. The UI never shows
   agent-internal steps as Patron tasks.
3. **Push, not poll.** Mock simulates the two SSE channels (workspace control-plane + per-task trace)
   so liveness/status/commission/approval arrive as live events, exactly as the real stack will.
4. **"You task. They collaborate. You trace."** — the three signature moments (commission-via-Leader,
   collaboration thread, live trace) are the product; everything else supports them.
5. **States everywhere.** Every list has loading / empty / error states. Emptiness is a *call to
   action* (empty projects → "Create project"; empty roster → "Invite an agent").

---

## 2. Information architecture

Two levels: **workspace shell** (entering a workspace) and **project interior** (inside one project).

### Workspace shell — nav (left rail)
```
[← back to workspaces: <workspace name>]
─────────────────
Projects        ← workspace HOME (list + create)
Directory       ← agents (invite/approve/designate)
Skills          ← author/import + editor
Patron Inbox    ← approvals + blocked (workspace-wide)
─────────────────
Account         ← identity + EN/VI toggle + session
Atelier         ← /style design playground
```
- After login → `/workspaces` launcher → enter a workspace → land on **Projects** (not a board).
- The language switch is **only** in Account.

### Project interior — tabs (entered from Projects)
```
Board   Roster   Commission   (task rooms via task click)
```
- `Board` = kanban + project header (status setup/active). `Roster` = roles + seats + grant → active.
- `Commission` = the Leader-chat surface (locked when project is `setup`).
- A task click opens its **Collaboration Room** (full screen, back to board).

---

## 3. Screen inventory (mapped to UCs)

> Mock = the in-memory store drives content; SSE is simulated. Scriptorium visual grammar on every
> screen: illuminated `.vellum` header (DropCap + Fraunces title + status chips + action), `.panel`
> cards w/ `.gilt` hover + `.quill-in` entrance, mono for data, earthy status palette, `<Icon>` set.

### Workspace-level

| # | Route | UC | Purpose & key elements |
|---|---|---|---|
| **S1** | `/workspaces` | UC1 | Launcher. Workspace cards (Personal + created) w/ project & agent counts. Enter → shell. |
| **S2** | `/` (Projects) | UC1, UC5 | **Workspace home.** Project cards: name, objective, status chip (setup/active/archived), seats filled / total, task count. Empty → "Create project" CTA. |
| **S3** | `/projects/new` | UC5 | **Create project** wizard. Fields: name, objective, target_date, github_url?, context, settings. **Roster builder:** one **Project Leader** (pick existing agent *or* leave empty) + worker roles (title, description, optional skills[], seats). HARD validation shown inline (needs 1 leader + ≥1 worker role). Submit → `setup` project → land on its board. |
| **S4** | `/directory` | UC2, UC3 | Agents w/ `invite_status` (invited → pending_review → approved) + liveness. **Invite** modal (adapter_type, name, role, skill_ids → copyable enroll prompt). **Approve** pending_review → flips ONLINE (simulated SSE). **Make Workspace Agent** (UC3). |
| **S5** | `/skills`, `/skills/:id` | UC4 | List + Create (manual/import GitHub) + nested-tree editor (file/folder, add/delete). |
| **S6** | `/inbox` | UC8 | Workspace-wide approvals (`in_review`) + blocked, grouped. Open → task room; Approve → done. |
| **S7** | `/account` | — | Identity, **EN/VI toggle (the only place)**, workshop switch, session, sign out. |

### Project-level

| # | Route | UC | Purpose & key elements |
|---|---|---|---|
| **P1** | `/projects/:id` (Board) | UC6–8 | Project header (name, objective, status). Kanban (backlog→done). If `setup`: staffing banner + Roster tab to grant seats; "Commission" locked. If `active`: "Commission task" enabled. |
| **P2** | `/projects/:id/commission` | UC7 | **FLAGSHIP — chat with the Project Leader.** See §4. |
| **P3** | `/tasks/:id` (Room) | UC8 | Collaboration room. See §5. |

---

## 4. Commission — chat with the Project Leader (UC7)  ⚑ flagship

This **replaces** the old manual task form entirely. "You task" is literal: you tell the Leader what
you want; the Leader shapes the task.

### Layout (P2)
A **two-pane surface**:
- **Left (60%) — Leader chat:** message stream. Patron messages (right, terracotta) and Leader
  messages (left, mono-accented, with Leader avatar + `pulse` while thinking). Composer at bottom.
- **Right (40%) — Task preview:** the Leader's proposed task, **Leader-filled**, updating live as the
  chat proceeds: `identifier` (ARM-n), title, description, **priority**, **definition_of_done**,
  **checklist[]** (tickable), **dependencies[]**, **due date**, **chosen workers** (from roster, with
  liveness). Empty until the Leader proposes.

### Flow
1. Patron types a request ("Redesign the settings page, AA contrast, ship by Friday").
2. Mock Leader (scripted) either **asks back** (renders as a Leader message; preview stays empty) or
   **proposes** (fills the preview panel).
3. Patron **Refine** (message a tweak → Leader revises preview) or **Confirm**.
4. Confirm → task created (status `todo`, participants = leader-picked workers), workers woken, task
   appears on the board (simulated `task.created` on workspace SSE). Redirect to its Room.

### Mock behaviour
A scripted Leader turn sequence (acknowledge → clarifying question OR propose → on refine, revise →
on confirm, finalize). Seeded with one in-flight commission session so the screen is populated on
first view.

### Locked-when-setup
If the project is `setup`, Commission shows a locked state pointing to **Roster** (staff it → active
first). Matches UC6/UC7 gating.

---

## 5. Collaboration Room (UC8) — P3

Three panes (unchanged shape from before, Scriptorium skin + the DONE gate made explicit):
- **Context:** description, status select, assignee/participants, DoD, **checklist**, dependencies,
  **DONE gate** (a task cannot reach `done` without a file|link artifact — shown as an explicit
  checklist item that's blocked until an artifact exists), **artifacts** (file icon → MinIO key,
  link icon → external).
- **Thread:** multi-participant comments (Patron + workers + Leader), `@mention` highlights, author
  chips (agent/human/system), approval bar when `in_review`.
- **Live trace:** per-task SSE timeline (run.delta/tool/usage) with wake control.

---

## 6. End-to-end flows (clickable in mock)

- **F1 Invite→approve→online (UC2):** Directory → Invite → copy prompt → (simulated) agent enrolls →
  card shows `pending_review` → Approve → card flips ONLINE (simulated `marius.online`).
- **F2 Create→staff→active (UC5+UC6):** Projects → Create project (leader + workers) → `setup` board
  → Roster → grant seats → when all granted **and** seated agents online → banner flips `active`,
  Commission unlocks (simulated `project.active`).
- **F3 Commission (UC7):** active board → Commission → chat Leader → preview → confirm → task on board.
- **F4 Work→DONE gate (UC8):** task room → participants collaborate → publish file/link artifact →
  status can advance to `in_review`/`done` (gate blocks otherwise) → Patron Inbox approval → done.

---

## 7. Mock-data seed (so every flow is clickable)

- **Workspaces:** `Atelier` (personal), `R&D Lab`.
- **Agents:** `Atlas` (Project Leader, approved, online); workers `Vega` (FE, working),
  `Orion` (BE, online), `Lyra` (design, idle), `Nova` (QA, offline); **`Marin` (pending_review)** to
  show enroll-and-wait; **`Echo-1` (invited)** still awaiting enroll. One designated Workspace Agent.
- **Skills:** `armarius-http` (builtin), `algorithmic-art` (github, multi-file).
- **Projects:** `Settings Redesign` (**active**, fully staffed, tasks across all statuses incl. one
  `in_review` with a file+link artifact, one `blocked`); `Docs Site` (**setup**, roster partially
  staffed — to demo the setup→active transition and the locked Commission).
- **Tasks:** with checklists, dependencies, multiple participants, artifacts (file + link),
  `next_action`, `status_reason`, `ARM-n` identifiers.
- **Commission:** one in-flight Leader-chat session with a draft preview.
- **Simulator:** liveness decay on workspace SSE; scripted per-task trace on trace SSE.

---

## 8. States & a11y

- **Loading** (`Loading the scriptorium…`), **empty** (each list → a CTA), **error** (failed loads,
  terracotta/rust). 404 for missing task/project.
- **a11y:** visible focus rings (terracotta), `prefers-reduced-motion` (disables quill/unfurl/pulse),
  semantic buttons/links, icon `aria-hidden`, no color-only meaning (label + dot).
- **i18n:** EN/VI for every string; toggle **only in Account**.

---

## 9. Out of scope (this round)

- **UC9 — agent-assisted onboarding chat** (Phase G, last). Manual UC5 creation covers project-making.
- Real backend / real SSE / real adapters — `MOCK=on`; the BE track (BE-1…BE-7) is **not started**.
- Custom illuminated illustrations, dark variant.

---

## 10. Build order (after this spec is approved)

1. **Primitives + mock store** (`ui.tsx`, `mock/store.ts` seeded per §7, simulated SSE bus).
2. **Workspace shell** + S1 launcher + S2 Projects + S3 Create project (UC5).
3. **Directory** (UC2/UC3 approve + designate) + **Skills** (UC4) + **Account** (lang toggle) + **Inbox**.
4. **Project interior:** P1 Board+Roster (UC6 active gate) → **P2 Commission chat** (UC7) → P3 Room (UC8 DONE gate).
5. **Polish:** i18n EN/VI, states, a11y, reduced-motion → FE freeze + report. No BE.
