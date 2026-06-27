import { useEffect, useRef, useState } from "react";
import { useI18n } from "./i18n";
import type { TaskStatus } from "./api";
import type { TranslationKey } from "./i18n";

// Colors only — labels are resolved via i18n ("status.*" / "liveness.*") so the UI
// is fully bilingual. `soft` is the translucent badge background derived from `color`.
// Palette: warm Scriptorium (see docs/FE_DESIGN.md).
export const STATUS_META: Record<TaskStatus, { color: string; soft: string; key: TranslationKey }> = {
  backlog:     { color: "#857B6A", soft: "rgba(133,123,106,0.15)",  key: "status.backlog" },
  todo:        { color: "#3A5876", soft: "rgba(58,88,118,0.14)",    key: "status.todo" },
  in_progress: { color: "#C25A3A", soft: "rgba(194,90,58,0.16)",    key: "status.in_progress" },
  in_review:   { color: "#7A5A8A", soft: "rgba(122,90,138,0.15)",   key: "status.in_review" },
  blocked:     { color: "#A8492C", soft: "rgba(168,73,44,0.15)",    key: "status.blocked" },
  done:        { color: "#5E7A4A", soft: "rgba(94,122,74,0.16)",    key: "status.done" },
  cancelled:   { color: "#9A8E78", soft: "rgba(154,142,120,0.15)",  key: "status.cancelled" },
};

export const BOARD_COLUMNS: TaskStatus[] = [
  "backlog", "todo", "in_progress", "in_review", "blocked", "done",
];

const LIVENESS_META: Record<string, { color: string; key: TranslationKey; pulse?: boolean }> = {
  online:  { color: "#5E7A4A", key: "liveness.online" },
  working: { color: "#C25A3A", key: "liveness.working", pulse: true },
  idle:    { color: "#C9A227", key: "liveness.idle" },
  offline: { color: "#9A8E78", key: "liveness.offline" },
  hung:    { color: "#A8492C", key: "liveness.hung" },
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  const { t } = useI18n();
  const m = STATUS_META[status];
  return (
    <span
      className="chip font-medium"
      style={{ background: m.soft, color: m.color, borderColor: "transparent" }}
    >
      <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: m.color }} />
      {t(m.key)}
    </span>
  );
}

export function LivenessDot({ liveness, withLabel }: { liveness: string; withLabel?: boolean }) {
  const { t } = useI18n();
  const m = LIVENESS_META[liveness] ?? LIVENESS_META.offline;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={"inline-block w-2 h-2 rounded-full " + (m.pulse ? "pulse" : "")}
        style={{ background: m.color }}
      />
      {withLabel && <span className="text-xs" style={{ color: "var(--ink-faint)" }}>{t(m.key)}</span>}
    </span>
  );
}

// Decorated manuscript initial (drop-cap). Floats a large Fraunces letter;
// `blackletter` switches to UnifrakturMaguntia for ornamental flourishes.
export function DropCap({
  letter, blackletter = false, size = 46, color = "var(--terra)",
}: {
  letter: string; blackletter?: boolean; size?: number; color?: string;
}) {
  return (
    <span
      className={blackletter ? "font-initial" : "font-display"}
      style={{
        float: "left",
        fontSize: size,
        lineHeight: 0.8,
        fontWeight: 700,
        color,
        margin: "4px 10px 0 0",
        textShadow: "0 1px 0 rgba(201,162,39,0.28)",
      }}
    >
      {letter}
    </span>
  );
}

