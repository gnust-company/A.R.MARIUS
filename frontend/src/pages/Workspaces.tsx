import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Workspace } from "../api";
import { useApp } from "../store";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { Modal } from "../ui";

interface Counts { projects: number; agents: number }

function WorkspaceCard({
  ws, personal, current, counts, onOpen,
}: {
  ws: Workspace; personal: boolean; current: boolean; counts?: Counts; onOpen: () => void;
}) {
  const { t } = useI18n();
  return (
    <button onClick={onOpen} className="panel p-5 flex flex-col gap-3 text-left hover:-translate-y-0.5 transition-transform">
      <div className="flex items-start gap-3">
        <div
          className="flex items-center justify-center rounded-lg font-serif text-xl shrink-0"
          style={{
            width: 46, height: 46,
            background: personal ? "linear-gradient(180deg,#d8a23a,#b3812a)" : "var(--panel-2)",
            color: personal ? "#fff8e8" : "var(--ink)",
            border: personal ? "none" : "1px solid var(--line)",
          }}
        >
          {ws.name.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-serif text-lg font-semibold leading-tight truncate">{ws.name}</div>
          <div className="flex items-center gap-1.5 mt-1">
            {personal && <span className="chip">{t("ws.personal")}</span>}
            {current && <span className="chip" style={{ background: "var(--panel-2)" }}>{t("ws.current")}</span>}
          </div>
        </div>
      </div>
      <div className="rule" />
      <div className="flex items-center gap-4 text-xs" style={{ color: "var(--ink-faint)" }}>
        <span>{counts ? counts.projects : "—"} {counts && counts.projects === 1 ? t("ws.project") : t("ws.projects")}</span>
        <span>{counts ? counts.agents : "—"} {counts && counts.agents === 1 ? t("ws.agent") : t("ws.agents")}</span>
      </div>
    </button>
  );
}

export default function Workspaces() {
  const { workspaces, workspace, setWorkspaceId, reloadWorkspaces } = useApp();
  const { user, signOut } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [counts, setCounts] = useState<Record<string, Counts>>({});
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

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
    <div className="h-screen flex flex-col" style={{ background: "var(--panel)" }}>
      {/* Top bar: brand + user */}
      <header className="h-16 shrink-0 flex items-center gap-3 px-6" style={{ borderBottom: "1px solid var(--line)" }}>
        <div className="flex items-center justify-center rounded-lg font-serif text-lg"
          style={{ width: 34, height: 34, background: "linear-gradient(180deg,#d8a23a,#b3812a)", color: "#fff8e8" }}>A</div>
        <div className="font-serif text-[1.15rem] font-semibold tracking-tight">Armarius</div>
        <div className="ml-auto flex items-center gap-2.5">
          <span className="text-sm" style={{ color: "var(--ink-soft)" }}>{user?.full_name}</span>
          <button className="btn !py-1 !px-2.5 text-xs" onClick={signOut}>⎋ {t("auth.signOut")}</button>
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-10">
          <div className="flex items-center gap-3 mb-1">
            <h1 className="font-serif text-2xl font-semibold">{t("ws.title")}</h1>
            <span className="chip">{workspaces.length === 1 ? t("ws.countOne") : t("ws.count", { n: workspaces.length })}</span>
            <div className="ml-auto">
              <button className="btn btn-primary" onClick={() => setCreating(true)}>＋ {t("ws.create")}</button>
            </div>
          </div>
          <p className="text-sm mb-6" style={{ color: "var(--ink-soft)" }}>{t("ws.subtitle")}</p>

          <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))" }}>
            {workspaces.map((w, i) => (
              <WorkspaceCard
                key={w.id} ws={w} personal={i === 0} current={w.id === workspace?.id}
                counts={counts[w.id]} onOpen={() => open(w.id)}
              />
            ))}
          </div>
        </div>
      </div>

      {creating && (
        <Modal title={t("ws.createTitle")} onClose={() => { setCreating(false); setName(""); }}
          footer={<>
            <button className="btn" onClick={() => { setCreating(false); setName(""); }}>{t("ws.cancel")}</button>
            <button className="btn btn-primary" disabled={!name.trim() || busy} onClick={create}>{t("ws.create")}</button>
          </>}>
          <label className="text-[0.66rem] uppercase tracking-[0.14em] mb-1.5 block" style={{ color: "var(--ink-faint)" }}>{t("ws.namePlaceholder")}</label>
          <input
            autoFocus className="input" placeholder={t("ws.namePlaceholder")}
            value={name} onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") create(); }}
          />
        </Modal>
      )}
    </div>
  );
}
