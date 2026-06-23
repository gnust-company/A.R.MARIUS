import { useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useI18n, type Lang } from "../i18n";

type Mode = "signin" | "signup";

function Brand() {
  return (
    <div className="flex items-center gap-3 mb-1">
      <div
        className="flex items-center justify-center rounded-md"
        style={{
          width: 40, height: 40, transform: "rotate(45deg)",
          background: "linear-gradient(180deg,#d8a23a,#b3812a)",
          boxShadow: "0 8px 20px -8px rgba(179,129,42,0.9)",
        }}
      />
      <div className="font-serif text-[1.7rem] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
        Armarius
      </div>
    </div>
  );
}

function LangSwitch() {
  const { lang, setLang } = useI18n();
  const langs: Lang[] = ["en", "vi"];
  return (
    <div
      className="flex items-center gap-1 p-1 rounded-lg text-xs font-medium"
      style={{ background: "var(--panel-2)", border: "1px solid var(--line)" }}
    >
      {langs.map((l) => (
        <button
          key={l}
          onClick={() => setLang(l)}
          className="px-2.5 py-1 rounded-md transition-colors uppercase tracking-wide"
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

export default function Auth() {
  const { signIn, signUp } = useAuth();
  const { t } = useI18n();
  const navigate = useNavigate();
  const location = useLocation();
  const mode = (location.pathname.includes("register") ? "signup" : "signin") as Mode;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [fullName, setFullName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (mode === "signup" && password !== confirm) {
      setError(t("auth.passwordMismatch"));
      return;
    }
    setBusy(true);
    try {
      if (mode === "signup") {
        await signUp({ email, full_name: fullName, password });
      } else {
        await signIn(email, password);
      }
      // Land on the workspace overview (the single list of workspaces).
      navigate("/workspaces");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("auth.failed"));
    } finally {
      setBusy(false);
    }
  };

  const isSignUp = mode === "signup";

  return (
    <div
      className="h-screen w-screen flex flex-col items-center justify-center p-6 relative"
      style={{ background: "var(--panel)" }}
    >
      <div className="absolute top-5 right-5"><LangSwitch /></div>

      <div
        className="w-full max-w-[400px] rounded-2xl p-8"
        style={{ background: "var(--surface)", border: "1px solid var(--line)", boxShadow: "0 30px 60px -30px rgba(60,40,10,0.25)" }}
      >
        <Brand />
        <h1 className="font-serif text-[1.4rem] font-semibold mb-1" style={{ color: "var(--ink)" }}>
          {isSignUp ? t("auth.createAccount") : t("auth.signIn")}
        </h1>
        <p className="text-sm mb-6" style={{ color: "var(--ink-soft)" }}>
          {isSignUp ? t("auth.createSub") : t("auth.signInSub")}
        </p>

        <form onSubmit={submit} className="flex flex-col gap-3.5">
          {isSignUp && (
            <Field label={t("auth.fullName")}>
              <input
                className="input"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                required
                autoComplete="name"
              />
            </Field>
          )}
          <Field label={t("auth.email")}>
            <input
              className="input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
            />
          </Field>
          <Field label={t("auth.password")} hint={!isSignUp ? undefined : t("auth.minPassword")}>
            <input
              className="input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete={isSignUp ? "new-password" : "current-password"}
            />
          </Field>
          {isSignUp && (
            <Field label={t("auth.confirmPassword")}>
              <input
                className="input"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                required
                minLength={8}
                autoComplete="new-password"
              />
            </Field>
          )}

          {error && (
            <div
              className="text-xs rounded-lg px-3 py-2"
              style={{ color: "var(--rust)", background: "var(--panel-2)", border: "1px solid var(--line)" }}
            >
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={busy}
            className="btn mt-1 disabled:opacity-60"
            style={{ background: "linear-gradient(180deg,#d8a23a,#b3812a)", color: "#fff8e8" }}
          >
            {busy ? t("auth.loading") : (isSignUp ? t("auth.signUpBtn") : t("auth.signInBtn"))}
          </button>
        </form>

        <div className="mt-5 text-center text-sm" style={{ color: "var(--ink-soft)" }}>
          {isSignUp ? t("auth.haveAccount") : t("auth.noAccount")}{" "}
          <a
            href={isSignUp ? "/login" : "/register"}
            className="font-medium"
            style={{ color: "var(--gold)" }}
          >
            {isSignUp ? t("auth.signInLink") : t("auth.register")}
          </a>
        </div>
      </div>

      <div className="mt-6 font-serif italic text-sm" style={{ color: "var(--ink-faint)" }}>
        {t("app.tagline")}
      </div>
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[0.66rem] uppercase tracking-[0.14em]" style={{ color: "var(--ink-faint)" }}>
        {label}
      </span>
      {children}
      {hint && <span className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{hint}</span>}
    </label>
  );
}
