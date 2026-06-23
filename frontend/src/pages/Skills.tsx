import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Modal } from "../ui";

const SKILL_MD = "SKILL.md";

function SkillCard({ s, onOpen, onPreview }: { s: Skill; onOpen: () => void; onPreview: (e: React.MouseEvent) => void }) {
  const { t } = useI18n();
  const builtin = s.source === "builtin";
  return (
    <div className="panel p-4 flex flex-col gap-3">
      <button onClick={onOpen} className="flex items-start gap-3 text-left">
        <div
          className="flex items-center justify-center rounded-lg text-base shrink-0 font-serif"
          style={{
            width: 38, height: 38,
            background: builtin ? "linear-gradient(180deg,#d8a23a,#b3812a)" : "var(--panel-2)",
            color: builtin ? "#fff8e8" : "var(--ink)",
            border: builtin ? "none" : "1px solid var(--line)",
          }}
        >⚒</div>
        <div className="min-w-0 flex-1">
          <div className="font-serif text-base font-semibold leading-tight">{s.name}</div>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="chip">{builtin ? t("skill.builtin") : s.source}</span>
            <span className="text-[0.66rem] font-mono" style={{ color: "var(--ink-faint)" }}>{Object.keys(s.files).length} files</span>
          </div>
        </div>
      </button>
      {s.description && <div className="text-sm" style={{ color: "var(--ink-soft)" }}>{s.description}</div>}
      <div className="flex items-center gap-2 mt-auto pt-1">
        <button className="btn !py-1 !px-2.5 text-xs" onClick={onPreview}>{t("skill.preview")}</button>
        <button className="btn !py-1 !px-2.5 text-xs ml-auto" onClick={onOpen}>{t("common.edit")}</button>
      </div>
    </div>
  );
}

function PreviewModal({ s, onClose }: { s: Skill; onClose: () => void }) {
  const { t } = useI18n();
  const content = s.files?.[SKILL_MD] ?? Object.values(s.files)[0] ?? "";
  return (
    <Modal title={s.name} onClose={onClose} wide
      footer={<button className="btn" onClick={onClose}>{t("common.done")}</button>}>
      {content ? (
        <pre className="font-mono text-[0.74rem] leading-relaxed whitespace-pre-wrap" style={{ color: "var(--ink)" }}>{content}</pre>
      ) : (
        <div style={{ color: "var(--ink-faint)" }}>{t("skill.noContent")}</div>
      )}
    </Modal>
  );
}

function NewSkillModal({ wsId, onClose, onCreated }: { wsId: string; onClose: () => void; onCreated: (s: Skill) => void }) {
  const { t } = useI18n();
  const [tab, setTab] = useState<"manual" | "import">("manual");
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  const submit = async () => {
    setBusy(true); setError(undefined);
    try {
      const s = tab === "manual"
        ? await api.createManualSkill(wsId, { name: name.trim(), description: desc.trim() })
        : await api.importSkill(wsId, url.trim());
      onCreated(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("err.failedLoad"));
    } finally {
      setBusy(false);
    }
  };

  const canSubmit = tab === "manual" ? name.trim() : url.trim();

  return (
    <Modal title={t("skill.newSkill")} onClose={onClose}
      footer={<>
        <button className="btn" onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={!canSubmit || busy} onClick={submit}>
          {busy ? t("skill.importing") : (tab === "manual" ? t("skill.create") : t("skill.importBtn"))}
        </button>
      </>}>
      <div className="flex gap-1 p-1 rounded-lg mb-4" style={{ background: "var(--panel-2)", border: "1px solid var(--line)" }}>
        {(["manual", "import"] as const).map((k) => (
          <button key={k} className="flex-1 py-1.5 rounded-md text-sm transition-colors"
            style={{ background: tab === k ? "var(--ink)" : "transparent", color: tab === k ? "var(--panel)" : "var(--ink-soft)" }}
            onClick={() => setTab(k)}>
            {k === "manual" ? t("skill.newManual") : t("skill.newImport")}
          </button>
        ))}
      </div>

      {tab === "manual" ? (
        <div className="grid gap-3">
          <label className="flex flex-col gap-1.5">
            <span className="text-[0.66rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>{t("skill.name")}</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("skill.name")} autoFocus />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[0.66rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>{t("skill.desc")}</span>
            <textarea className="input resize-none" rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} />
          </label>
          <div className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("skill.manualHint")}</div>
        </div>
      ) : (
        <div className="grid gap-2.5">
          <label className="text-[0.66rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>{t("skill.newImport")}</label>
          <input className="input font-mono text-[0.8rem]" placeholder={t("skill.importPlaceholder")} value={url} onChange={(e) => setUrl(e.target.value)} autoFocus />
          <div className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("skill.importHint")}</div>
        </div>
      )}
      {error && <div className="text-xs mt-3 px-2.5 py-2 rounded" style={{ background: "rgba(168,73,44,0.1)", color: "var(--rust)" }}>{error}</div>}
    </Modal>
  );
}

export default function Skills() {
  const { workspace } = useApp();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [preview, setPreview] = useState<Skill>();
  const [creating, setCreating] = useState(false);

  const load = async () => { if (workspace) setSkills(await api.skills(workspace.id)); };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [workspace?.id]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center gap-3 mb-1">
        <h1 className="font-serif text-xl font-semibold">{t("skill.title")}</h1>
        <span className="chip">{t("skill.count", { n: skills.length })}</span>
        <div className="ml-auto">
          {workspace && <button className="btn btn-primary" onClick={() => setCreating(true)}>＋ {t("skill.newSkill")}</button>}
        </div>
      </div>
      <p className="text-sm mb-5" style={{ color: "var(--ink-soft)" }}>{t("skill.subtitle")}</p>

      {skills.length === 0 && (
        <div className="panel p-8 text-center" style={{ color: "var(--ink-faint)" }}>{t("skill.empty")}</div>
      )}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))" }}>
        {skills.map((s) => (
          <SkillCard
            key={s.id} s={s}
            onOpen={() => navigate(`/skills/${s.id}`)}
            onPreview={(e) => { e.stopPropagation(); setPreview(s); }}
          />
        ))}
      </div>

      {preview && <PreviewModal s={preview} onClose={() => setPreview(undefined)} />}
      {creating && workspace && (
        <NewSkillModal
          wsId={workspace.id}
          onClose={() => setCreating(false)}
          onCreated={(s) => { setCreating(false); navigate(`/skills/${s.id}`); }}
        />
      )}
    </div>
  );
}