// Inline SVG icon set — consistent hand-drawn line icons (replaces the mixed glyphs).
const ICONS: Record<string, React.ReactNode> = {
  board: (<><rect x="3" y="4" width="5" height="16" rx="1" /><rect x="9.5" y="4" width="5" height="11" rx="1" /><rect x="16" y="4" width="5" height="14" rx="1" /></>),
  directory: (<><circle cx="9" cy="8" r="3" /><path d="M3.5 20c0-3.2 2.8-5 5.5-5s5.5 1.8 5.5 5" /><circle cx="17" cy="6.5" r="2.3" /><path d="M14.5 15c3.6 0 6 1.9 6 5" /></>),
  skills: (<><path d="M5.5 4H17a1.5 1.5 0 0 1 1.5 1.5v14H7a1.5 1.5 0 0 1-1.5-1.5z" /><path d="M5.5 18.5A1.5 1.5 0 0 1 7 17h11.5" /></>),
  inbox: (<><rect x="3" y="5" width="18" height="14" rx="1.5" /><path d="M3.5 7.5l8.5 5.5 8.5-5.5" /></>),
  atelier: (<><path d="M5 19c7 0 13-5 13-13-1 7-6 12-13 13z" /><path d="M5 19l5-5" /><path d="M14 5l3 3" /></>),
  user: (<><circle cx="12" cy="8" r="3.4" /><path d="M5.5 20c0-3.8 3-6 6.5-6s6.5 2.2 6.5 6" /></>),
  back: (<><path d="M14 5l-7 7 7 7" /></>),
  signout: (<><path d="M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4" /><path d="M15 16l4-4-4-4" /><path d="M19 12H9" /></>),
  plus: (<><path d="M12 5v14M5 12h14" /></>),
  send: (<><path d="M4 11.5l16-7.5-6.5 16-2.8-6.7z" /><path d="M11 13l4-4" /></>),
  wake: (<><path d="M13 3L4.5 13.5h6L9.5 21l9-11.5h-6z" /></>),
  seal: (<><circle cx="12" cy="12" r="7" /><path d="M9 11l2 2 4-4" /></>),
  close: (<><path d="M6 6l12 12M18 6L6 18" /></>),
};
export function Icon({ name, size = 18, className }: { name: string; size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      {ICONS[name] ?? ICONS.board}
    </svg>
  );
}

// Click-outside hook for popovers/dropdowns.
export function useClickOutside<T extends HTMLElement>(onOut: () => void) {
  const ref = useRef<T>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onOut();
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [onOut]);
  return ref;
}

// Centered modal overlay. Used for all "create" actions (commission task, provision
// agent, submit skill, edit agent) so they don't render as cramped inline corner panels.
export function Modal({
  title, onClose, children, footer, wide,
}: {
  title: string; onClose: () => void; children: React.ReactNode; footer?: React.ReactNode; wide?: boolean;
}) {
  const { t } = useI18n();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6"
      style={{ background: "rgba(60,45,25,0.45)", backdropFilter: "blur(2px)" }} onClick={onClose}>
      <div className="panel ornate unfurl w-full flex flex-col"
        style={{ maxWidth: wide ? 680 : 460, maxHeight: "85vh", boxShadow: "0 30px 60px -30px rgba(60,40,15,0.5)" }}
        onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center gap-3 px-5 py-3.5 shrink-0" style={{ borderBottom: "1px solid var(--line)" }}>
          <span className="font-display text-lg font-semibold">{title}</span>
          <button className="ml-auto text-lg leading-none px-2" onClick={onClose} style={{ color: "var(--ink-faint)" }}>×</button>
        </header>
        <div className="flex-1 min-h-0 overflow-auto p-5">{children}</div>
        {footer && <footer className="px-5 py-3.5 flex gap-2 justify-end shrink-0" style={{ borderTop: "1px solid var(--line)" }}>{footer}</footer>}
      </div>
    </div>
  );
}

