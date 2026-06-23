import { useEffect, useState } from "react";
import { api, type Marius, type MariusInput, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, LivenessDot } from "../ui";

// Multi-select list of the workspace's skills, used in both create & edit forms.
function SkillPicker({
  skills, selected, toggle,
}: { skills: Skill[]; selected: Set<string>; toggle: (id: string) => void }) {
  const { t } = useI18n();
  if (skills.length === 0) {
    return <div className="text-xs" style={{ color: "var(--ink-faint)" }}>{t("skill.empty")}</div>;
  }
  return (
    <div className="flex flex-col gap-1.5">
      {skills.map((s) => (
        <label
          key={s.id}
          className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-lg cursor-pointer"
          style={{
            background: selected.has(s.id) ? "var(--panel-2)" : "transparent",
            border: "1px solid " + (selected.has(s.id) ? "var(--line)" : "transparent"),
          }}
        >
          <input type="checkbox" checked={selected.has(s.id)} onChange={() => toggle(s.id)} />
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{s.name}</div>
            <div className="text-[0.66rem] truncate" style={{ color: "var(--ink-faint)" }}>
              {s.source === "builtin" ? t("skill.builtin") : t("skill.custom")} · {s.kind}
            </div>
          </div>
        </label>
      ))}
    </div>
  );
}

function InviteView({ name, invite, onClose }: { name: string; invite: string; onClose: () => void }) {
  return (
    <div className="panel p-4">
      <div className="font-serif text-lg mb-1">Invitation for {name}</div>
      <p className="text-sm mb-3" style={{ color: "var(--ink-soft)" }}>
        Paste this to your agent so it joins, saves its token, confirms online, and installs its skills.
      </p>
      <pre className="font-mono text-[0.72rem] p-3 rounded overflow-x-auto whitespace-pre-wrap"
        style={{ background: "var(--paper-2)", border: "1px solid var(--line)" }}>{invite}</pre>
      <div className="flex gap-2 mt-3">
        <button className="btn" onClick={() => navigator.clipboard?.writeText(invite)}>Copy</button>
        <button className="btn btn-primary" onClick={onClose}>Done</button>
      </div>
    </div>
  );
}

