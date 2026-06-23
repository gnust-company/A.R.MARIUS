import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { AppProvider, useApp } from "./store";
import { useAuth } from "./auth";
import { useI18n, type Lang } from "./i18n";
import Board from "./pages/Board";
import Room from "./pages/Room";
import Directory from "./pages/Directory";
import Skills from "./pages/Skills";
import Approvals from "./pages/Approvals";
import Workspaces from "./pages/Workspaces";
import Auth from "./pages/Auth";

function Brand() {
  const { t } = useI18n();
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
          {t("app.scriptorium")}
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

function LangSwitch() {
  const { lang, setLang } = useI18n();
  const langs: Lang[] = ["en", "vi"];
  return (
    <div
      className="flex items-center gap-0.5 p-0.5 rounded-md text-[0.66rem] font-semibold"
      style={{ background: "var(--panel-2)", border: "1px solid var(--line)" }}
    >
      {langs.map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          className="px-2 py-1 rounded uppercase tracking-wide"
          style={{
            background: lang === l ? "var(--ink)" : "transparent",
            color: lang === l ? "var(--panel)" : "var(--ink-soft)",
          }}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

// Current workspace indicator (NOT a second list). Shows where you are and links to
// the Workspaces page, which is the single authoritative list of workspaces.
function CurrentWorkspace() {
  const { workspace } = useApp();
  const { t } = useI18n();
  if (!workspace) return null;
  return (
    <NavLink to="/workspaces" className="mx-3 mb-2 flex items-center gap-2.5 px-2.5 py-2 rounded-lg" style={{ background: "var(--panel-2)", border: "1px solid var(--line)" }}>
      <span className="font-serif text-base shrink-0" style={{ color: "var(--gold)" }}>◳</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[0.6rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>{t("nav.workspace")}</span>
        <span className="block text-sm font-medium truncate" style={{ color: "var(--ink)" }}>{workspace.name}</span>
      </span>
    </NavLink>
  );
}

function Sidebar() {
  const { user, signOut } = useAuth();
  const { t, tEn } = useI18n();
  return (
    <aside
      className="w-[220px] shrink-0 flex flex-col"
      style={{ borderRight: "1px solid var(--line)", background: "var(--panel)" }}
    >
      <Brand />
      <div className="rule mx-4 mb-2" />
      <CurrentWorkspace />
      <nav className="flex flex-col gap-0.5">
        <NavItem to="/" label={t("nav.board")} icon="▦" />
        <NavItem to="/directory" label={t("nav.directory")} icon="❖" />
        <NavItem to="/skills" label={t("nav.skills")} icon="⚒" />
        <NavItem to="/workspaces" label={t("nav.workspaces")} icon="◳" />
        {/* Patron Inbox intentionally stays English regardless of UI language. */}
        <NavItem to="/approvals" label={tEn("nav.inbox")} icon="✦" />
      </nav>
      <div className="mt-auto px-4 pb-4">
        <div className="rule mb-3" />
        <div className="flex items-center gap-2 mb-3">
          <LangSwitch />
        </div>
        <div className="flex items-center gap-2.5 mb-2">
          <div
            className="flex items-center justify-center rounded-full text-xs font-semibold shrink-0"
            style={{ width: 30, height: 30, background: "var(--ink)", color: "var(--panel)" }}
          >
            {(user?.full_name ?? "Y").charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-xs font-medium truncate" style={{ color: "var(--ink)" }}>
              {user?.full_name ?? "—"}
            </div>
            <div className="text-[0.66rem] truncate" style={{ color: "var(--ink-faint)" }}>
              {user?.email ?? ""}
            </div>
          </div>
        </div>
        <button
          onClick={signOut}
          className="w-full text-left text-xs px-3 py-1.5 rounded-md transition-colors"
          style={{ color: "var(--ink-soft)" }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--panel-2)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          ⎋ {t("auth.signOut")}
        </button>
      </div>
    </aside>
  );
}

function TopBar() {
  const { workspace, projects, project, setProjectId } = useApp();
  const { tEn } = useI18n();
  const navigate = useNavigate();
  const multiProject = projects.length > 1;
  return (
    <header
      className="h-14 shrink-0 flex items-center gap-4 px-5"
      style={{ borderBottom: "1px solid var(--line)", background: "var(--panel)" }}
    >
      <div className="text-sm font-medium" style={{ color: "var(--ink-soft)" }}>
        {workspace?.name ?? "—"}
        {multiProject && <span className="mx-1.5" style={{ color: "var(--ink-faint)" }}>/</span>}
      </div>
      {multiProject && (
        <select
          className="input !w-auto !py-1.5 !px-2.5 font-medium"
          value={project?.id ?? ""}
          onChange={(e) => { setProjectId(e.target.value); navigate("/"); }}
        >
          {projects.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      )}
      <div className="ml-auto flex items-center gap-2.5">
        {/* Patron Inbox label stays English regardless of UI language. */}
        <NavLink to="/approvals" className="btn" title={tEn("nav.inbox")}>✦ {tEn("nav.inbox")}</NavLink>
      </div>
    </header>
  );
}

function Shell() {
  const { loading, error } = useApp();
  const { t } = useI18n();
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <TopBar />
        <main className="flex-1 min-h-0 overflow-hidden">
          {loading ? (
            <div className="h-full flex items-center justify-center" style={{ color: "var(--ink-faint)" }}>
              {t("app.loadingScriptorium")}
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
              <Route path="/skills" element={<Skills />} />
              <Route path="/workspaces" element={<Workspaces />} />
              <Route path="/approvals" element={<Approvals />} />
            </Routes>
          )}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const { user, loading } = useAuth();
  const { t } = useI18n();

  // Auth routes (visible when logged out)
  if (!user) {
    if (loading) {
      return (
        <div className="h-screen flex items-center justify-center" style={{ background: "var(--panel)", color: "var(--ink-faint)" }}>
          {t("app.loading")}
        </div>
      );
    }
    return (
      <Routes>
        <Route path="/login" element={<Auth />} />
        <Route path="/register" element={<Auth />} />
        <Route path="*" element={<Auth />} />
      </Routes>
    );
  }

  return (
    <AppProvider>
      <Shell />
    </AppProvider>
  );
}
