// @ts-nocheck
import { useState, useMemo, useEffect } from 'react';
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
  Zap,
  Lock,
  X,
  ArrowRight,
  GripVertical,
  Trash2,
} from 'lucide-react';
import { useMockStore, type TaskStatus, type Priority, type Task } from '@/store/mockStore';
import VellumPanel from '@/components/VellumPanel';
import StatusChip from '@/components/StatusChip';
import Modal from '@/components/Modal';
import { cn, wsHref } from '@/lib/utils';

const KANBAN_COLUMNS: { status: TaskStatus; label: string; bg: string; headerBg: string; borderColor: string }[] = [
  { status: 'backlog', label: 'Backlog', bg: 'bg-[#EDE4CE]', headerBg: 'bg-[#EDE4CE]', borderColor: 'border-[#E3D7BC]' },
  { status: 'todo', label: 'To Do', bg: 'bg-[#E8DED0]', headerBg: 'bg-[#E8DED0]', borderColor: 'border-[#D9CDB8]' },
  { status: 'in_progress', label: 'In Progress', bg: 'bg-[#D4E8F0]', headerBg: 'bg-[#D4E8F0]', borderColor: 'border-[#A8D0E0]' },
  { status: 'in_review', label: 'In Review', bg: 'bg-[#F5E8CC]', headerBg: 'bg-[#F5E8CC]', borderColor: 'border-[#E8D5A0]' },
  { status: 'done', label: 'Done', bg: 'bg-[#D8EADD]', headerBg: 'bg-[#D8EADD]', borderColor: 'border-[#A8D8B8]' },
];

const PRIORITY_BORDER: Record<Priority, string> = {
  P0: 'border-l-[#C25E3A]',
  P1: 'border-l-[#D4A843]',
  P2: 'border-l-[#A89880]',
};

const STATUS_BORDER: Record<string, string> = {
  backlog: 'border-b-[#E3D7BC]',
  todo: 'border-b-[#D9CDB8]',
  in_progress: 'border-b-[#A8D0E0]',
  blocked: 'border-b-[#E8B8A8]',
  in_review: 'border-b-[#E8D5A0]',
  done: 'border-b-[#A8D8B8]',
};

const PRIORITY_BADGE: Record<Priority, { bg: string; text: string }> = {
  P0: { bg: 'bg-[#F5DDD6]', text: 'text-[#B84A32]' },
  P1: { bg: 'bg-[#F5E8CC]', text: 'text-[#8B6A28]' },
  P2: { bg: 'bg-[#E8E0D8]', text: 'text-[#8B7A6A]' },
};

// ─── Task Card ───────────────────────────────────────────────────────────────

