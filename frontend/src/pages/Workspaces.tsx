import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Workspace } from "../api";
import { useApp } from "../store";
import { useAuth } from "../auth";
import { useI18n } from "../i18n";
import { DropCap, Icon, Modal } from "../ui";

interface Counts { projects: number; agents: number }

function WorkspaceCard({
  ws, personal, current, counts, onOpen,
}: {
  ws: Workspace; personal: boolean; current: boolean; counts?: Counts; onOpen: () => void;
}) {
  const { t } = useI18n();
  return (
    <button onClick={onOpen} className="panel gilt quill-in p-5 flex flex-col gap-3 text-left">
      <div className="flex items-start gap-3">
        <div
          className="flex items-center justify-center rounded-lg font-display text-xl shrink-0"
          style={{
            width: 48, height: 48,
            background: personal ? "linear-gradient(180deg,#D9744E,#C25A3A)" : "var(--panel-2)",
            color: personal ? "#FBF7EC" : "var(--ink)",
            border: personal ? "1px solid #A8462E" : "1px solid var(--line)",
            boxShadow: personal ? "0 0 0 2px rgba(201,162,39,.3) inset" : "none",
          }}
        >
          {ws.name.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-display text-lg font-semibold leading-tight truncate" style={{ color: "var(--ink)" }}>{ws.name}</div>
          <div className="flex items-center gap-1.5 mt-1 flex-wrap">
            {personal && <span className="chip" style={{ background: "rgba(194,90,58,0.1)", color: "var(--terra)", borderColor: "transparent" }}>{t("ws.personal")}</span>}
            {current && <span className="chip" style={{ background: "var(--panel-2)" }}>{t("ws.current")}</span>}
          </div>
        </div>
        <Icon name="back" size={16} className="shrink-0 rotate-180 mt-1" />
      </div>
      <div className="rule" />
      <div className="flex items-center gap-4 text-xs font-mono" style={{ color: "var(--ink-faint)" }}>
        <span className="flex items-center gap-1.5"><Icon name="board" size={13} /> {counts ? counts.projects : "—"} {counts && counts.projects === 1 ? t("ws.project") : t("ws.projects")}</span>
        <span className="flex items-center gap-1.5"><Icon name="directory" size={13} /> {counts ? counts.agents : "—"} {counts && counts.agents === 1 ? t("ws.agent") : t("ws.agents")}</span>
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
    <div className="h-screen flex flex-col">
      {/* Top bar: brand + user */}
      <header className="h-16 shrink-0 flex items-center gap-3 px-6" style={{ borderBottom: "1px solid var(--line)", background: "var(--panel)" }}>
        <div className="flex items-center justify-center rounded-lg font-initial text-lg"
          style={{ width: 34, height: 34, background: "linear-gradient(180deg,#D9744E,#C25A3A)", color: "#FBF7EC", border: "1px solid #A8462E" }}>A</div>
        <div className="font-display text-[1.15rem] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>Armarius</div>
        <div className="ml-auto flex items-center gap-2.5">
          <span className="text-sm" style={{ color: "var(--ink-soft)" }}>{user?.full_name}</span>
          <button className="btn !py-1 !px-2.5 text-xs" onClick={signOut}>
            <Icon name="signout" size={13} /> {t("auth.signOut")}
          </button>
        </div>
      </header>

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-6 py-10">
          {/* Illuminated header */}
          <header className="vellum quill-in px-7 py-6 mb-8 flex items-start gap-4">
            <DropCap letter={t("ws.title").charAt(0)} size={52} />
            <div className="min-w-0 flex-1">
              <h1 className="font-display text-2xl font-semibold leading-none" style={{ color: "var(--ink)" }}>{t("ws.title")}</h1>
              <p className="text-sm mt-2 leading-relaxed" style={{ color: "var(--ink-soft)" }}>{t("ws.subtitle")}</p>
              <div className="flex items-center gap-2 mt-3 flex-wrap">
                <span className="chip">{workspaces.length === 1 ? t("ws.countOne") : t("ws.count", { n: workspaces.length })}</span>
              </div>
            </div>
            <button className="btn btn-primary shrink-0" onClick={() => setCreating(true)}>
              <Icon name="plus" size={15} /> {t("ws.create")}
            </button>
          </header>

          <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(290px,1fr))" }}>
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
            <button className="btn btn-primary" disabled={!name.trim() || busy} onClick={create}>
              <Icon name="plus" size={14} /> {t("ws.create")}
            </button>
          </>}>
          <label className="text-[0.62rem] uppercase tracking-[0.16em] mb-1.5 block font-mono" style={{ color: "var(--ink-faint)" }}>{t("ws.namePlaceholder")}</label>
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
