import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  api, streamRun,
  type Artifact, type Comment, type Run, type RunEvent, type Task, type TaskStatus,
} from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, STATUS_META, StatusBadge, relTime } from "../ui";

const ALL_STATUSES: TaskStatus[] = [
  "backlog", "todo", "in_progress", "in_review", "blocked", "done", "cancelled",
];

function Mentioned({ body }: { body: string }) {
  const parts = body.split(/(@[A-Za-z0-9_\-.]+)/g);
  return (
    <>
      {parts.map((p, i) =>
        p.startsWith("@") ? (
          <span key={i} className="font-medium px-1 rounded"
            style={{ background: "rgba(216,162,58,0.18)", color: "var(--gold)" }}>{p}</span>
        ) : (
          <span key={i}>{p}</span>
        )
      )}
    </>
  );
}

/* ───────────────────────────── Left: task context ───────────────────────────── */
function TaskContext({
  task, artifacts, onChange,
}: { task: Task; artifacts: Artifact[]; onChange: () => void }) {
  const { t } = useI18n();
  const { mariuses, mariusById, reloadDirectory } = useApp();
  const assignee = mariusById(task.assigned_marius_id);
  const hasArtifact = artifacts.length > 0;

  const setStatus = async (status: TaskStatus) => {
    try { await api.transition(task.id, status); onChange(); }
    catch (e) { alert(e instanceof Error ? e.message : t("room.cannotStatus")); }
  };
  const assign = async (mariusId: string) => {
    if (!mariusId) return;
    await api.assign(task.id, mariusId);
    await reloadDirectory(); onChange();
  };

  return (
    <div className="h-full overflow-y-auto p-5" style={{ borderRight: "1px solid var(--line)" }}>
      <div className="flex items-center gap-2 mb-3">
        <StatusBadge status={task.status} />
      </div>
      <h1 className="font-serif text-[1.35rem] font-semibold leading-snug mb-3">{task.title}</h1>
      {task.description && (
        <p className="text-sm leading-relaxed mb-4" style={{ color: "var(--ink-soft)" }}>
          {task.description}
        </p>
      )}

      <Label>{t("room.status")}</Label>
      <select className="input mb-4" value={task.status}
        onChange={(e) => setStatus(e.target.value as TaskStatus)}>
        {ALL_STATUSES.map((s) => <option key={s} value={s}>{t(STATUS_META[s].key)}</option>)}
      </select>

      <Label>{t("room.assignee")}</Label>
      <select className="input mb-1" value={task.assigned_marius_id ?? ""}
        onChange={(e) => assign(e.target.value)}>
        <option value="">{t("room.unassigned")}</option>
        {mariuses.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.role}</option>)}
      </select>
      {assignee && (
        <div className="flex items-center gap-2 mb-4 mt-2">
          <Avatar name={assignee.name} size={24} liveness={assignee.liveness} />
          <span className="text-xs" style={{ color: "var(--ink-faint)" }}>
            {t("room.assignWake")}
          </span>
        </div>
      )}

      {task.status_reason && (
        <div className="text-[0.78rem] mb-4 px-2.5 py-1.5 rounded"
          style={{ background: "rgba(168,73,44,0.1)", color: "var(--rust)" }}>
          {task.status_reason}
        </div>
      )}

      {task.next_action && (
        <>
          <Label>{t("room.recordedNext")}</Label>
          <div className="text-sm italic mb-4 px-3 py-2 panel-flat" style={{ color: "var(--ink-soft)" }}>
            {task.next_action}
          </div>
        </>
      )}

      <Label>{t("room.dod")}</Label>
      <div className="flex items-center gap-2 text-sm mb-3">
        <span style={{ color: hasArtifact ? "var(--green)" : "var(--ink-faint)" }}>
          {hasArtifact ? "☑" : "☐"}
        </span>
        <span style={{ color: "var(--ink-soft)" }}>{t("room.dodArtifact")}</span>
      </div>

      <Label>{t("room.artifacts")}</Label>
      {artifacts.length === 0 && (
        <div className="text-xs" style={{ color: "var(--ink-faint)" }}>{t("room.noneYet")}</div>
      )}
      {artifacts.map((a) => (
        <div key={a.id} className="panel-flat px-3 py-2 mb-2 flex items-center gap-2">
          <span>📄</span>
          <div className="min-w-0">
            <div className="text-sm font-medium truncate">{a.name}</div>
            <div className="text-[0.68rem] font-mono truncate" style={{ color: "var(--ink-faint)" }}>{a.uri}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[0.66rem] uppercase tracking-[0.14em] mb-1.5" style={{ color: "var(--ink-faint)" }}>
      {children}
    </div>
  );
}

/* ─────────────────────────────── Center: thread ─────────────────────────────── */
function Thread({
  task, comments, onPosted,
}: { task: Task; comments: Comment[]; onPosted: () => void }) {
  const { t } = useI18n();
  const { mariusById } = useApp();
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [comments.length]);

  const post = async () => {
    if (!body.trim()) return;
    setBusy(true);
    try { await api.postComment(task.id, body.trim()); setBody(""); onPosted(); }
    finally { setBusy(false); }
  };

  return (
    <div className="h-full flex flex-col min-w-0">
      {task.status === "in_review" && <ApprovalBar task={task} onChange={onPosted} />}
      <div className="flex-1 min-h-0 overflow-y-auto px-6 py-5">
        <div className="text-[0.66rem] uppercase tracking-[0.14em] mb-4" style={{ color: "var(--ink-faint)" }}>
          {t("room.thread")}
        </div>
        {comments.map((c) => {
          const agent = mariusById(c.author_marius_id);
          const name = agent?.name ?? (c.author_user_id ? t("room.patron") : t("room.system"));
          const isAgent = c.author_kind === "agent";
          return (
            <div key={c.id} className="flex gap-3 mb-5">
              <Avatar name={name} size={30} liveness={agent?.liveness} />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 mb-1">
                  <span className="font-medium text-sm">{name}</span>
                  <span className="chip !py-0 !text-[0.62rem]"
                    style={{ background: isAgent ? "rgba(58,88,118,0.12)" : "rgba(179,129,42,0.14)",
                             color: isAgent ? "var(--blue)" : "var(--gold)", borderColor: "transparent" }}>
                    {isAgent ? t("room.agent") : c.author_kind}
                  </span>
                  <span className="text-[0.66rem]" style={{ color: "var(--ink-faint)" }}>{relTime(c.created_at, t)}</span>
                </div>
                <div className="text-sm leading-relaxed panel-flat px-3.5 py-2.5"
                  style={{ background: "var(--panel)", color: "var(--ink)" }}>
                  <Mentioned body={c.body} />
                </div>
              </div>
            </div>
          );
        })}
        {comments.length === 0 && (
          <div className="text-sm" style={{ color: "var(--ink-faint)" }}>{t("room.noMessages")}</div>
        )}
        <div ref={endRef} />
      </div>
      <div className="p-4" style={{ borderTop: "1px solid var(--line)" }}>
        <textarea
          className="input resize-none" rows={2}
          placeholder={t("room.messagePlaceholder")}
          value={body} onChange={(e) => setBody(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) post(); }}
        />
        <div className="flex items-center justify-between mt-2">
          <span className="text-[0.68rem]" style={{ color: "var(--ink-faint)" }}>{t("room.sendHint")}</span>
          <button className="btn btn-primary" disabled={busy || !body.trim()} onClick={post}>{t("room.send")}</button>
        </div>
      </div>
    </div>
  );
}

