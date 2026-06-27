import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api, MOCK, type Marius, type Project, type Workspace } from "./api";
import { bus, ensureSimulator } from "./mock/bus";
import { useI18n } from "./i18n";

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
  const { t } = useI18n();
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
        if (ws.length === 0) { setError(t("err.noWorkspace")); setLoading(false); return; }
        setWorkspaces(ws);
        const stored = localStorage.getItem(WS_KEY);
        const pick = ws.find((w) => w.id === stored)?.id ?? ws[0].id;
        setWorkspaceIdState(pick);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("err.failedLoad"));
        setLoading(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Whenever the active workspace changes, load its projects + directory. If the
  // workspace has no project yet, lazily create the default "General" one so the
  // board always has a home (no confusing "Getting Started" artefact).
  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        let projs = await api.projects(workspace.id);
        if (projs.length === 0) {
          await api.createProject(workspace.id, "General");
          projs = await api.projects(workspace.id);
        }
        const mar = await api.mariuses(workspace.id);
        if (cancelled) return;
        setProjects(projs);
        setProjectId(projs[0]?.id);
        setMariuses(mar);
        setError(undefined);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : t("err.failedLoad"));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.id]);

  // FE-1 (MOCK only): subscribe to the simulated workspace event bus so liveness dots
  // decay live. The real workspace-SSE channel ships with the backend (BE-5).
  useEffect(() => {
    if (!MOCK) return;
    ensureSimulator();
    return bus.on("marius.liveness", ({ marius_id, liveness }) => {
      setMariuses((prev) => prev.map((m) => (m.id === marius_id ? { ...m, liveness } : m)));
    });
  }, []);

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
