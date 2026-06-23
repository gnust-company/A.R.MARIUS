import { useEffect, useState } from "react";
import { api, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";

function SkillCard({ s, onPreview }: { s: Skill; onPreview: (s: Skill) => void }) {
  const { t } = useI18n();
  const builtin = s.source === "builtin";
  return (
    <div className="panel p-4 flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div
          className="flex items-center justify-center rounded-lg text-base shrink-0 font-serif"
          style={{
            width: 38, height: 38,
            background: builtin ? "linear-gradient(180deg,#d8a23a,#b3812a)" : "var(--panel-2)",
            color: builtin ? "#fff8e8" : "var(--ink)",
            border: builtin ? "none" : "1px solid var(--line)",
          }}
        >
          {s.kind === "mcp" ? "⚙" : "⚒"}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-serif text-base font-semibold leading-tight">{s.name}</div>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="chip">{builtin ? t("skill.builtin") : t("skill.custom")}</span>
            <span className="chip" style={{ background: "var(--panel-2)" }}>{s.kind}</span>
          </div>
        </div>
      </div>
      {s.description && (
        <div className="text-sm" style={{ color: "var(--ink-soft)" }}>{s.description}</div>
      )}
      <div className="flex items-center gap-2 mt-auto pt-1">
        <button className="btn !py-1 !px-2.5 text-xs" onClick={() => onPreview(s)}>{t("skill.preview")}</button>
        {s.install_url && (
          <a href={s.install_url} target="_blank" rel="noreferrer" className="text-[0.72rem] font-mono truncate hover:underline" style={{ color: "var(--gold)" }}>
            {t("skill.install")} →
          </a>
        )}
      </div>
    </div>
  );
}

function PreviewModal({ s, onClose }: { s: Skill; onClose: () => void }) {
  const { t } = useI18n();
  const [content, setContent] = useState<string>();
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setContent(undefined);
    setError(false);
    (async () => {
      // Prefer the install_url (e.g. /static/skills/.../SKILL.md); fall back to inline notes.
      if (s.install_url) {
        try {
          const res = await fetch(s.install_url);
          if (!res.ok) throw new Error(String(res.status));
          const text = await res.text();
          if (!cancelled) setContent(text);
        } catch {
          if (!cancelled) setError(true);
        }
      } else if (s.instructions) {
        if (!cancelled) setContent(s.instructions);
      } else if (!cancelled) {
        setContent("");
      }
    })();
    return () => { cancelled = true; };
  }, [s]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: "rgba(40,28,10,0.45)" }}
      onClick={onClose}
    >
      <div
        className="panel w-full max-w-2xl max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
        style={{ boxShadow: "0 30px 60px -30px rgba(60,40,10,0.45)" }}
      >
        <div className="flex items-center gap-3 px-5 py-3.5" style={{ borderBottom: "1px solid var(--line)" }}>
          <span className="font-serif text-lg font-semibold">{s.name}</span>
          <span className="chip" style={{ background: "var(--panel-2)" }}>{s.kind}</span>
          <div className="ml-auto flex items-center gap-2">
            {s.install_url && (
              <a href={s.install_url} target="_blank" rel="noreferrer" className="text-xs" style={{ color: "var(--gold)" }}>{t("skill.install")} ↗</a>
            )}
            <button className="btn !py-1 !px-2.5 text-xs" onClick={onClose}>{t("common.done")}</button>
          </div>
        </div>
        <div className="flex-1 min-h-0 overflow-auto p-5">
          {content === undefined && !error && (
            <div style={{ color: "var(--ink-faint)" }}>{t("skill.loading")}</div>
          )}
          {error && (
            <div style={{ color: "var(--rust)" }}>{t("skill.fetchFail")}</div>
          )}
          {content === "" && (
            <div style={{ color: "var(--ink-faint)" }}>{t("skill.noContent")}</div>
          )}
          {content && (
            <pre className="font-mono text-[0.74rem] leading-relaxed whitespace-pre-wrap" style={{ color: "var(--ink)" }}>{content}</pre>
          )}
        </div>
      </div>
    </div>
  );
}

function Submit({ wsId, onDone }: { wsId: string; onDone: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [kind, setKind] = useState("http");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await api.createSkill(wsId, {
        name: name.trim(), description: desc.trim(), kind,
        install_url: url.trim() || undefined,
      });
      setName(""); setDesc(""); setUrl(""); setOpen(false);
      onDone();
    } finally {
      setBusy(false);
    }
  };

  if (!open) return <button className="btn btn-primary" onClick={() => setOpen(true)}>＋ {t("skill.submit")}</button>;

  return (
    <div className="panel p-4 grid gap-2.5" style={{ maxWidth: 460 }}>
      <div className="font-serif text-lg">{t("skill.submitTitle")}</div>
      <input className="input" placeholder={t("skill.name")} value={name} onChange={(e) => setName(e.target.value)} />
      <input className="input" placeholder={t("skill.desc")} value={desc} onChange={(e) => setDesc(e.target.value)} />
      <label className="text-[0.66rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>{t("skill.kind")}</label>
      <select className="input" value={kind} onChange={(e) => setKind(e.target.value)}>
        <option value="http">http</option>
        <option value="mcp">mcp</option>
      </select>
      <input className="input" placeholder={t("skill.installUrl")} value={url} onChange={(e) => setUrl(e.target.value)} />
      <div className="flex gap-2 mt-1">
        <button className="btn" onClick={() => setOpen(false)}>{t("skill.cancel")}</button>
        <button className="btn btn-primary" disabled={!name.trim() || busy} onClick={save}>{t("skill.save")}</button>
      </div>
    </div>
  );
}

export default function Skills() {
  const { workspace } = useApp();
  const { t } = useI18n();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [preview, setPreview] = useState<Skill>();

  const load = async () => { if (workspace) setSkills(await api.skills(workspace.id)); };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [workspace?.id]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center gap-3 mb-1">
        <h1 className="font-serif text-xl font-semibold">{t("skill.title")}</h1>
        <span className="chip">{t("skill.count", { n: skills.length })}</span>
        <div className="ml-auto">{workspace && <Submit wsId={workspace.id} onDone={load} />}</div>
      </div>
      <p className="text-sm mb-5" style={{ color: "var(--ink-soft)" }}>{t("skill.subtitle")}</p>

      {skills.length === 0 && (
        <div className="panel p-8 text-center" style={{ color: "var(--ink-faint)" }}>{t("skill.empty")}</div>
      )}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))" }}>
        {skills.map((s) => <SkillCard key={s.id} s={s} onPreview={setPreview} />)}
      </div>

      {preview && <PreviewModal s={preview} onClose={() => setPreview(undefined)} />}
    </div>
  );
}
