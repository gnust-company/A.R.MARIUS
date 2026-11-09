import { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Calendar,
  GitBranch,
  Users,
  ScrollText,
  AlertTriangle,
  Plus,
  Check,
  MessageSquare,
  Paperclip,
  Lock,
  X,
  ArrowRight,
  GripVertical,
  Trash2,
  Radar,
  Hourglass,
  CircleDashed,
} from 'lucide-react';
import { EMPTY_CARD_COUNTS, useAppStore, type TaskStatus, type Task } from '@/store/appStore';
import { CREATABLE_PHASES, type TaskPhase } from '@/lib/taskRules';
import * as api from '@/lib/api';
import { subscribeProjectEvents } from '@/lib/sse';
import VellumPanel from '@/components/VellumPanel';
import StatusChip from '@/components/StatusChip';
import Modal from '@/components/Modal';
import Dropdown from '@/components/Dropdown';
import LeaderChatWidget from '@/components/LeaderChatWidget';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { stallText } from '@/lib/stall';
import { WAITING_FOR_A_MACHINE, waitKind, waitText } from '@/lib/drive';

// The board's lanes. Eight statuses read as four stages of work — getting ready, being
// worked, waiting for signatures, finished — and each card still names its own status, so
// nothing is folded away. *Bị chặn* stays visible on purpose: a blocked task used to fall
// off the board entirely, which is the exact failure spec 001 is built to prevent. It sits
// in the "being worked" lane with a vermilion tag rather than in a column of its own.
type LaneKey = 'prep' | 'doing' | 'review' | 'done';
const LANES: { key: LaneKey; statuses: TaskStatus[]; dot: string; createAs?: TaskStatus }[] = [
  { key: 'prep', statuses: ['draft', 'backlog', 'todo'], dot: 'border-[1.5px] border-ash', createAs: 'todo' },
  { key: 'doing', statuses: ['in_progress', 'blocked'], dot: 'bg-lapis' },
  { key: 'review', statuses: ['in_review'], dot: 'bg-gold' },
  { key: 'done', statuses: ['done'], dot: 'bg-verdigris' },
];

type BoardPriority = 'P0' | 'P1' | 'P2' | 'P3'

