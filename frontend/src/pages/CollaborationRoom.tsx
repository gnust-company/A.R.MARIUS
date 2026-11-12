import { useState, useRef, useEffect, type ReactNode } from 'react';
import { useParams, useNavigate, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft,
  Send,
  ShieldCheck,
  ListChecks,
  Plus,
  X,
  Paperclip,
  ExternalLink,
  Lock,
  Unlock,
  Activity,
  Users,
  MessageSquare,
  XCircle,
  Hourglass,
  CircleDashed,
  Flag,
  CalendarDays,
  ChevronDown,
  Pencil,
  CornerDownRight,
} from 'lucide-react';
import {
  ApiError,
  downloadArtifact,
  listTaskApprovals,
  signTaskApproval,
  type ApprovalDTO,
} from '@/lib/api';
import {
  useAppStore,
  type Priority,
  type Task,
  type TaskEditPatch,
} from '@/store/appStore';
import { useTaskStream } from '@/hooks/use-task-stream';
import { subscribeProjectEvents } from '@/lib/sse';
import { cn, wsHref } from '@/lib/utils';
import { withVersions } from '@/lib/artifactVersions';
import { blockedReasonKey, needsReason, type TaskPhase } from '@/lib/taskRules';
import { errorText } from '@/lib/errors';
import { WAITING_FOR_A_MACHINE, waitKind, waitText } from '@/lib/drive';
import Dropdown from '@/components/Dropdown';
import Modal from '@/components/Modal';
import StatusChip from '@/components/StatusChip';
import AgentAvatar from '@/components/AgentAvatar';
import TaskComment, { PatronMark } from '@/components/task/TaskComment';
import TraceEventCard from '@/components/task/TraceEventCard';
import { notifyLoadFailed } from '@/lib/notify';

/** The four fields the patron can edit on this screen, as the strings the inputs use. */
interface TaskEditDraft {
  title: string
  description: string
  priority: Priority
  dueDate: string
}

/** The four priority levels, exactly the ones the server has. */
const PRIORITY_OPTIONS: readonly Priority[] = ['P0', 'P1', 'P2', 'P3'];

/** One colour per priority flag: urgent reads as danger, high as gold, the rest go quiet. */
const PRIORITY_TONE: Record<string, string> = {
  P0: 'text-danger',
  P1: 'text-gold',
  P2: 'text-ink-muted',
  P3: 'text-ink-faint',
};

const STATUS_OPTIONS = ['draft', 'backlog', 'todo', 'in_progress', 'blocked', 'in_review', 'done', 'cancelled'] as const;

/** Scroll the nearest scrollable ancestor of `end` to its bottom, leaving the window alone. */
function scrollPaneToEnd(end: HTMLElement | null) {
  let pane = end?.parentElement ?? null;
  while (pane && pane.scrollHeight <= pane.clientHeight) pane = pane.parentElement;
  if (pane && pane !== document.documentElement && pane !== document.body) {
    pane.scrollTo({ top: pane.scrollHeight, behavior: 'smooth' });
  }
}

/** One section of the task document: a mono label (with an optional figure on the right) over
 *  its content, divided from the next by a hairline. */
function DocSection({
  label,
  aside,
  children,
  className,
}: {
  label: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn('border-b border-line px-5 py-5 last:border-b-0 sm:px-6', className)}>
      <div className="flex items-center justify-between gap-3">
        <span className="eyebrow">{label}</span>
        {aside}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}

// ─── Main Collaboration Room ─────────────────────────────────────────────────

