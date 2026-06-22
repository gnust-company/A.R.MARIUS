import { useState } from "react";
import { api, API_BASE, type Marius } from "../api";
import { useApp } from "../store";
import { Avatar, LivenessDot } from "../ui";

function MariusCard({ m }: { m: Marius }) {
  return (
    <div className="panel p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Avatar name={m.name} size={40} liveness={m.liveness} />
        <div className="min-w-0">
          <div className="font-serif text-lg font-semibold leading-tight">{m.name}</div>
          <div className="text-xs" style={{ color: "var(--ink-faint)" }}>{m.role}</div>
        </div>
        <div className="ml-auto"><LivenessDot liveness={m.liveness} withLabel /></div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {m.skills.map((s) => <span key={s} className="chip">{s}</span>)}
        {m.skills.length === 0 && <span className="text-xs" style={{ color: "var(--ink-faint)" }}>no skills listed</span>}
      </div>
      <div className="rule" />
      <div className="text-[0.72rem] font-mono" style={{ color: "var(--ink-faint)" }}>
        adapter: {m.adapter_type}
      </div>
    </div>
  );
}

function Provision({ onDone }: { onDone: () => void }) {
  const { workspace } = useApp();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [skills, setSkills] = useState("");
  const [adapter, setAdapter] = useState("hermes_gateway");
  const [baseUrl, setBaseUrl] = useState("http://localhost:8642");
  const [apiKey, setApiKey] = useState("");
  const [token, setToken] = useState<string>();
  const [newName, setNewName] = useState("");

  const submit = async () => {
    if (!workspace || !name.trim()) return;
    const cfg: Record<string, string> = {};
    if (adapter === "hermes_gateway") { cfg.base_url = baseUrl; if (apiKey) cfg.api_key = apiKey; }
    const created = await api.registerMarius(workspace.id, {
      name: name.trim(), role: role.trim(),
      skills: skills.split(",").map((s) => s.trim()).filter(Boolean),
      adapter_type: adapter, adapter_config: cfg,
    });
    setToken(created.agent_token); setNewName(created.name);
    setName(""); setRole(""); setSkills(""); onDone();
  };

  if (token) {
    const invite =
`You are joining the Armarius workspace as "${newName}".
1. Save this Armarius token (bearer for the agent API): ${token}
2. Base API: ${API_BASE}
3. Install the Armarius skills: claim, comment (@mention), update status,
   record next_action, and publish_artifact.
4. When woken, read /agent/tasks/{id}, do the work, publish an artifact, then
   record a durable next_action before you stop.`;
    return (
      <div className="panel p-4">
        <div className="font-serif text-lg mb-1">Invitation for {newName}</div>
        <p className="text-sm mb-3" style={{ color: "var(--ink-soft)" }}>
          Paste this to your agent so it joins and can call back into Armarius.
        </p>
        <pre className="font-mono text-[0.72rem] p-3 rounded overflow-x-auto whitespace-pre-wrap"
          style={{ background: "var(--paper-2)", border: "1px solid var(--line)" }}>{invite}</pre>
        <div className="flex gap-2 mt-3">
          <button className="btn" onClick={() => navigator.clipboard?.writeText(invite)}>Copy</button>
          <button className="btn btn-primary" onClick={() => { setToken(undefined); setOpen(false); }}>Done</button>
        </div>
      </div>
    );
  }

  if (!open) return <button className="btn btn-primary" onClick={() => setOpen(true)}>❖ Provision a Marius</button>;

  return (
    <div className="panel p-4 grid gap-2.5" style={{ maxWidth: 460 }}>
      <div className="font-serif text-lg">Provision a Marius</div>
      <input className="input" placeholder="Name (e.g. Marin)" value={name} onChange={(e) => setName(e.target.value)} />
      <input className="input" placeholder="Role (e.g. Backend)" value={role} onChange={(e) => setRole(e.target.value)} />
      <input className="input" placeholder="Skills, comma-separated" value={skills} onChange={(e) => setSkills(e.target.value)} />
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
      <div className="flex gap-2 mt-1">
        <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
        <button className="btn btn-primary" disabled={!name.trim()} onClick={submit}>Create &amp; invite</button>
      </div>
    </div>
  );
}

export default function Directory() {
  const { mariuses, reloadDirectory } = useApp();
  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-center gap-3 mb-5">
        <h1 className="font-serif text-xl font-semibold">Agent directory</h1>
        <span className="chip">{mariuses.length} mariuses</span>
        <div className="ml-auto"><Provision onDone={reloadDirectory} /></div>
      </div>
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill,minmax(280px,1fr))" }}>
        {mariuses.map((m) => <MariusCard key={m.id} m={m} />)}
      </div>
    </div>
  );
}
