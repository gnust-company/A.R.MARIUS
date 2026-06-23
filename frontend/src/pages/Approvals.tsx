import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Task } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, StatusBadge } from "../ui";

export default function Approvals() {
  const { project, mariusById } = useApp();
  const { t } = useI18n();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);

  const load = async () => { if (project) setTasks(await api.tasks(project.id)); };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [project?.id]);

  const needsAttention = tasks.filter((t2) => t2.status === "in_review" || t2.status === "blocked");

  const approve = async (task: Task) => {
    try { await api.transition(task.id, "done"); load(); }
    catch (e) { alert(e instanceof Error ? e.message : t("room.failed")); }
  };

  return (
    <div className="h-full overflow-y-auto p-6" style={{ maxWidth: 860, margin: "0 auto" }}>
      <div className="flex items-center gap-3 mb-1">
        <h1 className="font-serif text-xl font-semibold">{t("inbox.title")}</h1>
        <span className="chip">{t("inbox.count", { n: needsAttention.length })}</span>
      </div>
      <p className="text-sm mb-5" style={{ color: "var(--ink-soft)" }}>{t("inbox.subtitle")}</p>

      {needsAttention.length === 0 && (
        <div className="panel p-8 text-center" style={{ color: "var(--ink-faint)" }}>
          {t("inbox.empty")}
        </div>
      )}

      {needsAttention.map((task) => {
        const who = mariusById(task.assigned_marius_id);
        const review = task.status === "in_review";
        return (
          <div key={task.id} className="panel p-4 mb-3 flex items-center gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1.5">
                <StatusBadge status={task.status} />
                {who && (
                  <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--ink-faint)" }}>
                    <Avatar name={who.name} size={18} /> {who.name}
                  </span>
                )}
              </div>
              <div className="font-serif text-base font-medium">{task.title}</div>
              {task.status_reason && (
                <div className="text-[0.78rem] mt-1" style={{ color: "var(--rust)" }}>{task.status_reason}</div>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <button className="btn" onClick={() => navigate(`/tasks/${task.id}`)}>{t("inbox.open")}</button>
              {review && <button className="btn btn-primary" onClick={() => approve(task)}>{t("inbox.approve")}</button>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