const PRIORITY_BADGE: Record<BoardPriority, { bg: string; text: string }> = {
  P0: { bg: 'bg-vermilion-bg', text: 'text-vermilion-ink' },
  P1: { bg: 'bg-gold-bg', text: 'text-gold-ink' },
  P2: { bg: 'bg-ash-bg', text: 'text-ink-light' },
  P3: { bg: 'bg-ash-bg', text: 'text-ink-muted' },
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

  // Normalize to a key the priority maps actually define (P0/P1/P2). The backend exposes no
  // priority, so tasks can arrive with values (e.g. 'normal') that have no PRIORITY_BADGE /
  // PRIORITY_BORDER entry — reading `.bg` off the resulting undefined crashed the whole board
  // (#70). Fall back to the lowest tier for anything unrecognized.
  const priorityKey: BoardPriority = (['P0', 'P1', 'P2', 'P3'] as const).includes(task.priority as BoardPriority)
    ? (task.priority as BoardPriority)
    : 'P2';
  // Read the counts, never `task.comments.length` and friends. Those arrays are filled by
  // the single-task screen and left empty by the board's own loader — so counting them here
  // drew nothing on any card, on any board, and no push event could have fixed that because
  // there was no loaded value to refresh (T177). Both loaders now fill `cardCounts`.
  const counts = task.cardCounts ?? EMPTY_CARD_COUNTS;
  const assigneeAgent = task.assigneeId ? mariuses.find((m) => m.id === task.assigneeId) : undefined;
  // Which ordinary wait this card is in, if any — waiting for a free machine and waiting
  // for anyone to pick it up are two different states and get two different lines (FR-008b).
  const waiting = waitKind(task);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      onClick={onClick}
      className={cn(
        'relative bg-paper border rounded-[10px] p-3.5 cursor-pointer group',
        'hover:border-line-strong hover:shadow-gilt-lg transition-[border-color,box-shadow] duration-200',
        task.status === 'in_review' ? 'border-[#EBCF8A]' : 'border-line',
        task.status === 'done' && 'bg-inset'
      )}
    >
      {/* Top row: ID + the task's own status (a lane holds more than one) */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <span className="font-mono text-mono-sm text-ink-muted">{task.identifier}</span>
        <span className="flex items-center gap-1.5">
          {(priorityKey === 'P0' || priorityKey === 'P1') && (
            <span
              className={cn(
                'text-body-xs font-medium px-1.5 py-0.5 rounded-full',
                PRIORITY_BADGE[priorityKey].bg,
                PRIORITY_BADGE[priorityKey].text
              )}
            >
              {t(`tasks.priority.${priorityKey}`)}
            </span>
          )}
          <StatusChip status={task.status} label={t(`tasks.status.${task.status}`)} />
        </span>
      </div>

      {/* Title */}
      <h4 className={cn('font-body text-[15px] font-medium mb-2.5 leading-snug', task.status === 'done' ? 'text-ink-light' : 'text-ink')}>
        {task.title}
      </h4>

      {/* Checklist + Comments + Artifacts */}
      <div className="flex items-center gap-3 mb-3 text-ink-light">
        {counts.criteriaTotal > 0 && (
          <span className="flex items-center gap-1 text-body-xs">
            <Check className="w-3.5 h-3.5" />
            {counts.criteriaPassed}/{counts.criteriaTotal}
          </span>
        )}
        {counts.comments > 0 && (
          <span className="flex items-center gap-1 text-body-xs">
            <MessageSquare className="w-3.5 h-3.5" />
            {counts.comments}
          </span>
        )}
        {counts.artifacts > 0 && (
          <span className="flex items-center gap-1 text-body-xs">
            <Paperclip className="w-3.5 h-3.5" />
          </span>
        )}
        {blockerCount > 0 && (
          <span
            className="flex items-center gap-1 text-body-xs text-error"
            title={t('board.blockedBy', { count: blockerCount })}
          >
            <Lock className="w-3.5 h-3.5" />
            {blockerCount}
          </span>
        )}
      </div>

      {/* Why this card is not moving. The stall flag comes first: it means the system
          dropped the task, and no door into *done* will open until it clears (FR-058).
          Below it, the reason whoever blocked or cancelled the task had to write (FR-030). */}
      {task.stalled && (
        <div className="flex items-start gap-1.5 mb-2">
          <AlertTriangle className="w-3.5 h-3.5 text-vermilion-ink flex-shrink-0 mt-0.5" />
          <span className="font-body text-body-sm text-vermilion-ink leading-snug">
            {stallText(task.stalledReasonCode, t) || t('board.stalled')}
          </span>
        </div>
      )}
      {!task.stalled && task.statusReason && (task.status === 'blocked' || task.status === 'cancelled') && (
        <p className={cn('mb-2 font-body text-body-sm leading-snug line-clamp-2', task.status === 'blocked' ? 'text-vermilion-ink' : 'text-ink-muted')}>
          {task.statusReason}
        </p>
      )}
      {/* And below that, the ordinary waits. Deliberately quiet — no alarm colour, no
          clock: a task waiting for a free machine is the system working, and the thing
          holding the machine is already being watched on its own (FR-008b, FR-008e). */}
      {waiting && (
        <div className="flex items-center gap-1.5 mb-2 text-ink-muted">
          {waiting === WAITING_FOR_A_MACHINE ? (
            <Hourglass className="w-3.5 h-3.5 flex-shrink-0" />
          ) : (
            <CircleDashed className="w-3.5 h-3.5 flex-shrink-0" />
          )}
          <span className="font-body text-body-xs">{waitText(waiting, t)}</span>
        </div>
      )}

      {/* Assignee avatar (single owner per task) */}
      {assigneeAgent && (
        <div className="flex items-center gap-2 font-body text-body-sm text-ink-light">
          <div
            className={cn(
              'w-6 h-6 rounded-full overflow-hidden shrink-0',
              assigneeAgent.status === 'working'
                ? 'bg-lapis-bg'
                : assigneeAgent.status === 'offline'
                  ? 'bg-vellum border-[1.5px] border-dashed border-ash'
                  : 'bg-verdigris-bg'
            )}
            title={assigneeAgent.displayName || assigneeAgent.name}
          >
            {assigneeAgent.avatar ? (
              <img src={assigneeAgent.avatar} alt={assigneeAgent.displayName || assigneeAgent.name} className="w-full h-full object-cover" />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-[11px] font-semibold text-ink-light">
                {(assigneeAgent.displayName || assigneeAgent.name).charAt(0)}
              </div>
            )}
          </div>
          <span className="truncate">{assigneeAgent.displayName || assigneeAgent.name}</span>
        </div>
      )}

      {/* Drag handle (visual only) */}
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <GripVertical className="w-4 h-4 text-ink-muted" />
      </div>
    </motion.div>
  );
}

