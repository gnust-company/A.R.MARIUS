import { useI18n } from "../i18n";
import {
  BOARD_COLUMNS,
  DropCap,
  LivenessDot,
  StatusBadge,
} from "../ui";

// /style — the Scriptorium design-system playground (FE-0). Renders every token,
// primitive, and motion so the system has a live spec. Dev-facing.
const SWATCHES: [string, string][] = [
  ["--paper", "#F8F3E6"], ["--paper-2", "#F1E9D6"], ["--panel", "#FBF7EC"], ["--panel-2", "#F6EFD9"],
  ["--line", "#D4B896"], ["--line-soft", "#E4D6B8"], ["--gilt", "#C9A227"], ["--gilt-bright", "#E0B540"],
  ["--ink", "#2B2722"], ["--ink-soft", "#6E6258"], ["--ink-faint", "#9A8E78"],
  ["--terra", "#C25A3A"], ["--terra-bright", "#D9744E"], ["--manuscript-gold", "#C9A227"], ["--ink-brown", "#8B4513"],
  ["--blue", "#3A5876"], ["--green", "#5E7A4A"], ["--rust", "#A8492C"], ["--violet", "#7A5A8A"], ["--slate", "#857B6A"],
];

const LIVENESS = ["online", "working", "idle", "offline", "hung"];

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-display text-xl font-semibold mb-3" style={{ color: "var(--ink)" }}>
      {children}
    </h2>
  );
}

export default function Style() {
  const { t } = useI18n();

  return (
    <div className="h-full overflow-auto">
      <div className="max-w-5xl mx-auto px-8 py-8">
        {/* Header */}
        <header className="quill-in mb-8">
          <DropCap letter="S" />
          <h1 className="font-display text-3xl font-semibold leading-none" style={{ color: "var(--ink)" }}>
            {t("style.title")}
          </h1>
          <p className="mt-1.5 text-sm" style={{ color: "var(--ink-soft)" }}>{t("style.subtitle")}</p>
          <div className="rule mt-4" />
        </header>

        {/* Palette */}
        <section className="mb-9 quill-in" style={{ animationDelay: "0.05s" }}>
          <SectionTitle>{t("style.palette")}</SectionTitle>
          <div className="grid grid-cols-4 sm:grid-cols-5 gap-2.5">
            {SWATCHES.map(([tok, hex]) => (
              <div key={tok} className="panel gilt p-2.5">
                <div className="h-10 rounded-md mb-2" style={{ background: hex, border: "1px solid var(--line-soft)" }} />
                <div className="font-mono text-[0.62rem] truncate" style={{ color: "var(--ink-soft)" }}>{tok}</div>
                <div className="font-mono text-[0.62rem]" style={{ color: "var(--ink-faint)" }}>{hex}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Typography */}
        <section className="mb-9 quill-in" style={{ animationDelay: "0.1s" }}>
          <SectionTitle>{t("style.typography")}</SectionTitle>
          <div className="panel p-5 space-y-4">
            <div>
              <div className="font-mono text-[0.62rem] uppercase tracking-wider mb-1" style={{ color: "var(--ink-faint)" }}>Fraunces · display</div>
              <div className="font-display text-3xl font-semibold" style={{ color: "var(--ink)" }}>Armarius Scriptorium</div>
            </div>
            <div className="rule" />
            <div>
              <div className="font-mono text-[0.62rem] uppercase tracking-wider mb-1" style={{ color: "var(--ink-faint)" }}>Spectral · body</div>
              <p className="text-[0.95rem] leading-relaxed" style={{ color: "var(--ink-soft)" }}>{t("style.bodySample")}</p>
            </div>
            <div className="rule" />
            <div className="flex items-center gap-4">
              <div>
                <div className="font-mono text-[0.62rem] uppercase tracking-wider mb-1" style={{ color: "var(--ink-faint)" }}>UnifrakturMaguntia · initial</div>
                <span className="font-initial text-5xl" style={{ color: "var(--terra)" }}>Aq</span>
              </div>
              <div>
                <div className="font-mono text-[0.62rem] uppercase tracking-wider mb-1" style={{ color: "var(--ink-faint)" }}>JetBrains Mono · data</div>
                <code className="font-mono text-sm" style={{ color: "var(--blue)" }}>enrollment_code: 8f3a-…</code>
              </div>
            </div>
          </div>
        </section>

        {/* Components */}
        <section className="mb-9 quill-in" style={{ animationDelay: "0.15s" }}>
          <SectionTitle>{t("style.components")}</SectionTitle>
          <div className="panel p-5 space-y-5">
            <div className="flex flex-wrap items-center gap-2.5">
              <button className="btn">Ghost</button>
              <button className="btn-primary btn">Primary</button>
              <button className="btn" disabled>Disabled</button>
            </div>
            <div className="rule" />
            <div className="flex flex-wrap items-center gap-2">
              {BOARD_COLUMNS.map((s) => <StatusBadge key={s} status={s} />)}
            </div>
            <div className="rule" />
            <div className="flex flex-wrap items-center gap-4">
              {LIVENESS.map((l) => (
                <LivenessDot key={l} liveness={l} withLabel />
              ))}
            </div>
            <div className="rule" />
            <input className="input" placeholder="Type to inscribe…" />
            <div className="grid grid-cols-2 gap-3">
              <div className="panel-flat p-4 text-sm" style={{ color: "var(--ink-soft)" }}>.panel-flat</div>
              <div className="panel ornate p-4 text-sm" style={{ color: "var(--ink-soft)" }}>.panel.ornate</div>
            </div>
          </div>
        </section>

        {/* Motion */}
        <section className="mb-4 quill-in" style={{ animationDelay: "0.2s" }}>
          <SectionTitle>{t("style.motion")}</SectionTitle>
          <div className="panel p-5">
            <div className="grid grid-cols-3 gap-3 mb-4">
              {["quill-in", "gilt-hover", "wax-seal"].map((m, i) => (
                <div key={m} className="panel-flat gilt p-3 text-center quill-in" style={{ animationDelay: `${0.25 + i * 0.08}s` }}>
                  <div className="font-display text-sm font-semibold" style={{ color: "var(--terra)" }}>{m}</div>
                </div>
              ))}
            </div>
            <p className="text-xs" style={{ color: "var(--ink-faint)" }}>
              · quill-in · scroll-unfurl · gilt-hover · wax-seal · pulse · drop-cap — all honor prefers-reduced-motion.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