function TaskCard({ task, onClick }: { task: Task; onClick: () => void }) {
  const mariuses = useMockStore((s) => s.mariuses);
  const { t } = useTranslation();

  // Normalize to a key the priority maps actually define (P0/P1/P2). The backend exposes no
  // priority, so tasks can arrive with values (e.g. 'normal') that have no PRIORITY_BADGE /
  // PRIORITY_BORDER entry — reading `.bg` off the resulting undefined crashed the whole board
  // (#70). Fall back to the lowest tier for anything unrecognized.
  const priorityKey = PRIORITY_BADGE[task.priority] ? task.priority : 'P2';
  const checklistTotal = (task.checklist || []).length;
  const checklistDone = (task.checklist || []).filter((c) => c.done).length;
  const hasArtifacts = (task.artifacts || []).length > 0;
  const participantAgents = (task.participants || [])
    .map((p) => mariuses.find((m) => m.id === p.id))
    .filter(Boolean);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
      onClick={onClick}
      className={cn(
        'bg-vellum rounded-sm p-4 cursor-pointer border-l-[3px] border-b-2',
        'hover:-translate-y-0.5 hover:shadow-gilt transition-all duration-200',
        'group',
        PRIORITY_BORDER[priorityKey],
        STATUS_BORDER[task.status]
      )}
    >
      {/* Top row: ID + Priority */}
      <div className="flex items-center justify-between mb-1.5">
        <span className="font-mono text-mono-sm text-ink-muted">{task.identifier}</span>
        <span
          className={cn(
            'text-body-xs font-medium px-1.5 py-0.5 rounded-sm',
            PRIORITY_BADGE[priorityKey].bg,
            PRIORITY_BADGE[priorityKey].text
          )}
        >
          {t(`tasks.priority.${priorityKey}`)}
        </span>
      </div>

      {/* Title */}
      <h4 className="font-body text-body-md font-medium text-ink mb-3 leading-snug">
        {task.title}
      </h4>

      {/* Checklist + Comments + Artifacts */}
      <div className="flex items-center gap-3 mb-3 text-ink-light">
        {checklistTotal > 0 && (
          <span className="flex items-center gap-1 text-body-xs">
            <Check className="w-3.5 h-3.5" />
            {checklistDone}/{checklistTotal}
          </span>
        )}
        {(task.comments || []).length > 0 && (
          <span className="flex items-center gap-1 text-body-xs">
            <MessageSquare className="w-3.5 h-3.5" />
            {(task.comments || []).length}
          </span>
        )}
        {hasArtifacts && (
          <span className="flex items-center gap-1 text-body-xs">
            <Paperclip className="w-3.5 h-3.5" />
          </span>
        )}
      </div>

      {/* Participant avatars */}
      {participantAgents.length > 0 && (
        <div className="flex items-center -space-x-2">
          {participantAgents.slice(0, 3).map((agent) => (
            <div
              key={agent!.id}
              className="w-6 h-6 rounded-full border-2 border-vellum bg-vellum-dark overflow-hidden"
              title={agent!.displayName}
            >
              {agent!.avatar ? (
                <img src={agent!.avatar} alt={agent!.displayName || agent!.name} className="w-full h-full object-cover" />
              ) : (
                <div className="w-full h-full flex items-center justify-center text-body-xs text-ink-muted">
                  {(agent!.displayName || agent!.name).charAt(0)}
                </div>
              )}
            </div>
          ))}
          {participantAgents.length > 3 && (
            <div className="w-6 h-6 rounded-full border-2 border-vellum bg-vellum-dark flex items-center justify-center text-body-xs text-ink-muted">
              +{participantAgents.length - 3}
            </div>
          )}
        </div>
      )}

      {/* Drag handle (visual only) */}
      <div className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity">
        <GripVertical className="w-4 h-4 text-ink-muted" />
      </div>
    </motion.div>
  );
}

// ─── Add Task Modal ──────────────────────────────────────────────────────────

function AddTaskModal({
  isOpen,
  onClose,
  columnStatus,
  projectId,
}: {
  isOpen: boolean;
  onClose: () => void;
  columnStatus: TaskStatus;
  projectId: string;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState('');
  const createTask = useMockStore((s) => s.createTask);

  const handleSubmit = () => {
    if (!title.trim()) return;
    createTask({
      title: title.trim(),
      status: columnStatus,
      priority: 'P2',
      projectId,
    });
    setTitle('');
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t('board.addTaskTitle')}
      footer={
        <>
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-vellum-deep text-ink border border-vellum-dark hover:bg-vellum-dark transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleSubmit}
            disabled={!title.trim()}
            className={cn(
              'px-4 py-2 rounded-md font-body text-body-md font-medium transition-colors',
              title.trim()
                ? 'bg-terracotta text-white hover:bg-terracotta-light'
                : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
            )}
          >
            {t('common.create')}
          </button>
        </>
      }
    >
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder={t('board.taskTitlePlaceholder')}
        className={cn(
          'w-full px-4 py-2.5 rounded-md bg-vellum border border-vellum-dark',
          'font-body text-body-md text-ink placeholder:text-ink-muted',
          'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
          'transition-all'
        )}
        autoFocus
        onKeyDown={(e) => {
          if (e.key === 'Enter') handleSubmit();
        }}
      />
    </Modal>
  );
}

// ─── Main ProjectBoard Page ──────────────────────────────────────────────────