function ApprovalBar({ task, onChange }: { task: Task; onChange: () => void }) {
  const { t } = useI18n();
  const act = async (status: TaskStatus) => {
    try { await api.transition(task.id, status); onChange(); }
    catch (e) { alert(e instanceof Error ? e.message : t("room.failed")); }
  };
  return (
    <div className="flex items-center gap-3 px-6 py-3"
      style={{ background: "rgba(107,79,134,0.1)", borderBottom: "1px solid var(--line)" }}>
      <span className="text-sm font-medium" style={{ color: "var(--violet)" }}>{t("room.awaitingReview")}</span>
      <div className="ml-auto flex gap-2">
        <button className="btn" onClick={() => act("in_progress")}>{t("room.requestChanges")}</button>
        <button className="btn btn-primary" onClick={() => act("done")}>{t("room.approvePublish")}</button>
      </div>
    </div>
  );
}

/* ──────────────────────────── Right: live trace ──────────────────────────── */
function TracePanel({ task, onActivity }: { task: Task; onActivity: () => void }) {
  const { t } = useI18n();
  const { mariuses, mariusById } = useApp();
  const [runs, setRuns] = useState<Run[]>([]);
  const [selected, setSelected] = useState<string>();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [live, setLive] = useState(false);
  const [agentId, setAgentId] = useState<string>(task.assigned_marius_id ?? "");
  const closeRef = useRef<() => void>();

  const loadRuns = async () => {
    const r = await api.runs(task.id);
    setRuns(r);
    if (!selected && r.length) selectRun(r[r.length - 1]);
  };
  useEffect(() => { loadRuns(); return () => closeRef.current?.(); /* eslint-disable-next-line */ }, [task.id]);
  useEffect(() => { setAgentId(task.assigned_marius_id ?? ""); }, [task.assigned_marius_id]);

  const selectRun = async (run: Run) => {
    closeRef.current?.();
    setSelected(run.id);
    setEvents(await api.runEvents(run.id));
    const terminal = ["completed", "failed", "timed_out", "stopped"].includes(run.status);
    if (!terminal) {
      setLive(true);
      closeRef.current = streamRun(run.id, (e) => {
        if (e.type === "run.finished") { setLive(false); loadRuns(); onActivity(); return; }
        setEvents((prev) => [...prev, e as RunEvent]);
      });
    } else setLive(false);
  };

  const wake = async () => {
    const target = agentId || mariuses[0]?.id;
    if (!target) return;
    const { run_id } = await api.wake(task.id, target, "manual wake from dashboard");
    const fresh = await api.runs(task.id);
    setRuns(fresh);
    const run = fresh.find((r) => r.id === run_id);
    if (run) selectRun(run);
    onActivity();
  };

  const selRun = runs.find((r) => r.id === selected);

  return (
    <div className="h-full flex flex-col" style={{ borderLeft: "1px solid var(--line)", background: "var(--panel)" }}>
      <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: "1px solid var(--line)" }}>
        <span className="font-serif font-semibold">{t("room.liveTrace")}</span>
        {live && <span className="text-[0.66rem] blink" style={{ color: "var(--gold)" }}>{t("room.streaming")}</span>}
        <div className="ml-auto flex items-center gap-1.5">
          <select className="input !w-auto !py-1 !px-2 !text-xs" value={agentId}
            onChange={(e) => setAgentId(e.target.value)}>
            <option value="">{t("room.pickAgent")}</option>
            {mariuses.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <button className="btn btn-primary !py-1 !px-2.5 !text-xs" onClick={wake}>{t("room.wake")}</button>
        </div>
      </div>

      {runs.length > 0 && (
        <div className="flex gap-1.5 px-3 py-2 overflow-x-auto" style={{ borderBottom: "1px solid var(--line-soft)" }}>
          {runs.map((r) => {
            const who = mariusById(r.marius_id);
            const active = r.id === selected;
            return (
              <button key={r.id} onClick={() => selectRun(r)}
                className="chip shrink-0"
                style={{ borderColor: active ? "var(--gold)" : "var(--line)",
                         background: active ? "rgba(216,162,58,0.14)" : "var(--panel-2)" }}>
                {who ? who.name : t("room.agent")} · {r.wake_source}
              </button>
            );
          })}
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 font-mono text-[0.78rem] leading-relaxed">
        {!selRun && <div style={{ color: "var(--ink-faint)" }}>{t("room.noRuns")}</div>}
        {selRun && <TraceTimeline events={events} />}
      </div>

      {selRun && (
        <div className="px-4 py-2.5 text-[0.7rem] flex items-center gap-3"
          style={{ borderTop: "1px solid var(--line)", color: "var(--ink-faint)" }}>
          <span>{t("room.status").toLowerCase()}: <b style={{ color: "var(--ink-soft)" }}>{selRun.status}</b></span>
          {selRun.usage_json?.total_tokens != null && <span>{selRun.usage_json.total_tokens} tok</span>}
          {selRun.error && <span style={{ color: "var(--rust)" }}>{selRun.error}</span>}
        </div>
      )}
    </div>
  );
}

function TraceTimeline({ events }: { events: RunEvent[] }) {
  const { t } = useI18n();
  const rows: React.ReactNode[] = [];
  let buffer = "";
  const flush = (key: string) => {
    if (buffer.trim()) {
      rows.push(
        <p key={`txt-${key}`} className="mb-2 whitespace-pre-wrap" style={{ color: "var(--ink)" }}>{buffer}</p>
      );
    }
    buffer = "";
  };
  events.forEach((e, i) => {
    if (e.type === "assistant.delta") { buffer += e.payload?.text ?? ""; return; }
    flush(String(i));
    if (e.type.startsWith("tool.")) {
      const name = e.payload?.tool_name ?? "tool";
      const map: Record<string, { icon: string; color: string }> = {
        "tool.started": { icon: "🔧", color: "var(--blue)" },
        "tool.completed": { icon: "✓", color: "var(--green)" },
        "tool.failed": { icon: "✗", color: "var(--rust)" },
        "tool.progress": { icon: "…", color: "var(--ink-faint)" },
      };
      const m = map[e.type] ?? { icon: "•", color: "var(--ink-soft)" };
      rows.push(
        <div key={i} className="mb-1.5 flex items-center gap-2">
          <span style={{ color: m.color }}>{m.icon}</span>
          <span style={{ color: m.color }}>{name}</span>
          {e.payload?.ok === false && <span style={{ color: "var(--rust)" }}>{t("room.failed").toLowerCase()}</span>}
        </div>
      );
    } else {
      const muted = ["run.started", "message.started", "assistant.completed", "run.completed", "run.finished"];
      rows.push(
        <div key={i} className="mb-1.5 text-[0.68rem] uppercase tracking-wide"
          style={{ color: muted.includes(e.type) ? "var(--ink-faint)" : "var(--ink-soft)" }}>
          ── {e.type.replace(/[._]/g, " ")} ──
        </div>
      );
    }
  });
  flush("end");
  return <>{rows}</>;
}

/* ─────────────────────────────────── Room ─────────────────────────────────── */
export default function Room() {
  const { t } = useI18n();
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task>();
  const [comments, setComments] = useState<Comment[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [missing, setMissing] = useState(false);

  const load = async () => {
    if (!taskId) return;
    try {
      const [tk, c, a] = await Promise.all([
        api.task(taskId), api.comments(taskId), api.artifacts(taskId),
      ]);
      setTask(tk); setComments(c); setArtifacts(a);
    } catch { setMissing(true); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [taskId]);

  if (missing) return <Center>{t("room.notFound")}</Center>;
  if (!task) return <Center>{t("room.loadingTask")}</Center>;

  return (
    <div className="h-full flex flex-col">
      <div className="px-5 py-2.5 flex items-center gap-2" style={{ borderBottom: "1px solid var(--line)" }}>
        <button className="btn !py-1 !px-2 !text-xs" onClick={() => navigate("/")}>{t("room.backToBoard")}</button>
        <span className="text-sm" style={{ color: "var(--ink-faint)" }}>{t("room.collaborationRoom")}</span>
      </div>
      <div className="flex-1 min-h-0 grid" style={{ gridTemplateColumns: "300px 1fr 380px" }}>
        <TaskContext task={task} artifacts={artifacts} onChange={load} />
        <Thread task={task} comments={comments} onPosted={load} />
        <TracePanel task={task} onActivity={load} />
      </div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-full flex items-center justify-center" style={{ color: "var(--ink-faint)" }}>{children}</div>
  );
}
