import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Task } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, BOARD_COLUMNS, STATUS_META, relTime } from "../ui";

function TaskCard({ task }: { task: Task }) {
  const { mariusById } = useApp();
  const { t } = useI18n();
  const navigate = useNavigate();
  const assignee = mariusById(task.assigned_marius_id);
  return (
    <button
      onClick={() => navigate(`/tasks/${task.id}`)}
      className="panel-flat w-full text-left p-3 mb-2.5 hover:-translate-y-0.5 transition-transform"
      style={{ background: "var(--panel)" }}
    >
      <div className="font-serif text-[0.95rem] leading-snug mb-2" style={{ color: "var(--ink)" }}>
        {task.title}
      </div>
      {task.status === "blocked" && task.status_reason && (
        <div className="text-[0.72rem] mb-2 px-2 py-1 rounded"
          style={{ background: "rgba(168,73,44,0.1)", color: "var(--rust)" }}>
          ⚠ {task.status_reason}
        </div>
      )}
      {task.next_action && task.status === "in_progress" && (
        <div className="text-[0.72rem] mb-2 italic" style={{ color: "var(--ink-faint)" }}>
          → {task.next_action}
        </div>
      )}
      <div className="flex items-center gap-2 mt-1">
        {assignee ? (
          <>
            <Avatar name={assignee.name} size={22} liveness={assignee.liveness} />
            <span className="text-xs" style={{ color: "var(--ink-soft)" }}>{assignee.name}</span>
            {assignee.liveness === "working" && (
              <span className="text-[0.66rem] blink" style={{ color: "var(--gold)" }}>{t("liveness.working")}</span>
            )}
          </>
        ) : (
          <span className="text-xs" style={{ color: "var(--ink-faint)" }}>{t("board.unassigned")}</span>
        )}
        <span className="ml-auto text-[0.66rem]" style={{ color: "var(--ink-faint)" }}>
          {relTime(task.updated_at, t)}
        </span>
      </div>
    </button>
  );
}

export default function Board() {
  const { project, mariuses } = useApp();
  const { t } = useI18n();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [composing, setComposing] = useState(false);
  const [title, setTitle] = useState("");

  const load = async () => {
    if (project) setTasks(await api.tasks(project.id));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [project?.id]);

  const commission = async () => {
    if (!project || !title.trim()) return;
    await api.createTask(project.id, title.trim());
    setTitle(""); setComposing(false); load();
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-3 px-6 pt-5 pb-3">
        <h1 className="font-serif text-xl font-semibold">{project?.name ?? t("board.title")}</h1>
        <span className="chip">{t("board.tasks", { n: tasks.length })}</span>
        <div className="ml-auto flex items-center gap-2">
          {composing && (
            <input
              autoFocus className="input !w-64" placeholder={t("board.newTaskPlaceholder")}
              value={title} onChange={(e) => setTitle(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") commission(); if (e.key === "Escape") setComposing(false); }}
            />
          )}
          <button className="btn btn-primary" onClick={() => (composing ? commission() : setComposing(true))}>
            {t("board.commission")}
          </button>
        </div>
      </div>

      <div className="flex-1 min-h-0 flex gap-3 px-6 pb-5 overflow-x-auto">
        {BOARD_COLUMNS.map((status) => {
          const items = tasks.filter((t2) => t2.status === status);
          const meta = STATUS_META[status];
          return (
            <div key={status} className="w-[260px] shrink-0 flex flex-col min-h-0">
              <div className="flex items-center gap-2 mb-2 px-1">
                <span className="inline-block w-2 h-2 rounded-full" style={{ background: meta.color }} />
                <span className="text-sm font-medium">{t(meta.key)}</span>
                <span className="text-xs ml-auto" style={{ color: "var(--ink-faint)" }}>{items.length}</span>
              </div>
              <div
                className="flex-1 min-h-0 overflow-y-auto rounded-lg p-1.5"
                style={{ background: "var(--paper-2)", border: "1px solid var(--line-soft)" }}
              >
                {items.map((t2) => <TaskCard key={t2.id} task={t2} />)}
                {items.length === 0 && (
                  <div className="text-center text-xs py-6" style={{ color: "var(--ink-faint)" }}>{t("board.empty")}</div>
                )}
              </div>
            </div>
          );
        })}

        <div className="w-[230px] shrink-0 flex flex-col min-h-0">
          <div className="text-sm font-medium mb-2 px-1">{t("board.inProject")}</div>
          <div className="panel p-2.5 flex-1 min-h-0 overflow-y-auto">
            {mariuses.map((m) => (
              <div key={m.id} className="flex items-center gap-2.5 px-1.5 py-2 rounded-lg">
                <Avatar name={m.name} size={26} liveness={m.liveness} />
                <div className="leading-tight min-w-0">
                  <div className="text-sm font-medium truncate">{m.name}</div>
                  <div className="text-[0.7rem] truncate" style={{ color: "var(--ink-faint)" }}>{m.role}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
