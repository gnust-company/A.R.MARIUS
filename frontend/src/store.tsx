import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, type Marius, type Project, type Workspace } from "./api";

const WS_KEY = "armarius_workspace_id";

interface AppState {
  loading: boolean;
  error?: string;
  // All workspaces owned by the user; the first is the personal one.
  workspaces: Workspace[];
  workspace?: Workspace;
  setWorkspaceId: (id: string) => void;
  reloadWorkspaces: () => Promise<void>;
  projects: Project[];
  project?: Project;
  setProjectId: (id: string) => void;
  mariuses: Marius[];
  mariusById: (id?: string | null) => Marius | undefined;
  reloadDirectory: () => Promise<void>;
}

const Ctx = createContext<AppState | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceIdState] = useState<string>();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>();
  const [mariuses, setMariuses] = useState<Marius[]>([]);

  const workspace = workspaces.find((w) => w.id === workspaceId) ?? workspaces[0];

  const setWorkspaceId = (id: string) => {
    setWorkspaceIdState(id);
    localStorage.setItem(WS_KEY, id);
  };

  // Load the workspace list once on mount; pick the stored one or the personal (first).
  useEffect(() => {
    (async () => {
      try {
        const ws = await api.workspaces();
        if (ws.length === 0) { setError("No workspace found."); setLoading(false); return; }
        setWorkspaces(ws);
        const stored = localStorage.getItem(WS_KEY);
        const pick = ws.find((w) => w.id === stored)?.id ?? ws[0].id;
        setWorkspaceIdState(pick);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
        setLoading(false);
      }
    })();
  }, []);

  // Whenever the active workspace changes, load its projects + directory.
  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [projs, mar] = await Promise.all([
          api.projects(workspace.id),
          api.mariuses(workspace.id),
        ]);
        if (cancelled) return;
        setProjects(projs);
        setProjectId(projs[0]?.id);
        setMariuses(mar);
        setError(undefined);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [workspace?.id]);

  const reloadWorkspaces = async () => setWorkspaces(await api.workspaces());
  const reloadDirectory = async () => {
    if (workspace) setMariuses(await api.mariuses(workspace.id));
  };

  const value: AppState = {
    loading, error,
    workspaces, workspace, setWorkspaceId, reloadWorkspaces,
    projects,
    project: projects.find((p) => p.id === projectId),
    setProjectId,
    mariuses,
    mariusById: (id) => (id ? mariuses.find((m) => m.id === id) : undefined),
    reloadDirectory,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useApp(): AppState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useApp must be used within AppProvider");
  return ctx;
}
