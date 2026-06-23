import { useEffect, useState } from "react";
import { api, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";

function SkillCard({ s }: { s: Skill }) {
  const { t } = useI18n();
  const builtin = s.source === "builtin";
  return (
    <div className="panel p-4 flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <div
          className="flex items-center justify-center rounded-lg text-base shrink-0"
          style={{
            width: 38, height: 38,
            background: builtin ? "linear-gradient(180deg,#d8a23a,#b3812a)" : "var(--panel-2)",
            color: builtin ? "#fff8e8" : "var(--ink)",
            border: builtin ? "none" : "1px solid var(--line)",
          }}
        >
          {s.kind === "mcp" ? "⚙" : "⌁"}
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
      {s.install_url && (
        <>
          <div className="rule" />
          <a
            href={s.install_url}
            target="_blank"
            rel="noreferrer"
            className="text-[0.72rem] font-mono truncate"
            style={{ color: "var(--gold)" }}
          >
            {t("skill.install")} →
          </a>
        </>
      )}
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

  const load = async () => { if (workspace) setSkills(await api.skills(workspace.id)); };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [workspace?.id]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center gap-3 mb-1">
        <h1 className="font-serif text-xl font-semibold">{t("skill.title")}</h1>
        <span className="chip">{skills.length}</span>
        <div className="ml-auto">{workspace && <Submit wsId={workspace.id} onDone={load} />}</div>
      </div>
      <p className="text-sm mb-5" style={{ color: "var(--ink-soft)" }}>{t("skill.subtitle")}</p>

      {skills.length === 0 && (
        <div className="panel p-8 text-center" style={{ color: "var(--ink-faint)" }}>{t("skill.empty")}</div>
      )}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))" }}>
        {skills.map((s) => <SkillCard key={s.id} s={s} />)}
      </div>
    </div>
  );
}
