import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";

const SKILL_MD = "SKILL.md";

export default function SkillEditor() {
  const { skillId } = useParams();
  const { workspace } = useApp();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [skill, setSkill] = useState<Skill>();
  const [files, setFiles] = useState<Record<string, string>>({});
  const [original, setOriginal] = useState<Record<string, string>>({});
  const [selected, setSelected] = useState<string>(SKILL_MD);
  const [newPath, setNewPath] = useState("");
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [savedAt, setSavedAt] = useState<number>();
  const [error, setError] = useState<string>();

  const load = async () => {
    if (!workspace || !skillId) return;
    try {
      const sk = await api.skill(workspace.id, skillId);
      setSkill(sk);
      setFiles({ ...sk.files });
      setOriginal({ ...sk.files });
      setSelected(sk.files[SKILL_MD] !== undefined ? SKILL_MD : Object.keys(sk.files)[0]);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("err.failedLoad"));
    }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [workspace?.id, skillId]);

  const paths = useMemo(() => Object.keys(files).sort((a, b) => {
    // SKILL.md first, then folders, then files.
    if (a === SKILL_MD) return -1;
    if (b === SKILL_MD) return 1;
    const af = a.includes("/"), bf = b.includes("/");
    if (af !== bf) return af ? -1 : 1;
    return a.localeCompare(b);
  }), [files]);

  const dirty = JSON.stringify(files) !== JSON.stringify(original);

  const setContent = (path: string, content: string) =>
    setFiles((f) => ({ ...f, [path]: content }));

  const addFile = () => {
    const p = newPath.trim().replace(/^\/+/, "");
    if (!p || files[p] !== undefined) return;
    setFiles((f) => ({ ...f, [p]: "" }));
    setSelected(p);
    setNewPath(""); setAdding(false);
  };

  const delFile = (path: string) => {
    if (!window.confirm(t("skill.confirmDelete"))) return;
    setFiles((f) => {
      const next = { ...f };
      delete next[path];
      return next;
    });
    if (selected === path) setSelected(SKILL_MD);
  };

  const save = async () => {
    if (!workspace || !skill) return;
    setBusy(true);
    try {
      const updated = await api.updateSkill(workspace.id, skill.id, files);
      setSkill(updated);
      setFiles({ ...updated.files });
      setOriginal({ ...updated.files });
      setSavedAt(Date.now());
      setError(undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("err.failedLoad"));
    } finally {
      setBusy(false);
    }
  };

  if (!workspace) return null;
  if (error && !skill) {
    return <div className="h-full flex items-center justify-center" style={{ color: "var(--rust)" }}>{error}</div>;
  }
  if (!skill) {
    return <div className="h-full flex items-center justify-center" style={{ color: "var(--ink-faint)" }}>{t("common.loading")}</div>;
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-3 px-6 pt-5 pb-3 shrink-0">
        <button className="btn !py-1 !px-2 !text-xs" onClick={() => navigate("/skills")}>← {t("nav.skills")}</button>
        <h1 className="font-serif text-xl font-semibold truncate">{skill.name}</h1>
        <span className="chip" style={{ background: "var(--panel-2)" }}>{skill.source}</span>
        <div className="ml-auto flex items-center gap-2">
          {dirty ? (
            <span className="text-xs" style={{ color: "var(--gold)" }}>{t("skill.unsaved")}</span>
          ) : savedAt ? (
            <span className="text-xs" style={{ color: "var(--ink-faint)" }}>{t("skill.saved")}</span>
          ) : null}
          <button className="btn btn-primary" disabled={!dirty || busy} onClick={save}>{t("skill.save")}</button>
        </div>
      </div>
      {error && <div className="px-6 text-xs" style={{ color: "var(--rust)" }}>{error}</div>}

      <div className="flex-1 min-h-0 flex gap-3 px-6 pb-5">
        {/* File tree */}
        <div className="w-[230px] shrink-0 flex flex-col min-h-0">
          <div className="text-[0.66rem] uppercase tracking-[0.14em] mb-2 px-1" style={{ color: "var(--ink-faint)" }}>{t("skill.files")}</div>
          <div className="panel p-1.5 flex-1 min-h-0 overflow-y-auto">
            {paths.map((p) => (
              <div
                key={p}
                className="group flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer text-sm"
                style={{ background: p === selected ? "var(--panel-2)" : "transparent" }}
                onClick={() => setSelected(p)}
              >
                <span style={{ color: "var(--ink-faint)" }}>{p === SKILL_MD ? "❖" : p.includes("/") ? "▤" : "▮"}</span>
                <span className="truncate font-mono text-[0.78rem] flex-1" style={{ color: p === SKILL_MD ? "var(--ink)" : "var(--ink-soft)" }}>{p}</span>
                {p !== SKILL_MD && (
                  <button
                    className="opacity-0 group-hover:opacity-100 text-[0.66rem] px-1"
                    style={{ color: "var(--rust)" }}
                    onClick={(e) => { e.stopPropagation(); delFile(p); }}
                    title={t("skill.deleteFile")}
                  >×</button>
                )}
              </div>
            ))}
            {adding ? (
              <div className="flex gap-1 p-1.5">
                <input
                  autoFocus className="input !py-1 !px-1.5 !text-xs font-mono" placeholder={t("skill.newFilePath")}
                  value={newPath} onChange={(e) => setNewPath(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") addFile(); if (e.key === "Escape") setAdding(false); }}
                />
              </div>
            ) : (
              <button className="w-full text-left text-xs px-2 py-1.5 rounded-md" style={{ color: "var(--gold)" }}
                onClick={() => setAdding(true)}>＋ {t("skill.addFile")}</button>
            )}
          </div>
        </div>

        {/* Editor */}
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="text-[0.66rem] uppercase tracking-[0.14em] mb-2 px-1 font-mono" style={{ color: "var(--ink-faint)" }}>
            {selected ?? "—"}
          </div>
          <textarea
            className="input flex-1 min-h-0 resize-none font-mono text-[0.8rem] leading-relaxed"
            spellCheck={false}
            value={selected ? (files[selected] ?? "") : ""}
            onChange={(e) => selected && setContent(selected, e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
