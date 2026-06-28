// @ts-nocheck
import { useState, useRef, useEffect, useCallback } from 'react';
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
} from 'lucide-react';
import { useMockStore, type TraceEvent, type Task } from '@/store/mockStore';
import { cn } from '@/lib/utils';

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

function TraceEventCard({ event }: { event: TraceEvent }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const colors = TRACE_TYPE_COLORS[event.type] || TRACE_TYPE_COLORS['run.delta'];

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

      {event.content && (
        <div
          className={cn(
            'font-body text-body-xs text-ink-light leading-relaxed',
            !isExpanded && 'line-clamp-3'
          )}
        >
          {event.content}
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
  const mariuses = useMockStore((s) => s.mariuses);
  const currentUser = useMockStore((s) => s.currentUser);
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
  const { id: taskId } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const store = useMockStore();
  const task = store.tasks.find((t) => t.id === taskId);

  const [commentInput, setCommentInput] = useState('');
  const [statusValue, setStatusValue] = useState<Task['status']>(task?.status ?? 'todo');
  const [isTraceActive, setIsTraceActive] = useState(true);
  const [showAddArtifactModal, setShowAddArtifactModal] = useState(false);
  const [artifactForm, setArtifactForm] = useState({ name: '', url: '', type: 'file' as 'file' | 'link' });
  const threadEndRef = useRef<HTMLDivElement>(null);
  const traceEndRef = useRef<HTMLDivElement>(null);

  // Get task participants with agent data
  const participants = store.mariuses.filter((m) => task?.participants.includes(m.id));
  const currentUser = store.currentUser;

  // Get dependency tasks
  const dependencyTasks = store.tasks.filter((t) => task?.dependencies.includes(t.id));

  // Check DONE gate
  const hasArtifacts = (task?.artifacts.length ?? 0) > 0;
  const checklistDone = task?.checklist.filter((c) => c.done).length ?? 0;
  const checklistTotal = task?.checklist.length ?? 0;

  // Auto-scroll
  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [task?.comments.length]);

  useEffect(() => {
    traceEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [task?.trace.length]);

  const handleStatusChange = useCallback((newStatus: string) => {
    if (!task) return;
    // DONE gate: block done/in_review without artifacts
    if ((newStatus === 'done' || newStatus === 'in_review') && !hasArtifacts) {
      return;
    }
    setStatusValue(newStatus as Task['status']);
    store.updateTask(task.id, { status: newStatus as Task['status'] });
  }, [task, hasArtifacts, store]);

  const handleSendComment = useCallback(() => {
    if (!commentInput.trim() || !task) return;
    store.addComment(task.id, {
      authorId: currentUser?.id || 'user-patron',
      authorName: currentUser?.name || 'Patron',
      content: commentInput.trim(),
    });
    setCommentInput('');
  }, [commentInput, task, store, currentUser]);

  const handleChecklistToggle = useCallback((checkId: string) => {
    if (!task) return;
    const newChecklist = task.checklist.map((c) =>
      c.id === checkId ? { ...c, done: !c.done } : c
    );
    store.updateTask(task.id, { checklist: newChecklist });
  }, [task, store]);

  const handleAddArtifact = useCallback(() => {
    if (!task || !artifactForm.name.trim()) return;
    store.publishArtifact(task.id, {
      type: artifactForm.type,
      name: artifactForm.name.trim(),
      url: artifactForm.url.trim() || undefined,
      content: artifactForm.type === 'file' ? 'file-content-placeholder' : undefined,
      createdBy: 'patron',
    });
    setArtifactForm({ name: '', url: '', type: 'file' });
    setShowAddArtifactModal(false);
  }, [task, artifactForm, store]);

  const handleApprove = useCallback(() => {
    if (!task) return;
    store.updateTask(task.id, { status: 'done' });
    setStatusValue('done');
  }, [task, store]);

  const handleRequestChanges = useCallback(() => {
    if (!task) return;
    store.updateTask(task.id, { status: 'todo' });
    setStatusValue('todo');
  }, [task, store]);

  if (!task) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <Activity className="w-12 h-12 text-ink-muted mx-auto mb-4" />
          <h2 className="font-display text-display-md text-ink">Task not found</h2>
          <button
            onClick={() => navigate(-1)}
            className="mt-4 px-4 py-2 rounded-md bg-terracotta text-white font-body text-body-md hover:bg-terracotta-light transition-colors"
          >
            Go Back
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
            onClick={() => navigate(`/projects/${task.projectId}`)}
            className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-vellum-deep border border-vellum-dark font-body text-body-sm text-ink hover:bg-vellum-dark transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
            {t('collaborationRoom.backToBoard')}
          </button>
          <span className="font-mono text-mono-md text-terracotta">{task.identifier}</span>
          <span className="text-ink-muted">&middot;</span>
          <span className="font-body text-body-sm text-ink-light truncate max-w-[200px]">
            {store.projects.find((p) => p.id === task.projectId)?.name}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-success-bg border border-success/20 font-body text-body-xs text-success animate-pulse-dot">
            <span className="w-1.5 h-1.5 rounded-full bg-success" />
            LIVE
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
            {/* Task Header */}
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="font-mono text-mono-md text-terracotta">{task.identifier}</span>
                <span className={cn('inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full font-body text-body-xs font-medium', task.priority === 'P0' ? 'bg-terracotta/10 text-terracotta' : task.priority === 'P1' ? 'bg-gold/10 text-gold' : 'bg-ink-muted/10 text-ink-muted')}>
                  <Star className="w-3 h-3" fill="currentColor" />
                  {task.priority}
                </span>
              </div>
              <h1 className="font-display text-display-sm text-ink leading-tight">
                {task.title}
              </h1>
            </div>

            {/* Status */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-1.5">
                Status
              </label>
              <select
                value={statusValue}
                onChange={(e) => handleStatusChange(e.target.value)}
                className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-sm text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors appearance-none cursor-pointer"
              >
                {STATUS_OPTIONS.map((s) => (
                  <option key={s} value={s} disabled={(s === 'done' || s === 'in_review') && !hasArtifacts}>
                    {s.replace(/_/g, ' ')}
                    {(s === 'done' || s === 'in_review') && !hasArtifacts ? ' (needs artifact)' : ''}
                  </option>
                ))}
              </select>
            </div>

            {/* Participants */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                {t('collaborationRoom.context.assigned')}
              </label>
              <div className="space-y-2">
                {participants.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-2.5 px-2.5 py-1.5 rounded-md bg-vellum border border-vellum-dark"
                  >
                    <div className="relative">
                      <img
                        src={p.avatar}
                        alt={p.displayName}
                        className="w-6 h-6 rounded-full object-cover"
                      />
                      <span className="absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border border-vellum"
                        style={{ backgroundColor: p.status === 'online' || p.status === 'working' ? '#4A9E6B' : '#8B7A6A' }}
                      />
                    </div>
                    <span className="font-body text-body-sm text-ink">{p.displayName}</span>
                    <span className="font-body text-body-xs text-ink-muted ml-auto">{p.role}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Definition of Done */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-1.5">
                {t('collaborationRoom.context.definitionOfDone')}
              </label>
              <textarea
                value={task.definitionOfDone}
                onChange={(e) => store.updateTask(task.id, { definitionOfDone: e.target.value })}
                rows={3}
                className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-sm font-body text-body-sm text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors resize-none"
              />
            </div>

            {/* Checklist */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                {t('collaborationRoom.context.checklist')}
              </label>
              <div className="flex items-center gap-2 mb-2">
                <div className="flex-1 h-1.5 bg-vellum-dark rounded-full overflow-hidden">
                  <motion.div
                    className="h-full bg-success rounded-full"
                    initial={{ width: 0 }}
                    animate={{ width: checklistTotal > 0 ? `${(checklistDone / checklistTotal) * 100}%` : '0%' }}
                    transition={{ duration: 0.3 }}
                  />
                </div>
                <span className="font-mono text-mono-sm text-ink-light">
                  {checklistDone}/{checklistTotal}
                </span>
              </div>
              <div className="space-y-1">
                {task.checklist.map((item) => (
                  <button
                    key={item.id}
                    onClick={() => handleChecklistToggle(item.id)}
                    className="flex items-center gap-2 w-full text-left group"
                  >
                    {item.done ? (
                      <CheckCircle2 className="w-4 h-4 text-success flex-shrink-0" />
                    ) : (
                      <Circle className="w-4 h-4 text-ink-muted group-hover:text-terracotta transition-colors flex-shrink-0" />
                    )}
                    <span className={cn('font-body text-body-sm', item.done && 'line-through text-ink-muted')}>
                      {item.text}
                    </span>
                  </button>
                ))}
              </div>
            </div>

            {/* Dependencies */}
            {dependencyTasks.length > 0 && (
              <div>
                <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                  {t('collaborationRoom.context.dependencies')}
                </label>
                <div className="space-y-1.5">
                  {dependencyTasks.map((dep) => (
                    <button
                      key={dep.id}
                      onClick={() => navigate(`/tasks/${dep.id}`)}
                      className="flex items-center gap-2 w-full text-left px-2.5 py-1.5 rounded-md bg-vellum border border-vellum-dark hover:border-gold-muted transition-colors"
                    >
                      <span className="font-mono text-mono-sm text-terracotta">{dep.identifier}</span>
                      <span className="font-body text-body-xs text-ink-light truncate">{dep.title}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Artifacts */}
            <div>
              <label className="block font-body text-body-xs font-semibold text-ink-light uppercase tracking-wider mb-2">
                {t('collaborationRoom.context.artifacts')}
              </label>
              <div className="space-y-1.5">
                {task.artifacts.map((artifact) => (
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
                {t('collaborationRoom.participants', { count: participants.length + 1 })}
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
            {task.comments.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <MessageSquare className="w-10 h-10 text-ink-muted mb-3" strokeWidth={1.5} />
                <p className="font-body text-body-md text-ink-light">No comments yet</p>
                <p className="font-body text-body-sm text-ink-muted">Start the conversation</p>
              </div>
            ) : (
              task.comments.map((comment) => (
                <CommentBubble
                  key={comment.id}
                  authorName={comment.authorName}
                  authorId={comment.authorId}
                  authorRole={
                    store.mariuses.find((m) => m.id === comment.authorId)?.role || 'Patron'
                  }
                  content={comment.content}
                  timestamp={comment.createdAt}
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
            {task.trace.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-full text-center">
                <Activity className="w-10 h-10 text-ink-muted mb-3" strokeWidth={1.5} />
                <p className="font-body text-body-md text-ink-light">{t('collaborationRoom.noTrace')}</p>
                <p className="font-body text-body-sm text-ink-muted max-w-[200px]">
                  {t('collaborationRoom.noTraceDescription')}
                </p>
              </div>
            ) : (
              <>
                {task.trace.map((event) => (
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
                  title={isTraceActive ? 'Pause' : 'Resume'}
                >
                  {isTraceActive ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
                </button>
                <button
                  onClick={() => setIsTraceActive(false)}
                  className="p-1.5 rounded-md bg-vellum-dark hover:bg-error/10 hover:text-error text-ink transition-colors"
                  title="Stop"
                >
                  <Square className="w-3.5 h-3.5" />
                </button>
                <button
                  onClick={() => setIsTraceActive(true)}
                  className="p-1.5 rounded-md bg-vellum-dark hover:bg-vellum text-ink transition-colors"
                  title="Resume"
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
                    {type === 'file' ? 'Upload File' : 'Add Link'}
                  </button>
                ))}
              </div>

              <div className="space-y-3">
                <div>
                  <label className="block font-body text-body-sm font-medium text-ink mb-1">
                    Name
                  </label>
                  <input
                    type="text"
                    value={artifactForm.name}
                    onChange={(e) => setArtifactForm((prev) => ({ ...prev, name: e.target.value }))}
                    placeholder={artifactForm.type === 'file' ? 'e.g., dark-mode.css' : 'e.g., PR #128'}
                    className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors"
                  />
                </div>

                <div>
                  <label className="block font-body text-body-sm font-medium text-ink mb-1">
                    {artifactForm.type === 'file' ? 'File Path / Key' : 'URL'}
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
                  Add Artifact
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
