import { NavLink, Route, Routes, useNavigate } from "react-router-dom";
import { AppProvider, useApp } from "./store";
import { useAuth } from "./auth";
import { useI18n, type Lang } from "./i18n";
import { Avatar, Icon } from "./ui";
import Board from "./pages/Board";
import Room from "./pages/Room";
import Directory from "./pages/Directory";
import Skills from "./pages/Skills";
import SkillEditor from "./pages/SkillEditor";
import Approvals from "./pages/Approvals";
import Workspaces from "./pages/Workspaces";
import Auth from "./pages/Auth";
import Profile from "./pages/Profile";
import Style from "./pages/Style";

function Brand() {
  const { t } = useI18n();
  return (
    <div className="flex items-center gap-2.5 px-4 pt-5 pb-4">
      <div
        className="flex items-center justify-center rounded-lg font-initial text-xl"
        style={{
          width: 36, height: 36,
          background: "linear-gradient(180deg,#D9744E,#C25A3A)",
          color: "#FBF7EC",
          border: "1px solid #A8462E",
          boxShadow: "0 6px 14px -8px rgba(194,90,58,.8), 0 0 0 2px rgba(201,162,39,.35) inset",
        }}
        aria-hidden="true"
      >
        A
      </div>
      <div className="leading-tight">
        <div className="font-display text-[1.15rem] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>Armarius</div>
        <div className="text-[0.62rem] uppercase tracking-[0.22em]" style={{ color: "var(--ink-faint)" }}>
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
        "group flex items-center gap-2.5 mx-2 px-3 py-2 rounded-lg text-sm transition-all " +
        (isActive ? "font-medium" : "")
      }
      style={({ isActive }) => ({
        background: isActive ? "var(--panel-2)" : "transparent",
        color: isActive ? "var(--ink)" : "var(--ink-soft)",
        border: isActive ? "1px solid var(--line)" : "1px solid transparent",
      })}
    >
      {({ isActive }) => (
        <>
          <Icon name={icon} size={17} className="shrink-0" />
          <span className="truncate">{label}</span>
          {isActive && <span className="ml-auto h-1.5 w-1.5 rounded-full" style={{ background: "var(--terra)" }} />}
        </>
      )}
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
          className="px-2 py-1 rounded uppercase tracking-wide transition-colors"
          style={{
            background: lang === l ? "var(--terra)" : "transparent",
            color: lang === l ? "#FBF7EC" : "var(--ink-soft)",
          }}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

// "Back" affordance — leaves the workspace and returns to the launcher (the outer
// workspace list). Reads as "exit", not a section: muted, with a back-arrow icon.
function BackToWorkspaces() {
  const { workspace } = useApp();
  const navigate = useNavigate();
  return (
    <button
      onClick={() => navigate("/workspaces")}
      className="group flex items-center gap-2.5 mx-2 px-3 py-2 rounded-lg text-sm transition-colors w-[calc(100%-1rem)]"
      style={{ color: "var(--ink-soft)", border: "1px solid transparent" }}
      onMouseEnter={(e) => { e.currentTarget.style.background = "var(--panel-2)"; e.currentTarget.style.borderColor = "var(--line)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = "transparent"; }}
      title={workspace?.name ?? ""}
    >
      <Icon name="back" size={17} className="shrink-0" />
      <span className="truncate">{workspace?.name ?? "Armarius"}</span>
    </button>
  );
}

function Sidebar() {
  const { user, signOut } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  return (
    <aside
      className="w-[224px] shrink-0 flex flex-col"
      style={{ borderRight: "1px solid var(--line)", background: "var(--panel)" }}
    >
      <Brand />
      <div className="rule mx-4 mb-2" />
      <nav className="flex flex-col gap-0.5">
        <BackToWorkspaces />
        <div className="rule mx-4 my-1.5" />
        <NavItem to="/" label={t("nav.board")} icon="board" />
        <NavItem to="/directory" label={t("nav.directory")} icon="directory" />
        <NavItem to="/skills" label={t("nav.skills")} icon="skills" />
        <NavItem to="/approvals" label={t("nav.inbox")} icon="inbox" />
        <div className="rule mx-4 my-1.5" />
        <NavItem to="/profile" label={t("nav.profile")} icon="user" />
        <NavItem to="/style" label={t("nav.style")} icon="atelier" />
      </nav>
      <div className="mt-auto px-4 pb-4">
        <div className="rule mb-3" />
        <div className="flex items-center justify-between mb-3">
          <LangSwitch />
        </div>
        <button
          onClick={() => navigate("/profile")}
          className="w-full flex items-center gap-2.5 mb-2 px-1 py-1 rounded-lg transition-colors text-left"
          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--panel-2)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          <Avatar name={user?.full_name ?? "Y"} size={30} />
          <div className="min-w-0 flex-1">
            <div className="text-xs font-medium truncate" style={{ color: "var(--ink)" }}>
              {user?.full_name ?? "—"}
            </div>
            <div className="text-[0.66rem] truncate" style={{ color: "var(--ink-faint)" }}>
              {user?.email ?? ""}
            </div>
          </div>
        </button>
        <button
          onClick={signOut}
          className="w-full flex items-center gap-2 text-xs px-3 py-1.5 rounded-md transition-colors"
          style={{ color: "var(--ink-soft)" }}
          onMouseEnter={(e) => { e.currentTarget.style.background = "var(--panel-2)"; }}
          onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
        >
          <Icon name="signout" size={14} /> {t("auth.signOut")}
        </button>
      </div>
    </aside>
  );
}

function TopBar() {
  const { workspace, projects, project, setProjectId } = useApp();
  const { t } = useI18n();
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
        <NavLink to="/approvals" className="btn" title={t("nav.inbox")}>
          <Icon name="inbox" size={15} /> {t("nav.inbox")}
        </NavLink>
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
            <div className="h-full flex items-center justify-center gap-3" style={{ color: "var(--ink-faint)" }}>
              <span className="font-display italic">{t("app.loadingScriptorium")}</span>
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
              <Route path="/skills/:skillId" element={<SkillEditor />} />
              <Route path="/approvals" element={<Approvals />} />
              <Route path="/profile" element={<Profile />} />
              <Route path="/style" element={<Style />} />
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
        {/* Public design-system playground — viewable without login. */}
        <Route path="/style" element={<Style />} />
        <Route path="*" element={<Auth />} />
      </Routes>
    );
  }

  return (
    <AppProvider>
      {/* The workspace launcher is a full-screen OUTER view (no app chrome).
          Picking a workspace enters the in-workspace Shell. */}
      <Routes>
        <Route path="/workspaces" element={<Workspaces />} />
        <Route path="/*" element={<Shell />} />
      </Routes>
    </AppProvider>
  );
}
