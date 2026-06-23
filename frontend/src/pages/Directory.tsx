import { useEffect, useState } from "react";
import { api, type Marius, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, LivenessDot } from "../ui";

// Native multi-select LIST BOX of the workspace's skills (replaces the old
// free-text field + checkbox grid). value is the list of selected skill ids.
function SkillListBox({
  skills, value, onChange,
}: { skills: Skill[]; value: string[]; onChange: (ids: string[]) => void }) {
  const { t } = useI18n();
  if (skills.length === 0) {
    return <div className="text-xs px-2 py-1.5" style={{ color: "var(--ink-faint)" }}>{t("agent.skillsEmpty")}</div>;
  }
  return (
    <select
      multiple
      size={Math.min(7, Math.max(4, skills.length))}
      className="input"
      value={value}
      onChange={(e) => onChange(Array.from(e.target.selectedOptions).map((o) => o.value))}
    >
      {skills.map((s) => (
        <option key={s.id} value={s.id}>
          {s.name} · {s.source === "builtin" ? t("skill.builtin") : t("skill.custom")}
        </option>
      ))}
    </select>
  );
}

function InviteView({ name, invite, onClose }: { name: string; invite: string; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div className="panel p-4">
      <div className="font-serif text-lg mb-1">{t("agent.inviteFor", { name })}</div>
      <p className="text-sm mb-3" style={{ color: "var(--ink-soft)" }}>{t("agent.inviteSub")}</p>
      <pre className="font-mono text-[0.72rem] p-3 rounded overflow-x-auto whitespace-pre-wrap"
        style={{ background: "var(--paper-2)", border: "1px solid var(--line)" }}>{invite}</pre>
      <div className="flex gap-2 mt-3">
        <button className="btn" onClick={() => navigator.clipboard?.writeText(invite)}>{t("common.copy")}</button>
        <button className="btn btn-primary" onClick={onClose}>{t("common.done")}</button>
      </div>
    </div>
  );
}

function linkedSkills(m: Marius, skills: Skill[]): Skill[] {
  return m.skill_ids.map((id) => skills.find((s) => s.id === id)).filter(Boolean) as Skill[];
}

function MariusCard({ m, skills, onEdited }: { m: Marius; skills: Skill[]; onEdited: () => void }) {
  const { workspace } = useApp();
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(m.name);
  const [role, setRole] = useState(m.role);
  const [adapter, setAdapter] = useState(m.adapter_type);
  const [selected, setSelected] = useState<string[]>(m.skill_ids);
  const [invite, setInvite] = useState<string>();
  const [busy, setBusy] = useState(false);

  // Reset form state when opening the editor for a different agent.
  useEffect(() => {
    if (editing) { setName(m.name); setRole(m.role); setAdapter(m.adapter_type); setSelected(m.skill_ids); }
  }, [editing, m]);

  const save = async () => {
    if (!workspace) return;
    setBusy(true);
    try {
      const updated = await api.updateMarius(workspace.id, m.id, {
        name: name.trim(), role: role.trim(), skill_ids: selected, adapter_type: adapter,
      });
      setInvite(updated.invite);
      onEdited();
    } finally {
      setBusy(false);
    }
  };

  if (invite) return <InviteView name={name} invite={invite} onClose={() => { setInvite(undefined); setEditing(false); }} />;

  if (editing) {
    return (
      <div className="panel p-4 grid gap-2.5">
        <div className="font-serif text-lg">{t("agent.editTitle")}</div>
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
        <input className="input" value={role} onChange={(e) => setRole(e.target.value)} placeholder={t("agent.rolePlaceholder")} />
        <div className="flex items-center justify-between">
          <span className="text-[0.66rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>{t("agent.skills")}</span>
        </div>
        <SkillListBox skills={skills} value={selected} onChange={setSelected} />
        <div className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("agent.skillsHint")}</div>
        <label className="text-[0.66rem] uppercase tracking-[0.14em] mt-1" style={{ color: "var(--ink-faint)" }}>{t("agent.adapter")}</label>
        <select className="input" value={adapter} onChange={(e) => setAdapter(e.target.value)}>
          <option value="hermes_gateway">hermes_gateway</option>
          <option value="echo">echo</option>
        </select>
        <div className="flex gap-2 mt-1">
          <button className="btn" onClick={() => setEditing(false)}>{t("common.cancel")}</button>
          <button className="btn btn-primary" disabled={busy || !name.trim()} onClick={save}>{t("common.save")}</button>
        </div>
      </div>
    );
  }

  const linked = linkedSkills(m, skills);
  return (
    <div className="panel p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Avatar name={m.name} size={40} liveness={m.liveness} />
        <div className="min-w-0">
          <div className="font-serif text-lg font-semibold leading-tight">{m.name}</div>
          <div className="text-xs" style={{ color: "var(--ink-faint)" }}>{m.role || "—"}</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <LivenessDot liveness={m.liveness} withLabel />
          <button className="btn !py-1 !px-2 text-xs" onClick={() => setEditing(true)}>{t("common.edit")}</button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {linked.length > 0 ? linked.map((s) => (
          <span key={s.id} className="chip" style={{ background: "var(--panel-2)" }}>◆ {s.name}</span>
        )) : <span className="text-xs" style={{ color: "var(--ink-faint)" }}>{t("agent.noSkills")}</span>}
      </div>
      <div className="rule" />
      <div className="text-[0.72rem] font-mono" style={{ color: "var(--ink-faint)" }}>
        {t("agent.adapterLabel")}: {m.adapter_type}
      </div>
    </div>
  );
}

