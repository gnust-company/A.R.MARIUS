import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { DropCap, Icon } from "../ui";

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
      {/* Illuminated header */}
      <header className="vellum mx-5 mt-4 px-6 py-4 flex items-center gap-4 shrink-0">
        <DropCap letter={skill.name.charAt(0)} size={40} />
        <div className="min-w-0 flex-1">
          <button className="text-xs flex items-center gap-1 mb-0.5" style={{ color: "var(--ink-faint)" }} onClick={() => navigate("/skills")}>
            <Icon name="back" size={12} /> {t("nav.skills")}
          </button>
          <h1 className="font-display text-xl font-semibold leading-none truncate" style={{ color: "var(--ink)" }}>{skill.name}</h1>
          <div className="flex items-center gap-2 mt-1.5">
            <span className="chip" style={{ background: "var(--panel-2)" }}>{skill.source}</span>
            <span className="text-[0.66rem] font-mono" style={{ color: "var(--ink-faint)" }}>{Object.keys(files).length} {t("skill.files").toLowerCase()}</span>
          </div>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {dirty ? (
            <span className="text-xs flex items-center gap-1.5" style={{ color: "var(--terra)" }}>
              <span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--terra)" }} /> {t("skill.unsaved")}
            </span>
          ) : savedAt ? (
            <span className="text-xs flex items-center gap-1.5" style={{ color: "var(--green)" }}>
              <Icon name="check" size={12} /> {t("skill.saved")}
            </span>
          ) : null}
          <button className="btn btn-primary" disabled={!dirty || busy} onClick={save}>
            <Icon name="seal" size={14} /> {t("skill.save")}
          </button>
        </div>
      </header>
      {error && <div className="px-6 mt-2 text-xs" style={{ color: "var(--rust)" }}>{error}</div>}

      <div className="flex-1 min-h-0 flex gap-4 px-5 py-4">
        {/* File tree */}
        <div className="w-[230px] shrink-0 flex flex-col min-h-0">
          <div className="text-[0.62rem] uppercase tracking-[0.16em] mb-2 px-1 font-mono" style={{ color: "var(--ink-faint)" }}>{t("skill.files")}</div>
          <div className="panel p-1.5 flex-1 min-h-0 overflow-y-auto">
            {paths.map((p) => {
              const isMd = p === SKILL_MD;
              const isFolder = p.includes("/");
              const active = p === selected;
              return (
                <div
                  key={p}
                  className="group flex items-center gap-1.5 px-2 py-1.5 rounded-md cursor-pointer text-sm transition-colors"
                  style={{ background: active ? "rgba(201,162,39,0.16)" : "transparent" }}
                  onClick={() => setSelected(p)}
                >
                  <Icon name={isMd ? "seal" : isFolder ? "folder" : "file"} size={14}
                    style={{ color: isMd ? "var(--manuscript-gold)" : "var(--ink-faint)" }} />
                  <span className="truncate font-mono text-[0.76rem] flex-1" style={{ color: active ? "var(--ink)" : "var(--ink-soft)" }}>{p}</span>
                  {!isMd && (
                    <button
                      className="opacity-0 group-hover:opacity-100 p-0.5"
                      style={{ color: "var(--rust)" }}
                      onClick={(e) => { e.stopPropagation(); delFile(p); }}
                      title={t("skill.deleteFile")}
                    ><Icon name="trash" size={13} /></button>
                  )}
                </div>
              );
            })}
            {adding ? (
              <div className="flex gap-1 p-1.5">
                <input
                  autoFocus className="input !py-1 !px-1.5 !text-xs font-mono" placeholder={t("skill.newFilePath")}
                  value={newPath} onChange={(e) => setNewPath(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") addFile(); if (e.key === "Escape") setAdding(false); }}
                />
              </div>
            ) : (
              <button className="w-full flex items-center gap-1.5 text-xs px-2 py-1.5 rounded-md" style={{ color: "var(--terra)" }}
                onClick={() => setAdding(true)}>
                <Icon name="plus" size={13} /> {t("skill.addFile")}
              </button>
            )}
          </div>
        </div>

        {/* Editor */}
        <div className="flex-1 min-h-0 flex flex-col">
          <div className="text-[0.62rem] uppercase tracking-[0.16em] mb-2 px-1 font-mono flex items-center gap-1.5" style={{ color: "var(--ink-faint)" }}>
            <Icon name="file" size={12} />
            {selected ?? "—"}
          </div>
          <textarea
            className="input flex-1 min-h-0 resize-none font-mono text-[0.82rem] leading-relaxed"
            spellCheck={false}
            value={selected ? (files[selected] ?? "") : ""}
            onChange={(e) => selected && setContent(selected, e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}