// ─── Add Task (full definition) Modal ────────────────────────────────────────

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
    if (projectId) api.listProjectAgents(projectId).then(setAgents).catch(() => {});
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

  const inputCls = cn(
    'w-full px-3 py-2 rounded-md bg-inset border border-line',
    'font-body text-body-md text-ink placeholder:text-ink-muted',
    'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15 transition-all',
  );
  const labelCls = 'block font-body text-body-sm text-ink-light mb-1';

  return (
    <Modal isOpen onClose={onClose} title={t('board.addTaskTitle')}>
      <div className="space-y-3">
        <input
          type="text"
          value={form.title}
          onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
          placeholder={t('board.taskTitlePlaceholder')}
          className={inputCls}
          autoFocus
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void submit();
            }
          }}
        />
        <div>
          <label className={labelCls}>{t('board.taskDescLabel')}</label>
          <textarea
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            rows={2}
            placeholder={t('board.taskDescPlaceholder')}
            className={cn(inputCls, 'resize-none')}
          />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>{t('board.taskStatusLabel')}</label>
            <Dropdown
              size="sm"
              value={form.status}
              onChange={(value) => setForm((f) => ({ ...f, status: value }))}
              items={CREATABLE_PHASES.map((phase) => ({
                value: phase,
                label: t('tasks.status.' + phase),
              }))}
            />
          </div>
          <div>
            <label className={labelCls}>{t('board.taskPriorityLabel')}</label>
            <Dropdown
              size="sm"
              value={form.priority}
              onChange={(value) => setForm((f) => ({ ...f, priority: value }))}
              items={[
                { value: 'critical', label: t('board.priorityCritical') },
                { value: 'high', label: t('board.priorityHigh') },
                { value: 'medium', label: t('board.priorityMedium') },
                { value: 'low', label: t('board.priorityLow') },
              ]}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>{t('board.taskAssigneeLabel')}</label>
            <Dropdown
              size="sm"
              value={form.assigneeId}
              onChange={(value) => setForm((f) => ({ ...f, assigneeId: value }))}
              items={[
                { value: '', label: t('board.taskAssigneeNone') },
                ...agents.map((a) => ({ value: a.marius_id, label: a.name })),
              ]}
            />
          </div>
          <div>
            <label className={labelCls}>{t('board.taskDueDateLabel')}</label>
            <input
              type="date"
              value={form.dueDate}
              onChange={(e) => setForm((f) => ({ ...f, dueDate: e.target.value }))}
              className={inputCls}
            />
          </div>
        </div>
        <div>
          <label className={labelCls}>{t('board.taskDodLabel')}</label>
          <textarea
            value={form.dod}
            onChange={(e) => setForm((f) => ({ ...f, dod: e.target.value }))}
            rows={2}
            placeholder={t('board.taskDodPlaceholder')}
            className={cn(inputCls, 'resize-none')}
          />
        </div>
        {err && <p className="font-body text-body-sm text-terracotta">{err}</p>}
      </div>
      <div className="flex justify-end gap-3 mt-5 -mb-1">
        <button
          onClick={onClose}
          className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-paper text-ink border border-line-strong hover:bg-inset transition-colors"
        >
          {t('common.cancel')}
        </button>
        <button
          onClick={submit}
          disabled={!form.title.trim() || busy}
          className={cn(
            'flex items-center gap-1.5 px-4 py-2 rounded-md font-body text-body-md font-medium transition-colors',
            form.title.trim() && !busy
              ? 'bg-ink text-paper hover:bg-ink/85'
              : 'bg-line text-ink-muted cursor-not-allowed',
          )}
        >
          <Plus className="w-4 h-4" />
          {t('common.create')}
        </button>
      </div>
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

  // One add-task form drives every entry point — the gold CTA (status=backlog) and each
  // column's "+" (status=that column). They used to open two different modals (title-only vs
  // full) and the column "+" silently dropped into backlog; now they're in sync (#82).
  const [addTask, setAddTask] = useState<{ open: boolean; status: TaskStatus }>({ open: false, status: 'backlog' });
  // The setup banner's close button used to be wired to nothing. Hidden for this visit only:
  // the next visit shows it again while the project is still being staffed.
  const [setupBannerHidden, setSetupBannerHidden] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  // Công tắc tự động công nhận của **chính người đang xem** (FR-036 → FR-038). Không phải
  // một thiết lập của dự án: mỗi người chủ có công tắc riêng, và không ai bật hộ ai.
  const [autoApproval, setAutoApproval] = useState<boolean | null>(null);
  const [switching, setSwitching] = useState(false);

  // Lượt rà gần nhất của nhịp điều phối (spec 001 FR-052 → FR-055). Đọc **bản ghi lượt rà**
  // chứ không tự tính lại danh sách điểm treo: một danh sách tính lại lúc mở trang sẽ trông
  // vẫn ổn ngay cả khi vòng điều phối đã chết — đúng thứ mà bản ghi này sinh ra để lộ.
  const [cadence, setCadence] = useState<api.OrchestrationDTO | null>(null);

  const loadCadence = useCallback(() => {
    if (!projectId) return;
    api
      .getProjectOrchestration(projectId)
      .then((row) => setCadence(row))
      .catch(() => setCadence(null));
  }, [projectId]);

  useEffect(() => { loadCadence(); }, [loadCadence]);

  useEffect(() => {
    if (!projectId) return;
    api
      .getAutoApproval(projectId)
      .then((row) => setAutoApproval(row.enabled))
      .catch(() => setAutoApproval(null));
  }, [projectId]);

  const toggleAutoApproval = async () => {
    if (!projectId || autoApproval === null) return;
    setSwitching(true);
    try {
      const row = await api.setAutoApproval(projectId, !autoApproval);
      setAutoApproval(row.enabled);
    } catch {
      // Giữ nguyên trạng thái đang hiện: thà không đổi còn hơn hiện sai điều người chủ đã chọn.
    }
    setSwitching(false);
  };

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
        <h2 className="font-display text-display-md text-ink mb-2">{t('common.loading')}</h2>
      </div>
    );
  }

  const isSetup = project.status === 'setup';
  // FR-003: a real task exists only once the patron approved the plan. Anything before
  // *operating* (and anything after *closed*) refuses task creation server-side, so the
  // board must not offer a button that is guaranteed to 409.
  const acceptsTasks = project.status === 'operating' || project.status === 'maintaining';
  const isPlanning = project.status === 'planning';
  const seatsTotal = (project.seats || []).length;
  const seatsFilled = (project.seats || []).filter((s) => s.mariusId).length;

  return (
    <div className="flex flex-col h-full">
      {/* ─── Project Header ─────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
      >
        <VellumPanel hover={false} className="mb-5">
          {/* Top row: name + status */}
          <div className="flex items-start justify-between mb-3">
            <h1 className="font-display text-[30px] font-medium leading-tight text-ink">{project.name}</h1>
            <div className="flex items-center gap-3">
              <StatusChip status={project.status ?? 'setup'} label={t(`projects.status.${project.status}`)} />
              <button
                onClick={() => setConfirmDelete(true)}
                className="p-1.5 rounded-md text-ink-muted hover:text-vermilion-ink hover:bg-vermilion-bg transition-colors"
                title={t('board.deleteProject')}
                aria-label={t('board.deleteProject')}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Công tắc tự động công nhận — chỉ hiện khi dự án đã nhận việc thật, vì trước
              đó chưa có đầu ra nào để công nhận. */}
          {autoApproval !== null && acceptsTasks && (
            <div className="mb-3 flex items-start gap-2">
              <input
                id="auto-approval"
                type="checkbox"
                checked={autoApproval}
                disabled={switching}
                onChange={() => void toggleAutoApproval()}
                className="mt-1"
              />
              <label htmlFor="auto-approval" className="font-body text-body-sm text-ink-light">
                <span className="text-ink">{t('board.autoApproval')}</span>
                <span className="block text-body-xs text-ink-muted">
                  {autoApproval ? t('board.autoApprovalOn') : t('board.autoApprovalOff')}
                </span>
              </label>
            </div>
          )}

          {/* Objective */}
          <p className="font-body text-body-md text-ink-light mb-3">{project.objective || ''}</p>

          {/* Meta row */}
          <div className="flex flex-wrap items-center gap-4 font-body text-body-sm text-ink-light">
            <span className="flex items-center gap-1.5">
              <Calendar className="w-4 h-4" />
              {t('board.targetDate', { date: project.createdAt ? new Date(project.createdAt).toLocaleDateString() : '—' })}
            </span>
            {project.githubUrl && (
              <>
                <span className="text-ink-muted">&middot;</span>
                <a
                  href={project.githubUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-terracotta hover:underline"
                >
                  <GitBranch className="w-4 h-4" />
                  <span>{project.githubUrl.replace(/^https?:\/\//, '')}</span>
                </a>
              </>
            )}
            <span className="text-ink-muted">&middot;</span>
            <span className="flex items-center gap-1.5">
              <Users className="w-4 h-4" />
              {t('board.seatCount', { filled: seatsFilled, total: seatsTotal })}
            </span>
            <span className="text-ink-muted">&middot;</span>
            <span className="flex items-center gap-1.5">
              <ScrollText className="w-4 h-4" />
              {t('board.taskCount', { count: projectTasks.length })}
            </span>
          </div>

          {/* ─── Nhịp điều phối ────────────────────────────────────────
              Chỉ hiện khi dự án đã thật sự chạy: trước giai đoạn *đang chạy* chưa có
              bảng việc nào để rà, nên một ô trống ở đó chỉ gây hoang mang. */}
          {acceptsTasks && cadence !== null && (
            <div className="mt-3 pt-3 border-t border-line">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-body text-body-sm">
                <span className="flex items-center gap-1.5 text-ink">
                  <Radar className="w-4 h-4" />
                  {t('board.cadence.title')}
                </span>
                <span className="text-ink-muted">&middot;</span>
                <span className="text-ink-light">
                  {cadence.last_swept_at
                    ? t('board.cadence.lastSwept', {
                        when: new Date(cadence.last_swept_at).toLocaleString(),
                      })
                    : t('board.cadence.neverSwept')}
                </span>
                {cadence.next_sweep_at && (
                  <>
                    <span className="text-ink-muted">&middot;</span>
                    <span className="text-ink-light">
                      {t('board.cadence.nextSweep', {
                        when: new Date(cadence.next_sweep_at).toLocaleString(),
                      })}
                    </span>
                  </>
                )}
              </div>

              {cadence.last_swept_at && cadence.snags.length === 0 && (
                <p className="mt-1.5 font-body text-body-sm text-ink-muted">
                  {t('board.cadence.allClear')}
                </p>
              )}

              {cadence.snags.length > 0 && (
                <ul className="mt-2 space-y-1">
                  {cadence.snags.map((snag) => (
                    <li key={`${snag.kind}-${snag.task_id}`} className="flex items-start gap-2">
                      <span className="mt-0.5 shrink-0 rounded px-1.5 py-0.5 bg-vermilion-bg text-vermilion-ink font-body text-body-xs">
                        {t(`board.cadence.kind.${snag.kind}`)}
                      </span>
                      <span className="font-body text-body-sm text-ink-light">
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
                <p className="mt-1.5 font-body text-body-xs text-ink-muted">
                  {t('board.cadence.skipped', { reason: cadence.skipped_reason })}
                </p>
              )}
            </div>
          )}
        </VellumPanel>
      </motion.div>

      {/* ─── Tabs ───────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1, duration: 0.3 }}
        className="flex items-center gap-1 mb-4 border-b border-line"
      >
        <TabLink>{t('board.title')}</TabLink>
        <TabLink to={wsHref(workspaceId, `/projects/${projectId}/roster`)}>{t('board.roster')}</TabLink>

        {/* Right-side actions: Add Task. (Leader chat moved to the floating bubble — LeaderChatWidget.) */}
        <div className="ml-auto mb-1 flex items-center gap-2">
          <AnimatePresence>
            {acceptsTasks && (
              <motion.button
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                onClick={() => setAddTask({ open: true, status: 'backlog' })}
                className={cn(
                  'flex items-center gap-1.5 px-4 py-2 rounded-md font-body text-body-sm font-medium',
                  'bg-gold text-ink hover:bg-gold-light transition-colors',
                  'animate-pulse-glow'
                )}
              >
                <Plus className="w-4 h-4" />
                {t('board.addTask')}
              </motion.button>
            )}
          </AnimatePresence>
        </div>
      </motion.div>

      {/* ─── Setup Banner ───────────────────────────────────────────── */}
      {/* ─── Planning Banner (spec 001 FR-003) ─────────────────────── */}
      <AnimatePresence>
        {isPlanning && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="mb-5 bg-gold-bg border border-[#EBCF8A] rounded-xl px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-2"
          >
            <AlertTriangle className="w-5 h-5 text-gold-ink flex-shrink-0" />
            <div className="flex-[1_1_240px] min-w-0">
              <p className="font-body text-body-md text-ink">{t('board.planningBanner')}</p>
            </div>
            <Link
              to={wsHref(workspaceId, `/projects/${projectId}/plan`)}
              className="flex items-center gap-1 min-h-[36px] font-body text-body-sm font-medium text-gold-ink hover:text-ink transition-colors whitespace-nowrap"
            >
              {t('board.goToPlan')}
              <ArrowRight className="w-4 h-4" />
            </Link>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {isSetup && !setupBannerHidden && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="mb-5 bg-gold-bg border border-[#EBCF8A] rounded-xl px-4 py-3 flex flex-wrap items-center gap-x-3 gap-y-2"
          >
            <AlertTriangle className="w-5 h-5 text-gold-ink flex-shrink-0" />
            <div className="flex-[1_1_240px] min-w-0">
              <p className="font-body text-body-md text-ink">{t('board.setupBanner')}</p>
            </div>
            <Link
              to={wsHref(workspaceId, `/projects/${projectId}/roster`)}
              className="flex items-center gap-1 min-h-[36px] font-body text-body-sm font-medium text-gold-ink hover:text-ink transition-colors whitespace-nowrap"
            >
              {t('board.goToRoster')}
              <ArrowRight className="w-4 h-4" />
            </Link>
            <button
              onClick={() => setSetupBannerHidden(true)}
              className="p-0.5 rounded text-ink-muted hover:text-ink transition-colors"
              aria-label={t('common.dismiss')}
            >
              <X className="w-4 h-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Board (kanban) + Leader chat dock (VS Code-style right panel) ──── */}
      <div className="flex flex-1 min-h-0">
        <div className="flex-1 min-w-0 min-h-0 flex">
        {/* One row of four lanes at every width — a board read as a 2×2 grid puts "done" under
            "getting ready". Below ~850px of room it scrolls sideways, lane by lane. */}
        <div className="grid grid-flow-col auto-cols-[minmax(200px,1fr)] gap-4 xl:gap-5 items-start pb-24 flex-1 min-h-0 overflow-x-auto snap-x snap-mandatory sm:snap-none -mx-4 px-4 sm:mx-0 sm:px-0">
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
          return (
            <motion.section
              key={lane.key}
              aria-label={laneLabel}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: 0.06 * laneIndex,
                duration: 0.35,
                ease: [0, 0, 0.2, 1] as [number, number, number, number],
              }}
              className="min-w-0 flex flex-col gap-2.5 snap-start"
            >
              {/* Lane header */}
              <div className="flex flex-col gap-0.5 px-0.5 pb-1.5">
                <div className="flex items-center gap-2">
                  <span className={cn('w-2.5 h-2.5 rounded-[3px] box-border', lane.dot)} />
                  <h2 className="font-display text-[18px] font-medium text-ink">{laneLabel}</h2>
                  <span className="font-body text-body-sm text-ink-muted">{laneTasks.length}</span>
                </div>
                <p className="font-body text-body-sm text-ink-muted min-h-[20px]">{parts.join(' · ')}</p>
              </div>

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
              {laneTasks.length === 0 && !(acceptsTasks && lane.createAs) && (
                <div className="flex items-center justify-center py-7 border border-dashed border-line-strong rounded-[10px] text-ink-muted">
                  <span className="font-body text-body-sm px-3 text-center">{t('board.reachedByWorking')}</span>
                </div>
              )}

              {/* Add button — only in the lane where a new task may legally start. A task
                  cannot be born *in review* or *done*: those are reached by doing the work
                  (spec 001 FR-024). */}
              {acceptsTasks && lane.createAs && CREATABLE_PHASES.includes(lane.createAs as TaskPhase) && (
                <button
                  onClick={() => setAddTask({ open: true, status: lane.createAs as TaskStatus })}
                  className="flex items-center justify-center gap-1.5 min-h-[44px] rounded-[10px] border border-dashed border-line-strong text-ink-light hover:text-ink hover:bg-paper transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  <span className="font-body text-body-md font-medium">{t('board.addTask')}</span>
                </button>
              )}
            </motion.section>
          );
        })}
        </div>
        </div>

      </div>

      {/* ─── Add Task (full definition) — one form for the CTA + every column "+" (#82) */}
      {addTask.open && projectId && (
        <AddTaskFormModal
          defaultStatus={addTask.status}
          onClose={() => setAddTask((a) => ({ ...a, open: false }))}
          projectId={projectId}
        />
      )}

      {/* ─── Delete Project Confirm ─────────────────────────────────── */}
      <Modal
        isOpen={confirmDelete}
        onClose={() => !deleting && setConfirmDelete(false)}
        title={t('board.deleteConfirmTitle')}
        footer={
          <>
            <button
              onClick={() => setConfirmDelete(false)}
              disabled={deleting}
              className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-paper text-ink border border-line-strong hover:bg-inset transition-colors disabled:opacity-50"
            >
              {t('common.cancel')}
            </button>
            <button
              onClick={handleDeleteProject}
              disabled={deleting}
              className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-vermilion-ink text-white hover:bg-ink transition-colors disabled:opacity-50"
            >
              {deleting ? t('board.deleting') : t('common.delete')}
            </button>
          </>
        }
      >
        <p className="font-body text-body-md text-ink-light">
          {t('board.deleteConfirmBody', { name: project.name })}
        </p>
      </Modal>

      {/* Floating Leader-chat bubble (project-only, bottom-right) — opens a large chat panel (#82) */}
      {projectId && <LeaderChatWidget projectId={projectId} />}
    </div>
  );
}

// ─── Tab Link Component ─────────────────────────────────────────────────────

// The active tab is the one without a `to` — there is nowhere to navigate to
// from the page you are already on. An `active` prop would be a second source
// of truth for the same fact, so there isn't one.
function TabLink({
  children,
  to,
  disabled,
}: {
  children: React.ReactNode;
  to?: string;
  disabled?: boolean;
}) {
  const { t } = useTranslation();
  if (disabled) {
    return (
      <span
        className={cn(
          'flex items-center px-4 py-2.5 font-body text-body-md font-medium text-ink-muted',
          'border-b-2 border-transparent cursor-not-allowed'
        )}
        title={t('board.commissionLocked')}
      >
        {children}
      </span>
    );
  }

  if (to) {
    return (
      <Link
        to={to}
        className={cn(
          'flex items-center px-4 py-2.5 font-body text-body-md font-medium text-ink-light hover:text-ink transition-colors',
          'border-b-2 border-transparent hover:border-line-strong'
        )}
      >
        {children}
      </Link>
    );
  }

  return (
    <span
      className={cn(
        'flex items-center px-4 py-2.5 font-body text-body-md font-medium text-terracotta',
        'border-b-2 border-terracotta'
      )}
    >
      {children}
    </span>
  );
}
