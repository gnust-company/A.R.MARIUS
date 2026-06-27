import { useEffect, useState } from "react";
import { api, type Marius, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, CheckboxDropdown, DropCap, Icon, LivenessDot, Modal, relTime } from "../ui";

function InvitePanel({ name, invite, onClose }: { name: string; invite: string; onClose: () => void }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const copy = () => { navigator.clipboard?.writeText(invite); setCopied(true); setTimeout(() => setCopied(false), 1400); };
  return (
    <div>
      <div className="flex items-start gap-2 mb-3 text-sm" style={{ color: "var(--ink-soft)" }}>
        <Icon name="seal" size={15} className="mt-0.5 shrink-0" style={{ color: "var(--terra)" }} />
        <span>{t("agent.inviteSub")}</span>
      </div>
      <pre className="font-mono text-[0.72rem] p-3 rounded overflow-auto whitespace-pre-wrap"
        style={{ background: "var(--paper-2)", border: "1px solid var(--line)", maxHeight: "44vh" }}>{invite}</pre>
      <div className="flex gap-2 mt-3 justify-end">
        <button className="btn" onClick={copy}>
          <Icon name="copy" size={13} /> {copied ? t("agent.copied") : t("common.copy")}
        </button>
        <button className="btn btn-primary" onClick={onClose}>{t("common.done")}</button>
      </div>
    </div>
  );
}

// Shared form for creating & editing an agent. Skills are picked from a checkbox
// dropdown of the workspace's skills; each checked skill generates install steps.
function AgentForm({
  skills, initial, submitLabel, onSubmit, onClose,
}: {
  skills: Skill[];
  initial: { name: string; role: string; adapter: string; skillIds: string[] };
  submitLabel: string;
  onSubmit: (v: { name: string; role: string; adapter: string; skillIds: string[]; adapterConfig: Record<string, string> }) => Promise<void>;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const [name, setName] = useState(initial.name);
  const [role, setRole] = useState(initial.role);
  const [adapter, setAdapter] = useState(initial.adapter);
  const [selected, setSelected] = useState<Set<string>>(new Set(initial.skillIds));
  const [baseUrl, setBaseUrl] = useState("http://localhost:8642");
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const cfg: Record<string, string> = {};
      if (adapter === "hermes_gateway") { cfg.base_url = baseUrl; if (apiKey) cfg.api_key = apiKey; }
      await onSubmit({ name: name.trim(), role: role.trim(), adapter, skillIds: [...selected], adapterConfig: cfg });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="grid gap-2.5">
        <input className="input" placeholder={t("agent.namePlaceholder")} value={name} onChange={(e) => setName(e.target.value)} />
        <input className="input" placeholder={t("agent.rolePlaceholder")} value={role} onChange={(e) => setRole(e.target.value)} />
        <div className="text-[0.62rem] uppercase tracking-[0.16em] mt-1 font-mono" style={{ color: "var(--ink-faint)" }}>{t("agent.skills")}</div>
        <CheckboxDropdown
          label={t("skill.selectLabel")}
          items={skills}
          selected={selected}
          onChange={setSelected}
          getKey={(s) => s.id}
          getLabel={(s) => s.name}
          getSub={(s) => (s.source === "builtin" ? t("skill.builtin") : t("skill.custom"))}
          emptyText={t("agent.skillsEmpty")}
        />
        <div className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("agent.skillsHint")}</div>
        <div className="text-[0.62rem] uppercase tracking-[0.16em] mt-1 font-mono" style={{ color: "var(--ink-faint)" }}>{t("agent.adapter")}</div>
        <select className="input" value={adapter} onChange={(e) => setAdapter(e.target.value)}>
          <option value="hermes_gateway">hermes_gateway</option>
          <option value="echo">echo</option>
        </select>
        {adapter === "hermes_gateway" && (
          <>
            <input className="input font-mono text-[0.8rem]" placeholder={t("agent.gatewayUrl")} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            <input className="input font-mono text-[0.8rem]" placeholder={t("agent.gatewayKey")} value={apiKey} onChange={(e) => setApiKey(e.target.value)} />
          </>
        )}
      </div>
      <div className="flex gap-2 mt-5 justify-end">
        <button className="btn" onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={!name.trim() || busy} onClick={submit}>
          <Icon name="seal" size={14} /> {submitLabel}
        </button>
      </div>
    </>
  );
}

function ProvisionModal({ skills, onClose, onDone }: { skills: Skill[]; onClose: () => void; onDone: () => void }) {
  const { workspace } = useApp();
  const { t } = useI18n();
  const [invite, setInvite] = useState<{ name: string; text: string }>();

  // Pre-select the built-in armarius-http skill so a new agent can talk to us.
  const initialSkillIds = (() => {
    const b = skills.find((s) => s.slug === "armarius-http");
    return b ? [b.id] : [];
  })();

  if (invite) {
    return (
      <Modal title={t("agent.inviteFor", { name: invite.name })} onClose={onClose} wide>
        <InvitePanel name={invite.name} invite={invite.text} onClose={onClose} />
      </Modal>
    );
  }

  return (
    <Modal title={t("agent.provisionTitle")} onClose={onClose}>
      <AgentForm
        skills={skills}
        initial={{ name: "", role: "", adapter: "hermes_gateway", skillIds: initialSkillIds }}
        submitLabel={t("agent.createInvite")}
        onClose={onClose}
        onSubmit={async (v) => {
          if (!workspace) return;
          const created = await api.registerMarius(workspace.id, {
            name: v.name, role: v.role, skills: [], skill_ids: v.skillIds,
            adapter_type: v.adapter, adapter_config: v.adapterConfig,
          });
          onDone();
          setInvite({ name: created.name, text: created.invite });
        }}
      />
    </Modal>
  );
}

