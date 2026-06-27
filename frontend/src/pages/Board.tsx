import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, type Task } from "../api";
import { useApp } from "../store";
import { useI18n } from "../i18n";
import { Avatar, BOARD_COLUMNS, DropCap, Icon, LivenessDot, Modal, relTime, STATUS_META } from "../ui";

function TaskCard({ task, index }: { task: Task; index: number }) {
  const { mariusById } = useApp();
  const { t } = useI18n();
  const navigate = useNavigate();
  const assignee = mariusById(task.assigned_marius_id);
  const meta = STATUS_META[task.status];
  return (
    <button
      onClick={() => navigate(`/tasks/${task.id}`)}
      className="panel-flat gilt quill-in w-full text-left p-3 mb-2.5"
      style={{ animationDelay: `${index * 0.04}s`, borderLeft: `3px solid ${meta.color}` }}
    >
      <div className="font-display text-[0.98rem] leading-snug mb-1.5" style={{ color: "var(--ink)" }}>
        {task.title}
      </div>
      {task.status === "blocked" && task.status_reason && (
        <div className="text-[0.7rem] mb-2 px-2 py-1 rounded flex items-center gap-1.5"
          style={{ background: "rgba(168,73,44,0.10)", color: "var(--rust)" }}>
          <Icon name="wake" size={12} /> {task.status_reason}
        </div>
      )}
      {task.next_action && task.status === "in_progress" && (
        <div className="text-[0.72rem] mb-2 italic" style={{ color: "var(--ink-faint)" }}>
          → {task.next_action}
        </div>
      )}
      <div className="flex items-center gap-2 mt-1.5">
        {assignee ? (
          <>
            <Avatar name={assignee.name} size={22} liveness={assignee.liveness} />
            <span className="text-xs" style={{ color: "var(--ink-soft)" }}>{assignee.name}</span>
          </>
        ) : (
          <span className="text-xs" style={{ color: "var(--ink-faint)" }}>{t("board.unassigned")}</span>
        )}
        <span className="ml-auto text-[0.66rem] font-mono" style={{ color: "var(--ink-faint)" }}>
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
  const [desc, setDesc] = useState("");

  const load = async () => { if (project) setTasks(await api.tasks(project.id)); };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [project?.id]);

  const commission = async () => {
    if (!project || !title.trim()) return;
    await api.createTask(project.id, title.trim(), desc.trim() || undefined);
    setTitle(""); setDesc(""); setComposing(false); load();
  };

  const name = project?.name ?? t("board.title");
  const working = mariuses.filter((m) => m.liveness === "working").length;

  return (
    <div className="h-full flex flex-col">
      {/* Illuminated project header — a torn-paper band */}
      <header className="vellum mx-6 mt-5 px-6 py-4 flex items-center gap-4">
        <DropCap letter={name.charAt(0)} size={42} />
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold leading-none truncate" style={{ color: "var(--ink)" }}>{name}</h1>
          <div className="flex items-center gap-2 mt-1.5 flex-wrap">
            <span className="chip">{t("board.tasks", { n: tasks.length })}</span>
            <span className="chip">{mariuses.length} {t("nav.directory").toLowerCase()}</span>
            {working > 0 && (
              <span className="chip" style={{ background: "rgba(194,90,58,0.12)", color: "var(--terra)", borderColor: "transparent" }}>
                <LivenessDot liveness="working" /> {working} {t("liveness.working").toLowerCase()}
              </span>
            )}
          </div>
        </div>
        <div className="ml-auto">
          <button className="btn btn-primary" onClick={() => setComposing(true)}>
            <Icon name="plus" size={15} /> {t("board.commission")}
          </button>
        </div>
      </header>

      <div className="flex-1 min-h-0 flex gap-4 px-6 pb-6 pt-4 overflow-x-auto">
        {BOARD_COLUMNS.map((status) => {
          const items = tasks.filter((t2) => t2.status === status);
          const meta = STATUS_META[status];
          return (
            <div key={status} className="w-[252px] shrink-0 flex flex-col min-h-0">
              <div className="flex items-center gap-2 mb-2 px-1">
                <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: meta.color, boxShadow: `0 0 8px ${meta.color}66` }} />
                <span className="font-display text-sm font-semibold" style={{ color: "var(--ink)" }}>{t(meta.key)}</span>
                <span className="text-xs ml-auto font-mono" style={{ color: "var(--ink-faint)" }}>{items.length}</span>
              </div>
              <div className="panel flex-1 min-h-0 overflow-y-auto p-2" style={{ background: "rgba(241,233,214,0.5)" }}>
                {items.map((t2, i) => <TaskCard key={t2.id} task={t2} index={i} />)}
                {items.length === 0 && (
                  <div className="text-center text-xs py-6" style={{ color: "var(--ink-faint)" }}>{t("board.empty")}</div>
                )}
              </div>
            </div>
          );
        })}

        {/* Scribes roster */}
        <div className="w-[220px] shrink-0 flex flex-col min-h-0">
          <div className="flex items-center gap-2 mb-2 px-1">
            <Icon name="directory" size={15} />
            <span className="font-display text-sm font-semibold" style={{ color: "var(--ink)" }}>{t("board.inProject")}</span>
          </div>
          <div className="vellum flex-1 min-h-0 overflow-y-auto p-3">
            {mariuses.map((m) => (
              <div key={m.id} className="flex items-center gap-2.5 px-1 py-2 rounded-lg">
                <Avatar name={m.name} size={28} liveness={m.liveness} />
                <div className="leading-tight min-w-0 flex-1">
                  <div className="text-sm font-medium truncate" style={{ color: "var(--ink)" }}>{m.name}</div>
                  <div className="text-[0.7rem] truncate font-mono" style={{ color: "var(--ink-faint)" }}>{m.role}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {composing && (
        <Modal title={t("board.commission")} onClose={() => { setComposing(false); setTitle(""); setDesc(""); }}
          footer={<>
            <button className="btn" onClick={() => { setComposing(false); setTitle(""); setDesc(""); }}>{t("common.cancel")}</button>
            <button className="btn btn-primary" disabled={!title.trim()} onClick={commission}>
              <Icon name="send" size={14} /> {t("board.commission")}
            </button>
          </>}>
          <div className="grid gap-3">
            <label className="flex flex-col gap-1.5">
              <span className="text-[0.66rem] uppercase tracking-[0.14em] font-mono" style={{ color: "var(--ink-faint)" }}>{t("board.titleLabel")}</span>
              <input autoFocus className="input" placeholder={t("board.newTaskPlaceholder")}
                value={title} onChange={(e) => setTitle(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && e.metaKey) commission(); }} />
            </label>
            <label className="flex flex-col gap-1.5">
              <span className="text-[0.66rem] uppercase tracking-[0.14em] font-mono" style={{ color: "var(--ink-faint)" }}>{t("board.descLabel")}</span>
              <textarea className="input resize-none" rows={4} placeholder={t("board.descPlaceholder")}
                value={desc} onChange={(e) => setDesc(e.target.value)} />
            </label>
          </div>
        </Modal>
      )}
    </div>
  );
}
