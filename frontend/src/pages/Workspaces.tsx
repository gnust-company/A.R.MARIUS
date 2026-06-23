import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Workspace } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";

interface Counts { projects: number; agents: number }

function WorkspaceCard({
  ws, personal, current, counts, onOpen,
}: {
  ws: Workspace; personal: boolean; current: boolean; counts?: Counts; onOpen: () => void;
}) {
  const { t } = useI18n();
  return (
    <div className="panel p-4 flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div
          className="flex items-center justify-center rounded-lg font-serif text-lg shrink-0"
          style={{
            width: 40, height: 40,
            background: "linear-gradient(180deg,#d8a23a,#b3812a)",
            color: "#fff8e8",
          }}
        >
          {ws.name.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-serif text-lg font-semibold leading-tight truncate">{ws.name}</div>
          <div className="flex items-center gap-1.5 mt-1">
            {personal && <span className="chip">{t("ws.personal")}</span>}
            {current && (
              <span className="chip" style={{ background: "var(--panel-2)" }}>{t("ws.current")}</span>
            )}
          </div>
        </div>
      </div>
      <div className="rule" />
      <div className="flex items-center gap-4 text-xs" style={{ color: "var(--ink-faint)" }}>
        <span>{counts ? counts.projects : "—"} {t("ws.projects")}</span>
        <span>{counts ? counts.agents : "—"} {t("ws.agents")}</span>
        <button className="btn ml-auto" disabled={current} onClick={onOpen}>
          {current ? t("ws.current") : t("ws.open")}
        </button>
      </div>
    </div>
  );
}

export default function Workspaces() {
  const { workspaces, workspace, setWorkspaceId, reloadWorkspaces } = useApp();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [counts, setCounts] = useState<Record<string, Counts>>({});
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  // Load lightweight per-workspace counts (projects + agents).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const entries = await Promise.all(
        workspaces.map(async (w) => {
          try {
            const [projs, mar] = await Promise.all([api.projects(w.id), api.mariuses(w.id)]);
            return [w.id, { projects: projs.length, agents: mar.length }] as const;
          } catch {
            return [w.id, { projects: 0, agents: 0 }] as const;
          }
        }),
      );
      if (!cancelled) setCounts(Object.fromEntries(entries));
    })();
    return () => { cancelled = true; };
  }, [workspaces]);

  const create = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const ws = await api.createWorkspace(name.trim());
      await reloadWorkspaces();
      setWorkspaceId(ws.id);
      setName(""); setCreating(false);
      navigate("/");
    } finally {
      setBusy(false);
    }
  };

  const open = (id: string) => { setWorkspaceId(id); navigate("/"); };

  return (
    <div className="h-full overflow-y-auto p-6" style={{ maxWidth: 920, margin: "0 auto" }}>
      <div className="flex items-center gap-3 mb-1">
        <h1 className="font-serif text-xl font-semibold">{t("ws.title")}</h1>
        <span className="chip">{workspaces.length}</span>
        <div className="ml-auto">
          {!creating && (
            <button className="btn btn-primary" onClick={() => setCreating(true)}>＋ {t("ws.create")}</button>
          )}
        </div>
      </div>
      <p className="text-sm mb-5" style={{ color: "var(--ink-soft)" }}>{t("ws.subtitle")}</p>

      {creating && (
        <div className="panel p-4 mb-5 grid gap-2.5" style={{ maxWidth: 460 }}>
          <div className="font-serif text-lg">{t("ws.createTitle")}</div>
          <input
            autoFocus className="input" placeholder={t("ws.namePlaceholder")}
            value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") create(); if (e.key === "Escape") setCreating(false); }}
          />
          <div className="flex gap-2 mt-1">
            <button className="btn" onClick={() => { setCreating(false); setName(""); }}>{t("ws.cancel")}</button>
            <button className="btn btn-primary" disabled={!name.trim() || busy} onClick={create}>
              {t("ws.create")}
            </button>
          </div>
        </div>
      )}

      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))" }}>
        {workspaces.map((w, i) => (
          <WorkspaceCard
            key={w.id}
            ws={w}
            personal={i === 0}
            current={w.id === workspace?.id}
            counts={counts[w.id]}
            onOpen={() => open(w.id)}
          />
        ))}
      </div>
    </div>
  );
}
