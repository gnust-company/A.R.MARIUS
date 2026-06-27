import { useI18n } from "../i18n";
import {
  BOARD_COLUMNS, DropCap, Icon, LivenessDot, StatusBadge,
} from "../ui";

// /style — the Scriptorium design-system atelier (FE-0). A manuscript-style showcase of
// the refined hand-torn parchment material, illuminated initials, wax seals, the icon set,
// palette, type, components and motion. Dev-facing, viewable without login.
const SWATCHES: [string, string][] = [
  ["--paper", "#F8F3E6"], ["--panel", "#FBF7EC"], ["--line", "#D4B896"], ["--gilt", "#C9A227"],
  ["--ink", "#2B2722"], ["--ink-soft", "#6E6258"], ["--terra", "#C25A3A"], ["--ink-brown", "#8B4513"],
  ["--blue", "#3A5876"], ["--green", "#5E7A4A"], ["--rust", "#A8492C"], ["--violet", "#7A5A8A"],
];
const ICONS = ["board", "directory", "skills", "inbox", "atelier", "user", "back", "signout", "plus", "send", "wake", "seal", "close"];
const LIVENESS = ["online", "working", "idle", "offline", "hung"];

function Label({ children }: { children: React.ReactNode }) {
  return <div className="font-mono text-[0.62rem] uppercase tracking-[0.18em] mb-2" style={{ color: "var(--ink-faint)" }}>{children}</div>;
}

export default function Style() {
  const { t } = useI18n();
  return (
    <div className="h-full overflow-auto">
      <div className="max-w-5xl mx-auto px-8 py-10">
        {/* Hero — hand-torn parchment banner with illuminated initial */}
        <header className="vellum quill-in px-8 py-7 mb-8">
          <DropCap letter="A" blackletter size={64} />
          <h1 className="font-display text-4xl font-semibold leading-none" style={{ color: "var(--ink)" }}>
            Scriptorium
          </h1>
          <p className="mt-2 text-sm" style={{ color: "var(--ink-soft)" }}>{t("style.subtitle")}</p>
          <hr className="illumine mt-5" />
        </header>

        {/* Material — two torn fragments: a wax seal + marginalia */}
        <section className="mb-8 grid grid-cols-2 gap-5 quill-in" style={{ animationDelay: "0.05s" }}>
          <div className="vellum px-6 py-6 flex items-center gap-5">
            <span className="shrink-0 rounded-full flex items-center justify-center font-display font-semibold"
              style={{ width: 64, height: 64, background: "radial-gradient(circle at 35% 30%, #D9744E, #A8462E)", color: "#FBF7EC", boxShadow: "0 6px 14px -6px rgba(168,70,46,.7), inset 0 -3px 6px rgba(80,30,15,.5), inset 0 3px 6px rgba(255,200,170,.4)", border: "2px solid #8B3A22" }}>
              <Icon name="seal" size={26} />
            </span>
            <div>
              <Label>{t("style.components")}</Label>
              <div className="font-display text-lg font-semibold" style={{ color: "var(--ink)" }}>Wax seal</div>
              <div className="text-xs" style={{ color: "var(--ink-soft)" }}>stamped, embossed accents</div>
            </div>
          </div>
          <div className="vellum px-6 py-6">
            <Label>{t("style.palette")}</Label>
            <div className="grid grid-cols-6 gap-2">
              {SWATCHES.map(([tok, hex]) => (
                <div key={tok} title={`${tok} · ${hex}`} className="h-8 rounded" style={{ background: hex, border: "1px solid var(--line-soft)", boxShadow: "inset 0 0 6px rgba(96,50,18,.18)" }} />
              ))}
            </div>
          </div>
        </section>

        {/* Typography on vellum */}
        <section className="mb-8 vellum px-7 py-6 quill-in" style={{ animationDelay: "0.1s" }}>
          <Label>{t("style.typography")}</Label>
          <div className="font-display text-3xl font-semibold mb-1" style={{ color: "var(--ink)" }}>Armarius Scriptorium</div>
          <p className="dropcap text-[0.95rem] leading-relaxed mb-4" style={{ color: "var(--ink-soft)" }}>{t("style.bodySample")}</p>
          <div className="flex items-end gap-6">
            <div>
              <Label>initial</Label>
              <span className="font-initial text-5xl" style={{ color: "var(--terra)" }}>Aa</span>
            </div>
            <div>
              <Label>mono</Label>
              <code className="font-mono text-sm" style={{ color: "var(--blue)" }}>enrollment_code: 8f3a-…</code>
            </div>
          </div>
        </section>

        {/* Icon set */}
        <section className="mb-8 panel px-6 py-5 quill-in" style={{ animationDelay: "0.15s" }}>
          <Label>icon set</Label>
          <div className="grid grid-cols-7 gap-3">
            {ICONS.map((n) => (
              <div key={n} className="flex flex-col items-center gap-1.5 py-2 rounded gilt" style={{ color: "var(--ink-soft)" }}>
                <Icon name={n} size={22} />
                <span className="font-mono text-[0.58rem]" style={{ color: "var(--ink-faint)" }}>{n}</span>
              </div>
            ))}
          </div>
        </section>

        {/* Components */}
        <section className="mb-8 panel px-6 py-5 quill-in space-y-5" style={{ animationDelay: "0.2s" }}>
          <Label>{t("style.components")}</Label>
          <div className="flex flex-wrap items-center gap-2.5">
            <button className="btn">Ghost</button>
            <button className="btn btn-primary">Primary</button>
            <button className="btn" disabled>Disabled</button>
          </div>
          <div className="flex flex-wrap items-center gap-2">{BOARD_COLUMNS.map((s) => <StatusBadge key={s} status={s} />)}</div>
          <div className="flex flex-wrap items-center gap-4">{LIVENESS.map((l) => <LivenessDot key={l} liveness={l} withLabel />)}</div>
          <input className="input" placeholder="Inscribe a message…" />
        </section>

        {/* Motion */}
        <section className="mb-4 panel px-6 py-5 quill-in" style={{ animationDelay: "0.25s" }}>
          <Label>{t("style.motion")}</Label>
          <div className="grid grid-cols-3 gap-3">
            {["quill-in", "gilt-hover", "wax-seal"].map((m, i) => (
              <div key={m} className="panel-flat gilt py-4 text-center quill-in" style={{ animationDelay: `${0.3 + i * 0.08}s` }}>
                <div className="font-display text-sm font-semibold" style={{ color: "var(--terra)" }}>{m}</div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
