import type { TaskStatus } from "./api";

export const STATUS_META: Record<TaskStatus, { label: string; color: string; soft: string }> = {
  backlog:     { label: "Backlog",     color: "#71766f", soft: "rgba(113,118,111,0.14)" },
  todo:        { label: "To do",       color: "#3a5876", soft: "rgba(58,88,118,0.14)" },
  in_progress: { label: "In progress", color: "#b3812a", soft: "rgba(216,162,58,0.18)" },
  in_review:   { label: "In review",   color: "#6b4f86", soft: "rgba(107,79,134,0.16)" },
  blocked:     { label: "Blocked",     color: "#a8492c", soft: "rgba(168,73,44,0.15)" },
  done:        { label: "Done",        color: "#4f7a3f", soft: "rgba(79,122,63,0.16)" },
  cancelled:   { label: "Cancelled",   color: "#8a7c64", soft: "rgba(138,124,100,0.14)" },
};

export const BOARD_COLUMNS: TaskStatus[] = [
  "backlog", "todo", "in_progress", "in_review", "blocked", "done",
];

const LIVENESS_META: Record<string, { color: string; label: string; pulse?: boolean }> = {
  online:  { color: "#4f7a3f", label: "Online" },
  working: { color: "#d8a23a", label: "Working", pulse: true },
  idle:    { color: "#9a8f78", label: "Idle" },
  offline: { color: "#b9ad94", label: "Offline" },
  hung:    { color: "#a8492c", label: "Hung" },
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  const m = STATUS_META[status];
  return (
    <span
      className="chip font-medium"
      style={{ background: m.soft, color: m.color, borderColor: "transparent" }}
    >
      <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: m.color }} />
      {m.label}
    </span>
  );
}

export function LivenessDot({ liveness, withLabel }: { liveness: string; withLabel?: boolean }) {
  const m = LIVENESS_META[liveness] ?? LIVENESS_META.offline;
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={"inline-block w-2 h-2 rounded-full " + (m.pulse ? "pulse" : "")}
        style={{ background: m.color }}
      />
      {withLabel && <span className="text-xs" style={{ color: "var(--ink-faint)" }}>{m.label}</span>}
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

export function relTime(iso?: string | null): string {
  if (!iso) return "";
  const then = new Date(iso).getTime();
  const s = Math.max(1, Math.floor((Date.now() - then) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