export default function ProjectBoard() {
  const { id: projectId, workspaceId } = useParams<{ id: string; workspaceId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const projects = useMockStore((s) => s.projects);
  const tasks = useMockStore((s) => s.tasks);
  const hydrateProject = useMockStore((s) => s.hydrateProject);
  const deleteProject = useMockStore((s) => s.deleteProject);

  const [addTaskColumn, setAddTaskColumn] = useState<TaskStatus | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

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

  const projectTasks = useMemo(
    () => tasks.filter((t) => t.projectId === projectId),
    [tasks, projectId]
  );

  const tasksByColumn = useMemo(() => {
    const map: Record<string, Task[]> = {};
    KANBAN_COLUMNS.forEach((col) => {
      map[col.status] = projectTasks.filter((t) => t.status === col.status);
    });
    return map;
  }, [projectTasks]);

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <h2 className="font-display text-display-md text-ink mb-2">{t('common.loading')}</h2>
      </div>
    );
  }

  const isSetup = project.status === 'setup';
  const isActive = project.status === 'active';
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
        <VellumPanel className="mb-4">
          {/* Top row: name + status */}
          <div className="flex items-start justify-between mb-3">
            <h1 className="font-display text-display-lg text-ink">{project.name}</h1>
            <div className="flex items-center gap-3">
              <StatusChip status={project.status} label={t(`projects.status.${project.status}`)} />
              <button
                onClick={() => setConfirmDelete(true)}
                className="p-1.5 rounded-md text-ink-muted hover:text-[#B84A32] hover:bg-[#F5DDD6] transition-colors"
                title={t('board.deleteProject')}
                aria-label={t('board.deleteProject')}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>
          </div>

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
        </VellumPanel>
      </motion.div>

      {/* ─── Tabs ───────────────────────────────────────────────────── */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.1, duration: 0.3 }}
        className="flex items-center gap-1 mb-4 border-b border-vellum-dark"
      >
        <TabLink active>{t('board.title')}</TabLink>
        <TabLink to={wsHref(workspaceId, `/projects/${projectId}/roster`)}>{t('board.roster')}</TabLink>

        {/* Commission Button (active only) */}
        <div className="ml-auto mb-1">
          <AnimatePresence>
            {isActive && (
              <motion.button
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.9 }}
                onClick={() => navigate(wsHref(workspaceId, `/projects/${projectId}/commission`))}
                className={cn(
                  'flex items-center gap-1.5 px-4 py-2 rounded-md font-body text-body-sm font-medium',
                  'bg-gold text-ink hover:bg-gold-light transition-colors',
                  'animate-pulse-glow'
                )}
              >
                <Zap className="w-4 h-4" />
                {t('board.commissionTask')}
              </motion.button>
            )}
          </AnimatePresence>
        </div>
      </motion.div>

      {/* ─── Setup Banner ───────────────────────────────────────────── */}
      <AnimatePresence>
        {isSetup && (
          <motion.div
            initial={{ opacity: 0, y: -20 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -20 }}
            transition={{ duration: 0.3 }}
            className="mb-4 bg-warning-bg border-l-4 border-warning rounded-md px-4 py-3 flex items-start gap-3"
          >
            <AlertTriangle className="w-5 h-5 text-warning flex-shrink-0 mt-0.5" />
            <div className="flex-1">
              <p className="font-body text-body-md text-ink">{t('board.setupBanner')}</p>
            </div>
            <Link
              to={wsHref(workspaceId, `/projects/${projectId}/roster`)}
              className="flex items-center gap-1 font-body text-body-sm font-medium text-warning hover:text-terracotta transition-colors whitespace-nowrap"
            >
              {t('board.goToRoster')}
              <ArrowRight className="w-4 h-4" />
            </Link>
            <button
              onClick={() => {}}
              className="p-0.5 rounded text-ink-muted hover:text-ink transition-colors"
              aria-label={t('common.dismiss')}
            >
              <X className="w-4 h-4" />
            </button>
          </motion.div>
        )}
      </AnimatePresence>

      {/* ─── Kanban Board ───────────────────────────────────────────── */}
      <div className="flex gap-4 overflow-x-auto pb-4 flex-1 min-h-0">
        {KANBAN_COLUMNS.map((col, colIndex) => {
          const colTasks = tasksByColumn[col.status] || [];
          return (
            <motion.div
              key={col.status}
              initial={{ opacity: 0, y: 30 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                delay: 0.08 * colIndex,
                duration: 0.4,
                ease: [0, 0, 0.2, 1] as [number, number, number, number],
              }}
              className="flex-shrink-0 w-[300px] flex flex-col max-h-full"
            >
              {/* Column header */}
              <div
                className={cn(
                  'flex items-center justify-between px-3 py-2.5 rounded-t-md border-b-2',
                  col.headerBg,
                  col.borderColor
                )}
              >
                <div className="flex items-center gap-2">
                  <span className="font-body text-body-sm font-semibold uppercase tracking-[0.05em] text-ink-light">
                    {col.label}
                  </span>
                  <span className="font-mono text-mono-sm text-ink-muted">
                    ({colTasks.length})
                  </span>
                </div>
                {!isSetup && (
                  <button
                    onClick={() => setAddTaskColumn(col.status)}
                    className="p-1 rounded text-ink-muted hover:text-terracotta transition-colors"
                    aria-label={`Add task to ${col.label}`}
                  >
                    <Plus className="w-4 h-4" />
                  </button>
                )}
              </div>

              {/* Column body */}
              <div className="flex-1 rounded-b-md p-3 flex flex-col gap-2 overflow-y-auto relative">
                {/* Column tint — contained to this column by `relative` above. Previously
                    this `absolute inset-0` had no positioned parent, so it escaped and
                    stacked a faint colored wash over the whole board ("mờ mờ"). */}
                <div className={cn('absolute inset-0 rounded-b-md opacity-[0.08] pointer-events-none', col.bg)} />

                <AnimatePresence mode="popLayout">
                  {colTasks.map((task) => (
                    <TaskCard
                      key={task.id}
                      task={task}
                      onClick={() => navigate(wsHref(workspaceId, `/tasks/${task.id}`))}
                    />
                  ))}
                </AnimatePresence>

                {/* Empty state */}
                {colTasks.length === 0 && (
                  <div className="flex flex-col items-center justify-center py-8 border-2 border-dashed border-vellum-dark rounded-md text-ink-muted">
                    <span className="font-body text-body-sm">{t('board.dropHere')}</span>
                  </div>
                )}

                {/* Add button at bottom */}
                {!isSetup && (
                  <button
                    onClick={() => setAddTaskColumn(col.status)}
                    className="flex items-center justify-center gap-1 py-2 rounded-md text-ink-muted hover:text-terracotta hover:bg-vellum-deep/50 transition-colors"
                  >
                    <Plus className="w-4 h-4" />
                    <span className="font-body text-body-xs font-medium">{t('board.addTask')}</span>
                  </button>
                )}
              </div>
            </motion.div>
          );
        })}
      </div>

      {/* ─── Add Task Modal ─────────────────────────────────────────── */}
      <AddTaskModal
        isOpen={addTaskColumn !== null}
        onClose={() => setAddTaskColumn(null)}
        columnStatus={addTaskColumn || 'backlog'}
        projectId={projectId || ''}
      />

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
              className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-vellum-deep text-ink border border-vellum-dark hover:bg-vellum-dark transition-colors disabled:opacity-50"
            >
              {t('common.cancel')}
            </button>
            <button
              onClick={handleDeleteProject}
              disabled={deleting}
              className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-[#B84A32] text-white hover:bg-[#C25E3A] transition-colors disabled:opacity-50"
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
    </div>
  );
}

// ─── Tab Link Component ─────────────────────────────────────────────────────

function TabLink({
  children,
  to,
  active: _active,
  disabled,
}: {
  children: React.ReactNode;
  to?: string;
  active?: boolean;
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
          'border-b-2 border-transparent hover:border-vellum-dark'
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
