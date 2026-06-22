import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Task } from "../api";
import { useApp } from "../store";
import { Avatar, StatusBadge } from "../ui";

export default function Approvals() {
  const { project, mariusById } = useApp();
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);

  const load = async () => { if (project) setTasks(await api.tasks(project.id)); };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [project?.id]);

  const needsAttention = tasks.filter((t) => t.status === "in_review" || t.status === "blocked");

  const approve = async (t: Task) => {
    try { await api.transition(t.id, "done"); load(); }
    catch (e) { alert(e instanceof Error ? e.message : "Failed"); }
  };

  return (
    <div className="h-full overflow-y-auto p-6" style={{ maxWidth: 860, margin: "0 auto" }}>
      <div className="flex items-center gap-3 mb-1">
        <h1 className="font-serif text-xl font-semibold">Patron inbox</h1>
        <span className="chip">{needsAttention.length} need you</span>
      </div>
      <p className="text-sm mb-5" style={{ color: "var(--ink-soft)" }}>
        Only what needs a human decision: artifacts ready for review, and blocked work.
      </p>

      {needsAttention.length === 0 && (
        <div className="panel p-8 text-center" style={{ color: "var(--ink-faint)" }}>
          Nothing awaits you. The scriptorium is calm. ✦
        </div>
      )}

      {needsAttention.map((t) => {
        const who = mariusById(t.assigned_marius_id);
        const review = t.status === "in_review";
        return (
          <div key={t.id} className="panel p-4 mb-3 flex items-center gap-4">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1.5">
                <StatusBadge status={t.status} />
                {who && (
                  <span className="flex items-center gap-1.5 text-xs" style={{ color: "var(--ink-faint)" }}>
                    <Avatar name={who.name} size={18} /> {who.name}
                  </span>
                )}
              </div>
              <div className="font-serif text-base font-medium">{t.title}</div>
              {t.status_reason && (
                <div className="text-[0.78rem] mt-1" style={{ color: "var(--rust)" }}>{t.status_reason}</div>
              )}
            </div>
            <div className="flex gap-2 shrink-0">
              <button className="btn" onClick={() => navigate(`/tasks/${t.id}`)}>Open</button>
              {review && <button className="btn btn-primary" onClick={() => approve(t)}>Approve</button>}
            </div>
          </div>
        );
      })}
    </div>
  );
}