function Provision({ skills, onDone }: { skills: Skill[]; onDone: () => void }) {
  const { workspace } = useApp();
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [adapter, setAdapter] = useState("hermes_gateway");
  const [baseUrl, setBaseUrl] = useState("http://localhost:8642");
  const [apiKey, setApiKey] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [invite, setInvite] = useState<string>();
  const [newName, setNewName] = useState("");

  // Default: pre-select the built-in armarius-http skill so a new agent can talk to us.
  useEffect(() => {
    const builtin = skills.find((s) => s.slug === "armarius-http");
    if (builtin) setSelected([builtin.id]);
    else setSelected([]);
  }, [skills]);

  const submit = async () => {
    if (!workspace || !name.trim()) return;
    const cfg: Record<string, string> = {};
    if (adapter === "hermes_gateway") { cfg.base_url = baseUrl; if (apiKey) cfg.api_key = apiKey; }
    const created = await api.registerMarius(workspace.id, {
      name: name.trim(), role: role.trim(),
      skills: [], skill_ids: selected,
      adapter_type: adapter, adapter_config: cfg,
    });
    setInvite(created.invite); setNewName(created.name);
    setName(""); setRole(""); onDone();
  };

  if (invite) return <InviteView name={newName} invite={invite} onClose={() => { setInvite(undefined); setOpen(false); }} />;

  if (!open) return <button className="btn btn-primary" onClick={() => setOpen(true)}>{t("agent.provision")}</button>;

  return (
    <div className="panel p-4 grid gap-2.5" style={{ maxWidth: 460 }}>
      <div className="font-serif text-lg">{t("agent.provisionTitle")}</div>
      <input className="input" placeholder={t("agent.namePlaceholder")} value={name} onChange={(e) => setName(e.target.value)} />
      <input className="input" placeholder={t("agent.rolePlaceholder")} value={role} onChange={(e) => setRole(e.target.value)} />
      <label className="text-[0.66rem] uppercase tracking-[0.14em] mt-1" style={{ color: "var(--ink-faint)" }}>{t("agent.skills")}</label>
      <SkillListBox skills={skills} value={selected} onChange={setSelected} />
      <div className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("agent.skillsHint")}</div>
      <label className="text-[0.66rem] uppercase tracking-[0.14em] mt-1" style={{ color: "var(--ink-faint)" }}>{t("agent.adapter")}</label>
      <select className="input" value={adapter} onChange={(e) => setAdapter(e.target.value)}>
        <option value="hermes_gateway">hermes_gateway</option>
        <option value="echo">echo</option>
      </select>
      {adapter === "hermes_gateway" && (
        <>
          <input className="input" placeholder={t("agent.gatewayUrl")} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          <input className="input" placeholder={t("agent.gatewayKey")} value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </>
      )}
      <div className="flex gap-2 mt-1">
        <button className="btn" onClick={() => setOpen(false)}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={!name.trim()} onClick={submit}>{t("agent.createInvite")}</button>
      </div>
    </div>
  );
}

export default function Directory() {
  const { workspace, mariuses, reloadDirectory } = useApp();
  const { t } = useI18n();
  const [skills, setSkills] = useState<Skill[]>([]);

  const loadSkills = async () => { if (workspace) setSkills(await api.skills(workspace.id)); };
  useEffect(() => { loadSkills(); /* eslint-disable-next-line */ }, [workspace?.id]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center gap-3 mb-5">
        <h1 className="font-serif text-xl font-semibold">{t("agent.directory")}</h1>
        <span className="chip">{t("agent.count", { n: mariuses.length })}</span>
        <div className="ml-auto"><Provision skills={skills} onDone={reloadDirectory} /></div>
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))" }}>
        {mariuses.map((m) => <MariusCard key={m.id} m={m} skills={skills} onEdited={reloadDirectory} />)}
      </div>
    </div>
  );
}