export default function CollaborationRoom() {
  const { id: taskId, workspaceId } = useParams<{ id: string; workspaceId: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  // One selector per value, the way every other page reads the store. `useAppStore()`
  // with no selector subscribes to the *whole* store and hands back a fresh object on
  // any change anywhere, so nothing derived from it could keep its identity across a
  // render — which is why the React Compiler gave up on this component fifteen times
  // over. Actions keep their identity for the life of the store; state slices change
  // only when that slice changes.
  const tasks = useAppStore((s) => s.tasks);
  const mariuses = useAppStore((s) => s.mariuses);
  const projects = useAppStore((s) => s.projects);
  const currentUser = useAppStore((s) => s.currentUser);
  const updateTask = useAppStore((s) => s.updateTask);
  const editTask = useAppStore((s) => s.editTask);
  const addComment = useAppStore((s) => s.addComment);
  const setTaskCriteria = useAppStore((s) => s.setTaskCriteria);
  const publishArtifact = useAppStore((s) => s.publishArtifact);
  const addTaskDependency = useAppStore((s) => s.addTaskDependency);
  const removeTaskDependency = useAppStore((s) => s.removeTaskDependency);
  const hydrateTask = useAppStore((s) => s.hydrateTask);

  const task = tasks.find((t) => t.id === taskId);

  // Subscribe to the per-task wake trace SSE.
  useTaskStream(taskId);

  // Load the task + its comment thread + artifacts on mount. Depends on the one
  // action, never on a whole-store object: an effect that re-runs on the very state it
  // writes is a loop.
  // `hydratedId` says the first read for this id has come back (either way), so a task
  // that is merely still loading is not announced as missing.
  const [hydratedId, setHydratedId] = useState<string | null>(null);
  useEffect(() => {
    if (!taskId) return;
    let alive = true;
    hydrateTask(taskId)
      .catch(notifyLoadFailed)
      .finally(() => {
        if (alive) setHydratedId(taskId);
      });
    return () => {
      alive = false;
    };
  }, [taskId, hydrateTask]);

  // Push, not poll (Constitution IV, FR-080a). The trace stream above carries one task's
  // run events and nothing else; everything a person changes about the task — the Leader
  // scoring a criterion, a comment, an artifact, a blocker — travels on the project
  // channel. Without this the criteria panel sat on whatever was true at mount: a screen
  // that only becomes right again on a reload is the exact shape FR-080a forbids.
  //
  // Filtered to this task on the way in. The board can afford to re-read a project on any
  // event because that is the one call it makes; a room re-reading a task, its thread, its
  // artifacts, its blockers and its trace on somebody else's card would spend five.
  const roomProjectId = task?.projectId;
  useEffect(() => {
    if (!taskId || !roomProjectId) return;
    return subscribeProjectEvents(roomProjectId, (event) => {
      if (event.data?.task_id === taskId) hydrateTask(taskId);
    });
  }, [taskId, roomProjectId, hydrateTask]);

  const [commentInput, setCommentInput] = useState('');
  // Read straight off the task, never mirrored into local state. A copy went stale the
  // moment the real task arrived: on a cold load the box froze on its `todo` fallback and
  // kept reporting it — a status control showing the wrong status is worse than none. The
  // store already updates optimistically, so the box follows a change without help.
  const statusValue: Task['status'] = task?.status ?? 'todo';
  // Which ordinary wait this task is in, if any (FR-008b).
  const waiting = task ? waitKind(task) : undefined;
  // null = the reader has not chosen; the drawer then opens only when there is a trace.
  const [traceChoice, setTraceOpen] = useState<boolean | null>(null);
  const [showAddArtifactModal, setShowAddArtifactModal] = useState(false);
  const [fetchingArtifact, setFetchingArtifact] = useState<string | null>(null);
  const [artifactError, setArtifactError] = useState<string | null>(null);

  // Fetch the bytes with this person's token, then hand the browser a blob to save. The
  // object URL is released straight away: it is a handle to memory, and one left behind per
  // download is a leak on a screen somebody keeps open all day.
  async function saveArtifact(artifact: { id: string; name?: string; title?: string }) {
    if (!task) return;
    setFetchingArtifact(artifact.id);
    setArtifactError(null);
    try {
      const blob = await downloadArtifact(task.id, artifact.id);
      const href = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = href;
      link.download = artifact.name || artifact.title || 'artifact';
      link.click();
      URL.revokeObjectURL(href);
    } catch (e) {
      setArtifactError(errorText(e, t));
    } finally {
      setFetchingArtifact(null);
    }
  }
  const [artifactForm, setArtifactForm] = useState({ name: '', url: '', type: 'file' as 'file' | 'link' });
  const [depPicker, setDepPicker] = useState('');
  const [depError, setDepError] = useState<string | null>(null);
  const threadEndRef = useRef<HTMLDivElement>(null);
  const traceEndRef = useRef<HTMLDivElement>(null);

  // The task's single assignee (one owner per task) resolved to agent data — 0 or 1.
  const assignedAgents = task?.assigneeId
    ? mariuses.filter((m) => m.id === task.assigneeId)
    : [];

  // Get dependency (blocked_by) tasks + the candidates the picker can add (same project,
  // not itself, not already a blocker).
  const dependencyTasks = tasks.filter((t) => task?.dependencies?.includes(t.id));
  const candidateBlockers = tasks.filter(
    (x) =>
      x.projectId === task?.projectId &&
      x.id !== task?.id &&
      !(task?.dependencies || []).includes(x.id),
  );

  // Check DONE gate
  const hasArtifacts = (task?.artifacts?.length ?? 0) > 0;
  // The dependency gate, from what the board already knows: a blocker that has not finished.
  const blockedByUnfinished = dependencyTasks.some((d) => d.status !== 'done');
  // Acceptance criteria — scored at approval (Story 3); here we render the yardstick.
  const criteriaPassed = task?.checklist?.filter((c) => c.result === 'passed').length ?? 0;
  const criteriaTotal = task?.checklist?.length ?? 0;
  const criteriaPercent = criteriaTotal ? Math.round((criteriaPassed / criteriaTotal) * 100) : 0;
  const criteriaEditable = ['draft', 'backlog', 'todo'].includes(task?.status ?? '');

  // Auto-scroll to the newest message/event — inside its own pane only. `scrollIntoView`
  // also scrolled the window, so on a stacked (narrow) layout opening a task jumped the page
  // down past the task's own header to the end of the thread.
  useEffect(() => {
    scrollPaneToEnd(threadEndRef.current);
  }, [task?.comments?.length]);

  useEffect(() => {
    scrollPaneToEnd(traceEndRef.current);
  }, [task?.trace?.length]);

  // The handlers below are deliberately plain functions. With the React Compiler on, it
  // memoizes them itself and does a better job of it: hand-written dependency arrays here
  // could not be preserved (fifteen reports), and a `useCallback` the compiler cannot
  // preserve makes it bail out of the *whole component*, so the manual memoization was
  // costing every optimization in this file to buy back seven.
  const handleStatusChange = (newStatus: string) => {
    if (!task) return;
    const from = task.status as TaskPhase;
    const to = newStatus as TaskPhase;
    // Mirror of the server's gates — the point is not to enforce (the server does that)
    // but not to offer a move that is certain to come back a 409.
    if (blockedReasonKey(from, to, { hasArtifact: hasArtifacts, stalled: !!task.stalled, depsSatisfied: !blockedByUnfinished })) {
      return;
    }
    let reason: string | undefined;
    if (needsReason(from, to)) {
      const answer = window.prompt(t('taskRules.reasonPrompt'));
      if (!answer || !answer.trim()) return;  // no reason, no move — the server agrees
      reason = answer.trim();
    }
    updateTask(task.id, { status: to as Task['status'], statusReason: reason });
  };

  const handleSendComment = () => {
    if (!commentInput.trim() || !task) return;
    addComment(task.id, {
      authorId: currentUser?.id || 'user-patron',
      authorName: currentUser?.name || t('collaborationRoom.patron'),
      content: commentInput.trim(),
    });
    setCommentInput('');
  };

  const [criteriaDraft, setCriteriaDraft] = useState<string | null>(null);
  const [criteriaError, setCriteriaError] = useState<string | null>(null);

  // ── The patron edits the task in place (FR-070, FR-070a) ─────────────────────
  // Without this, a mistyped due date meant cancelling the task and creating it again,
  // losing its comments, artifacts and trace. The draft is `null` while the editor is closed.
  const [editDraft, setEditDraft] = useState<TaskEditDraft | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const openEditor = () => {
    if (!task) return;
    setEditError(null);
    setEditDraft({
      title: task.title,
      description: task.description ?? '',
      priority: (task.priority as Priority) ?? 'P2',
      // The browser's date input only takes "YYYY-MM-DD"; the server sends the time too.
      dueDate: task.dueDate ? task.dueDate.slice(0, 10) : '',
    });
  };

  const handleSaveEdit = async () => {
    if (!task || !editDraft) return;
    setEditError(null);
    setSaving(true);
    try {
      // Send only what actually changed. An emptied field **clears** the current value, so
      // it goes out as an empty value rather than being silently skipped — that is how a
      // wrongly set due date is removed.
      const patch: TaskEditPatch = {};
      if (editDraft.title !== task.title) patch.title = editDraft.title;
      if (editDraft.description !== (task.description ?? '')) {
        patch.description = editDraft.description.trim() ? editDraft.description : null;
      }
      if (editDraft.priority !== task.priority) patch.priority = editDraft.priority;
      const currentDue = task.dueDate ? task.dueDate.slice(0, 10) : '';
      if (editDraft.dueDate !== currentDue) {
        patch.dueDate = editDraft.dueDate ? `${editDraft.dueDate}T00:00:00Z` : null;
      }
      if (Object.keys(patch).length > 0) {
        await editTask(task.id, patch);
      }
      setEditDraft(null);
    } catch (e) {
      setEditError(errorText(e, t));
    } finally {
      setSaving(false);
    }
  };

  const handleSaveCriteria = async () => {
    if (!task || criteriaDraft === null) return;
    setCriteriaError(null);
    try {
      await setTaskCriteria(
        task.id,
        criteriaDraft.split('\n').map((line) => line.trim()).filter(Boolean),
      );
      setCriteriaDraft(null);
    } catch (e) {
      setCriteriaError(errorText(e, t));
    }
  };

  // ── Output acceptance (FR-033, FR-035) ──────────────────────────────────────
  const [approvals, setApprovals] = useState<ApprovalDTO[]>([]);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);

  // Load the signatures through a promise chain, not a bare `await` in the effect body:
  // setting state synchronously there costs an extra render every time the task changes.
  const [approvalsKey, setApprovalsKey] = useState(0);
  const signedTaskId = task?.id;
  const signedTaskStatus = task?.status;

  useEffect(() => {
    if (!signedTaskId) return;
    let alive = true;
    listTaskApprovals(signedTaskId)
      .then((rows) => {
        if (alive) setApprovals(rows);
      })
      .catch(() => {
        // The signature list is read-only; if it fails the signing box still works, so it
        // must not take the whole page down.
        if (alive) setApprovals([]);
      });
    return () => {
      alive = false;
    };
  }, [signedTaskId, signedTaskStatus, approvalsKey]);

  /** Current round = times sent back + 1; a signature from an old round does not carry over. */
  const currentRound = approvals.filter((a) => a.result === 'reject').length + 1;
  const leaderSigned = approvals.some(
    (a) => a.round === currentRound && a.signer_kind === 'leader' && a.result === 'approve',
  );

  const handleSign = async (approve: boolean) => {
    if (!task) return;
    let reason: string | undefined;
    if (!approve) {
      const said = window.prompt(t('collaborationRoom.acceptance.reasonPrompt'));
      if (!said || !said.trim()) return;
      reason = said.trim();
    }
    setSigning(true);
    setApprovalError(null);
    try {
      await signTaskApproval(task.id, approve, reason);
      await hydrateTask(task.id);
      setApprovalsKey((n) => n + 1);
    } catch (e) {
      setApprovalError(errorText(e, t));
    }
    setSigning(false);
  };

  const handleAddDependency = async (blocksTaskId: string) => {
    if (!task || !blocksTaskId) return;
    setDepError(null);
    try {
      await addTaskDependency(task.id, blocksTaskId);
      setDepPicker('');
    } catch (e) {
      // Server rejects self-loop/duplicate/cross-project/cycle with a 422 detail (#91).
      setDepError(e instanceof ApiError ? errorText(e, t) : t('collaborationRoom.context.dependencyFailed'));
    }
  };

  const handleRemoveDependency = async (blocksTaskId: string) => {
    if (!task) return;
    setDepError(null);
    try {
      await removeTaskDependency(task.id, blocksTaskId);
    } catch (e) {
      setDepError(e instanceof ApiError ? errorText(e, t) : t('collaborationRoom.context.dependencyFailed'));
    }
  };

  const handleAddArtifact = () => {
    if (!task || !artifactForm.name.trim()) return;
    publishArtifact(task.id, {
      type: artifactForm.type,
      name: artifactForm.name.trim(),
      url: artifactForm.url.trim() || undefined,
      content: artifactForm.type === 'file' ? 'file-content-placeholder' : undefined,
    });
    setArtifactForm({ name: '', url: '', type: 'file' });
    setShowAddArtifactModal(false);
  };

  if (!task && hydratedId !== taskId) {
    return (
      <div className="flex h-[60vh] items-center justify-center" role="status">
        <p className="font-body text-body-md text-ink-muted">{t('common.loading')}</p>
      </div>
    );
  }

  if (!task) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="text-center">
          <Activity className="mx-auto mb-4 h-12 w-12 text-ink-muted" strokeWidth={1.5} />
          <h2 className="font-display text-display-md text-ink-strong">{t('collaborationRoom.taskNotFound')}</h2>
          <button onClick={() => navigate(-1)} className="btn btn-secondary mt-4">
            {t('collaborationRoom.goBack')}
          </button>
        </div>
      </div>
    );
  }

  const traceOpen = traceChoice ?? (task.trace?.length ?? 0) > 0;
  const traceCount = task.trace?.length ?? 0;
  const comments = task.comments ?? [];
  const project = projects.find((p) => p.id === task.projectId);
  const projectCode = project?.key || project?.name || task.identifier?.split('-')[0] || '';
  const code = task.identifier || task.id.slice(0, 8);
  const assignee = assignedAgents[0];
  const agentName = (id: string) => {
    const m = mariuses.find((x) => x.id === id);
    return m ? m.displayName || m.name : undefined;
  };

  // Who is in this thread: every agent that spoke in it, the assignee, and the patron, who
  // owns the task whether or not they have said anything yet.
  const isPatronId = (id: string) => id === 'user-patron' || id === currentUser?.id;
  const participantIds = Array.from(
    new Set([
      ...(task.assigneeId ? [task.assigneeId] : []),
      ...comments.map((c) => c.authorId).filter((id) => !isPatronId(id) && !id.startsWith('system')),
    ]),
  );
  const participantCount = participantIds.length + 1;

  return (
    <div className="mx-auto w-full max-w-[1480px]">
      <Link
        to={wsHref(workspaceId, `/projects/${task.projectId}`)}
        className="mb-4 inline-flex min-h-[44px] items-center gap-2 font-body text-[15px] text-ink hover:text-sapphire-strong transition-colors"
      >
        <ArrowLeft className="h-[18px] w-[18px]" />
        {t('collaborationRoom.backToProjectBoard', { code: projectCode })}
      </Link>

      {/* Summary first and the thread beside it on a wide screen; stacked below xl as
          summary → thread → the rest of the working context, so a narrow reader learns
          which task this is before reading the conversation about it. */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.16fr)_minmax(370px,0.84fr)] xl:grid-rows-[auto_1fr] xl:gap-5">
        {/* ─── Task summary ─── */}
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.3 }}
          aria-label={task.title}
          className="surface min-w-0 px-5 py-5 sm:px-6 sm:py-6 xl:col-start-2 xl:row-start-1"
        >
          <div className="flex items-center justify-between gap-3">
            <span className="task-code">{code}</span>
            <div className="flex items-center gap-3">
              <span
                className={cn(
                  'inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.08em]',
                  PRIORITY_TONE[task.priority] ?? 'text-ink-muted'
                )}
              >
                <Flag className="h-3.5 w-3.5" />
                {t(`tasks.priority.${task.priority}`)}
              </span>
              {editDraft === null && (
                <button onClick={openEditor} className="btn-text min-h-[32px] text-[12px]">
                  <Pencil className="h-3.5 w-3.5" />
                  {t('collaborationRoom.context.edit.open')}
                </button>
              )}
            </div>
          </div>

          {/* Reading and editing happen in the same place (FR-070, FR-070a). */}
          {editDraft !== null ? (
            <div className="mt-4 space-y-3">
              <input
                value={editDraft.title}
                onChange={(e) => setEditDraft({ ...editDraft, title: e.target.value })}
                placeholder={t('collaborationRoom.context.edit.titlePlaceholder')}
                aria-label={t('collaborationRoom.context.edit.titlePlaceholder')}
                className="field font-display text-[20px]"
              />
              <textarea
                value={editDraft.description}
                onChange={(e) => setEditDraft({ ...editDraft, description: e.target.value })}
                rows={4}
                placeholder={t('collaborationRoom.context.edit.descriptionPlaceholder')}
                aria-label={t('collaborationRoom.context.edit.descriptionPlaceholder')}
                className="field resize-y py-2.5"
              />
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="block min-w-0">
                  <span className="mb-1.5 block font-body text-[12px] font-medium text-ink-light">
                    {t('collaborationRoom.context.edit.priority')}
                  </span>
                  <Dropdown
                    size="sm"
                    value={editDraft.priority}
                    onChange={(value) => setEditDraft({ ...editDraft, priority: value as Priority })}
                    items={PRIORITY_OPTIONS.map((p) => ({
                      value: p,
                      label: t(`tasks.priority.${p}`),
                    }))}
                  />
                </label>
                <label className="block min-w-0">
                  <span className="mb-1.5 block font-body text-[12px] font-medium text-ink-light">
                    {t('collaborationRoom.context.edit.dueDate')}
                  </span>
                  <input
                    type="date"
                    value={editDraft.dueDate}
                    onChange={(e) => setEditDraft({ ...editDraft, dueDate: e.target.value })}
                    className="field"
                  />
                </label>
              </div>
              {/* An empty due date removes it rather than skipping it — said plainly, since
                  this is exactly the button people hesitate over when unsure what happens. */}
              <p className="font-body text-[12px] leading-relaxed text-ink-muted">
                {t('collaborationRoom.context.edit.hint')}
              </p>
              {editError && <p className="font-body text-[12px] text-danger" role="alert">{editError}</p>}
              <div className="flex flex-wrap gap-2">
                <button disabled={saving} onClick={() => void handleSaveEdit()} className="btn btn-primary btn-sm">
                  {t('common.save')}
                </button>
                <button
                  disabled={saving}
                  onClick={() => { setEditDraft(null); setEditError(null); }}
                  className="btn btn-secondary btn-sm"
                >
                  {t('common.cancel')}
                </button>
              </div>
            </div>
          ) : (
            <>
              <h1 className="mt-3.5 break-words font-display text-[28px] font-normal leading-[1.13] tracking-[-0.035em] text-ink-strong sm:text-[clamp(30px,2.5vw,39px)]">
                {task.title}
              </h1>
              {task.description && (
                <p className="mt-3 whitespace-pre-wrap break-words font-body text-[14px] leading-[1.75] text-ink-light">
                  {task.description}
                </p>
              )}
            </>
          )}

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-b border-line pb-4">
            <StatusChip status={task.status} label={t('tasks.status.' + task.status)} size="md" />
            {task.dueDate && (
              <span
                className="inline-flex items-center gap-1.5 font-body text-[12px] text-ink-light"
                title={t('collaborationRoom.context.edit.dueDate')}
              >
                <CalendarDays className="h-4 w-4" />
                {new Date(task.dueDate).toLocaleDateString()}
              </span>
            )}
          </div>

          {/* The wait the status alone cannot say. *Todo* covers both "nobody has come for
              it" and "it is ready and every machine is busy", and the second one is not a
              fault — so it is stated quietly, with no clock (FR-008b, FR-008e). */}
          {waiting && (
            <p className="mt-3 flex items-center gap-1.5 font-body text-[12px] text-ink-muted">
              {waiting === WAITING_FOR_A_MACHINE ? (
                <Hourglass className="h-3.5 w-3.5 shrink-0" />
              ) : (
                <CircleDashed className="h-3.5 w-3.5 shrink-0" />
              )}
              {waitText(waiting, t)}
            </p>
          )}

          {/* Assignee (single owner per task) */}
          <div className="mt-4">
            {assignee ? (
              <button
                onClick={() => navigate(wsHref(workspaceId, `/agents/${assignee.id}`))}
                className="group flex w-full items-center gap-3 rounded-md border border-line bg-surface px-3 py-3 text-left transition-colors hover:border-sapphire hover:bg-surface-hover"
              >
                <AgentAvatar name={assignee.displayName || assignee.name} status={assignee.status} size="sm" />
                <span className="grid min-w-0 gap-0.5">
                  <small className="font-mono text-[8px] uppercase tracking-[0.1em] text-ink-muted">
                    {t('collaborationRoom.context.assigned')}
                  </small>
                  <strong className="truncate font-body text-[13px] font-semibold text-ink-strong group-hover:text-sapphire-strong">
                    {assignee.displayName || assignee.name}
                  </strong>
                </span>
                <span className="ml-auto truncate text-right font-body text-[11px] text-ink-muted">{assignee.role}</span>
              </button>
            ) : (
              <div className="flex items-center gap-3 rounded-md border border-dashed border-line-strong px-3 py-3">
                <span className="font-mono text-[8px] uppercase tracking-[0.1em] text-ink-muted">
                  {t('collaborationRoom.context.assigned')}
                </span>
                <span className="font-body text-[13px] text-ink-muted">{t('board.taskAssigneeNone')}</span>
              </div>
            )}
          </div>
        </motion.section>

        {/* ─── Thread ─── */}
        <motion.section
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.05 }}
          aria-label={t('collaborationRoom.thread.eyebrow', { code })}
          className={cn(
            'flex min-w-0 flex-col overflow-hidden rounded-lg border border-line-strong bg-surface',
            'h-[76dvh] min-h-[500px] md:h-[min(720px,82dvh)] md:min-h-[560px]',
            'xl:sticky xl:top-[90px] xl:col-start-1 xl:row-span-2 xl:row-start-1 xl:h-[calc(100dvh-184px)] xl:min-h-[600px] xl:self-start'
          )}
        >
          <header className="flex shrink-0 items-start justify-between gap-4 px-4 pb-4 pt-5 sm:px-6 sm:pb-5 sm:pt-6">
            <div className="min-w-0">
              <span className="eyebrow">{t('collaborationRoom.thread.eyebrow', { code })}</span>
              <h2 className="mt-1.5 font-display text-[26px] font-normal leading-[1.12] tracking-[-0.025em] text-ink-strong sm:text-[clamp(28px,2.4vw,37px)]">
                {t('collaborationRoom.thread.title')}
              </h2>
              <p className="mt-1.5 hidden font-body text-[12px] text-ink-light sm:block">
                {t('collaborationRoom.thread.subtitle')}
              </p>
            </div>
            <div className="grid shrink-0 justify-items-end gap-2">
              <div className="flex pl-2">
                {participantIds.slice(0, 3).map((id) => (
                  <AgentAvatar
                    key={id}
                    name={agentName(id) || '?'}
                    size="sm"
                    className="-ml-2 ring-2 ring-surface"
                  />
                ))}
                <PatronMark className="-ml-2 ring-2 ring-surface" />
              </div>
              <span className="inline-flex items-center gap-1 whitespace-nowrap font-body text-[10px] text-ink-muted">
                <Users className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">{t('collaborationRoom.participants', { count: participantCount })}</span>
                <span className="sm:hidden">{participantCount}</span>
              </span>
            </div>
          </header>

          <div className="mx-4 flex shrink-0 items-center gap-3 border-y border-line py-2.5 font-mono text-[9px] text-ink-muted sm:mx-6">
            <span className="inline-flex items-center gap-1.5 uppercase tracking-[0.09em]">
              <i className="h-[5px] w-[5px] rounded-full bg-success shadow-[0_0_0_3px_oklch(var(--success)/0.12)]" />
              {t('collaborationRoom.thread.open')}
            </span>
            <strong className="font-medium text-sapphire-strong">{code}</strong>
            <small className="ml-auto text-[9px]">{t('collaborationRoom.thread.comments', { count: comments.length })}</small>
          </div>

          {/* Approval Bar (when in_review) */}
          <AnimatePresence>
            {statusValue === 'in_review' && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="shrink-0 overflow-hidden"
              >
                <div className="mx-4 mt-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-gold/35 bg-gold-soft px-4 py-3 sm:mx-6">
                  {/* A notice, not a second set of buttons. This bar used to carry its own
                      Approve and Request-changes, which moved the status directly — a door
                      the server refuses, since *done* takes two signatures — beside the
                      real ones in the acceptance section. Two pairs, one of them dead. */}
                  <p className="font-body text-[13px] font-medium text-gold">
                    {t('collaborationRoom.approval.awaitingReview')}
                    <span className="font-normal">
                      {' · '}
                      {leaderSigned
                        ? t('collaborationRoom.acceptance.yourTurn')
                        : t('collaborationRoom.acceptance.waitingLeader')}
                    </span>
                  </p>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Messages */}
          <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4 pt-1 sm:px-6">
            {comments.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center px-3 py-10 text-center">
                <MessageSquare className="mb-3 h-8 w-8 text-ink-muted" strokeWidth={1.5} />
                <strong className="font-body text-[14px] font-semibold text-ink">{t('collaborationRoom.noComments')}</strong>
                <p className="mt-1.5 font-body text-[12px] text-ink-light">{t('collaborationRoom.startConversation')}</p>
              </div>
            ) : (
              comments.map((comment) => {
                const author = mariuses.find((m) => m.id === comment.authorId);
                return (
                  <TaskComment
                    key={comment.id}
                    // An agent's comment arrives without a name of its own; falling straight
                    // back to "Patron" put the patron's name on every agent's words.
                    authorName={
                      comment.authorName ??
                      (author ? author.displayName || author.name : t('collaborationRoom.patron'))
                    }
                    authorId={comment.authorId}
                    authorRole={author?.role || t('collaborationRoom.patron')}
                    content={comment.content}
                    timestamp={comment.timestamp}
                  />
                );
              })
            )}
            <div ref={threadEndRef} />
          </div>

          {/* Comment Composer */}
          <form
            className="shrink-0 border-t border-line-strong bg-surface-raised px-3 pb-4 pt-3.5 sm:px-6 sm:pb-5 sm:pt-4"
            onSubmit={(e) => {
              e.preventDefault();
              handleSendComment();
            }}
          >
            <label htmlFor="task-comment" className="mb-2 block font-body text-[12px] font-medium text-ink-light">
              {t('collaborationRoom.composer.label', { code })}
            </label>
            <textarea
              id="task-comment"
              value={commentInput}
              onChange={(e) => setCommentInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  handleSendComment();
                }
              }}
              placeholder={
                assignee
                  ? t('collaborationRoom.composer.placeholderAgent', { name: assignee.displayName || assignee.name })
                  : t('collaborationRoom.composer.placeholder')
              }
              rows={2}
              className="field min-h-[64px] resize-none py-2.5 sm:min-h-[82px]"
            />
            <div className="mt-2.5 flex items-center justify-between gap-3">
              <small className="hidden font-body text-[11px] leading-snug text-ink-muted sm:block">
                {t('collaborationRoom.composer.hint')}
              </small>
              <button
                type="submit"
                disabled={!commentInput.trim()}
                aria-label={t('collaborationRoom.composer.send')}
                className="btn btn-primary btn-sm ml-auto min-h-[40px]"
              >
                <Send className="h-4 w-4" />
                <span className="hidden sm:inline">{t('collaborationRoom.composer.send')}</span>
              </button>
            </div>
          </form>
        </motion.section>

        {/* ─── Working context ─── */}
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, delay: 0.1 }}
          className="flex min-w-0 flex-col gap-4 self-start xl:col-start-2 xl:row-start-2"
        >
          <div className="overflow-hidden rounded-lg border border-line bg-surface">
            {task.definitionOfDone && (
              <DocSection label={t('collaborationRoom.context.definitionOfDone')}>
                <p className="whitespace-pre-wrap break-words font-body text-[13px] leading-[1.75] text-ink-light">
                  {task.definitionOfDone}
                </p>
              </DocSection>
            )}

            {/* Why the task sits where it does — a block, a cancellation, a send-back. */}
            {task.statusReason && (
              <section
                className={cn(
                  'flex gap-3 border-b border-line px-5 py-4 sm:px-6',
                  task.status === 'blocked' ? 'bg-danger-soft text-danger' : 'text-ink-light'
                )}
              >
                {task.status === 'blocked' ? (
                  <Lock className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                ) : (
                  <CornerDownRight className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                )}
                <div className="min-w-0">
                  <strong className="block font-body text-[13px] font-semibold">
                    {t('collaborationRoom.context.statusReason')}
                  </strong>
                  <p className="mt-1 whitespace-pre-wrap break-words font-body text-[13px] leading-relaxed text-ink-light">
                    {task.statusReason}
                  </p>
                </div>
              </section>
            )}

            {/* Acceptance criteria (spec 001 FR-019) — the yardstick, replacing the old
                free-text "definition of done". Written before the worker starts; after
                that the server refuses an edit, because moving the bar mid-work is a
                scope change the patron has to decide on. */}
            <DocSection
              label={t('collaborationRoom.context.criteria')}
              aside={
                criteriaTotal > 0 && criteriaDraft === null ? (
                  <strong className="font-mono text-[12px] font-medium text-ink-strong">
                    {criteriaPassed}/{criteriaTotal}
                  </strong>
                ) : undefined
              }
            >
              {criteriaDraft !== null ? (
                <div className="space-y-2.5">
                  <textarea
                    value={criteriaDraft}
                    onChange={(e) => setCriteriaDraft(e.target.value)}
                    rows={5}
                    placeholder={t('collaborationRoom.context.criteriaPlaceholder')}
                    aria-label={t('collaborationRoom.context.criteria')}
                    className="field resize-y py-2.5"
                  />
                  <p className="font-body text-[12px] leading-relaxed text-ink-muted">
                    {t('collaborationRoom.context.criteriaHint')}
                  </p>
                  {criteriaError && <p className="font-body text-[12px] text-danger" role="alert">{criteriaError}</p>}
                  <div className="flex flex-wrap gap-2">
                    <button onClick={handleSaveCriteria} className="btn btn-primary btn-sm">
                      {t('common.save')}
                    </button>
                    <button
                      onClick={() => { setCriteriaDraft(null); setCriteriaError(null); }}
                      className="btn btn-secondary btn-sm"
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {criteriaTotal > 0 && (
                    <div className="mb-2 grid grid-cols-[1fr_auto] items-center gap-4">
                      <div className="h-1 overflow-hidden rounded-full bg-line">
                        <motion.div
                          className="h-full rounded-full bg-sapphire"
                          initial={{ width: 0 }}
                          animate={{ width: `${criteriaPercent}%` }}
                          transition={{ duration: 0.3 }}
                        />
                      </div>
                      <strong className="font-body text-[13px] font-semibold text-ink-strong">{criteriaPercent}%</strong>
                    </div>
                  )}
                  <ul>
                    {task.checklist?.map((item) => (
                      <li
                        key={item.id}
                        className={cn(
                          'flex gap-3 border-t border-line py-3 first:border-t-0',
                          item.result === 'passed'
                            ? 'text-success'
                            : item.result === 'failed'
                              ? 'text-danger'
                              : 'text-ink-muted'
                        )}
                      >
                        {item.result === 'passed' ? (
                          <ShieldCheck className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                        ) : item.result === 'failed' ? (
                          <XCircle className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                        ) : (
                          <ListChecks className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                        )}
                        <span className="min-w-0 break-words font-body text-[13px] font-medium leading-relaxed text-ink">
                          {item.text}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {criteriaTotal === 0 && (
                    <p className="font-body text-[13px] text-ink-muted">{t('collaborationRoom.context.criteriaEmpty')}</p>
                  )}
                  {criteriaEditable ? (
                    <button
                      onClick={() => setCriteriaDraft((task.checklist || []).map((c) => c.text).join('\n'))}
                      className="btn-text mt-1 min-h-[36px] text-[12px]"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                      {criteriaTotal === 0
                        ? t('collaborationRoom.context.criteriaSet')
                        : t('collaborationRoom.context.criteriaEdit')}
                    </button>
                  ) : (
                    <p className="mt-2 font-body text-[12px] leading-relaxed text-ink-muted">
                      {t('collaborationRoom.context.criteriaLocked')}
                    </p>
                  )}
                </>
              )}
            </DocSection>

            {/* Output acceptance (spec 001 FR-033) — right under the criteria and the
                artifacts, since those are the two things a signer must look at first. Shown
                only while the task is *in review*: earlier there is nothing to score, later
                the work is closed. */}
            {statusValue === 'in_review' && (
              <DocSection label={t('collaborationRoom.acceptance.title')} className="bg-gold-soft/50">
                <p className="font-body text-[13px] leading-relaxed text-ink">
                  {leaderSigned
                    ? t('collaborationRoom.acceptance.yourTurn')
                    : t('collaborationRoom.acceptance.waitingLeader')}
                </p>
                {approvals.length > 0 && (
                  <ul className="mt-3 space-y-1.5">
                    {approvals.map((a) => (
                      <li key={a.id} className="flex items-start gap-2 font-body text-[12px] text-ink-light">
                        {a.result === 'approve' ? (
                          <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0 text-success" />
                        ) : (
                          <XCircle className="mt-px h-3.5 w-3.5 shrink-0 text-danger" />
                        )}
                        <span className="min-w-0 break-words">
                          {t(`collaborationRoom.acceptance.signer.${a.signer_kind}`)} ·{' '}
                          {t(`collaborationRoom.acceptance.result.${a.result}`)}
                          {a.is_auto && ` · ${t('collaborationRoom.acceptance.auto')}`}
                          {a.reason && ` — ${a.reason}`}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
                {approvalError && <p className="mt-2 font-body text-[12px] text-danger" role="alert">{approvalError}</p>}
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    disabled={!leaderSigned || signing}
                    onClick={() => void handleSign(true)}
                    className="btn btn-primary btn-sm"
                  >
                    {t('collaborationRoom.acceptance.accept')}
                  </button>
                  <button
                    disabled={!leaderSigned || signing}
                    onClick={() => void handleSign(false)}
                    className="btn btn-secondary btn-sm"
                  >
                    {t('collaborationRoom.acceptance.sendBack')}
                  </button>
                </div>
              </DocSection>
            )}

            {/* Artifacts + the done gate they open */}
            <DocSection
              label={t('collaborationRoom.context.artifacts')}
              aside={<strong className="font-mono text-[12px] font-medium text-ink-strong">{task.artifacts?.length ?? 0}</strong>}
            >
              <div className="space-y-2">
                {/* Two kinds, two things to do with them. A link names something somewhere
                    else and opens where it points; a file's bytes live in the shared store
                    behind a door that needs this person's token, so it is fetched and saved
                    rather than linked to — an `<a href>` carries no header, which is why the
                    link on this row used to point at a store path that resolves to nothing. */}
                {withVersions(task.artifacts ?? []).map(({ artifact, version, of, current }) =>
                  artifact.type === 'link' ? (
                    <a
                      key={artifact.id}
                      href={artifact.url || '#'}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="group flex min-h-[44px] items-center gap-3 rounded-md border border-line bg-field px-3 py-2 transition-colors hover:border-sapphire"
                    >
                      <ExternalLink className="h-4 w-4 shrink-0 text-ink-muted group-hover:text-sapphire-strong" />
                      <span className="truncate font-body text-[13px] text-ink group-hover:text-sapphire-strong">
                        {artifact.name}
                      </span>
                    </a>
                  ) : (
                    <button
                      key={artifact.id}
                      type="button"
                      onClick={() => void saveArtifact(artifact)}
                      disabled={fetchingArtifact === artifact.id}
                      className="group flex min-h-[44px] w-full items-center gap-3 rounded-md border border-line bg-field px-3 py-2 text-left transition-colors hover:border-sapphire disabled:opacity-60"
                    >
                      <Paperclip className="h-4 w-4 shrink-0 text-ink-muted group-hover:text-sapphire-strong" />
                      <span
                        className={cn(
                          'min-w-0 flex-1 truncate font-body text-[13px] group-hover:text-sapphire-strong',
                          current ? 'text-ink' : 'text-ink-muted line-through decoration-line-strong',
                        )}
                      >
                        {artifact.name}
                      </span>
                      {/* The same name published twice is two versions of one file. Without
                          this nobody could tell which `script.js` was the corrected one. */}
                      {of > 1 && (
                        <span className="shrink-0 font-mono text-[11px] text-ink-muted">
                          {current
                            ? t('collaborationRoom.artifactVersionCurrent', { version, of })
                            : t('collaborationRoom.artifactVersionOld', { version, of })}
                        </span>
                      )}
                    </button>
                  )
                )}
                {artifactError && (
                  <p className="font-body text-[12px] text-danger" role="alert">
                    {artifactError}
                  </p>
                )}
                <button
                  onClick={() => setShowAddArtifactModal(true)}
                  className="btn btn-secondary btn-sm border-dashed"
                >
                  <Plus className="h-3.5 w-3.5" />
                  {t('collaborationRoom.context.addArtifact')}
                </button>
              </div>

              {/* DONE Gate */}
              <div
                className={cn(
                  'mt-4 flex items-start gap-3 rounded-md border px-4 py-3.5',
                  hasArtifacts
                    ? 'border-success/35 bg-success-soft text-success'
                    : 'border-danger/35 bg-danger-soft text-danger'
                )}
              >
                {hasArtifacts ? (
                  <Unlock className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                ) : (
                  <Lock className="mt-0.5 h-[18px] w-[18px] shrink-0" />
                )}
                <div className="min-w-0">
                  <p className="font-body text-[13px] font-semibold">
                    {hasArtifacts
                      ? t('collaborationRoom.context.doneGateUnblocked')
                      : t('collaborationRoom.context.doneGateBlocked')}
                  </p>
                  {!hasArtifacts && (
                    <p className="mt-1 font-body text-[12px] text-ink-light">
                      {t('collaborationRoom.context.statusRequiredArtifact')}
                    </p>
                  )}
                </div>
              </div>
            </DocSection>

            {/* Dependencies (blocked_by, #91) */}
            <DocSection label={t('collaborationRoom.context.dependencies')}>
              <div className="space-y-2">
                {dependencyTasks.map((dep) => (
                  <div
                    key={dep.id}
                    className="group flex min-h-[44px] items-center gap-2 rounded-md border border-line bg-field px-3 py-1.5"
                  >
                    <Link
                      to={wsHref(workspaceId, `/tasks/${dep.id}`)}
                      className="flex min-w-0 flex-1 items-center gap-2 text-left"
                    >
                      {dep.status === 'done' ? (
                        <Unlock className="h-3.5 w-3.5 shrink-0 text-success" />
                      ) : (
                        <Lock className="h-3.5 w-3.5 shrink-0 text-danger" />
                      )}
                      <span className="task-code shrink-0">{dep.identifier}</span>
                      <span className="truncate font-body text-[12px] text-ink-light group-hover:text-ink-strong">
                        {dep.title}
                      </span>
                    </Link>
                    <button
                      onClick={() => handleRemoveDependency(dep.id)}
                      title={t('collaborationRoom.context.removeDependency')}
                      aria-label={t('collaborationRoom.context.removeDependency')}
                      className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-ink-muted transition-all hover:bg-danger-soft hover:text-danger focus:opacity-100 xl:opacity-0 xl:group-hover:opacity-100"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
                {dependencyTasks.length === 0 && (
                  <p className="font-body text-[12px] text-ink-muted">{t('collaborationRoom.context.noDependencies')}</p>
                )}
                {candidateBlockers.length > 0 && (
                  <Dropdown
                    size="sm"
                    className="border-dashed"
                    value={depPicker}
                    onChange={(value) => {
                      setDepPicker(value);
                      if (value) handleAddDependency(value);
                    }}
                    placeholder={t('collaborationRoom.context.addDependency')}
                    items={candidateBlockers.map((c) => ({
                      value: c.id,
                      label: c.identifier ? `${c.identifier} — ${c.title}` : c.title,
                    }))}
                  />
                )}
                {depError && <p className="font-body text-[12px] text-danger" role="alert">{depError}</p>}
              </div>
            </DocSection>

            {/* Status update */}
            <DocSection label={t('collaborationRoom.statusLabel')} className="bg-canvas">
              <Dropdown
                size="sm"
                value={statusValue}
                onChange={handleStatusChange}
                ariaLabel={t('collaborationRoom.statusLabel')}
                items={STATUS_OPTIONS.map((s) => {
                  const why =
                    s === task.status
                      ? null
                      : blockedReasonKey(task.status as TaskPhase, s as TaskPhase, {
                          hasArtifact: hasArtifacts,
                          stalled: !!task.stalled,
                          depsSatisfied: !blockedByUnfinished,
                        });
                  return {
                    value: s,
                    label: t('tasks.status.' + s),
                    disabled: !!why,
                    hint: why ? t(why) : undefined,
                  };
                })}
              />
            </DocSection>
          </div>

          {/* ─── Live trace ─── */}
          {/* A drawer: it opens by itself only while there is a trace to read. */}
          <section className="overflow-hidden rounded-lg border border-line bg-surface">
            <button
              onClick={() => setTraceOpen(!traceOpen)}
              aria-expanded={traceOpen}
              className="flex min-h-[52px] w-full items-center gap-2.5 px-5 py-3 text-left transition-colors hover:bg-surface-hover sm:px-6"
            >
              <Activity className="h-4 w-4 shrink-0 text-sapphire-strong" />
              <span className="eyebrow">{t('collaborationRoom.liveTrace')}</span>
              {traceCount > 0 && (
                <span className="font-mono text-[11px] text-ink-muted">{t('runTrace.count', { count: traceCount })}</span>
              )}
              <ChevronDown
                className={cn('ml-auto h-4 w-4 shrink-0 text-ink-muted transition-transform', traceOpen && 'rotate-180')}
              />
            </button>
            {traceOpen && (
              <div className="max-h-[480px] overflow-y-auto border-t border-line px-4 py-4 sm:px-5">
                {traceCount === 0 ? (
                  <div className="flex flex-col items-center py-6 text-center">
                    <Activity className="mb-3 h-8 w-8 text-ink-muted" strokeWidth={1.5} />
                    <strong className="font-body text-[14px] font-semibold text-ink">{t('collaborationRoom.noTrace')}</strong>
                    <p className="mt-1 max-w-[260px] font-body text-[12px] text-ink-light">
                      {t('collaborationRoom.noTraceDescription')}
                    </p>
                  </div>
                ) : (
                  <ol>
                    {(task.trace ?? []).map((event, i) => (
                      <TraceEventCard key={event.id} event={event} last={i === traceCount - 1} />
                    ))}
                  </ol>
                )}
                <div ref={traceEndRef} />
              </div>
            )}
          </section>
        </motion.div>
      </div>

      {/* ─── Add Artifact Modal ─── */}
      <Modal
        isOpen={showAddArtifactModal}
        onClose={() => setShowAddArtifactModal(false)}
        title={t('collaborationRoom.context.addArtifact')}
        maxWidth="max-w-md"
      >
        <div className="mb-4 grid grid-cols-2 gap-1 rounded-md border border-line bg-canvas-deep p-1">
          {(['file', 'link'] as const).map((type) => (
            <button
              key={type}
              onClick={() => setArtifactForm((prev) => ({ ...prev, type }))}
              aria-pressed={artifactForm.type === type}
              className={cn(
                'min-h-[38px] rounded-[6px] px-3 font-body text-[13px] font-medium transition-colors',
                artifactForm.type === type
                  ? 'bg-surface text-ink-strong shadow-sm'
                  : 'text-ink-light hover:text-ink-strong'
              )}
            >
              {type === 'file' ? t('collaborationRoom.uploadFile') : t('collaborationRoom.addLink')}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          <label className="block">
            <span className="mb-1.5 block font-body text-[13px] font-medium text-ink">
              {t('collaborationRoom.artifactName')}
            </span>
            <input
              type="text"
              value={artifactForm.name}
              onChange={(e) => setArtifactForm((prev) => ({ ...prev, name: e.target.value }))}
              placeholder={
                artifactForm.type === 'file'
                  ? t('collaborationRoom.artifactNamePlaceholderFile')
                  : t('collaborationRoom.artifactNamePlaceholderLink')
              }
              className="field"
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block font-body text-[13px] font-medium text-ink">
              {artifactForm.type === 'file' ? t('collaborationRoom.filePathLabel') : t('collaborationRoom.urlLabel')}
            </span>
            <input
              type="text"
              value={artifactForm.url}
              onChange={(e) => setArtifactForm((prev) => ({ ...prev, url: e.target.value }))}
              placeholder={artifactForm.type === 'file' ? 'armarius/...' : 'https://...'}
              className="field font-mono text-[13px]"
            />
          </label>

          <button onClick={handleAddArtifact} disabled={!artifactForm.name.trim()} className="btn btn-primary w-full">
            {t('collaborationRoom.context.addArtifact')}
          </button>
        </div>
      </Modal>
    </div>
  );
}