// Multi-select dropdown of checkboxes. Collapsed button → click opens a popover panel;
// each checked item is selected (drives the install steps in the invitation).
export function CheckboxDropdown<T extends { id: string }>({
  label, items, selected, onChange, getKey, getLabel, getSub, emptyText,
}: {
  label: string;
  items: T[];
  selected: Set<string>;
  onChange: (next: Set<string>) => void;
  getKey: (item: T) => string;
  getLabel: (item: T) => string;
  getSub?: (item: T) => string | undefined;
  emptyText: string;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const ref = useClickOutside<HTMLDivElement>(() => setOpen(false));
  const toggle = (k: string) => {
    const next = new Set(selected);
    next.has(k) ? next.delete(k) : next.add(k);
    onChange(next);
  };
  const count = selected.size;
  return (
    <div className="relative" ref={ref}>
      <button type="button" className="input w-full flex items-center justify-between"
        onClick={() => setOpen((o) => !o)}>
        <span className="truncate" style={{ color: count ? "var(--ink)" : "var(--ink-soft)" }}>
          {count ? t("agent.skillsSelected", { n: count }) : label}
        </span>
        <span className="text-xs ml-2 shrink-0" style={{ color: "var(--ink-faint)" }}>{open ? "▴" : "▾"}</span>
      </button>
      {open && (
        <div className="absolute z-40 mt-1 w-full rounded-lg overflow-auto"
          style={{ background: "var(--panel)", border: "1px solid var(--line)", maxHeight: 240, boxShadow: "0 18px 36px -14px rgba(60,40,10,0.45)" }}>
          {items.length === 0 && <div className="px-3 py-2.5 text-xs" style={{ color: "var(--ink-faint)" }}>{emptyText}</div>}
          {items.map((it, i) => {
            const k = getKey(it);
            const on = selected.has(k);
            return (
              <label key={k} className="flex items-start gap-2.5 px-3 py-2 cursor-pointer"
                style={{
                  background: on ? "rgba(201,162,39,0.16)" : "var(--panel)",
                  borderBottom: i < items.length - 1 ? "1px solid var(--line-soft)" : "none",
                }}>
                <input type="checkbox" className="mt-0.5" checked={on} onChange={() => toggle(k)} />
                <div className="min-w-0">
                  <div className="text-sm font-medium truncate" style={{ color: "var(--ink)" }}>{getLabel(it)}</div>
                  {getSub?.(it) && <div className="text-[0.66rem] truncate" style={{ color: "var(--ink-faint)" }}>{getSub(it)}</div>}
                </div>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}

const AVATAR_COLORS = ["#C25A3A", "#3A5876", "#7A5A8A", "#5E7A4A", "#A8492C", "#8B4513", "#857B6A"];
function colorFor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

export function Avatar({ name, size = 26, liveness }: { name: string; size?: number; liveness?: string }) {
  const initials = name.split(/\s+/).map((p) => p[0]).slice(0, 2).join("").toUpperCase();
  return (
    <span className="relative inline-flex" title={name}>
      <span
        className="inline-flex items-center justify-center rounded-full font-display text-white font-medium select-none"
        style={{ width: size, height: size, background: colorFor(name), fontSize: size * 0.42, boxShadow: "0 0 0 1px rgba(201,162,39,0.4)" }}
      >
        {initials}
      </span>
      {liveness && (
        <span
          className="absolute -bottom-0.5 -right-0.5 rounded-full"
          style={{ padding: 2, background: "var(--panel)" }}
        >
          <LivenessDot liveness={liveness} />
        </span>
      )}
    </span>
  );
}

// Relative-time formatter. Pass the translation function to localize; defaults to
// English so it stays usable in any non-component context.
export function relTime(
  iso?: string | null,
  t?: (key: TranslationKey, params?: Record<string, string | number>) => string,
): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const s = Math.max(1, Math.floor((Date.now() - then) / 1000));
  const fmt = (key: TranslationKey) => (t ? t(key, { n: s }) : key === "time.secondsAgo" ? `${s}s ago` : `${s} ago`);
  if (s < 60) return fmt("time.secondsAgo");
  const m = Math.floor(s / 60);
  if (t) {
    if (m < 60) return t("time.minutesAgo", { n: m });
    const h = Math.floor(m / 60);
    if (h < 24) return t("time.hoursAgo", { n: h });
    return t("time.daysAgo", { n: Math.floor(h / 24) });
  }
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
