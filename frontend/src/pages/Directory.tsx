import { useEffect, useState } from "react";
import { api, type Marius, type Skill } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, CheckboxDropdown, LivenessDot, Modal } from "../ui";

function InvitePanel({ name, invite, onClose }: { name: string; invite: string; onClose: () => void }) {
  const { t } = useI18n();
  return (
    <div>
      <p className="text-sm mb-3" style={{ color: "var(--ink-soft)" }}>{t("agent.inviteSub")}</p>
      <pre className="font-mono text-[0.72rem] p-3 rounded overflow-auto whitespace-pre-wrap"
        style={{ background: "var(--paper-2)", border: "1px solid var(--line)", maxHeight: "44vh" }}>{invite}</pre>
      <div className="flex gap-2 mt-3 justify-end">
        <button className="btn" onClick={() => navigator.clipboard?.writeText(invite)}>{t("common.copy")}</button>
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
        <div className="text-[0.66rem] uppercase tracking-[0.14em] mt-1" style={{ color: "var(--ink-faint)" }}>{t("agent.skills")}</div>
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
        <div className="text-[0.66rem] uppercase tracking-[0.14em] mt-1" style={{ color: "var(--ink-faint)" }}>{t("agent.adapter")}</div>
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
      </div>
      <div className="flex gap-2 mt-5 justify-end">
        <button className="btn" onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={!name.trim() || busy} onClick={submit}>{submitLabel}</button>
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

function MariusCard({ m, skills, onEdit }: { m: Marius; skills: Skill[]; onEdit: () => void }) {
  const { t } = useI18n();
  const linked = m.skill_ids.map((id) => skills.find((s) => s.id === id)).filter(Boolean) as Skill[];
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
          <button className="btn !py-1 !px-2 text-xs" onClick={onEdit}>{t("common.edit")}</button>
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

export default function Directory() {
  const { workspace, mariuses, reloadDirectory } = useApp();
  const { t } = useI18n();
  const [skills, setSkills] = useState<Skill[]>([]);
  const [provisioning, setProvisioning] = useState(false);
  const [editing, setEditing] = useState<Marius>();

  const loadSkills = async () => { if (workspace) setSkills(await api.skills(workspace.id)); };
  useEffect(() => { loadSkills(); /* eslint-disable-next-line */ }, [workspace?.id]);

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center gap-3 mb-5">
        <h1 className="font-serif text-xl font-semibold">{t("agent.directory")}</h1>
        <span className="chip">{t("agent.count", { n: mariuses.length })}</span>
        <div className="ml-auto">
          <button className="btn btn-primary" onClick={() => setProvisioning(true)}>{t("agent.provision")}</button>
        </div>
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(300px,1fr))" }}>
        {mariuses.map((m) => (
          <MariusCard key={m.id} m={m} skills={skills} onEdit={() => setEditing(m)} />
        ))}
      </div>

      {provisioning && (
        <ProvisionModal skills={skills} onClose={() => setProvisioning(false)} onDone={reloadDirectory} />
      )}
      {editing && (
        <EditModal m={editing} skills={skills} onClose={() => setEditing(undefined)} onDone={reloadDirectory} />
      )}
    </div>
  );
}
