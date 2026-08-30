import { useState, useRef, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ChevronLeft,
  Send,
  CheckCircle2,
  Circle,
  Plus,
  X,
  Paperclip,
  ExternalLink,
  Lock,
  Unlock,
  Play,
  Pause,
  Square,
  RotateCcw,
  Activity,
  Bot,
  User,
  Star,
  MessageSquare,
  XCircle,
  Hourglass,
  CircleDashed,
} from 'lucide-react';
import { ApiError, listTaskApprovals, signTaskApproval, type ApprovalDTO } from '@/lib/api';
import {
  useAppStore,
  type Priority,
  type Task,
  type TaskEditPatch,
  type TraceEvent,
} from '@/store/appStore';
import { useTaskStream } from '@/hooks/use-task-stream';
import { subscribeProjectEvents } from '@/lib/sse';
import { cn, wsHref } from '@/lib/utils';
import { blockedReasonKey, needsReason, type TaskPhase } from '@/lib/taskRules';
import { errorText } from '@/lib/errors';
import { WAITING_FOR_A_MACHINE, waitKind, waitText } from '@/lib/drive';

/** Bốn trường người chủ sửa được trên màn, ở dạng chuỗi mà ô nhập dùng. */
interface TaskEditDraft {
  title: string
  description: string
  priority: Priority
  dueDate: string
}

/** Bốn mức ưu tiên, đúng bốn mức máy chủ có. */
const PRIORITY_OPTIONS: readonly Priority[] = ['P0', 'P1', 'P2', 'P3'];

// ─── Trace Event Type Colors ─────────────────────────────────────────────────

const TRACE_TYPE_COLORS: Record<string, { border: string; bg: string; label: string }> = {
  'run.delta': { border: 'border-l-gold', bg: 'bg-gold/10', label: 'text-gold' },
  'run.tool': { border: 'border-l-terracotta', bg: 'bg-terracotta/10', label: 'text-terracotta' },
  'run.usage': { border: 'border-l-status-online', bg: 'bg-status-online/10', label: 'text-status-online' },
  'run.complete': { border: 'border-l-success', bg: 'bg-success/10', label: 'text-success' },
  'run.error': { border: 'border-l-error', bg: 'bg-error/10', label: 'text-error' },
  'agent.comment': { border: 'border-l-vellum-dark', bg: 'bg-vellum-dark/10', label: 'text-ink-light' },
  'agent.status': { border: 'border-l-ink-muted', bg: 'bg-ink-muted/10', label: 'text-ink-muted' },
};

const STATUS_OPTIONS = ['draft', 'backlog', 'todo', 'in_progress', 'blocked', 'in_review', 'done', 'cancelled'] as const;

// ─── Helper: format timestamp ────────────────────────────────────────────────

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ─── Trace Event Card ────────────────────────────────────────────────────────

/** A safe i18n key segment: the daemon's codes are snake_case, and anything else is a code this
 *  screen has never heard of rather than a path into the phrase table. */
function segment(code: string): string {
  return /^[a-z0-9_]+$/.test(code) ? code : 'unknown';
}

function TraceEventCard({ event }: { event: TraceEvent }) {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);
  const colors = TRACE_TYPE_COLORS[event.type] || TRACE_TYPE_COLORS['run.delta'];

  // The daemon says what went wrong as a code with its details (Constitution VII); the sentence
  // is built here, where the reader's language is known. A code this build has no phrase for
  // still becomes a sentence — showing the raw key would put our own internals on their screen.
  const said = event.code
    ? t(`collaborationRoom.trace.error.${segment(event.code)}`, {
        defaultValue: t('collaborationRoom.trace.error.unknown', { code: event.code }),
        ...event.codeParams,
      })
    : '';
  const body = event.content || said;

  return (
    <motion.div
      initial={{ opacity: 0, y: -10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn(
        'border-l-[3px] rounded-sm bg-vellum-deep px-3 py-2 cursor-pointer hover:bg-vellum/50 transition-colors',
        colors.border
      )}
      onClick={() => setIsExpanded(!isExpanded)}
    >
      <div className="flex items-center justify-between mb-1">
        <span className={cn('font-mono text-mono-sm font-medium', colors.label)}>
          {event.type}
        </span>
        <span className="font-mono text-mono-sm text-ink-muted">
          {formatTime(event.timestamp)}
        </span>
      </div>

      {event.model && (
        <div className="font-mono text-mono-sm text-ink-light mb-1">
          model: {event.model}
        </div>
      )}

      {event.tokens && (
        <div className="font-mono text-mono-sm text-ink-light mb-1">
          tokens: {event.tokens.used} / {event.tokens.total}
          {event.tokens.prompt !== undefined && (
            <span className="text-ink-muted ml-1">
              (prompt: {event.tokens.prompt}, completion: {event.tokens.completion})
            </span>
          )}
        </div>
      )}

      {event.toolName && (
        <div className={cn('font-mono text-mono-sm rounded-sm px-2 py-0.5 mb-1 inline-block', colors.bg)}>
          {event.toolName}
        </div>
      )}

      {body && (
        <div
          className={cn(
            'font-body text-body-xs text-ink-light leading-relaxed',
            !isExpanded && 'line-clamp-3'
          )}
        >
          {body}
        </div>
      )}

      {/* Say what is missing and why, rather than leaving a gap (FR-047). A gap here reads as
          an agent that called no tools — a different and untrue story. */}
      {event.omission && (
        <div className="font-mono text-mono-sm text-ink-muted mt-1">
          {t(`collaborationRoom.trace.omission.${segment(event.omission.reason)}`, {
            defaultValue: t('collaborationRoom.trace.omission.unknown'),
          })}
          {event.omission.originalBytes !== undefined && (
            <span className="ml-1">
              {t('collaborationRoom.trace.omission.size', { bytes: event.omission.originalBytes })}
            </span>
          )}
        </div>
      )}

      {event.redacted && (
        <div className="font-mono text-mono-sm text-ink-muted mt-1">
          {t('collaborationRoom.trace.redacted')}
        </div>
      )}

      {event.args && isExpanded && (
        <pre className="mt-1.5 p-2 bg-vellum rounded-sm font-mono text-mono-sm text-ink-light overflow-x-auto">
          {JSON.stringify(event.args, null, 2)}
        </pre>
      )}
    </motion.div>
  );
}

