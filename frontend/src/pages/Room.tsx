import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  api, streamRun,
  type Artifact, type Comment, type Run, type RunEvent, type Task, type TaskStatus,
} from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, DropCap, Icon, STATUS_META, StatusBadge, relTime } from "../ui";

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
            style={{ background: "rgba(194,90,58,0.14)", color: "var(--terra)" }}>{p}</span>
        ) : (
          <span key={i}>{p}</span>
        )
      )}
    </>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[0.62rem] uppercase tracking-[0.16em] mb-1.5 font-mono" style={{ color: "var(--ink-faint)" }}>
      {children}
    </div>
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
    <div className="h-full overflow-y-auto p-5">
      {task.description && (
        <p className="text-sm leading-relaxed mb-5 dropcap" style={{ color: "var(--ink-soft)" }}>
          {task.description}
        </p>
      )}

      <Label>{t("room.status")}</Label>
      <div className="relative mb-4">
        <select className="input appearance-none pr-8" value={task.status}
          onChange={(e) => setStatus(e.target.value as TaskStatus)}>
          {ALL_STATUSES.map((s) => <option key={s} value={s}>{t(STATUS_META[s].key)}</option>)}
        </select>
        <Icon name="back" size={14} className="absolute right-2.5 top-1/2 -translate-y-1/2 -rotate-90 pointer-events-none" style={{ color: "var(--ink-faint)" }} />
      </div>

      <Label>{t("room.assignee")}</Label>
      <select className="input mb-2" value={task.assigned_marius_id ?? ""}
        onChange={(e) => assign(e.target.value)}>
        <option value="">{t("room.unassigned")}</option>
        {mariuses.map((m) => <option key={m.id} value={m.id}>{m.name} · {m.role}</option>)}
      </select>
      {assignee && (
        <div className="flex items-center gap-2 mb-4 mt-2 text-xs" style={{ color: "var(--ink-faint)" }}>
          <Avatar name={assignee.name} size={22} liveness={assignee.liveness} />
          {t("room.assignWake")}
        </div>
      )}

      {task.status_reason && (
        <div className="text-[0.78rem] mb-4 px-2.5 py-1.5 rounded flex items-start gap-2"
          style={{ background: "rgba(168,73,44,0.1)", color: "var(--rust)" }}>
          <Icon name="wake" size={13} className="mt-0.5 shrink-0" />
          <span>{task.status_reason}</span>
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
      <div className="flex items-center gap-2 text-sm mb-4">
        <Icon name={hasArtifact ? "check" : "square"} size={16} style={{ color: hasArtifact ? "var(--green)" : "var(--ink-faint)" }} />
        <span style={{ color: "var(--ink-soft)" }}>{t("room.dodArtifact")}</span>
      </div>

      <Label>{t("room.artifacts")}</Label>
      {artifacts.length === 0 && (
        <div className="text-xs" style={{ color: "var(--ink-faint)" }}>{t("room.noneYet")}</div>
      )}
      {artifacts.map((a) => {
        const isLink = a.kind === "link";
        return (
          <div key={a.id} className="panel-flat gilt px-3 py-2 mb-2 flex items-center gap-2.5">
            <Icon name={isLink ? "link" : "file"} size={16} style={{ color: isLink ? "var(--blue)" : "var(--terra)" }} />
            <div className="min-w-0">
              <div className="text-sm font-medium truncate" style={{ color: "var(--ink)" }}>{a.name}</div>
              <div className="text-[0.68rem] font-mono truncate" style={{ color: "var(--ink-faint)" }}>{a.uri}</div>
            </div>
          </div>
        );
      })}
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
        <Label>{t("room.thread")}</Label>
        <div className="space-y-5">
          {comments.map((c) => {
            const agent = mariusById(c.author_marius_id);
            const name = agent?.name ?? (c.author_user_id ? t("room.patron") : t("room.system"));
            const isAgent = c.author_kind === "agent";
            const isHuman = c.author_kind === "human";
            return (
              <div key={c.id} className="flex gap-3 quill-in">
                <Avatar name={name} size={30} liveness={agent?.liveness} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline gap-2 mb-1">
                    <span className="font-medium text-sm" style={{ color: "var(--ink)" }}>{name}</span>
                    <span className="chip !py-0 !text-[0.62rem]"
                      style={{ background: isAgent ? "rgba(58,88,118,0.12)" : isHuman ? "rgba(194,90,58,0.12)" : "var(--panel-2)",
                               color: isAgent ? "var(--blue)" : isHuman ? "var(--terra)" : "var(--ink-faint)", borderColor: "transparent" }}>
                      {isAgent ? t("room.agent") : c.author_kind}
                    </span>
                    <span className="text-[0.66rem] font-mono" style={{ color: "var(--ink-faint)" }}>{relTime(c.created_at, t)}</span>
                  </div>
                  <div className="text-sm leading-relaxed panel-flat px-3.5 py-2.5" style={{ color: "var(--ink)" }}>
                    <Mentioned body={c.body} />
                  </div>
                </div>
              </div>
            );
          })}
          {comments.length === 0 && (
            <div className="text-sm" style={{ color: "var(--ink-faint)" }}>{t("room.noMessages")}</div>
          )}
        </div>
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
          <button className="btn btn-primary" disabled={busy || !body.trim()} onClick={post}>
            <Icon name="send" size={14} /> {t("room.send")}
          </button>
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
      style={{ background: "rgba(122,90,138,0.1)", borderBottom: "1px solid var(--line)" }}>
      <Icon name="eye" size={16} style={{ color: "var(--violet)" }} />
      <span className="text-sm font-medium" style={{ color: "var(--violet)" }}>{t("room.awaitingReview")}</span>
      <div className="ml-auto flex gap-2">
        <button className="btn" onClick={() => act("in_progress")}>{t("room.requestChanges")}</button>
        <button className="btn btn-primary" onClick={() => act("done")}>
          <Icon name="check" size={14} /> {t("room.approvePublish")}
        </button>
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
    <div className="h-full flex flex-col" style={{ background: "var(--panel)" }}>
      <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: "1px solid var(--line)" }}>
        <Icon name="atelier" size={15} style={{ color: "var(--terra)" }} />
        <span className="font-display font-semibold" style={{ color: "var(--ink)" }}>{t("room.liveTrace")}</span>
        {live && <span className="text-[0.66rem] blink flex items-center gap-1" style={{ color: "var(--terra)" }}><span className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--terra)" }} /> {t("room.streaming")}</span>}
        <div className="ml-auto flex items-center gap-1.5">
          <select className="input !w-auto !py-1 !px-2 !text-xs" value={agentId}
            onChange={(e) => setAgentId(e.target.value)}>
            <option value="">{t("room.pickAgent")}</option>
            {mariuses.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>
          <button className="btn btn-primary !py-1 !px-2.5 !text-xs" onClick={wake}>
            <Icon name="wake" size={13} /> {t("room.wake")}
          </button>
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
                style={{ borderColor: active ? "var(--gilt)" : "var(--line)",
                         background: active ? "rgba(201,162,39,0.16)" : "var(--panel-2)" }}>
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
        <div className="px-4 py-2.5 text-[0.7rem] flex items-center gap-3 flex-wrap"
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
  const rows: React.ReactNode[] = [];
  let buffer = "";
  const flush = (key: string) => {
    if (buffer.trim()) {
      rows.push(
        <p key={`txt-${key}`} className="mb-2.5 ml-5 whitespace-pre-wrap" style={{ color: "var(--ink-soft)" }}>{buffer}</p>
      );
    }
    buffer = "";
  };
  events.forEach((e, i) => {
    if (e.type === "run.delta" || e.type === "assistant.delta") { buffer += e.payload?.text ?? ""; return; }
    flush(String(i));
    const isTool = e.type.startsWith("tool.") || e.type === "run.tool";
    if (isTool) {
      const name = e.payload?.name ?? e.payload?.tool_name ?? "tool";
      const path = e.payload?.path;
      let color = "var(--blue)", node = "•";
      if (e.type === "tool.completed") { color = "var(--green)"; node = "✓"; }
      if (e.type === "tool.failed") { color = "var(--rust)"; node = "✗"; }
      rows.push(
        <div key={i} className="mb-2 flex items-center gap-2">
          <span className="inline-flex items-center justify-center w-4 h-4 rounded-full text-[0.6rem] shrink-0"
            style={{ background: `${color}22`, color }}>{node}</span>
          <span style={{ color }}>{name}</span>
          {path && <span className="font-mono text-[0.7rem] truncate" style={{ color: "var(--ink-faint)" }}>{path}</span>}
        </div>
      );
    } else if (e.type === "run.usage") {
      const u = e.payload;
      rows.push(
        <div key={i} className="mb-2 ml-5">
          <span className="chip !py-0 !text-[0.62rem] font-mono">{u.input_tokens}↑ {u.output_tokens}↓</span>
        </div>
      );
    } else {
      const muted = ["run.started", "message.started", "assistant.completed", "run.completed", "run.finished"];
      rows.push(
        <div key={i} className="mb-2.5 text-[0.62rem] uppercase tracking-[0.12em] flex items-center gap-2"
          style={{ color: muted.includes(e.type) ? "var(--ink-faint)" : "var(--ink-soft)" }}>
          <span className="inline-block w-1 h-1 rounded-full" style={{ background: "var(--gilt)" }} />
          {e.type.replace(/[._]/g, " ")}
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
  const { mariusById } = useApp();
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

  const assignee = mariusById(task.assigned_marius_id);

  return (
    <div className="h-full flex flex-col">
      {/* Top breadcrumb bar */}
      <div className="px-5 py-2.5 flex items-center gap-3 shrink-0" style={{ borderBottom: "1px solid var(--line)" }}>
        <button className="btn !py-1 !px-2.5 !text-xs" onClick={() => navigate("/")}>
          <Icon name="back" size={13} /> {t("room.backToBoard")}
        </button>
        <span className="text-xs uppercase tracking-[0.16em] font-mono" style={{ color: "var(--ink-faint)" }}>{t("room.collaborationRoom")}</span>
      </div>

      {/* Illuminated task header */}
      <header className="vellum mx-5 mt-4 px-6 py-4 flex items-center gap-4 shrink-0">
        <DropCap letter={task.title.charAt(0)} size={40} />
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-xl font-semibold leading-snug" style={{ color: "var(--ink)" }}>{task.title}</h1>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <StatusBadge status={task.status} />
            {assignee && (
              <span className="chip" style={{ background: "var(--panel-2)" }}>
                <Avatar name={assignee.name} size={16} liveness={assignee.liveness} /> {assignee.name}
              </span>
            )}
          </div>
        </div>
      </header>

      <div className="flex-1 min-h-0 grid gap-px mt-4 mb-4 mx-5 rounded-lg overflow-hidden panel-flat" style={{ gridTemplateColumns: "300px 1fr 360px" }}>
        <div className="overflow-hidden" style={{ borderRight: "1px solid var(--line)", background: "var(--panel)" }}>
          <TaskContext task={task} artifacts={artifacts} onChange={load} />
        </div>
        <div className="overflow-hidden flex flex-col" style={{ background: "var(--paper)" }}>
          <Thread task={task} comments={comments} onPosted={load} />
        </div>
        <div className="overflow-hidden" style={{ borderLeft: "1px solid var(--line)" }}>
          <TracePanel task={task} onActivity={load} />
        </div>
      </div>
    </div>
  );
}

function Center({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-full flex items-center justify-center" style={{ color: "var(--ink-faint)" }}>{children}</div>
  );
}
