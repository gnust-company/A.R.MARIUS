export const API_BASE =
  (import.meta.env.VITE_API_URL?.replace(/\/$/, "") || "http://localhost:8000");

export interface Workspace { id: string; name: string; slug: string }
export interface Project {
  id: string; workspace_id: string; name: string; slug: string; description?: string | null;
}
export interface Marius {
  id: string; workspace_id: string; name: string; role: string; skills: string[];
  adapter_type: string; liveness: string; last_seen_at?: string | null;
}
export type TaskStatus =
  | "backlog" | "todo" | "in_progress" | "in_review" | "blocked" | "done" | "cancelled";
export interface Task {
  id: string; project_id: string; title: string; description?: string | null;
  status: TaskStatus; status_reason?: string | null; assigned_marius_id?: string | null;
  next_action?: string | null; created_at?: string | null; updated_at?: string | null;
}
export interface Comment {
  id: string; task_id: string; author_kind: "human" | "agent" | "system";
  author_marius_id?: string | null; author_user_id?: string | null;
  body: string; mentions: string[]; created_at?: string | null;
}
export interface Artifact {
  id: string; task_id: string; marius_id?: string | null; name: string; kind: string;
  uri: string; content_sha256?: string | null; size_bytes?: number | null; created_at?: string | null;
}
export interface Run {
  id: string; task_id?: string | null; marius_id?: string | null; adapter_type: string;
  wake_source: string; status: string; error?: string | null; next_action?: string | null;
  continuation_attempt: number; usage_json: Record<string, number>;
  started_at?: string | null; finished_at?: string | null; created_at?: string | null;
}
export interface RunEvent { seq: number; type: string; payload: Record<string, any>; created_at?: string | null }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail ?? detail; } catch { /* ignore */ }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  workspaces: () => req<Workspace[]>("/v1/workspaces"),
  projects: (ws: string) => req<Project[]>(`/v1/workspaces/${ws}/projects`),
  mariuses: (ws: string) => req<Marius[]>(`/v1/workspaces/${ws}/mariuses`),
  registerMarius: (ws: string, body: {
    name: string; role: string; skills: string[]; adapter_type: string; adapter_config: Record<string, string>;
  }) =>
    req<Marius & { agent_token: string }>(`/v1/workspaces/${ws}/mariuses`, {
      method: "POST", body: JSON.stringify(body),
    }),
  tasks: (project: string) => req<Task[]>(`/v1/projects/${project}/tasks`),
  task: (id: string) => req<Task>(`/v1/tasks/${id}`),
  createTask: (project: string, title: string, description?: string) =>
    req<Task>(`/v1/projects/${project}/tasks`, {
      method: "POST", body: JSON.stringify({ title, description }),
    }),
  assign: (taskId: string, marius_id: string) =>
    req<Task>(`/v1/tasks/${taskId}/assign`, { method: "POST", body: JSON.stringify({ marius_id }) }),
  transition: (taskId: string, status: TaskStatus, reason?: string) =>
    req<Task>(`/v1/tasks/${taskId}/status`, { method: "POST", body: JSON.stringify({ status, reason }) }),
  comments: (taskId: string) => req<Comment[]>(`/v1/tasks/${taskId}/comments`),
  postComment: (taskId: string, body: string, author_user_id = "patron@armarius") =>
    req<Comment>(`/v1/tasks/${taskId}/comments`, {
      method: "POST", body: JSON.stringify({ body, author_kind: "human", author_user_id }),
    }),
  artifacts: (taskId: string) => req<Artifact[]>(`/v1/tasks/${taskId}/artifacts`),
  runs: (taskId: string) => req<Run[]>(`/v1/tasks/${taskId}/runs`),
  runEvents: (runId: string) => req<RunEvent[]>(`/v1/runs/${runId}/events`),
  wake: (taskId: string, marius_id: string, reason?: string) =>
    req<{ run_id: string }>(`/v1/tasks/${taskId}/wake`, {
      method: "POST", body: JSON.stringify({ marius_id, reason }),
    }),
  adapters: () => req<{ adapters: string[] }>("/v1/adapters"),
};

export function streamRun(runId: string, onEvent: (e: RunEvent & { type: string }) => void): () => void {
  const es = new EventSource(`${API_BASE}/v1/runs/${runId}/stream`);
  es.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      onEvent(data);
      if (data.type === "run.finished") es.close();
    } catch { /* ignore */ }
  };
  es.onerror = () => es.close();
  return () => es.close();
}
