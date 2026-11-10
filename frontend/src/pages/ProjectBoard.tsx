import { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle,
  Plus,
  ListChecks,
  MessageSquare,
  Paperclip,
  Lock,
  X,
  ArrowRight,
  Trash2,
  Radar,
  Hourglass,
  CircleDashed,
} from 'lucide-react';
import { EMPTY_CARD_COUNTS, useAppStore, type TaskStatus, type Task } from '@/store/appStore';
import { CREATABLE_PHASES, type TaskPhase } from '@/lib/taskRules';
import * as api from '@/lib/api';
import { subscribeProjectEvents } from '@/lib/sse';
import StatusChip from '@/components/StatusChip';
import AgentAvatar from '@/components/AgentAvatar';
import Modal from '@/components/Modal';
import ProjectHeader from '@/components/project/ProjectHeader';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { stallText } from '@/lib/stall';
import { WAITING_FOR_A_MACHINE, waitKind, waitText } from '@/lib/drive';
import { notifyLoadFailed } from '@/lib/notify';

// The board's lanes. Eight statuses read as four stages of work — getting ready, being
// worked, waiting for signatures, finished — and each card still names its own status, so
// nothing is folded away. *Bị chặn* stays visible on purpose: a blocked task used to fall
// off the board entirely, which is the exact failure spec 001 is built to prevent. It sits
// in the "being worked" lane with a danger tag rather than in a column of its own.
type LaneKey = 'prep' | 'doing' | 'review' | 'done';
const LANES: { key: LaneKey; statuses: TaskStatus[]; dot: string; createAs?: TaskStatus }[] = [
  { key: 'prep', statuses: ['draft', 'backlog', 'todo'], dot: 'border-[1.5px] border-ink-muted', createAs: 'todo' },
  { key: 'doing', statuses: ['in_progress', 'blocked'], dot: 'bg-gold' },
  { key: 'review', statuses: ['in_review'], dot: 'bg-sapphire' },
  { key: 'done', statuses: ['done'], dot: 'bg-success' },
];

type BoardPriority = 'P0' | 'P1' | 'P2' | 'P3';

// The top two tiers read in the danger colour, the rest stay faint (DESIGN: one meaning per colour).
const PRIORITY_TONE: Record<BoardPriority, string> = {
  P0: 'text-danger',
  P1: 'text-danger',
  P2: 'text-ink-muted',
  P3: 'text-ink-muted',
};

// ─── Task Card ───────────────────────────────────────────────────────────────

function TaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
  const mariuses = useAppStore((s) => s.mariuses);
  const allTasks = useAppStore((s) => s.tasks);
  const { t } = useTranslation();

  // Count blockers that are not yet done (a `blocked_by` edge whose target hasn't finished);
  // the card shows a lock so the patron sees at a glance why it can't advance (#91).
  const blockerCount = (task.dependencies || []).filter((depId) => {
    const b = allTasks.find((x) => x.id === depId);
    return !b || b.status !== 'done';
  }).length;

  // Normalize to a key the priority maps actually define. Tasks can arrive with values
  // (e.g. 'normal') that have no entry — reading a field off the resulting undefined crashed
  // the whole board once (#70). Fall back to the middle tier for anything unrecognized.
  const priorityKey: BoardPriority = (['P0', 'P1', 'P2', 'P3'] as const).includes(task.priority as BoardPriority)
    ? (task.priority as BoardPriority)
    : 'P2';
  // Read the counts, never `task.comments.length` and friends. Those arrays are filled by
  // the single-task screen and left empty by the board's own loader — so counting them here
  // drew nothing on any card, on any board, and no push event could have fixed that because
  // there was no loaded value to refresh (T177). Both loaders now fill `cardCounts`.
  const counts = task.cardCounts ?? EMPTY_CARD_COUNTS;
  const assigneeAgent = task.assigneeId ? mariuses.find((m) => m.id === task.assigneeId) : undefined;
  const assigneeName = assigneeAgent ? assigneeAgent.displayName || assigneeAgent.name : null;
  // Which ordinary wait this card is in, if any — waiting for a free machine and waiting
  // for anyone to pick it up are two different states and get two different lines (FR-008b).
  const waiting = waitKind(task);
  const hasCounts = counts.criteriaTotal > 0 || counts.comments > 0 || counts.artifacts > 0 || blockerCount > 0;

  return (
    <motion.button
      type="button"
      layout
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.97 }}
      transition={{ duration: 0.2 }}
      onClick={onClick}
      className={cn(
        'w-full min-w-0 text-left rounded-[9px] border bg-surface p-[15px]',
        'transition-[border-color,box-shadow,transform] duration-200 hover:-translate-y-0.5 hover:border-sapphire hover:shadow-gilt',
        task.status === 'in_review' ? 'border-sapphire/40' : 'border-line'
      )}
    >
      {/* Top row: identifier + priority */}
      <div className="flex items-center justify-between gap-2.5">
        <span className="task-code truncate">{task.identifier}</span>
        <span className={cn('shrink-0 font-mono text-[10px] uppercase tracking-[0.06em]', PRIORITY_TONE[priorityKey])}>
          {t(`tasks.priority.${priorityKey}`)}
        </span>
      </div>

      {/* Title */}
      <h3
        className={cn(
          'mt-2.5 mb-3 font-display text-[16px] font-normal leading-[1.45] break-words',
          task.status === 'done' || task.status === 'cancelled' ? 'text-ink-light' : 'text-ink-strong'
        )}
      >
        {task.title}
      </h3>

      {/* Why this card is not moving. The stall flag comes first: it means the system
          dropped the task, and no door into *done* will open until it clears (FR-058).
          Below it, the reason whoever blocked or cancelled the task had to write (FR-030). */}
      {task.stalled && (
        <div className="-mt-1 mb-3 flex items-start gap-1.5 text-danger">
          <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
          <span className="font-body text-[12px] leading-snug">
            {stallText(task.stalledReasonCode, t) || t('board.stalled')}
          </span>
        </div>
      )}
      {!task.stalled && task.statusReason && (task.status === 'blocked' || task.status === 'cancelled') && (
        <p
          className={cn(
            '-mt-1 mb-3 font-body text-[12px] leading-snug line-clamp-2',
            task.status === 'blocked' ? 'text-danger' : 'text-ink-muted'
          )}
        >
          {task.statusReason}
        </p>
      )}
      {/* And below that, the ordinary waits. Deliberately quiet — no alarm colour, no
          clock: a task waiting for a free machine is the system working, and the thing
          holding the machine is already being watched on its own (FR-008b, FR-008e). */}
      {waiting && (
        <div className="-mt-1 mb-3 flex items-center gap-1.5 text-ink-muted">
          {waiting === WAITING_FOR_A_MACHINE ? (
            <Hourglass className="w-3.5 h-3.5 flex-shrink-0" />
          ) : (
            <CircleDashed className="w-3.5 h-3.5 flex-shrink-0" />
          )}
          <span className="font-body text-[12px]">{waitText(waiting, t)}</span>
        </div>
      )}

      {/* Acceptance criteria · comments · artifacts · open blockers */}
      {hasCounts && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-body text-[12px] text-ink-muted">
          {counts.criteriaTotal > 0 && (
            <span className="inline-flex items-center gap-1">
              <ListChecks className="w-3.5 h-3.5" />
              {counts.criteriaPassed}/{counts.criteriaTotal}
            </span>
          )}
          {counts.comments > 0 && (
            <span className="inline-flex items-center gap-1">
              <MessageSquare className="w-3.5 h-3.5" />
              {counts.comments}
            </span>
          )}
          {counts.artifacts > 0 && (
            <span className="inline-flex items-center gap-1">
              <Paperclip className="w-3.5 h-3.5" />
              {counts.artifacts}
            </span>
          )}
          {blockerCount > 0 && (
            <span className="inline-flex items-center gap-1 text-danger" title={t('board.blockedBy', { count: blockerCount })}>
              <Lock className="w-3.5 h-3.5" />
              {blockerCount}
            </span>
          )}
        </div>
      )}

      {/* Footer: the single owner, and the task's own status (a lane holds more than one) */}
      <div className="mt-3.5 flex items-center gap-2 border-t border-line pt-3">
        {assigneeAgent ? (
          <AgentAvatar name={assigneeName ?? ''} status={assigneeAgent.status} size="sm" />
        ) : (
          <span className="w-8 h-8 shrink-0 rounded-full border border-dashed border-line-strong" aria-hidden />
        )}
        <span className={cn('flex-1 min-w-0 truncate font-body text-[12px]', assigneeAgent ? 'text-ink-light' : 'text-ink-muted')}>
          {assigneeName ?? t('projectView.unassigned')}
        </span>
        <StatusChip status={task.status} label={t(`tasks.status.${task.status}`)} />
      </div>
    </motion.button>
  );
}

