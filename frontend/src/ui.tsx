import { useI18n } from "./i18n";
import type { TaskStatus } from "./api";
import type { TranslationKey } from "./i18n";

// Colors only — labels are resolved via i18n ("status.*" / "liveness.*") so the UI
// is fully bilingual. `soft` is the translucent badge background derived from `color`.
export const STATUS_META: Record<TaskStatus, { color: string; soft: string; key: TranslationKey }> = {
  backlog:     { color: "#71766f", soft: "rgba(113,118,111,0.14)", key: "status.backlog" },
  todo:        { color: "#3a5876", soft: "rgba(58,88,118,0.14)",   key: "status.todo" },
  in_progress: { color: "#b3812a", soft: "rgba(216,162,58,0.18)",  key: "status.in_progress" },
  in_review:   { color: "#6b4f86", soft: "rgba(107,79,134,0.16)",  key: "status.in_review" },
  blocked:     { color: "#a8492c", soft: "rgba(168,73,44,0.15)",   key: "status.blocked" },
  done:        { color: "#4f7a3f", soft: "rgba(79,122,63,0.16)",   key: "status.done" },
  cancelled:   { color: "#8a7c64", soft: "rgba(138,124,100,0.14)", key: "status.cancelled" },
};

export const BOARD_COLUMNS: TaskStatus[] = [
  "backlog", "todo", "in_progress", "in_review", "blocked", "done",
];

const LIVENESS_META: Record<string, { color: string; key: TranslationKey; pulse?: boolean }> = {
  online:  { color: "#4f7a3f", key: "liveness.online" },
  working: { color: "#d8a23a", key: "liveness.working", pulse: true },
  idle:    { color: "#9a8f78", key: "liveness.idle" },
  offline: { color: "#b9ad94", key: "liveness.offline" },
  hung:    { color: "#a8492c", key: "liveness.hung" },
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

const AVATAR_COLORS = ["#b3812a", "#3a5876", "#6b4f86", "#4f7a3f", "#a8492c", "#5c4f3c"];
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
        className="inline-flex items-center justify-center rounded-full font-serif text-white font-medium select-none"
        style={{ width: size, height: size, background: colorFor(name), fontSize: size * 0.42 }}
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