// ─── Comment Bubble ──────────────────────────────────────────────────────────

function CommentBubble({
  authorName,
  authorId,
  authorRole,
  content,
  timestamp,
}: {
  authorName: string;
  authorId: string;
  authorRole: string;
  content: string;
  timestamp: string;
}) {
  const mariuses = useAppStore((s) => s.mariuses);
  const currentUser = useAppStore((s) => s.currentUser);
  const agent = mariuses.find((m) => m.id === authorId);
  const isPatron = authorId === 'user-patron' || authorId === currentUser?.id;
  const isSystem = authorId.startsWith('system');

  // Highlight @mentions
  const renderContent = (text: string) => {
    const parts = text.split(/(@\w+)/g);
    return parts.map((part, i) => {
      if (part.startsWith('@')) {
        return (
          <span key={i} className="bg-gold/20 px-1 rounded-sm font-medium">
            {part}
          </span>
        );
      }
      return part;
    });
  };

  if (isSystem) {
    return (
      <div className="flex items-center justify-center gap-3 my-3">
        <span className="w-10 h-px bg-vellum-dark" />
        <span className="font-body text-body-xs text-ink-muted italic">{content}</span>
        <span className="w-10 h-px bg-vellum-dark" />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 15 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn('flex gap-3 mb-4', isPatron && 'flex-row-reverse')}
    >
      {/* Avatar */}
      <div className="flex flex-col items-center gap-0.5 flex-shrink-0">
        <div
          className={cn(
            'rounded-full overflow-hidden border flex items-center justify-center',
            isPatron ? 'border-terracotta' : 'border-gold-muted'
          )}
          style={{ width: 28, height: 28 }}
        >
          {agent?.avatar ? (
            <img src={agent.avatar} alt={authorName} className="w-full h-full object-cover" />
          ) : (
            isPatron ? (
              <User className="w-3.5 h-3.5 text-terracotta" />
            ) : (
              <Bot className="w-3.5 h-3.5 text-gold" />
            )
          )}
        </div>
      </div>

      {/* Bubble */}
      <div className={cn('max-w-[85%]', isPatron && 'text-right')}>
        {/* Name label */}
        <div className={cn('flex items-center gap-1.5 mb-0.5', isPatron && 'justify-end')}>
          <span className="font-body text-body-xs text-ink-light">{authorName}</span>
          {!isPatron && (
            <span className="font-body text-body-xs text-ink-muted bg-vellum-deep px-1.5 py-0.5 rounded-sm">
              {authorRole}
            </span>
          )}
          <span className="font-mono text-mono-sm text-ink-muted">{formatTime(timestamp)}</span>
        </div>

        <div
          className={cn(
            'inline-block px-4 py-2.5 rounded-lg font-body text-body-md text-left',
            isPatron
              ? 'bg-terracotta text-white rounded-tr-sm'
              : 'bg-vellum-deep border border-vellum-dark rounded-tl-sm text-ink'
          )}
        >
          {renderContent(content)}
        </div>
      </div>
    </motion.div>
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
  useEffect(() => {
    if (!taskId) return;
    hydrateTask(taskId);
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
  const [isTraceActive, setIsTraceActive] = useState(true);
  const [showAddArtifactModal, setShowAddArtifactModal] = useState(false);
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
  const criteriaEditable = ['draft', 'backlog', 'todo'].includes(task?.status ?? '');

  // Auto-scroll
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [task?.comments?.length]);

  useEffect(() => {
    traceEndRef.current?.scrollIntoView({ behavior: 'smooth' });
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

  // ── Người chủ sửa thẳng đầu việc (FR-070, FR-070a) ─────────────────────────
  // Không có ô này thì người chủ gõ nhầm một hạn chót là phải huỷ đầu việc rồi tạo lại,
  // mất cả bình luận, thành phẩm và vết. Bản nháp là `null` khi không mở ô sửa.
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
      // Ô ngày của trình duyệt chỉ nhận "YYYY-MM-DD"; máy chủ gửi về cả giờ.
      dueDate: task.dueDate ? task.dueDate.slice(0, 10) : '',
    });
  };

  const handleSaveEdit = async () => {
    if (!task || !editDraft) return;
    setEditError(null);
    setSaving(true);
    try {
      // Chỉ gửi thứ thật sự đổi. Ô để trống là **xoá** cái đang có, nên nó gửi đi một giá
      // trị rỗng chứ không phải im lặng bỏ qua — đó là cách gỡ một hạn chót đặt nhầm.
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

  // ── Công nhận đầu ra (FR-033, FR-035) ──────────────────────────────────────
  const [approvals, setApprovals] = useState<ApprovalDTO[]>([]);
  const [approvalError, setApprovalError] = useState<string | null>(null);
  const [signing, setSigning] = useState(false);

  // Tải danh sách chữ ký bằng chuỗi lời hứa, không dùng `await` thẳng trong thân hiệu
  // ứng: đặt trạng thái đồng bộ ở đó kéo theo một vòng vẽ lại thừa mỗi lần đầu việc đổi.
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
        // Danh sách chữ ký chỉ để đọc; hỏng thì ô ký vẫn dùng được, không chặn cả trang.
        if (alive) setApprovals([]);
      });
    return () => {
      alive = false;
    };
  }, [signedTaskId, signedTaskStatus, approvalsKey]);

  /** Vòng hiện tại = số lần bị trả lại + 1; chữ ký vòng cũ không tính sang vòng mới. */
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

  const handleApprove = () => {
    if (!task) return;
    updateTask(task.id, { status: 'done' });
  };

  const handleRequestChanges = () => {
    if (!task) return;
    // Sending work back is *in_review → in_progress*, and it costs a reason: the worker
    // has to know what to fix (spec 001 FR-030).
    const answer = window.prompt(t('taskRules.reworkPrompt'));
    if (!answer || !answer.trim()) return;
    updateTask(task.id, { status: 'in_progress', statusReason: answer.trim() });
  };

  if (!task) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <Activity className="w-12 h-12 text-ink-muted mx-auto mb-4" />
          <h2 className="font-display text-display-md text-ink">{t('collaborationRoom.taskNotFound')}</h2>
          <button
            onClick={() => navigate(-1)}
            className="mt-4 px-4 py-2 rounded-md bg-terracotta text-white font-body text-body-md hover:bg-terracotta-light transition-colors"
          >
            {t('collaborationRoom.goBack')}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100dvh-140px)] -m-6">
      {/* ─── Collapsed Header ─── */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        className="flex-shrink-0 flex items-center justify-between px-6 py-3 border-b border-vellum-dark bg-vellum/80 backdrop-blur-sm"
      >
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(wsHref(workspaceId, `/projects/${task.projectId}`))}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-vellum-deep border border-vellum-dark font-body text-body-sm text-ink hover:bg-vellum-dark transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            {t('collaborationRoom.backToBoard')}
          </button>
          <span className="font-mono text-mono-md text-terracotta">{task.identifier}</span>
          <span className="text-ink-muted">&middot;</span>
          <span className="font-body text-body-sm text-ink-light truncate max-w-[200px]">
            {projects.find((p) => p.id === task.projectId)?.name}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-success-bg border border-success/20 font-body text-body-xs text-success animate-pulse-dot">
            <span className="w-1.5 h-1.5 rounded-full bg-success" />
            {t('collaborationRoom.live')}
          </span>
        </div>
      </motion.div>

      {/* ─── Three-Pane Layout ─── */}
      <div className="flex flex-1 min-h-0 px-6 py-4 gap-4">
        {/* ─── Left Pane: Context (30%) ─── */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4, delay: 0.1 }}
          className="flex-[30] flex flex-col min-h-0 bg-vellum-deep border border-vellum-dark rounded-md overflow-hidden"
        >
          <div className="flex-1 overflow-y-auto px-4 py-4 space-y-5">
            {/* Task Header — cùng chỗ đọc và chỗ sửa (FR-070, FR-070a). */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="font-mono text-mono-md text-terracotta">{task.identifier}</span>
                <span className={cn('inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full font-body text-body-xs font-medium', task.priority === 'P0' ? 'bg-terracotta/10 text-terracotta' : task.priority === 'P1' ? 'bg-gold/10 text-gold' : 'bg-ink-muted/10 text-ink-muted')}>
                  <Star className="w-3 h-3" fill="currentColor" />
                  {t(`tasks.priority.${task.priority}`)}
                </span>
              </div>

              {editDraft !== null ? (
                <div className="space-y-2">
                  <input
                    value={editDraft.title}
                    onChange={(e) => setEditDraft({ ...editDraft, title: e.target.value })}
                    placeholder={t('collaborationRoom.context.edit.titlePlaceholder')}
                    className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-sm font-body text-body-sm text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors"
                  />
                  <textarea
                    value={editDraft.description}
                    onChange={(e) => setEditDraft({ ...editDraft, description: e.target.value })}
                    rows={4}
                    placeholder={t('collaborationRoom.context.edit.descriptionPlaceholder')}
                    className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-sm font-body text-body-sm text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors resize-none"
                  />
                  <div className="flex gap-2">
                    <label className="flex-1">
                      <span className="block font-body text-body-xs text-ink-muted mb-1">
                        {t('collaborationRoom.context.edit.priority')}
                      </span>
                      <select
                        value={editDraft.priority}
                        onChange={(e) =>
                          setEditDraft({ ...editDraft, priority: e.target.value as Priority })
                        }
                        className="w-full px-2 py-1.5 bg-vellum border border-vellum-dark rounded-sm font-body text-body-sm text-ink focus:border-terracotta focus:outline-none cursor-pointer"
                      >
                        {PRIORITY_OPTIONS.map((p) => (
                          <option key={p} value={p}>
                            {t(`tasks.priority.${p}`)}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex-1">
                      <span className="block font-body text-body-xs text-ink-muted mb-1">
                        {t('collaborationRoom.context.edit.dueDate')}
                      </span>
                      <input
                        type="date"
                        value={editDraft.dueDate}
                        onChange={(e) => setEditDraft({ ...editDraft, dueDate: e.target.value })}
                        className="w-full px-2 py-1.5 bg-vellum border border-vellum-dark rounded-sm font-body text-body-sm text-ink focus:border-terracotta focus:outline-none"
                      />
                    </label>
                  </div>
                  {/* Ô hạn chót để trống là xoá hẳn, không phải bỏ qua — nói thẳng ra, vì
                      đây đúng là chỗ người ta ngại bấm nếu không chắc chuyện gì xảy ra. */}
                  <p className="font-body text-body-xs text-ink-muted">
                    {t('collaborationRoom.context.edit.hint')}
                  </p>
                  {editError && (
                    <p className="font-body text-body-xs text-error">{editError}</p>
                  )}
                  <div className="flex gap-2">
                    <button
                      disabled={saving}
                      onClick={() => void handleSaveEdit()}
                      className="px-3 py-1.5 rounded-md bg-gold text-ink font-body text-body-xs font-medium hover:bg-gold-light transition-colors disabled:opacity-50"
                    >
                      {t('common.save')}
                    </button>
                    <button
                      disabled={saving}
                      onClick={() => { setEditDraft(null); setEditError(null); }}
                      className="px-3 py-1.5 rounded-md border border-vellum-dark text-ink-light font-body text-body-xs hover:text-ink transition-colors disabled:opacity-50"
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  <h1 className="font-display text-display-sm text-ink leading-tight">
                    {task.title}
                  </h1>
                  {task.description && (
                    <p className="mt-1.5 font-body text-body-sm text-ink-light whitespace-pre-wrap">
                      {task.description}
                    </p>
                  )}
                  {task.dueDate && (
                    <p className="mt-1.5 font-body text-body-xs text-ink-muted">
                      {t('collaborationRoom.context.edit.dueDate')}:{' '}
                      {new Date(task.dueDate).toLocaleDateString()}
                    </p>
                  )}
                  <button
                    onClick={openEditor}
                    className="mt-2 font-body text-body-xs text-terracotta hover:underline"
                  >
                    {t('collaborationRoom.context.edit.open')}
                  </button>
                </>
              )}
            </div>

            {/* Status */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-1.5">
                {t('collaborationRoom.statusLabel')}
              </label>
              {/* The wait the status alone cannot say. *Todo* covers both "nobody has come
                  for it" and "it is ready and every machine is busy", and the second one is
                  not a fault — so it is stated quietly, with no clock (FR-008b, FR-008e). */}
              {waiting && (
                <div className="flex items-center gap-1.5 mb-1.5 text-ink-muted">
                  {waiting === WAITING_FOR_A_MACHINE ? (
                    <Hourglass className="w-3.5 h-3.5 flex-shrink-0" />
                  ) : (
                    <CircleDashed className="w-3.5 h-3.5 flex-shrink-0" />
                  )}
                  <span className="font-body text-body-xs">{waitText(waiting, t)}</span>
                </div>
              )}
              <select
                value={statusValue}
                onChange={(e) => handleStatusChange(e.target.value)}
                className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-sm text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors appearance-none cursor-pointer"
              >
                {STATUS_OPTIONS.map((s) => {
                  const why =
                    s === task.status
                      ? null
                      : blockedReasonKey(task.status as TaskPhase, s as TaskPhase, {
                          hasArtifact: hasArtifacts,
                          stalled: !!task.stalled,
                          depsSatisfied: !blockedByUnfinished,
                        });
                  return (
                    <option key={s} value={s} disabled={!!why}>
                      {t('tasks.status.' + s)}
                      {why ? ` — ${t(why)}` : ''}
                    </option>
                  );
                })}
              </select>
            </div>

            {/* Assignee (single owner per task) */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                {t('collaborationRoom.context.assigned')}
              </label>
              <div className="space-y-2">
                {assignedAgents.length === 0 && (
                  <span className="font-body text-body-sm text-ink-muted">{t('board.taskAssigneeNone')}</span>
                )}
                {assignedAgents.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-md bg-vellum border border-vellum-dark"
                  >
                    <div className="relative">
                      {p.avatar ? (
                        <img
                          src={p.avatar}
                          alt={p.displayName || p.name}
                          className="w-6 h-6 rounded-full object-cover"
                        />
                      ) : (
                        <div className="w-6 h-6 rounded-full bg-vellum-dark flex items-center justify-center font-body text-body-xs text-ink-muted">
                          {(p.displayName || p.name).charAt(0).toUpperCase()}
                        </div>
                      )}
                      <span className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border border-vellum"
                        style={{ backgroundColor: p.status === 'online' || p.status === 'working' ? '#4A9E6B' : '#8B7A6A' }}
                      />
                    </div>
                    <span className="font-body text-body-sm text-ink">{p.displayName || p.name}</span>
                    <span className="font-body text-body-xs text-ink-muted ml-auto">{p.role}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Acceptance criteria (spec 001 FR-019) — the yardstick, replacing the old
                free-text "definition of done". Written before the worker starts; after
                that the server refuses an edit, because moving the bar mid-work is a
                scope change the patron has to decide on. */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                {t('collaborationRoom.context.criteria')}
              </label>

              {criteriaDraft !== null ? (
                <div className="space-y-2">
                  <textarea
                    value={criteriaDraft}
                    onChange={(e) => setCriteriaDraft(e.target.value)}
                    rows={5}
                    placeholder={t('collaborationRoom.context.criteriaPlaceholder')}
                    className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-sm font-body text-body-sm text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors resize-none"
                  />
                  <p className="font-body text-body-xs text-ink-muted">
                    {t('collaborationRoom.context.criteriaHint')}
                  </p>
                  {criteriaError && (
                    <p className="font-body text-body-xs text-error">{criteriaError}</p>
                  )}
                  <div className="flex gap-2">
                    <button
                      onClick={handleSaveCriteria}
                      className="px-3 py-1.5 rounded-md bg-gold text-ink font-body text-body-xs font-medium hover:bg-gold-light transition-colors"
                    >
                      {t('common.save')}
                    </button>
                    <button
                      onClick={() => { setCriteriaDraft(null); setCriteriaError(null); }}
                      className="px-3 py-1.5 rounded-md border border-vellum-dark text-ink-light font-body text-body-xs hover:text-ink transition-colors"
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {criteriaTotal > 0 && (
                    <div className="flex items-center gap-2 mb-2">
                      <div className="flex-1 h-1.5 bg-vellum-dark rounded-full overflow-hidden">
                        <motion.div
                          className="h-full bg-success rounded-full"
                          initial={{ width: 0 }}
                          animate={{ width: `${(criteriaPassed / criteriaTotal) * 100}%` }}
                          transition={{ duration: 0.3 }}
                        />
                      </div>
                      <span className="font-mono text-mono-sm text-ink-light">
                        {criteriaPassed}/{criteriaTotal}
                      </span>
                    </div>
                  )}
                  <div className="space-y-1">
                    {task.checklist?.map((item) => (
                      <div key={item.id} className="flex items-start gap-2">
                        {item.result === 'passed' ? (
                          <CheckCircle2 className="w-4 h-4 text-success flex-shrink-0 mt-0.5" />
                        ) : item.result === 'failed' ? (
                          <XCircle className="w-4 h-4 text-error flex-shrink-0 mt-0.5" />
                        ) : (
                          <Circle className="w-4 h-4 text-ink-muted flex-shrink-0 mt-0.5" />
                        )}
                        <span className="font-body text-body-sm text-ink">{item.text}</span>
                      </div>
                    ))}
                    {criteriaTotal === 0 && (
                      <p className="font-body text-body-sm text-ink-muted">
                        {t('collaborationRoom.context.criteriaEmpty')}
                      </p>
                    )}
                  </div>
                  {criteriaEditable ? (
                    <button
                      onClick={() => setCriteriaDraft((task.checklist || []).map((c) => c.text).join('\n'))}
                      className="mt-2 font-body text-body-xs text-terracotta hover:underline"
                    >
                      {criteriaTotal === 0
                        ? t('collaborationRoom.context.criteriaSet')
                        : t('collaborationRoom.context.criteriaEdit')}
                    </button>
                  ) : (
                    <p className="mt-2 font-body text-body-xs text-ink-muted">
                      {t('collaborationRoom.context.criteriaLocked')}
                    </p>
                  )}
                </>
              )}
            </div>

            {/* Công nhận đầu ra (spec 001 FR-033) — đặt ngay dưới bộ tiêu chí và thành
                phẩm, vì đó chính là hai thứ người ký phải nhìn trước khi ký. Ô này chỉ
                hiện khi đầu việc đang *chờ rà soát*: ký sớm hơn thì chưa có gì để chấm,
                ký muộn hơn thì việc đã đóng. */}
            {statusValue === 'in_review' && (
              <div>
                <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                  {t('collaborationRoom.acceptance.title')}
                </label>
                <p className="font-body text-body-xs text-ink-muted mb-2">
                  {leaderSigned
                    ? t('collaborationRoom.acceptance.yourTurn')
                    : t('collaborationRoom.acceptance.waitingLeader')}
                </p>
                {approvals.length > 0 && (
                  <ul className="space-y-1 mb-2">
                    {approvals.map((a) => (
                      <li key={a.id} className="font-body text-body-xs text-ink-light">
                        {t(`collaborationRoom.acceptance.signer.${a.signer_kind}`)} ·{' '}
                        {t(`collaborationRoom.acceptance.result.${a.result}`)}
                        {a.is_auto && ` · ${t('collaborationRoom.acceptance.auto')}`}
                        {a.reason && ` — ${a.reason}`}
                      </li>
                    ))}
                  </ul>
                )}
                {approvalError && (
                  <p className="font-body text-body-xs text-error mb-2">{approvalError}</p>
                )}
                <div className="flex gap-2">
                  <button
                    disabled={!leaderSigned || signing}
                    onClick={() => void handleSign(true)}
                    className="px-3 py-1.5 rounded-md bg-gold text-white font-body text-body-xs disabled:opacity-50"
                  >
                    {t('collaborationRoom.acceptance.accept')}
                  </button>
                  <button
                    disabled={!leaderSigned || signing}
                    onClick={() => void handleSign(false)}
                    className="px-3 py-1.5 rounded-md bg-vellum-dark text-ink font-body text-body-xs disabled:opacity-50"
                  >
                    {t('collaborationRoom.acceptance.sendBack')}
                  </button>
                </div>
              </div>
            )}

            {/* Dependencies (blocked_by, #91) */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                {t('collaborationRoom.context.dependencies')}
              </label>
              <div className="space-y-1.5">
                {dependencyTasks.map((dep) => (
                  <div
                    key={dep.id}
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-vellum border border-vellum-dark group"
                  >
                    <button
                      onClick={() => navigate(wsHref(workspaceId, `/tasks/${dep.id}`))}
                      className="flex items-center gap-2 flex-1 min-w-0 text-left hover:text-terracotta transition-colors"
                    >
                      {dep.status === 'done' ? (
                        <Unlock className="w-3.5 h-3.5 text-success flex-shrink-0" />
                      ) : (
                        <Lock className="w-3.5 h-3.5 text-error flex-shrink-0" />
                      )}
                      <span className="font-mono text-mono-sm text-terracotta">{dep.identifier}</span>
                      <span className="font-body text-body-xs text-ink-light truncate">{dep.title}</span>
                    </button>
                    <button
                      onClick={() => handleRemoveDependency(dep.id)}
                      title={t('collaborationRoom.context.removeDependency')}
                      className="opacity-0 group-hover:opacity-100 text-ink-muted hover:text-error transition-all flex-shrink-0"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </div>
                ))}
                {dependencyTasks.length === 0 && (
                  <p className="font-body text-body-xs text-ink-muted">
                    {t('collaborationRoom.context.noDependencies')}
                  </p>
                )}
                {candidateBlockers.length > 0 && (
                  <select
                    value={depPicker}
                    onChange={(e) => {
                      setDepPicker(e.target.value);
                      if (e.target.value) handleAddDependency(e.target.value);
                    }}
                    className="w-full px-2.5 py-1.5 rounded-md border border-dashed border-vellum-dark bg-vellum font-body text-body-xs text-ink-muted focus:border-terracotta focus:outline-none"
                  >
                    <option value="">{t('collaborationRoom.context.addDependency')}</option>
                    {candidateBlockers.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.identifier ? `${c.identifier} — ${c.title}` : c.title}
                      </option>
                    ))}
                  </select>
                )}
                {depError && (
                  <p className="font-body text-body-xs text-error">{depError}</p>
                )}
              </div>
            </div>

            {/* Artifacts */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                {t('collaborationRoom.context.artifacts')}
              </label>
              <div className="space-y-1.5">
                {(task.artifacts ?? []).map((artifact) => (
                  <a
                    key={artifact.id}
                    href={artifact.url || '#'}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-2 px-2.5 py-1.5 rounded-md bg-vellum border border-vellum-dark hover:border-terracotta hover:text-terracotta transition-colors group"
                  >
                    {artifact.type === 'file' ? (
                      <Paperclip className="w-3.5 h-3.5 text-ink-muted group-hover:text-terracotta" />
                    ) : (
                      <ExternalLink className="w-3.5 h-3.5 text-ink-muted group-hover:text-terracotta" />
                    )}
                    <span className="font-body text-body-sm text-ink group-hover:text-terracotta truncate">
                      {artifact.name}
                    </span>
                  </a>
                ))}
                <button
                  onClick={() => setShowAddArtifactModal(true)}
                  className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md border border-dashed border-vellum-dark hover:border-terracotta hover:bg-terracotta/5 font-body text-body-xs text-ink-muted hover:text-terracotta transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                  {t('collaborationRoom.context.addArtifact')}
                </button>
              </div>
            </div>

            {/* DONE Gate */}
            <div
              className={cn(
                'rounded-md border-l-4 px-3 py-3',
                hasArtifacts
                  ? 'bg-success-bg border-l-success'
                  : 'bg-error-bg border-l-error'
              )}
            >
              <div className="flex items-start gap-2">
                {hasArtifacts ? (
                  <Unlock className="w-4 h-4 text-success flex-shrink-0 mt-0.5" />
                ) : (
                  <Lock className="w-4 h-4 text-error flex-shrink-0 mt-0.5" />
                )}
                <div>
                  <p className={cn('font-body text-body-sm font-medium', hasArtifacts ? 'text-success' : 'text-error')}>
                    {hasArtifacts
                      ? t('collaborationRoom.context.doneGateUnblocked')
                      : t('collaborationRoom.context.doneGateBlocked')}
                  </p>
                  {!hasArtifacts && (
                    <p className="font-body text-body-xs text-error/70 mt-0.5">
                      {t('collaborationRoom.context.statusRequiredArtifact')}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </motion.div>

        {/* ─── Center Pane: Thread (40%) ─── */}
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, delay: 0.15 }}
          className="flex-[40] flex flex-col min-h-0 bg-vellum border border-vellum-dark rounded-md overflow-hidden"
        >
          {/* Thread Header */}
          <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-vellum-dark">
            <div>
              <h2 className="font-display text-display-sm text-ink">{t('collaborationRoom.threadTitle')}</h2>
              <span className="font-body text-body-xs text-ink-muted">
                {t('collaborationRoom.participants', { count: assignedAgents.length + 1 })}
              </span>
            </div>
          </div>

          {/* Approval Bar (when in_review) */}
          <AnimatePresence>
            {statusValue === 'in_review' && (
              <motion.div
                initial={{ height: 0, opacity: 0 }}
                animate={{ height: 'auto', opacity: 1 }}
                exit={{ height: 0, opacity: 0 }}
                className="flex-shrink-0 overflow-hidden"
              >
                <div className="bg-warning-bg border-b border-warning/20 px-4 py-3">
                  <p className="font-body text-body-sm text-warning font-medium mb-2">
                    {t('collaborationRoom.approval.awaitingReview')}
                  </p>
                  <div className="flex gap-2">
                    <button
                      onClick={handleApprove}
                      className="px-4 py-1.5 rounded-md bg-gold text-ink font-body text-body-sm font-medium hover:bg-gold-light transition-colors"
                    >
                      {t('collaborationRoom.approval.approve')}
                    </button>
                    <button
                      onClick={handleRequestChanges}
                      className="px-4 py-1.5 rounded-md border border-vellum-dark bg-vellum-deep font-body text-body-sm text-ink hover:bg-vellum-dark transition-colors"
                    >
                      {t('collaborationRoom.approval.requestChanges')}
                    </button>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {(task.comments?.length ?? 0) === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <MessageSquare className="w-10 h-10 text-ink-muted mb-3" strokeWidth={1.5} />
                <p className="font-body text-body-md text-ink-light">{t('collaborationRoom.noComments')}</p>
                <p className="font-body text-body-sm text-ink-muted">{t('collaborationRoom.startConversation')}</p>
              </div>
            ) : (
              (task.comments ?? []).map((comment) => (
                <CommentBubble
                  key={comment.id}
                  authorName={comment.authorName ?? t('collaborationRoom.patron')}
                  authorId={comment.authorId}
                  authorRole={
                    mariuses.find((m) => m.id === comment.authorId)?.role || t('collaborationRoom.patron')
                  }
                  content={comment.content}
                  timestamp={comment.timestamp}
                />
              ))
            )}
            <div ref={threadEndRef} />
          </div>

          {/* Comment Composer */}
          <div className="flex-shrink-0 border-t border-vellum-dark bg-vellum-deep px-4 py-3">
            <div className="flex items-end gap-2">
              <textarea
                value={commentInput}
                onChange={(e) => setCommentInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    handleSendComment();
                  }
                }}
                placeholder={t('collaborationRoom.composer.placeholder')}
                rows={1}
                className="flex-1 resize-none px-4 py-2.5 bg-vellum border border-vellum-dark rounded-lg font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors max-h-[120px]"
              />
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleSendComment}
                disabled={!commentInput.trim()}
                className={cn(
                  'w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 transition-colors',
                  commentInput.trim()
                    ? 'bg-terracotta text-white hover:bg-terracotta-light'
                    : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
                )}
              >
                <Send className="w-4 h-4" />
              </motion.button>
            </div>
          </div>
        </motion.div>

        {/* ─── Right Pane: Live Trace (30%) ─── */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4, delay: 0.2 }}
          className="flex-[30] flex flex-col min-h-0 bg-vellum-deep border border-vellum-dark rounded-md overflow-hidden"
        >
          {/* Trace Header */}
          <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-vellum-dark">
            <div className="flex items-center gap-2">
              <h2 className="font-display text-display-sm text-ink">{t('collaborationRoom.liveTrace')}</h2>
              <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full bg-success-bg border border-success/20 font-body text-body-xs text-success">
                <span className="w-1.5 h-1.5 rounded-full bg-success" />
                {isTraceActive ? t('collaborationRoom.traceRunning') : t('collaborationRoom.traceIdle')}
              </span>
            </div>
          </div>

          {/* Trace Stream */}
          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-2">
            {(task.trace?.length ?? 0) === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <Activity className="w-10 h-10 text-ink-muted mb-3" strokeWidth={1.5} />
                <p className="font-body text-body-md text-ink-light">{t('collaborationRoom.noTrace')}</p>
                <p className="font-body text-body-sm text-ink-muted max-w-[200px]">
                  {t('collaborationRoom.noTraceDescription')}
                </p>
              </div>
            ) : (
              <>
                {(task.trace ?? []).map((event) => (
                  <TraceEventCard key={event.id} event={event} />
                ))}
              </>
            )}
            <div ref={traceEndRef} />
          </div>

          {/* Wake Controls */}
          <div className="flex-shrink-0 border-t border-vellum-dark px-4 py-3">
            <div className="flex items-center justify-between">
              <span className="font-body text-body-xs text-ink-muted">{t('collaborationRoom.wakeControls.pause')}</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setIsTraceActive(!isTraceActive)}
                  className="p-1.5 rounded-md bg-vellum-dark hover:bg-vellum text-ink transition-colors"
                  title={isTraceActive ? t('collaborationRoom.wakeControls.pause') : t('collaborationRoom.wakeControls.resume')}
                >
                  {isTraceActive ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                </button>
                <button
                  onClick={() => setIsTraceActive(false)}
                  className="p-1.5 rounded-md bg-vellum-dark hover:bg-error/10 hover:text-error text-ink transition-colors"
                  title={t('collaborationRoom.wakeControls.stop')}
                >
                  <Square className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => setIsTraceActive(true)}
                  className="p-1.5 rounded-md bg-vellum-dark hover:bg-vellum text-ink transition-colors"
                  title={t('collaborationRoom.wakeControls.resume')}
                >
                  <RotateCcw className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>
          </div>
        </motion.div>
      </div>

      {/* ─── Add Artifact Modal ─── */}
      <AnimatePresence>
        {showAddArtifactModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-modal flex items-center justify-center p-4"
            onClick={() => setShowAddArtifactModal(false)}
          >
            <div className="absolute inset-0 bg-ink/50 backdrop-blur-sm" />
            <motion.div
              initial={{ opacity: 0, y: -8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.98 }}
              transition={{ duration: 0.25 }}
              className="relative bg-vellum-deep rounded-xl w-full max-w-md shadow-gilt-lg border border-vellum-dark p-6"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between mb-4">
                <h3 className="font-display text-display-md text-ink">
                  {t('collaborationRoom.context.addArtifact')}
                </h3>
                <button
                  onClick={() => setShowAddArtifactModal(false)}
                  className="p-1 rounded-md text-ink-muted hover:text-ink hover:bg-vellum-dark transition-colors"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* Tabs */}
              <div className="flex gap-2 mb-4">
                {(['file', 'link'] as const).map((type) => (
                  <button
                    key={type}
                    onClick={() => setArtifactForm((prev) => ({ ...prev, type }))}
                    className={cn(
                      'flex-1 px-3 py-2 rounded-md font-body text-body-sm font-medium transition-colors capitalize',
                      artifactForm.type === type
                        ? 'bg-terracotta text-white'
                        : 'bg-vellum text-ink border border-vellum-dark hover:bg-vellum-dark'
                    )}
                  >
                    {type === 'file' ? t('collaborationRoom.uploadFile') : t('collaborationRoom.addLink')}
                  </button>
                ))}
              </div>

              <div className="space-y-3">
                <div>
                  <label className="block font-body text-body-sm font-medium text-ink mb-1">
                    {t('collaborationRoom.artifactName')}
                  </label>
                  <input
                    type="text"
                    value={artifactForm.name}
                    onChange={(e) => setArtifactForm((prev) => ({ ...prev, name: e.target.value }))}
                    placeholder={artifactForm.type === 'file' ? t('collaborationRoom.artifactNamePlaceholderFile') : t('collaborationRoom.artifactNamePlaceholderLink')}
                    className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors"
                  />
                </div>

                <div>
                  <label className="block font-body text-body-sm font-medium text-ink mb-1">
                    {artifactForm.type === 'file' ? t('collaborationRoom.filePathLabel') : t('collaborationRoom.urlLabel')}
                  </label>
                  <input
                    type="text"
                    value={artifactForm.url}
                    onChange={(e) => setArtifactForm((prev) => ({ ...prev, url: e.target.value }))}
                    placeholder={artifactForm.type === 'file' ? 'armarius/...' : 'https://...'}
                    className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors"
                  />
                </div>

                <button
                  onClick={handleAddArtifact}
                  disabled={!artifactForm.name.trim()}
                  className={cn(
                    'w-full px-4 py-2.5 rounded-md font-body text-body-md font-medium transition-colors',
                    artifactForm.name.trim()
                      ? 'bg-terracotta text-white hover:bg-terracotta-light'
                      : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
                  )}
                >
                  {t('collaborationRoom.context.addArtifact')}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
