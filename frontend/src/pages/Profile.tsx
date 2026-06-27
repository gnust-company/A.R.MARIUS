import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useApp } from "../store";
import { useI18n, type Lang } from "../i18n";
import { Avatar, DropCap, Icon, LivenessDot, relTime } from "../ui";

// The Patron's "trang cá nhân" — an illuminated attribution page: identity, the
// workshop they belong to, and their session. The one screen that was missing.
function Row({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5" style={{ borderBottom: "1px solid var(--line-soft)" }}>
      <span className="text-[0.62rem] uppercase tracking-[0.16em] font-mono shrink-0" style={{ color: "var(--ink-faint)" }}>{label}</span>
      <span className={"text-sm text-right truncate " + (mono ? "font-mono text-[0.8rem]" : "")} style={{ color: "var(--ink)" }}>{value}</span>
    </div>
  );
}

export default function Profile() {
  const { user, signOut } = useAuth();
  const { workspace, workspaces, setWorkspaceId, mariuses } = useApp();
  const { lang, setLang, t } = useI18n();
  const navigate = useNavigate();

  if (!user) return null;
  const name = user.full_name || user.username || "Patron";
  const langs: Lang[] = ["en", "vi"];

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-7">
        {/* Illuminated identity header */}
        <header className="vellum ornate quill-in px-7 py-7 mb-6 flex items-start gap-5">
          <DropCap letter={name.charAt(0)} blackletter size={64} />
          <div className="min-w-0 flex-1">
            <div className="text-[0.62rem] uppercase tracking-[0.22em] font-mono" style={{ color: "var(--ink-faint)" }}>
              {t("profile.attribution")}
            </div>
            <h1 className="font-display text-3xl font-semibold leading-none mt-1.5" style={{ color: "var(--ink)" }}>{name}</h1>
            <div className="flex items-center gap-2 mt-3 flex-wrap">
              <span className="chip" style={{ background: "rgba(194,90,58,0.1)", color: "var(--terra)", borderColor: "transparent" }}>
                <Icon name="seal" size={12} /> {user.role}
              </span>
              {user.is_verified && (
                <span className="chip" style={{ background: "rgba(94,122,74,0.14)", color: "var(--green)", borderColor: "transparent" }}>
                  <Icon name="check" size={12} /> {t("profile.verified")}
                </span>
              )}
              {!user.is_active && <span className="chip" style={{ color: "var(--rust)" }}>{t("profile.inactive")}</span>}
            </div>
          </div>
          <Avatar name={name} size={56} />
        </header>

        <div className="grid gap-5" style={{ gridTemplateColumns: "1.4fr 1fr" }}>
          {/* Identity */}
          <section className="panel quill-in px-6 py-5" style={{ animationDelay: "0.05s" }}>
            <div className="flex items-center gap-2 mb-1">
              <Icon name="user" size={15} style={{ color: "var(--terra)" }} />
              <h2 className="font-display text-base font-semibold" style={{ color: "var(--ink)" }}>{t("profile.identity")}</h2>
            </div>
            <hr className="illumine mb-2" />
            <Row label={t("profile.fullName")} value={name} />
            <Row label={t("auth.email")} value={user.email} mono />
            <Row label={t("auth.username")} value={user.username} mono />
            <Row label={t("profile.role")} value={user.role} />
            <Row label={t("profile.memberSince")} value={fmt(user.created_at, lang)} />
            <Row label={t("profile.lastLogin")} value={user.last_login_at ? relTime(user.last_login_at, t) : t("profile.never")} />
            <div className="flex items-center justify-between gap-4 pt-3">
              <span className="text-[0.62rem] uppercase tracking-[0.16em] font-mono" style={{ color: "var(--ink-faint)" }}>{t("profile.userId")}</span>
              <code className="font-mono text-[0.7rem]" style={{ color: "var(--ink-faint)" }}>{user.id}</code>
            </div>
          </section>

          <div className="flex flex-col gap-5">
            {/* Workshop */}
            <section className="panel quill-in px-6 py-5" style={{ animationDelay: "0.1s" }}>
              <div className="flex items-center gap-2 mb-1">
                <Icon name="board" size={15} />
                <h2 className="font-display text-base font-semibold" style={{ color: "var(--ink)" }}>{t("profile.workshop")}</h2>
              </div>
              <hr className="illumine mb-2" />
              <div className="text-sm font-medium mb-3" style={{ color: "var(--ink)" }}>{workspace?.name ?? "—"}</div>
              <div className="flex items-center gap-3 text-xs mb-3 font-mono" style={{ color: "var(--ink-faint)" }}>
                <span className="flex items-center gap-1.5"><Icon name="directory" size={13} /> {mariuses.length} {t("nav.directory").toLowerCase()}</span>
              </div>
              {workspaces.length > 1 && (
                <select
                  className="input !py-1.5 !px-2.5 text-sm"
                  value={workspace?.id ?? ""}
                  onChange={(e) => { setWorkspaceId(e.target.value); }}
                >
                  {workspaces.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
                </select>
              )}
            </section>

            {/* Preferences */}
            <section className="panel quill-in px-6 py-5" style={{ animationDelay: "0.15s" }}>
              <div className="flex items-center gap-2 mb-1">
                <Icon name="atelier" size={15} />
                <h2 className="font-display text-base font-semibold" style={{ color: "var(--ink)" }}>{t("profile.preferences")}</h2>
              </div>
              <hr className="illumine mb-2" />
              <Row label={t("profile.language")} value={
                <div className="flex items-center gap-0.5 p-0.5 rounded-md text-[0.66rem] font-semibold"
                  style={{ background: "var(--panel-2)", border: "1px solid var(--line)" }}>
                  {langs.map((l) => (
                    <button key={l} onClick={() => setLang(l)} className="px-2 py-1 rounded uppercase tracking-wide"
                      style={{ background: lang === l ? "var(--terra)" : "transparent", color: lang === l ? "#FBF7EC" : "var(--ink-soft)" }}>
                      {l}
                    </button>
                  ))}
                </div>
              } />
            </section>
          </div>
        </div>

        {/* Session */}
        <section className="panel quill-in mt-5 px-6 py-5 flex items-center gap-4" style={{ animationDelay: "0.2s" }}>
          <LivenessDot liveness="online" />
          <div className="min-w-0 flex-1">
            <div className="font-display text-sm font-semibold" style={{ color: "var(--ink)" }}>{t("profile.session")}</div>
            <div className="text-xs" style={{ color: "var(--ink-soft)" }}>{t("profile.sessionSub")}</div>
          </div>
          <button className="btn" onClick={() => navigate("/style")}>
            <Icon name="atelier" size={14} /> {t("nav.style")}
          </button>
          <button className="btn" onClick={signOut} style={{ borderColor: "var(--rust)", color: "var(--rust)" }}>
            <Icon name="signout" size={14} /> {t("auth.signOut")}
          </button>
        </section>
      </div>
    </div>
  );
}

function fmt(iso?: string | null, lang: Lang = "en"): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(lang === "vi" ? "vi-VN" : "en-US", { year: "numeric", month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}