function MariusCard({ m, skills, onEdited }: { m: Marius; skills: Skill[]; onEdited: () => void }) {
  const { workspace } = useApp();
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(m.name);
  const [role, setRole] = useState(m.role);
  const [tags, setTags] = useState(m.skills.join(", "));
  const [selected, setSelected] = useState<Set<string>>(new Set(m.skill_ids));
  const [invite, setInvite] = useState<string>();
  const [busy, setBusy] = useState(false);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const save = async () => {
    if (!workspace) return;
    setBusy(true);
    try {
      const updated = await api.updateMarius(workspace.id, m.id, {
        name: name.trim(), role: role.trim(),
        skills: tags.split(",").map((s) => s.trim()).filter(Boolean),
        skill_ids: [...selected],
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
        <input className="input" value={role} onChange={(e) => setRole(e.target.value)} placeholder="Role" />
        <input className="input" value={tags} onChange={(e) => setTags(e.target.value)} placeholder="Skill tags, comma-separated" />
        <div className="text-[0.66rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>
          {t("agent.skills")}
        </div>
        <SkillPicker skills={skills} selected={selected} toggle={toggle} />
        <div className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("agent.skillsHint")}</div>
        <div className="flex gap-2 mt-1">
          <button className="btn" onClick={() => setEditing(false)}>{t("agent.cancel")}</button>
          <button className="btn btn-primary" disabled={busy || !name.trim()} onClick={save}>{t("agent.save")}</button>
        </div>
      </div>
    );
  }

  const linked = m.skill_ids.map((id) => skills.find((s) => s.id === id)).filter(Boolean) as Skill[];
  return (
    <div className="panel p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Avatar name={m.name} size={40} liveness={m.liveness} />
        <div className="min-w-0">
          <div className="font-serif text-lg font-semibold leading-tight">{m.name}</div>
          <div className="text-xs" style={{ color: "var(--ink-faint)" }}>{m.role}</div>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <LivenessDot liveness={m.liveness} withLabel />
          <button className="btn !py-1 !px-2 text-xs" onClick={() => setEditing(true)}>{t("agent.edit")}</button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {m.skills.map((s) => <span key={s} className="chip">{s}</span>)}
        {m.skills.length === 0 && <span className="text-xs" style={{ color: "var(--ink-faint)" }}>no skill tags</span>}
      </div>
      {linked.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {linked.map((s) => (
            <span key={s.id} className="chip" style={{ background: "var(--panel-2)" }}>⌁ {s.name}</span>
          ))}
        </div>
      )}
      <div className="rule" />
      <div className="text-[0.72rem] font-mono" style={{ color: "var(--ink-faint)" }}>
        adapter: {m.adapter_type}
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
  const [tags, setTags] = useState("");
  const [adapter, setAdapter] = useState("hermes_gateway");
  const [baseUrl, setBaseUrl] = useState("http://localhost:8642");
  const [apiKey, setApiKey] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [invite, setInvite] = useState<string>();
  const [newName, setNewName] = useState("");

  // Default: pre-select the built-in armarius-http skill so a new agent can talk to us.
  useEffect(() => {
    const builtin = skills.find((s) => s.slug === "armarius-http");
    if (builtin) setSelected(new Set([builtin.id]));
  }, [skills]);

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const submit = async () => {
    if (!workspace || !name.trim()) return;
    const cfg: Record<string, string> = {};
    if (adapter === "hermes_gateway") { cfg.base_url = baseUrl; if (apiKey) cfg.api_key = apiKey; }
    const body: MariusInput = {
      name: name.trim(), role: role.trim(),
      skills: tags.split(",").map((s) => s.trim()).filter(Boolean),
      skill_ids: [...selected],
      adapter_type: adapter, adapter_config: cfg,
    };
    const created = await api.registerMarius(workspace.id, body);
    setInvite(created.invite); setNewName(created.name);
    setName(""); setRole(""); setTags(""); onDone();
  };

  if (invite) return <InviteView name={newName} invite={invite} onClose={() => { setInvite(undefined); setOpen(false); }} />;

  if (!open) return <button className="btn btn-primary" onClick={() => setOpen(true)}>❖ Provision a Marius</button>;

  return (
    <div className="panel p-4 grid gap-2.5" style={{ maxWidth: 460 }}>
      <div className="font-serif text-lg">Provision a Marius</div>
      <input className="input" placeholder="Name (e.g. Marin)" value={name} onChange={(e) => setName(e.target.value)} />
      <input className="input" placeholder="Role (e.g. Backend)" value={role} onChange={(e) => setRole(e.target.value)} />
      <input className="input" placeholder="Skill tags, comma-separated" value={tags} onChange={(e) => setTags(e.target.value)} />
      <select className="input" value={adapter} onChange={(e) => setAdapter(e.target.value)}>
        <option value="hermes_gateway">hermes_gateway</option>
        <option value="echo">echo (demo)</option>
      </select>
      {adapter === "hermes_gateway" && (
        <>
          <input className="input" placeholder="Gateway base_url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
          <input className="input" placeholder="API_SERVER_KEY (bearer)" value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
        </>
      )}
      <div className="text-[0.66rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>
        {t("agent.skills")}
      </div>
      <SkillPicker skills={skills} selected={selected} toggle={toggle} />
      <div className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("agent.skillsHint")}</div>
      <div className="flex gap-2 mt-1">
        <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
        <button className="btn btn-primary" disabled={!name.trim()} onClick={submit}>Create &amp; invite</button>
      </div>
    </div>
  );
}

export default function Directory() {
  const { workspace, mariuses, reloadDirectory } = useApp();
  const [skills, setSkills] = useState<Skill[]>([]);

  const loadSkills = async () => { if (workspace) setSkills(await api.skills(workspace.id)); };
  useEffect(() => { loadSkills(); /* eslint-disable-next-line */ }, [workspace?.id]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center gap-3 mb-5">
        <h1 className="font-serif text-xl font-semibold">Agent directory</h1>
        <span className="chip">{mariuses.length} mariuses</span>
        <div className="ml-auto"><Provision skills={skills} onDone={reloadDirectory} /></div>
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))" }}>
        {mariuses.map((m) => <MariusCard key={m.id} m={m} skills={skills} onEdited={reloadDirectory} />)}
      </div>
    </div>
  );
}
