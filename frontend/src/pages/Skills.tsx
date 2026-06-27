import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { DropCap, Icon, Modal } from "../ui";

const SKILL_MD = "SKILL.md";

function SkillCard({ s, index, onOpen, onPreview }: { s: Skill; index: number; onOpen: () => void; onPreview: () => void }) {
  const { t } = useI18n();
  const builtin = s.source === "builtin";
  return (
    <div className="panel gilt quill-in p-4 flex flex-col gap-3" style={{ animationDelay: `${index * 0.04}s` }}>
      <button onClick={onOpen} className="flex items-start gap-3 text-left">
        <div
          className="flex items-center justify-center rounded-lg shrink-0"
          style={{
            width: 40, height: 40,
            background: builtin ? "linear-gradient(180deg,#E0B540,#C9A227)" : "var(--panel-2)",
            color: builtin ? "#FBF7EC" : "var(--ink-soft)",
            border: builtin ? "1px solid #A8841D" : "1px solid var(--line)",
          }}
        >
          <Icon name="skills" size={20} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-display text-base font-semibold leading-tight truncate" style={{ color: "var(--ink)" }}>{s.name}</div>
          <div className="flex items-center gap-1.5 mt-1">
            <span className="chip" style={{ background: builtin ? "rgba(201,162,39,0.14)" : "var(--panel-2)", borderColor: "transparent", color: builtin ? "var(--manuscript-gold)" : "var(--ink-soft)" }}>
              {builtin ? t("skill.builtin") : s.source}
            </span>
            <span className="text-[0.66rem] font-mono" style={{ color: "var(--ink-faint)" }}>{Object.keys(s.files).length} {t("skill.files").toLowerCase()}</span>
          </div>
        </div>
      </button>
      {s.description && <div className="text-sm leading-relaxed" style={{ color: "var(--ink-soft)" }}>{s.description}</div>}
      <div className="flex items-center gap-2 mt-auto pt-1">
        <button className="btn !py-1 !px-2.5 text-xs" onClick={onPreview}>
          <Icon name="eye" size={13} /> {t("skill.preview")}
        </button>
        <button className="btn !py-1 !px-2.5 text-xs ml-auto" onClick={onOpen}>
          <Icon name="edit" size={13} /> {t("common.edit")}
        </button>
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
        <pre className="font-mono text-[0.76rem] leading-relaxed whitespace-pre-wrap p-4 rounded" style={{ color: "var(--ink)", background: "var(--paper-2)", border: "1px solid var(--line)" }}>{content}</pre>
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
          <Icon name={tab === "manual" ? "plus" : "link"} size={13} />
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
            <span className="text-[0.62rem] uppercase tracking-[0.16em] font-mono" style={{ color: "var(--ink-faint)" }}>{t("skill.name")}</span>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder={t("skill.name")} autoFocus />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[0.62rem] uppercase tracking-[0.16em] font-mono" style={{ color: "var(--ink-faint)" }}>{t("skill.desc")}</span>
            <textarea className="input resize-none" rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} />
          </label>
          <div className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("skill.manualHint")}</div>
        </div>
      ) : (
        <div className="grid gap-2.5">
          <span className="text-[0.62rem] uppercase tracking-[0.16em] font-mono" style={{ color: "var(--ink-faint)" }}>{t("skill.newImport")}</span>
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
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-7">
        {/* Illuminated header */}
        <header className="vellum quill-in px-7 py-5 mb-6 flex items-start gap-4">
          <DropCap letter={t("skill.title").charAt(0)} size={48} />
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-2xl font-semibold leading-none" style={{ color: "var(--ink)" }}>{t("skill.title")}</h1>
            <p className="text-sm mt-2 leading-relaxed" style={{ color: "var(--ink-soft)" }}>{t("skill.subtitle")}</p>
            <div className="flex items-center gap-2 mt-3">
              <span className="chip">{t("skill.count", { n: skills.length })}</span>
            </div>
          </div>
          {workspace && (
            <button className="btn btn-primary shrink-0" onClick={() => setCreating(true)}>
              <Icon name="plus" size={15} /> {t("skill.newSkill")}
            </button>
          )}
        </header>

        {skills.length === 0 && (
          <div className="panel p-10 text-center" style={{ color: "var(--ink-faint)" }}>{t("skill.empty")}</div>
        )}
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(290px,1fr))" }}>
          {skills.map((s, i) => (
            <SkillCard
              key={s.id} s={s} index={i}
              onOpen={() => navigate(`/skills/${s.id}`)}
              onPreview={() => setPreview(s)}
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
    </div>
  );
}
