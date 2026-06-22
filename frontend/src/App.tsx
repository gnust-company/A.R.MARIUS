import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { useApp } from "./store";
import Board from "./pages/Board";
import Room from "./pages/Room";
import Directory from "./pages/Directory";
import Approvals from "./pages/Approvals";

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-4 pt-5 pb-4">
      <div
        className="flex items-center justify-center rounded-lg font-serif text-lg"
        style={{
          width: 34, height: 34,
          background: "linear-gradient(180deg,#d8a23a,#b3812a)",
          color: "#fff8e8", boxShadow: "0 6px 14px -8px rgba(179,129,42,0.9)",
        }}
      >
        A
      </div>
      <div className="leading-tight">
        <div className="font-serif text-[1.15rem] font-semibold tracking-tight">Armarius</div>
        <div className="text-[0.66rem] uppercase tracking-[0.18em]" style={{ color: "var(--ink-faint)" }}>
          Scriptorium
        </div>
      </div>
    </div>
  );
}

function NavItem({ to, label, icon }: { to: string; label: string; icon: string }) {
  return (
    <NavLink
      to={to}
      end={to === "/"}
      className={({ isActive }) =>
        "flex items-center gap-2.5 mx-2 px-3 py-2 rounded-lg text-sm transition-colors " +
        (isActive ? "font-medium" : "")
      }
      style={({ isActive }) => ({
        background: isActive ? "var(--panel-2)" : "transparent",
        color: isActive ? "var(--ink)" : "var(--ink-soft)",
        border: isActive ? "1px solid var(--line)" : "1px solid transparent",
      })}
    >
      <span className="text-base w-5 text-center">{icon}</span>
      {label}
    </NavLink>
  );
}

function Sidebar() {
  return (
    <aside
      className="w-[220px] shrink-0 flex flex-col"
      style={{ borderRight: "1px solid var(--line)", background: "var(--panel)" }}
    >
      <Brand />
      <div className="rule mx-4 mb-2" />
      <nav className="flex flex-col gap-0.5">
        <NavItem to="/" label="Board" icon="▦" />
        <NavItem to="/directory" label="Directory" icon="❖" />
        <NavItem to="/approvals" label="Patron inbox" icon="✦" />
      </nav>
      <div className="mt-auto px-5 py-4 text-[0.7rem] leading-relaxed" style={{ color: "var(--ink-faint)" }}>
        <div className="font-serif italic mb-1" style={{ color: "var(--ink-soft)" }}>
          You task. They collaborate. You trace.
        </div>
        Commission · Provision · Trace · Approve
      </div>
    </aside>
  );
}

function TopBar() {
  const { workspace, projects, project, setProjectId } = useApp();
  const navigate = useNavigate();
  return (
    <header
      className="h-14 shrink-0 flex items-center gap-4 px-5"
      style={{ borderBottom: "1px solid var(--line)", background: "var(--panel)" }}
    >
      <div className="text-sm" style={{ color: "var(--ink-faint)" }}>
        {workspace?.name ?? "—"}
        <span className="mx-1.5">/</span>
      </div>
      {projects.length > 0 && (
        <select
          className="input !w-auto !py-1.5 !px-2.5 font-medium"
          value={project?.id}
          onChange={(e) => { setProjectId(e.target.value); navigate("/"); }}
        >
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      )}
      <div className="ml-auto flex items-center gap-2.5">
        <NavLink to="/approvals" className="btn" title="Patron inbox">✦ Inbox</NavLink>
      </div>
    </header>
  );
}

export default function App() {
  const { loading, error } = useApp();
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <main className="flex-1 min-h-0 overflow-hidden">
          {loading ? (
            <div className="h-full flex items-center justify-center" style={{ color: "var(--ink-faint)" }}>
              Loading the scriptorium…
            </div>
          ) : error ? (
            <div className="h-full flex items-center justify-center" style={{ color: "var(--rust)" }}>
              {error}
            </div>
          ) : (
            <Routes>
              <Route path="/" element={<Board />} />
              <Route path="/tasks/:taskId" element={<Room />} />
              <Route path="/directory" element={<Directory />} />
              <Route path="/approvals" element={<Approvals />} />
            </Routes>
          )}
        </main>
      </div>
    </div>
  );
}
