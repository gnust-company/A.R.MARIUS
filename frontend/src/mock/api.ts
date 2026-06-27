import type {
  Artifact, AuthTokens, Comment, Marius, MariusInput, Project, Run, RunEvent, Skill, Task, TaskStatus, User, Workspace,
} from "../api";
import { ago, db, nid, now } from "./store";

// Mock implementation of the `api` surface (FE-1). Same shapes as the real client so the
// app runs with zero backend. MOCK switch lives in api.ts; this module is import-free of it.

const lag = <T>(value: T): Promise<T> =>
  new Promise((resolve) => setTimeout(() => resolve(value), 90 + Math.random() * 130));
const snap = <T>(v: T): T => JSON.parse(JSON.stringify(v));

const DEMO_USER: User = {
  id: "u-1", email: "patron@armarius.dev", username: "patron", full_name: "Patron",
  role: "patron", is_active: true, is_verified: true, created_at: ago(86400), last_login_at: ago(60),
};
const MOCK_TOKENS: AuthTokens = { access_token: "mock-access", refresh_token: "mock-refresh", token_type: "bearer" };

function invitePrompt(m: Marius): string {
  return [
    `# Invitation — ${m.name} (${m.role})`,
    `Adapter: ${m.adapter_type}`,
    `Enrollment code: ${m.id}-ENROLL-CODE  (no token in this prompt)`,
    `1. POST /agent/enroll  { enrollment_code }   — held open until a Patron approves`,
    `2. On approval the agent_token is returned AS the enroll response.`,
    `3. GET /agent/me to confirm online, then install skills and work tasks.`,
  ].join("\n");
}

