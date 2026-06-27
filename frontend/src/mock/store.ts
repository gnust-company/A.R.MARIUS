import type {
  Artifact, Comment, Marius, Project, Run, RunEvent, Skill, Task, User, Workspace,
} from "../api";

// In-memory mock database for the mock-data app (FE-1). Seeded once on module load;
// mutated by mockApi + the liveness simulator. No persistence — refresh resets it.

export interface MockDB {
  session: { user: User | null };
  workspaces: Workspace[];
  projects: Project[];
  mariuses: Marius[];
  skills: Skill[];
  tasks: Task[];
  comments: Comment[];
  artifacts: Artifact[];
  runs: Run[];
  runEvents: Record<string, RunEvent[]>;
  seq: number;
}

const now = () => new Date().toISOString();
const ago = (sec: number) => new Date(Date.now() - sec * 1000).toISOString();
let idc = 100;
const nid = (p: string) => `${p}-${++idc}`;

function seed(): MockDB {
  const user: User = {
    id: "u-1", email: "patron@armarius.dev", username: "patron",
    full_name: "Patron", role: "patron", is_active: true, is_verified: true,
    created_at: ago(86400), last_login_at: ago(60),
  };

  const workspaces: Workspace[] = [
    { id: "ws-1", name: "Atelier", slug: "atelier" },
    { id: "ws-2", name: "R&D Lab", slug: "rnd-lab" },
  ];

  const projects: Project[] = [
    { id: "proj-1", workspace_id: "ws-1", name: "Settings Redesign", slug: "settings-redesign",
      description: "Redesign the settings experience end-to-end — tokens, layout, accessibility." },
  ];

  const mariuses: Marius[] = [
    { id: "m-leader", workspace_id: "ws-1", name: "Atlas", role: "Project Leader", skills: [], skill_ids: [],
      adapter_type: "hermes_gateway", liveness: "online", last_seen_at: ago(20) },
    { id: "m-fe", workspace_id: "ws-1", name: "Vega", role: "Frontend Engineer", skills: [], skill_ids: ["sk-http"],
      adapter_type: "hermes_gateway", liveness: "working", last_seen_at: ago(5) },
    { id: "m-be", workspace_id: "ws-1", name: "Orion", role: "Backend Engineer", skills: [], skill_ids: ["sk-http"],
      adapter_type: "openclaw_gateway", liveness: "online", last_seen_at: ago(40) },
    { id: "m-design", workspace_id: "ws-1", name: "Lyra", role: "Designer", skills: [], skill_ids: [],
      adapter_type: "claude_local", liveness: "idle", last_seen_at: ago(600) },
    { id: "m-qa", workspace_id: "ws-1", name: "Nova", role: "QA Engineer", skills: [], skill_ids: ["sk-http"],
      adapter_type: "hermes_gateway", liveness: "offline", last_seen_at: ago(3600) },
  ];

  const skills: Skill[] = [
    { id: "sk-http", workspace_id: "ws-1", slug: "armarius-http", name: "Armarius HTTP",
      description: "Call the Armarius agent API from any runtime.",
      source: "builtin", source_url: "/static/skills/armarius-http/SKILL.md",
      files: { "SKILL.md": "# Armarius HTTP\n\nRead credentials, confirm online, install, then work tasks." } },
    { id: "sk-art", workspace_id: "ws-1", slug: "algorithmic-art", name: "Algorithmic Art",
      description: "Generative art skill (imported from GitHub).",
      source: "github", source_url: "github.com/anthropics/skills/algorithmic-art",
      files: {
        "SKILL.md": "# Algorithmic Art\n\nCreate generative art with Python.",
        "templates/spiral.py": "# spiral template\n",
        "templates/mandala.py": "# mandala template\n",
      } },
  ];

  const tasks: Task[] = [
    { id: "t-1", project_id: "proj-1", title: "Redesign the settings page", status: "in_progress",
      description: "New layout with the Scriptorium tokens.", assigned_marius_id: "m-fe",
      next_action: "Wire the new toggle component.", created_at: ago(7200), updated_at: ago(120) },
    { id: "t-2", project_id: "proj-1", title: "Add a dark-mode toggle", status: "todo",
      description: "Persist preference locally.", assigned_marius_id: null,
      next_action: null, created_at: ago(5400), updated_at: ago(5400) },
    { id: "t-3", project_id: "proj-1", title: "Preferences API endpoint", status: "in_review",
      description: "GET/PATCH /v1/me/preferences.", assigned_marius_id: "m-be",
      next_action: "Awaiting Patron review.", created_at: ago(9000), updated_at: ago(400) },
    { id: "t-4", project_id: "proj-1", title: "Define design tokens", status: "done",
      description: "Parchment + terracotta + gilt.", assigned_marius_id: "m-design",
      next_action: null, created_at: ago(18000), updated_at: ago(2000) },
    { id: "t-5", project_id: "proj-1", title: "Accessibility audit", status: "backlog",
      description: "WCAG AA pass on the new screens.", assigned_marius_id: null,
      next_action: null, created_at: ago(3600), updated_at: ago(3600) },
    { id: "t-6", project_id: "proj-1", title: "Fix mobile layout overflow", status: "blocked",
      description: "Board cards overflow < 380px.", assigned_marius_id: "m-fe",
      next_action: "Blocked by the responsive-grid task.", status_reason: "blocked_by t-9",
      created_at: ago(4800), updated_at: ago(900) },
  ];

  const comments: Comment[] = [
    { id: "c-1", task_id: "t-1", author_kind: "agent", author_marius_id: "m-fe",
      body: "Started on the new layout — dropping in the Scriptorium tokens now.", mentions: [],
      created_at: ago(300) },
    { id: "c-2", task_id: "t-1", author_kind: "human", author_user_id: "u-1",
      body: "Looks great — @m-design can you sanity-check the contrast?", mentions: ["m-design"],
      created_at: ago(180) },
    { id: "c-3", task_id: "t-1", author_kind: "agent", author_marius_id: "m-design",
      body: "Contrast is AA on parchment. Ship it.", mentions: [],
      created_at: ago(120) },
  ];

  const artifacts: Artifact[] = [
    { id: "a-1", task_id: "t-3", marius_id: "m-be", name: "preferences_api.py",
      kind: "file", uri: "settings-redesign/t-3/preferences_api.py", size_bytes: 1843, created_at: ago(400) },
    { id: "a-2", task_id: "t-3", marius_id: "m-be", name: "Spec — Preferences API",
      kind: "link", uri: "https://armarius.dev/specs/preferences", created_at: ago(380) },
    { id: "a-3", task_id: "t-4", marius_id: "m-design", name: "tokens.css",
      kind: "file", uri: "settings-redesign/t-4/tokens.css", size_bytes: 2210, created_at: ago(2000) },
  ];

  const runs: Run[] = [
    { id: "run-1", task_id: "t-1", marius_id: "m-fe", adapter_type: "hermes_gateway",
      wake_source: "assign", status: "running", continuation_attempt: 0,
      usage_json: { input_tokens: 1280, output_tokens: 640 },
      started_at: ago(60), created_at: ago(60) },
  ];

  const runEvents: Record<string, RunEvent[]> = {
    "run-1": [
      { seq: 1, type: "run.started", payload: { adapter: "hermes_gateway" }, created_at: ago(60) },
      { seq: 2, type: "run.tool", payload: { name: "read_file", path: "src/Settings.tsx" }, created_at: ago(55) },
      { seq: 3, type: "run.delta", payload: { text: "Replacing the panel styles with parchment tokens…" }, created_at: ago(50) },
    ],
  };

  return { session: { user: null }, workspaces, projects, mariuses, skills, tasks, comments, artifacts, runs, runEvents, seq: 100 };
}

export const db: MockDB = seed();

// --- mutators ---
export function nextSeq(): number { return ++db.seq; }
export function setMariusLiveness(id: string, liveness: string): void {
  const m = db.mariuses.find((x) => x.id === id);
  if (m) { m.liveness = liveness; m.last_seen_at = liveness === "offline" ? m.last_seen_at : now(); }
}
export { nid, now, ago };
