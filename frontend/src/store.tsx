import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, type Marius, type Project, type Workspace } from "./api";

interface AppState {
  loading: boolean;
  error?: string;
  workspace?: Workspace;
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
  const [workspace, setWorkspace] = useState<Workspace>();
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState<string>();
  const [mariuses, setMariuses] = useState<Marius[]>([]);

  useEffect(() => {
    (async () => {
      try {
        const ws = await api.workspaces();
        if (ws.length === 0) { setError("No workspace found."); setLoading(false); return; }
        setWorkspace(ws[0]);
        const [projs, mar] = await Promise.all([api.projects(ws[0].id), api.mariuses(ws[0].id)]);
        setProjects(projs);
        setProjectId(projs[0]?.id);
        setMariuses(mar);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const reloadDirectory = async () => {
    if (workspace) setMariuses(await api.mariuses(workspace.id));
  };

  const value: AppState = {
    loading, error, workspace, projects,
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