export const mockApi = {
  register: (body: { email: string; full_name: string; password: string }) => {
    db.session.user = { ...DEMO_USER, email: body.email, full_name: body.full_name || "Patron" };
    return lag({ user: snap(db.session.user), tokens: MOCK_TOKENS });
  },
  login: (_email: string, _password: string) => {
    db.session.user = DEMO_USER;
    return lag({ user: snap(DEMO_USER), tokens: MOCK_TOKENS });
  },
  me: () => lag(snap(db.session.user ?? DEMO_USER)),

  workspaces: () => lag(snap(db.workspaces)),
  createWorkspace: (name: string) => {
    const w: Workspace = { id: nid("ws"), name, slug: name.toLowerCase().replace(/\s+/g, "-") };
    db.workspaces.push(w);
    return lag(snap(w));
  },
  projects: (ws: string) => lag(snap(db.projects.filter((p) => p.workspace_id === ws))),
  createProject: (ws: string, name: string, description?: string) => {
    const p: Project = { id: nid("proj"), workspace_id: ws, name,
      slug: name.toLowerCase().replace(/\s+/g, "-"), description: description ?? null };
    db.projects.push(p);
    return lag(snap(p));
  },
  mariuses: (ws: string) => lag(snap(db.mariuses.filter((m) => m.workspace_id === ws))),

  skills: (ws: string) => lag(snap(db.skills.filter((s) => s.workspace_id === ws))),
  skill: (ws: string, id: string) => lag(snap(db.skills.find((s) => s.workspace_id === ws && s.id === id)!)),
  createManualSkill: (ws: string, body: { name: string; description?: string }) => {
    const s: Skill = { id: nid("sk"), workspace_id: ws, slug: body.name.toLowerCase().replace(/\s+/g, "-"),
      name: body.name, description: body.description ?? "", source: "manual", source_url: "",
      files: { "SKILL.md": `# ${body.name}\n\nDescribe the skill here.` } };
    db.skills.push(s);
    return lag(snap(s));
  },
  importSkill: (ws: string, source_url: string) => {
    const name = source_url.split("/").pop() ?? "imported-skill";
    const s: Skill = { id: nid("sk"), workspace_id: ws, slug: name, name, description: "Imported skill.",
      source: "github", source_url, files: { "SKILL.md": `# ${name}\n\nImported.` } };
    db.skills.push(s);
    return lag(snap(s));
  },
  updateSkill: (ws: string, id: string, files: Record<string, string>) => {
    const s = db.skills.find((x) => x.workspace_id === ws && x.id === id)!;
    s.files = files;
    return lag(snap(s));
  },

  registerMarius: (ws: string, body: MariusInput) => {
    const m: Marius = { id: nid("m"), workspace_id: ws, name: body.name, role: body.role,
      skills: body.skills ?? [], skill_ids: body.skill_ids ?? [], adapter_type: body.adapter_type,
      liveness: "offline", last_seen_at: now() };
    db.mariuses.push(m);
    return lag(snap({ ...m, agent_token: `${m.id}-TOKEN`, invite: invitePrompt(m) }));
  },
  updateMarius: (ws: string, id: string, body: Partial<MariusInput>) => {
    const m = db.mariuses.find((x) => x.workspace_id === ws && x.id === id)!;
    if (body.name) m.name = body.name;
    if (body.role) m.role = body.role;
    if (body.skill_ids) m.skill_ids = body.skill_ids;
    if (body.adapter_type) m.adapter_type = body.adapter_type;
    return lag(snap({ ...m, agent_token: `${m.id}-TOKEN`, invite: invitePrompt(m) }));
  },

  meta: () => lag({ version: "mock-1.0", public_base_url: "http://localhost", adapters: ["hermes_gateway", "openclaw_gateway", "claude_local", "echo"] }),
  adapters: () => lag({ adapters: ["hermes_gateway", "openclaw_gateway", "claude_local", "echo"] }),

  tasks: (project: string) => lag(snap(db.tasks.filter((t) => t.project_id === project))),
  task: (id: string) => lag(snap(db.tasks.find((t) => t.id === id)!)),
  createTask: (project: string, title: string, description?: string) => {
    const t: Task = { id: nid("t"), project_id: project, title, description: description ?? null,
      status: "backlog", assigned_marius_id: null, next_action: null, created_at: now(), updated_at: now() };
    db.tasks.push(t);
    return lag(snap(t));
  },
  assign: (taskId: string, marius_id: string) => {
    const t = db.tasks.find((x) => x.id === taskId)!;
    t.assigned_marius_id = marius_id; t.updated_at = now();
    return lag(snap(t));
  },
  transition: (taskId: string, status: TaskStatus, reason?: string) => {
    const t = db.tasks.find((x) => x.id === taskId)!;
    t.status = status; t.status_reason = reason ?? null; t.updated_at = now();
    return lag(snap(t));
  },

  comments: (taskId: string) => lag(snap(db.comments.filter((c) => c.task_id === taskId).sort((a, b) => (a.created_at! < b.created_at! ? -1 : 1)))),
  postComment: (taskId: string, body: string, author_user_id = "u-1") => {
    const mentions = (body.match(/@(\w+)/g) ?? []).map((s) => s.slice(1));
    const c: Comment = { id: nid("c"), task_id: taskId, author_kind: "human", author_user_id,
      body, mentions, created_at: now() };
    db.comments.push(c);
    return lag(snap(c));
  },

  artifacts: (taskId: string) => lag(snap(db.artifacts.filter((a) => a.task_id === taskId))),
  runs: (taskId: string) => lag(snap(db.runs.filter((r) => r.task_id === taskId))),
  runEvents: (runId: string) => lag(snap(db.runEvents[runId] ?? [])),
  wake: (taskId: string, marius_id: string, _reason?: string) => {
    const run: Run = { id: nid("run"), task_id: taskId, marius_id, adapter_type: "hermes_gateway",
      wake_source: "on_demand", status: "running", continuation_attempt: 0, usage_json: {},
      started_at: now(), created_at: now() };
    db.runs.push(run);
    db.runEvents[run.id] = [{ seq: 1, type: "run.started", payload: { adapter: "hermes_gateway" }, created_at: now() }];
    return lag({ run_id: run.id });
  },
};
