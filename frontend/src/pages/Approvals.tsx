import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Task, type TaskStatus } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, DropCap, Icon, STATUS_META, StatusBadge, relTime } from "../ui";

export default function Approvals() {
  const { project, mariusById } = useApp();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);

  const load = async () => { if (project) setTasks(await api.tasks(project.id)); };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [project?.id]);

  const needsAttention = tasks.filter((t2) => t2.status === "in_review" || t2.status === "blocked");
  const review = tasks.filter((t2) => t2.status === "in_review");
  const blocked = tasks.filter((t2) => t2.status === "blocked");

  const approve = async (task: Task) => {
    try { await api.transition(task.id, "done"); load(); }
    catch (e) { alert(e instanceof Error ? e.message : t("room.failed")); }
  };

  const group = (title: string, status: TaskStatus, icon: string, accent: string, list: Task[]) => {
    if (list.length === 0) return null;
    return (
      <section className="mb-6">
        <div className="flex items-center gap-2 mb-3 px-1">
          <Icon name={icon} size={15} style={{ color: accent }} />
          <h2 className="font-display text-sm font-semibold uppercase tracking-[0.08em]" style={{ color: "var(--ink)" }}>{title}</h2>
          <span className="text-xs font-mono ml-1" style={{ color: "var(--ink-faint)" }}>{list.length}</span>
          <div className="ml-3 flex-1 rule" />
        </div>
        <div className="grid gap-3">{list.map((task, i) => card(task, status, i))}</div>
      </section>
    );
  };

  const card = (task: Task, status: TaskStatus, i: number) => {
    const who = mariusById(task.assigned_marius_id);
    const isReview = status === "in_review";
    const meta = STATUS_META[status];
    return (
      <div key={task.id} className="panel gilt quill-in p-4 flex items-center gap-4" style={{ animationDelay: `${i * 0.05}s`, borderLeft: `3px solid ${meta.color}` }}>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <StatusBadge status={task.status} />
            {who && (
              <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--ink-faint)" }}>
                <Avatar name={who.name} size={18} liveness={who.liveness} /> {who.name}
              </span>
            )}
            <span className="text-[0.66rem] font-mono ml-auto" style={{ color: "var(--ink-faint)" }}>{relTime(task.updated_at, t)}</span>
          </div>
          <button className="block text-left" onClick={() => navigate(`/tasks/${task.id}`)}>
            <div className="font-display text-base font-medium hover:underline underline-offset-2" style={{ color: "var(--ink)" }}>{task.title}</div>
          </button>
          {task.status_reason && (
            <div className="text-[0.78rem] mt-1 flex items-start gap-1.5" style={{ color: "var(--rust)" }}>
              <Icon name="wake" size={12} className="mt-0.5 shrink-0" /> {task.status_reason}
            </div>
          )}
        </div>
        <div className="flex gap-2 shrink-0">
          <button className="btn" onClick={() => navigate(`/tasks/${task.id}`)}>
            <Icon name="eye" size={13} /> {t("inbox.open")}
          </button>
          {isReview && (
            <button className="btn btn-primary" onClick={() => approve(task)}>
              <Icon name="check" size={13} /> {t("inbox.approve")}
            </button>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-7">
        {/* Illuminated header */}
        <header className="vellum quill-in px-7 py-5 mb-6 flex items-start gap-4">
          <DropCap letter={t("inbox.title").charAt(0)} size={48} />
          <div className="min-w-0 flex-1">
            <h1 className="font-display text-2xl font-semibold leading-none" style={{ color: "var(--ink)" }}>{t("inbox.title")}</h1>
            <p className="text-sm mt-2 leading-relaxed" style={{ color: "var(--ink-soft)" }}>{t("inbox.subtitle")}</p>
            <div className="flex items-center gap-2 mt-3">
              <span className="chip" style={needsAttention.length === 0 ? { background: "rgba(94,122,74,0.14)", color: "var(--green)", borderColor: "transparent" } : { background: "rgba(194,90,58,0.12)", color: "var(--terra)", borderColor: "transparent" }}>
                {t("inbox.count", { n: needsAttention.length })}
              </span>
            </div>
          </div>
        </header>

        {needsAttention.length === 0 && (
          <div className="panel ornate p-10 text-center flex flex-col items-center gap-3" style={{ color: "var(--ink-faint)" }}>
            <span className="flex items-center justify-center rounded-full" style={{ width: 48, height: 48, background: "rgba(94,122,74,0.14)", color: "var(--green)" }}>
              <Icon name="check" size={22} />
            </span>
            <div className="font-display italic text-sm">{t("inbox.empty")}</div>
          </div>
        )}

        {group(t("inbox.reviewGroup"), "in_review", "eye", "var(--violet)", review)}
        {group(t("inbox.blockedGroup"), "blocked", "wake", "var(--rust)", blocked)}
      </div>
    </div>
  );
}