function EditModal({ m, skills, onClose, onDone }: { m: Marius; skills: Skill[]; onClose: () => void; onDone: () => void }) {
  const { workspace } = useApp();
  const { t } = useI18n();
  const [invite, setInvite] = useState<string>();

  if (invite) {
    return (
      <Modal title={t("agent.inviteFor", { name: m.name })} onClose={onClose} wide>
        <InvitePanel name={m.name} invite={invite} onClose={onClose} />
      </Modal>
    );
  }

  return (
    <Modal title={t("agent.editTitle")} onClose={onClose}>
      <AgentForm
        skills={skills}
        initial={{ name: m.name, role: m.role, adapter: m.adapter_type, skillIds: m.skill_ids }}
        submitLabel={t("common.save")}
        onClose={onClose}
        onSubmit={async (v) => {
          if (!workspace) return;
          const updated = await api.updateMarius(workspace.id, m.id, {
            name: v.name, role: v.role, skill_ids: v.skillIds, adapter_type: v.adapter,
          });
          onDone();
          setInvite(updated.invite);
        }}
      />
    </Modal>
  );
}

function MariusCard({ m, skills, index, onEdit }: { m: Marius; skills: Skill[]; index: number; onEdit: () => void }) {
  const { t } = useI18n();
  const linked = m.skill_ids.map((id) => skills.find((s) => s.id === id)).filter(Boolean) as Skill[];
  return (
    <div className="panel gilt quill-in p-4 flex flex-col gap-3" style={{ animationDelay: `${index * 0.04}s` }}>
      <div className="flex items-center gap-3">
        <Avatar name={m.name} size={44} liveness={m.liveness} />
        <div className="min-w-0 flex-1">
          <div className="font-display text-lg font-semibold leading-tight truncate" style={{ color: "var(--ink)" }}>{m.name}</div>
          <div className="text-xs truncate" style={{ color: "var(--ink-faint)" }}>{m.role || "—"}</div>
        </div>
        <LivenessDot liveness={m.liveness} withLabel />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {linked.length > 0 ? linked.map((s) => (
          <span key={s.id} className="chip" style={{ background: "rgba(201,162,39,0.12)", borderColor: "transparent", color: "var(--ink-soft)" }}>
            <Icon name="skills" size={12} style={{ color: "var(--gilt)" }} /> {s.name}
          </span>
        )) : <span className="text-xs italic" style={{ color: "var(--ink-faint)" }}>{t("agent.noSkills")}</span>}
      </div>
      <div className="rule" />
      <div className="flex items-center gap-2">
        <span className="text-[0.72rem] font-mono" style={{ color: "var(--ink-faint)" }}>
          {`${t("agent.adapterLabel")}: `}<span style={{ color: "var(--ink-soft)" }}>{m.adapter_type}</span>
        </span>
        {m.last_seen_at && (
          <span className="text-[0.68rem] font-mono ml-auto" style={{ color: "var(--ink-faint)" }}>{relTime(m.last_seen_at, t)}</span>
        )}
        <button className="btn !py-1 !px-2 text-xs" onClick={onEdit}>
          <Icon name="edit" size={12} /> {t("common.edit")}
        </button>
      </div>
    </div>
  );
}

export default function Directory() {
  const { workspace, mariuses, reloadDirectory } = useApp();
  const { t } = useI18n();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [provisioning, setProvisioning] = useState(false);
  const [editing, setEditing] = useState<Marius>();

  const loadSkills = async () => { if (workspace) setSkills(await api.skills(workspace.id)); };
  useEffect(() => { loadSkills(); /* eslint-disable-next-line */ }, [workspace?.id]);

  const working = mariuses.filter((m) => m.liveness === "working").length;
  const online = mariuses.filter((m) => m.liveness === "online" || m.liveness === "working").length;

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-5xl mx-auto px-6 py-7">
        {/* Illuminated header */}
        <header className="vellum quill-in px-7 py-5 mb-6 flex items-start gap-4">
          <DropCap letter={t("agent.directory").charAt(0)} size={48} />
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-2xl font-semibold leading-none" style={{ color: "var(--ink)" }}>{t("agent.directory")}</h1>
            <div className="flex items-center gap-2 mt-2 flex-wrap">
              <span className="chip">{t("agent.count", { n: mariuses.length })}</span>
              {online > 0 && <span className="chip" style={{ background: "rgba(94,122,74,0.14)", color: "var(--green)", borderColor: "transparent" }}>
                <LivenessDot liveness="online" /> {online} {t("liveness.online").toLowerCase()}
              </span>}
              {working > 0 && <span className="chip" style={{ background: "rgba(194,90,58,0.12)", color: "var(--terra)", borderColor: "transparent" }}>
                <LivenessDot liveness="working" /> {working} {t("liveness.working").toLowerCase()}
              </span>}
            </div>
          </div>
          <button className="btn btn-primary shrink-0" onClick={() => setProvisioning(true)}>
            <Icon name="plus" size={15} /> {t("agent.provision")}
          </button>
        </header>

        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))" }}>
          {mariuses.map((m, i) => (
            <MariusCard key={m.id} m={m} skills={skills} index={i} onEdit={() => setEditing(m)} />
          ))}
        </div>

        {provisioning && (
          <ProvisionModal skills={skills} onClose={() => setProvisioning(false)} onDone={reloadDirectory} />
        )}
        {editing && (
          <EditModal m={editing} skills={skills} onClose={() => setEditing(undefined)} onDone={reloadDirectory} />
        )}
      </div>
    </div>
  );
}