// ─── Add Task (full definition) Modal ────────────────────────────────────────

const LABEL = 'block mb-1.5 font-body text-[13px] font-semibold text-ink';

function AddTaskFormModal({
  onClose,
  projectId,
  defaultStatus = 'backlog',
}: {
  onClose: () => void;
  projectId: string;
  defaultStatus?: TaskStatus;
}) {
  const { t } = useTranslation();
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const [form, setForm] = useState({
    title: '', description: '', status: defaultStatus as string, assigneeId: '', priority: 'medium', dueDate: '', dod: '',
  });
  const [agents, setAgents] = useState<api.ProjectAgentDTO[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Fresh mount each time the modal opens (conditionally rendered), so state resets.
  useEffect(() => {
    if (projectId) api.listProjectAgents(projectId).then(setAgents).catch(notifyLoadFailed);
  }, [projectId]);

  const submit = async () => {
    if (!form.title.trim() || busy) return;
    setBusy(true);
    setErr(null);
    // The payload is worked out before the block: every `||`/`?:` in it is a conditional
    // expression, and the React Compiler has no lowering for those inside try/catch — it
    // drops the whole component when it meets one.
    const payload = {
      title: form.title.trim(),
      description: form.description.trim() || undefined,
      status: form.status,
      priority: form.priority || undefined,
      due_date: form.dueDate ? new Date(form.dueDate).toISOString() : undefined,
      definition_of_done: form.dod.trim() || undefined,
      assigned_marius_id: form.assigneeId || undefined,
    };
    try {
      await api.createTask(projectId, payload);
      await hydrateProject(projectId);
      setForm({ title: '', description: '', status: defaultStatus, assigneeId: '', priority: 'medium', dueDate: '', dod: '' });
      onClose();
    } catch (e) {
      setErr(errorText(e, t));
    }
    setBusy(false);
  };

  return (
    <Modal
      isOpen
      onClose={onClose}
      maxWidth="sm:max-w-[620px]"
      eyebrow={t('projectView.createTaskEyebrow')}
      title={t('projectView.createTaskTitle')}
      footer={
        <>
          <button type="button" onClick={onClose} className="btn btn-secondary">
            {t('common.cancel')}
          </button>
          <button type="submit" form="new-task-form" disabled={!form.title.trim() || busy} className="btn btn-primary">
            <Plus className="w-4 h-4" />
            {t('projectView.createTask')}
          </button>
        </>
      }
    >
      <form
        id="new-task-form"
        className="flex flex-col gap-[17px]"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div>
          <label htmlFor="new-task-title" className={LABEL}>{t('projectView.taskTitleLabel')}</label>
          <input
            id="new-task-title"
            type="text"
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder={t('board.taskTitlePlaceholder')}
            className="field"
            autoFocus
          />
        </div>
        <div>
          <label htmlFor="new-task-desc" className={LABEL}>{t('board.taskDescLabel')}</label>
          <textarea
            id="new-task-desc"
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            rows={3}
            placeholder={t('board.taskDescPlaceholder')}
            className="field py-3 leading-relaxed resize-none"
          />
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-[13px]">
          <div className="min-w-0">
            <label htmlFor="new-task-status" className={LABEL}>{t('board.taskStatusLabel')}</label>
            <select
              id="new-task-status"
              value={form.status}
              onChange={(e) => setForm((f) => ({ ...f, status: e.target.value }))}
              className="field"
            >
              {CREATABLE_PHASES.map((phase) => (
                <option key={phase} value={phase}>{t('tasks.status.' + phase)}</option>
              ))}
            </select>
          </div>
          <div className="min-w-0">
            <label htmlFor="new-task-priority" className={LABEL}>{t('board.taskPriorityLabel')}</label>
            <select
              id="new-task-priority"
              value={form.priority}
              onChange={(e) => setForm((f) => ({ ...f, priority: e.target.value }))}
              className="field"
            >
              <option value="critical">{t('board.priorityCritical')}</option>
              <option value="high">{t('board.priorityHigh')}</option>
              <option value="medium">{t('board.priorityMedium')}</option>
              <option value="low">{t('board.priorityLow')}</option>
            </select>
          </div>
          <div className="min-w-0">
            <label htmlFor="new-task-assignee" className={LABEL}>{t('board.taskAssigneeLabel')}</label>
            <select
              id="new-task-assignee"
              value={form.assigneeId}
              onChange={(e) => setForm((f) => ({ ...f, assigneeId: e.target.value }))}
              className="field"
            >
              <option value="">{t('projectView.unassigned')}</option>
              {agents.map((a) => (
                <option key={a.marius_id} value={a.marius_id}>{a.name}</option>
              ))}
            </select>
          </div>
          <div className="min-w-0">
            <label htmlFor="new-task-due" className={LABEL}>{t('board.taskDueDateLabel')}</label>
            <input
              id="new-task-due"
              type="date"
              value={form.dueDate}
              onChange={(e) => setForm((f) => ({ ...f, dueDate: e.target.value }))}
              className="field"
            />
          </div>
        </div>
        <div>
          <label htmlFor="new-task-dod" className={LABEL}>{t('board.taskDodLabel')}</label>
          <textarea
            id="new-task-dod"
            value={form.dod}
            onChange={(e) => setForm((f) => ({ ...f, dod: e.target.value }))}
            rows={3}
            placeholder={t('board.taskDodPlaceholder')}
            className="field py-3 leading-relaxed resize-none"
          />
        </div>
        {err && <p role="alert" className="font-body text-[13px] text-danger">{err}</p>}
      </form>
    </Modal>
  );
}

// ─── Main ProjectBoard Page ──────────────────────────────────────────────────

export default function ProjectBoard() {
  const { id: projectId, workspaceId } = useParams<{ id: string; workspaceId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const projects = useAppStore((s) => s.projects);
  const tasks = useAppStore((s) => s.tasks);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const deleteProject = useAppStore((s) => s.deleteProject);

  // One add-task form drives every entry point — the header CTA (status=backlog) and the prep
  // lane's "+" (status=that lane). They used to open two different modals (title-only vs
  // full) and the column "+" silently dropped into backlog; now they're in sync (#82).
  const [addTask, setAddTask] = useState<{ open: boolean; status: TaskStatus }>({ open: false, status: 'backlog' });
  // The setup banner's close button used to be wired to nothing. Hidden for this visit only:
  // the next visit shows it again while the project is still being staffed.
  const [setupBannerHidden, setSetupBannerHidden] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // The orchestration cadence's latest sweep (spec 001 FR-052 → FR-055). Read the **sweep
  // record** rather than recomputing the snag list here: a list recomputed on page open would
  // still look fine after the orchestration loop died — exactly what this record exists to expose.
  const [cadence, setCadence] = useState<api.OrchestrationDTO | null>(null);

  const loadCadence = useCallback(() => {
    if (!projectId) return;
    api
      .getProjectOrchestration(projectId)
      .then((row) => setCadence(row))
      .catch(() => setCadence(null));
  }, [projectId]);

  useEffect(() => { loadCadence(); }, [loadCadence]);

  const handleDeleteProject = async () => {
    if (!projectId) return;
    setDeleting(true);
    try {
      await deleteProject(projectId);
      navigate(wsHref(workspaceId, '/projects'));
    } catch {
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  const project = projects.find((p) => p.id === projectId);

  // Load this project's roster + tasks on mount.
  useEffect(() => {
    if (!projectId) return;
    hydrateProject(projectId);
  }, [projectId, hydrateProject]);

  // Push, not poll (Constitution IV, FR-080). Almost nothing on this board is changed by
  // the person looking at it: workers move tasks, the stall flag rises, the orchestration
  // loop finishes a pass. It used to load once on mount and then ask for the sweep row
  // again every minute — so the cards sat frozen for the life of the tab while the cadence
  // block spent a request a minute to usually learn nothing.
  //
  // An event is only a **signal**: on receipt re-read the slice that changed, never build
  // state out of the event stream itself (contracts/push-events, principle 1).
  useEffect(() => {
    if (!projectId) return;
    return subscribeProjectEvents(projectId, (event) => {
      if (event.type.startsWith('orchestration.')) {
        loadCadence();
        return;
      }
      // Everything else on this channel moves something drawn on a card or in the header:
      // status changes, unlocks, stall flags, signatures, phase changes, plan decisions.
      hydrateProject(projectId);
    });
  }, [projectId, hydrateProject, loadCadence]);

  const projectTasks = useMemo(
    () => tasks.filter((t) => t.projectId === projectId),
    [tasks, projectId]
  );

  const tasksByLane = useMemo(() => {
    const map = {} as Record<LaneKey, Task[]>;
    LANES.forEach((lane) => {
      map[lane.key] = projectTasks.filter((t) => lane.statuses.includes(t.status));
    });
    return map;
  }, [projectTasks]);
  const cancelledCount = projectTasks.filter((t) => t.status === 'cancelled').length;

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <h2 className="font-display text-display-md font-normal text-ink-light">{t('common.loading')}</h2>
      </div>
    );
  }

  const isSetup = project.status === 'setup';
  // FR-003: a real task exists only once the patron approved the plan. Anything before
  // *operating* (and anything after *closed*) refuses task creation server-side, so the
  // board must not offer a button that is guaranteed to 409.
  const acceptsTasks = project.status === 'operating' || project.status === 'maintaining';
  const isPlanning = project.status === 'planning';

  return (
    <div className="mx-auto w-full max-w-[1440px] flex flex-col">
      <ProjectHeader
        project={project}
        active="board"
        actions={
          <>
            {acceptsTasks && (
              <button type="button" onClick={() => setAddTask({ open: true, status: 'backlog' })} className="btn btn-primary">
                <Plus className="w-4 h-4" />
                {t('projectView.createTask')}
              </button>
            )}
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="btn btn-ghost w-11 px-0 hover:enabled:text-danger"
              title={t('board.deleteProject')}
              aria-label={t('board.deleteProject')}
            >
              <Trash2 className="w-4 h-4" />
            </button>
          </>
        }
      />

      {/* ─── Planning banner (spec 001 FR-003) ─── */}
      <AnimatePresence>
        {isPlanning && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25 }}
            className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-gold/30 bg-gold-soft px-4 py-3.5"
          >
            <AlertTriangle className="w-5 h-5 shrink-0 text-gold" />
            <p className="flex-[1_1_240px] min-w-0 font-body text-[14px] text-ink">{t('board.planningBanner')}</p>
            <Link
              to={wsHref(workspaceId, `/projects/${projectId}/plan`)}
              className="btn-text min-h-[36px] text-gold hover:text-sapphire-strong whitespace-nowrap"
            >
              {t('board.goToPlan')}
              <ArrowRight className="w-4 h-4" />
            </Link>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Setup banner ─── */}
      <AnimatePresence>
        {isSetup && !setupBannerHidden && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25 }}
            className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-md border border-gold/30 bg-gold-soft px-4 py-3.5"
          >
            <AlertTriangle className="w-5 h-5 shrink-0 text-gold" />
            <p className="flex-[1_1_240px] min-w-0 font-body text-[14px] text-ink">{t('board.setupBanner')}</p>
            <Link
              to={wsHref(workspaceId, `/projects/${projectId}/roster`)}
              className="btn-text min-h-[36px] text-gold hover:text-sapphire-strong whitespace-nowrap"
            >
              {t('board.goToRoster')}
              <ArrowRight className="w-4 h-4" />
            </Link>
            <button
              onClick={() => setSetupBannerHidden(true)}
              className="grid place-items-center w-9 h-9 rounded-md text-ink-muted hover:text-ink-strong hover:bg-surface/70 transition-colors"
              aria-label={t('common.dismiss')}
            >
              <X className="w-4 h-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Orchestration cadence ───
          Only once the project is really running: before *operating* there is no board to
          sweep, so an empty box there would only confuse. */}
      {acceptsTasks && cadence !== null && (
        <section className="surface mb-5 px-5 py-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-body text-[13px]">
            <span className="inline-flex items-center gap-1.5 font-semibold text-ink-strong">
              <Radar className="w-4 h-4 text-sapphire-strong" />
              {t('board.cadence.title')}
            </span>
            <span className="text-ink-muted" aria-hidden>&middot;</span>
            <span className="text-ink-light">
              {cadence.last_swept_at
                ? t('board.cadence.lastSwept', { when: new Date(cadence.last_swept_at).toLocaleString() })
                : t('board.cadence.neverSwept')}
            </span>
            {cadence.next_sweep_at && (
              <>
                <span className="text-ink-muted" aria-hidden>&middot;</span>
                <span className="text-ink-light">
                  {t('board.cadence.nextSweep', { when: new Date(cadence.next_sweep_at).toLocaleString() })}
                </span>
              </>
            )}
          </div>

          {cadence.last_swept_at && cadence.snags.length === 0 && (
            <p className="mt-1.5 font-body text-[13px] text-ink-muted">{t('board.cadence.allClear')}</p>
          )}

          {cadence.snags.length > 0 && (
            <ul className="mt-2.5 space-y-1.5">
              {cadence.snags.map((snag) => (
                <li key={`${snag.kind}-${snag.task_id}`} className="flex items-start gap-2">
                  <span className="mt-0.5 shrink-0 rounded-full border border-danger/35 px-2 py-px font-body text-[11px] text-danger">
                    {t(`board.cadence.kind.${snag.kind}`)}
                  </span>
                  <span className="min-w-0 font-body text-[13px] text-ink-light">
                    {t(`board.cadence.detail.${snag.kind}`, {
                      identifier: snag.identifier,
                      title: snag.title,
                      hours: snag.mark_hours ?? '',
                    })}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {cadence.skipped_reason && (
            <p className="mt-1.5 font-body text-[12px] text-ink-muted">
              {t('board.cadence.skipped', { reason: cadence.skipped_reason })}
            </p>
          )}
        </section>
      )}

      {/* ─── Board (kanban) ───
          One row of four lanes at every width — a board read as a 2×2 grid puts "done" under
          "getting ready". Where there is no room for all four it scrolls sideways and snaps lane
          by lane; on a phone each lane is most of the screen wide and the next one peeks in, so
          the swipe is obvious and no lane is ever cut in an arbitrary place. */}
      <div
        className={cn(
          'grid grid-flow-col gap-3 items-stretch pb-24 overflow-x-auto snap-x snap-mandatory overscroll-x-contain',
          'auto-cols-[minmax(272px,86%)] -mx-4 px-4 scroll-px-4',
          'sm:auto-cols-[minmax(272px,60%)] sm:-mx-6 sm:px-6 sm:scroll-px-6',
          'md:auto-cols-[minmax(250px,1fr)] md:mx-0 md:px-0 md:scroll-px-0'
        )}
      >
        {LANES.map((lane, laneIndex) => {
          const laneLabel = t(`board.lanes.${lane.key}`);
          const laneTasks = tasksByLane[lane.key] || [];
          // What the lane holds, status by status — the four lanes fold eight statuses, so
          // the header says which ones are inside.
          const parts = lane.statuses
            .map((st) => ({ st, n: laneTasks.filter((tk) => tk.status === st).length }))
            .filter((p) => p.n > 0)
            .map((p) => `${t('tasks.status.' + p.st)} ${p.n}`);
          if (lane.key === 'done' && cancelledCount > 0) parts.push(`${t('tasks.status.cancelled')} ${cancelledCount}`);
          const canCreateHere = acceptsTasks && lane.createAs && CREATABLE_PHASES.includes(lane.createAs as TaskPhase);
          return (
            <motion.section
              key={lane.key}
              aria-label={laneLabel}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: 0.05 * laneIndex,
                duration: 0.3,
                ease: [0, 0, 0.2, 1] as [number, number, number, number],
              }}
              className="min-w-0 min-h-[340px] snap-start flex flex-col gap-2.5 rounded-lg border border-line bg-canvas-deep/50 p-3"
            >
              {/* Lane header: label + count, then which statuses it folds */}
              <header className="px-[3px] pt-[3px] pb-2">
                <div className="flex items-center gap-2">
                  <span className={cn('w-2 h-2 rounded-full box-border shrink-0', lane.dot)} />
                  <h2 className="flex-1 min-w-0 truncate font-body text-[13px] font-medium text-ink-light">{laneLabel}</h2>
                  <b className="grid place-items-center min-w-[22px] h-[22px] px-1.5 rounded-full bg-surface font-body text-[11px] font-semibold text-ink-strong">
                    {laneTasks.length}
                  </b>
                </div>
                {parts.length > 0 && (
                  <p className="mt-1 pl-4 font-body text-[11px] text-ink-muted truncate">{parts.join(' · ')}</p>
                )}
              </header>

              <AnimatePresence mode="popLayout">
                {laneTasks.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    onClick={() => navigate(wsHref(workspaceId, `/tasks/${task.id}`))}
                  />
                ))}
              </AnimatePresence>

              {/* Empty state. A lane you cannot create into says so instead of inviting a
                  drop that would skip every gate. */}
              {laneTasks.length === 0 && !canCreateHere && (
                <div className="grid place-items-center min-h-[90px] rounded-lg border border-dashed border-line-strong px-3 text-center font-body text-[12px] text-ink-muted">
                  {lane.createAs ? t('projectView.laneEmpty') : t('board.reachedByWorking')}
                </div>
              )}

              {/* Add button — only in the lane where a new task may legally start. A task
                  cannot be born *in review* or *done*: those are reached by doing the work
                  (spec 001 FR-024). */}
              {canCreateHere && (
                <button
                  onClick={() => setAddTask({ open: true, status: lane.createAs as TaskStatus })}
                  className="flex items-center justify-center gap-1.5 min-h-[44px] rounded-lg border border-dashed border-line-strong font-body text-[13px] font-medium text-ink-light hover:text-sapphire-strong hover:border-sapphire hover:bg-surface transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  {t('projectView.createTask')}
                </button>
              )}
            </motion.section>
          );
        })}
      </div>

      {/* ─── Add Task (full definition) — one form for the CTA + the lane "+" (#82) */}
      {addTask.open && projectId && (
        <AddTaskFormModal
          defaultStatus={addTask.status}
          onClose={() => setAddTask((a) => ({ ...a, open: false }))}
          projectId={projectId}
        />
      )}

      {/* ─── Delete Project Confirm ─── */}
      <Modal
        isOpen={confirmDelete}
        onClose={() => !deleting && setConfirmDelete(false)}
        title={t('board.deleteConfirmTitle')}
        footer={
          <>
            <button onClick={() => setConfirmDelete(false)} disabled={deleting} className="btn btn-secondary">
              {t('common.cancel')}
            </button>
            <button onClick={handleDeleteProject} disabled={deleting} className="btn btn-danger">
              <Trash2 className="w-4 h-4" />
              {deleting ? t('board.deleting') : t('common.delete')}
            </button>
          </>
        }
      >
        <p className="font-body text-[14px] leading-relaxed text-ink-light">
          {t('board.deleteConfirmBody', { name: project.name })}
        </p>
      </Modal>
    </div>
  );
}
