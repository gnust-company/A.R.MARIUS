// Chat with Leader (#82) — a project-level 1-1 conversation with the Leader agent.
// The reply streams straight back on the leader-chat SSE channel (no agent callback);
// input is locked while the Leader replies (turn-taking) and disabled when it is offline.
import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Send, Bot, Loader2, WifiOff, Plus, Check, X, ArrowLeft, Sparkles, Zap,
} from 'lucide-react';
import VellumPanel from '@/components/VellumPanel';
import PageTitle from '@/components/PageTitle';
import { cn, wsHref } from '@/lib/utils';
import * as api from '@/lib/api';
import { subscribeLeaderChat } from '@/lib/sse';

interface ChatMessage {
  role: 'patron' | 'leader';
  text: string;
}

function toMessages(transcript: Array<{ role: string; text: string }> | undefined): ChatMessage[] {
  return (transcript ?? []).map((t) => ({
    role: t.role === 'patron' ? 'patron' : 'leader',
    text: t.text,
  }));
}

export default function ChatWithLeader() {
  const { id: projectId, workspaceId } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [chat, setChat] = useState<api.LeaderChatDTO | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streaming, setStreaming] = useState('');
  const [state, setState] = useState<'idle' | 'thinking' | 'failed'>('idle');
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [proposed, setProposed] = useState<api.TaskDTO[]>([]);
  const [yoloBusy, setYoloBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const [showAddTask, setShowAddTask] = useState(false);
  const [taskForm, setTaskForm] = useState({
    title: '', description: '', assigneeId: '', priority: 'medium', dueDate: '', dod: '',
  });
  const [agents, setAgents] = useState<api.ProjectAgentDTO[]>([]);
  const [addingTask, setAddingTask] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);

  const leaderOnline = chat?.leader_online ?? false;
  const yolo = chat?.yolo_mode ?? false;
  const locked = !leaderOnline || state === 'thinking';

  const refreshProposed = useCallback(async () => {
    if (!projectId) return;
    try {
      setProposed(await api.listProposedTasks(projectId));
    } catch {
      /* non-fatal */
    }
  }, [projectId]);

  // Initial load: the conversation transcript (durable history) + any pending drafts.
  useEffect(() => {
    if (!projectId) return;
    let alive = true;
    (async () => {
      try {
        const dto = await api.getLeaderChat(projectId);
        if (!alive) return;
        setChat(dto);
        setMessages(toMessages(dto.transcript));
        setState((dto.state as 'idle' | 'thinking' | 'failed') ?? 'idle');
        await refreshProposed();
        // Load the seated agents for the add-task assignee dropdown (non-fatal).
        api.listProjectAgents(projectId).then(setAgents).catch(() => {});
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [projectId, refreshProposed]);

  // Live stream: the Leader's reply arrives as assistant.delta; chat.state marks the turn.
  useEffect(() => {
    if (!projectId) return;
    const disconnect = subscribeLeaderChat(projectId, ({ type, data }) => {
      if (type === 'assistant.delta' && typeof data.text === 'string') {
        setStreaming((s) => s + (data.text as string));
      } else if (type === 'leader.message' && typeof data.text === 'string') {
        setMessages((m) => [...m, { role: 'leader', text: data.text as string }]);
        setStreaming('');
      } else if (type === 'chat.state' && typeof data.state === 'string') {
        const next = data.state as 'idle' | 'thinking' | 'failed';
        setState(next);
        if (next !== 'thinking') {
          setStreaming('');
          refreshProposed(); // the Leader may have proposed a draft during its turn
          api.getLeaderChat(projectId).then(setChat).catch(() => {});
        }
        if (next === 'failed') setError(t('leaderChat.turnFailed'));
      }
    });
    return disconnect;
  }, [projectId, refreshProposed, t]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, streaming]);

  const handleSend = useCallback(async () => {
    const message = input.trim();
    if (!message || !projectId || locked) return;
    setError(null);
    setInput('');
    setMessages((m) => [...m, { role: 'patron', text: message }]);
    setState('thinking');
    try {
      const dto = await api.sendLeaderChatMessage(projectId, message);
      setChat(dto);
    } catch (e) {
      // Rejected (offline / turn in flight) → resync from the server, surface the detail.
      setError(e instanceof Error ? e.message : String(e));
      try {
        const dto = await api.getLeaderChat(projectId);
        setChat(dto);
        setMessages(toMessages(dto.transcript));
        setState((dto.state as 'idle' | 'thinking' | 'failed') ?? 'idle');
      } catch {
        setState('idle');
      }
    }
  }, [input, projectId, locked]);

  const toggleYolo = useCallback(async () => {
    if (!projectId || yoloBusy) return;
    setYoloBusy(true);
    try {
      const dto = await api.setYoloMode(projectId, !yolo);
      setChat(dto);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setYoloBusy(false);
    }
  }, [projectId, yolo, yoloBusy]);

  const decide = useCallback(async (taskId: string, approve: boolean) => {
    try {
      if (approve) await api.approveTask(taskId);
      else await api.rejectTask(taskId);
      setProposed((p) => p.filter((task) => task.id !== taskId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const submitTask = useCallback(async () => {
    const title = taskForm.title.trim();
    if (!title || !projectId || addingTask) return;
    setAddingTask(true);
    try {
      await api.createTask(projectId, {
        title,
        description: taskForm.description.trim() || undefined,
        priority: taskForm.priority || undefined,
        due_date: taskForm.dueDate ? new Date(taskForm.dueDate).toISOString() : undefined,
        definition_of_done: taskForm.dod.trim() || undefined,
        assigned_marius_id: taskForm.assigneeId || undefined,
      });
      setShowAddTask(false);
      setTaskForm({ title: '', description: '', assigneeId: '', priority: 'medium', dueDate: '', dod: '' });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setAddingTask(false);
    }
  }, [taskForm, projectId, addingTask]);

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-4">
        <button
          onClick={() => navigate(wsHref(workspaceId, `/projects/${projectId}`))}
          className="flex items-center gap-1 text-ink-light hover:text-ink transition-colors text-body-sm"
        >
          <ArrowLeft className="w-4 h-4" /> {t('leaderChat.backToBoard')}
        </button>
        <div className="flex-1">
          <PageTitle title={t('leaderChat.title')} subtitle={t('leaderChat.subtitle')} />
        </div>
        <button
          onClick={() => setShowAddTask(true)}
          className="flex items-center gap-1.5 px-3 py-2 rounded-md font-body text-body-sm font-medium bg-vellum-deep border border-vellum-dark text-ink hover:bg-vellum-dark transition-colors whitespace-nowrap"
        >
          <Plus className="w-4 h-4" /> {t('leaderChat.addTask')}
        </button>
      </div>

      {/* Leader status + YOLO toggle */}
      <VellumPanel className="mb-4">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <div className={cn(
              'w-8 h-8 rounded-full flex items-center justify-center border-2 bg-vellum-deep font-display text-terracotta',
              leaderOnline ? 'border-gold' : 'border-vellum-dark',
            )}>
              <Bot className="w-4 h-4" />
            </div>
            <div>
              <p className="font-body text-body-md text-ink">
                {chat?.leader_name || t('leaderChat.leader')}
              </p>
              <p className={cn('text-body-sm flex items-center gap-1',
                leaderOnline ? 'text-success' : 'text-ink-muted')}>
                {leaderOnline
                  ? <><span className="w-1.5 h-1.5 rounded-full bg-success inline-block" /> {t('leaderChat.online')}</>
                  : <><WifiOff className="w-3 h-3" /> {t('leaderChat.offline')}</>}
              </p>
            </div>
          </div>
          <button
            onClick={toggleYolo}
            disabled={yoloBusy}
            title={t('leaderChat.yoloHint')}
            className={cn(
              'flex items-center gap-2 px-3 py-2 rounded-md font-body text-body-sm font-medium border transition-colors',
              yolo
                ? 'bg-gold/15 border-gold text-gold-dark'
                : 'bg-vellum-deep border-vellum-dark text-ink-light hover:text-ink',
            )}
          >
            {yolo ? <Zap className="w-4 h-4" /> : <Sparkles className="w-4 h-4" />}
            {t('leaderChat.yolo')}: {yolo ? t('leaderChat.on') : t('leaderChat.off')}
          </button>
        </div>
      </VellumPanel>

      {/* Proposed tasks awaiting approval (YOLO off) */}
      <AnimatePresence>
        {proposed.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-4"
          >
            <VellumPanel className="border-l-4 border-l-gold">
              <p className="font-body text-body-sm text-ink-light mb-2">
                {t('leaderChat.proposedTitle', { count: proposed.length })}
              </p>
              <div className="space-y-2">
                {proposed.map((task) => (
                  <div key={task.id} className="flex items-start justify-between gap-3 bg-vellum-deep rounded-md px-3 py-2">
                    <div className="min-w-0">
                      <p className="font-body text-body-md text-ink truncate">{task.title}</p>
                      {task.description && (
                        <p className="text-body-sm text-ink-muted line-clamp-2">{task.description}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      <button
                        onClick={() => decide(task.id, true)}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-body-sm font-medium bg-success/15 text-success hover:bg-success/25 transition-colors"
                      >
                        <Check className="w-3.5 h-3.5" /> {t('leaderChat.approve')}
                      </button>
                      <button
                        onClick={() => decide(task.id, false)}
                        className="flex items-center gap-1 px-2.5 py-1.5 rounded-md text-body-sm font-medium bg-vellum-dark text-ink-light hover:text-ink transition-colors"
                      >
                        <X className="w-3.5 h-3.5" /> {t('leaderChat.reject')}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </VellumPanel>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Offline banner */}
      {!loading && !leaderOnline && (
        <div className="mb-4 bg-warning-bg border-l-4 border-warning rounded-md px-4 py-3 flex items-center gap-3">
          <WifiOff className="w-5 h-5 text-warning flex-shrink-0" />
          <p className="font-body text-body-sm text-ink">{t('leaderChat.offlineBanner')}</p>
        </div>
      )}

      {/* Conversation */}
      <VellumPanel className="flex flex-col" style={{ minHeight: '48vh' }}>
        <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 max-h-[52vh] pr-1">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-ink-muted">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : messages.length === 0 && !streaming ? (
            <div className="flex flex-col items-center justify-center py-16 text-center text-ink-muted">
              <Bot className="w-10 h-10 mb-2 opacity-50" />
              <p className="font-body text-body-md">{t('leaderChat.empty')}</p>
            </div>
          ) : (
            <>
              {messages.map((m, i) => (
                <MessageBubble key={i} role={m.role} text={m.text} />
              ))}
              {streaming && <MessageBubble role="leader" text={streaming} streaming />}
              {state === 'thinking' && !streaming && (
                <div className="flex items-center gap-2 text-ink-muted text-body-sm">
                  <Loader2 className="w-4 h-4 animate-spin" /> {t('leaderChat.thinking')}
                </div>
              )}
            </>
          )}
        </div>

        {error && (
          <div className="mt-2 text-body-sm text-terracotta flex items-center gap-1.5">
            <X className="w-3.5 h-3.5" /> {error}
          </div>
        )}

        {/* Input */}
        <div className="mt-3 flex items-end gap-2 border-t border-vellum-dark pt-3">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            disabled={locked}
            rows={2}
            placeholder={
              !leaderOnline ? t('leaderChat.inputDisabled')
                : state === 'thinking' ? t('leaderChat.inputThinking')
                : t('leaderChat.inputPlaceholder')
            }
            className="flex-1 bg-vellum border border-vellum-dark rounded-md px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-terracotta resize-none disabled:opacity-60 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleSend}
            disabled={locked || !input.trim()}
            className="flex items-center justify-center w-10 h-10 rounded-md bg-terracotta text-white hover:bg-terracotta-dark transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {state === 'thinking' ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
      </VellumPanel>

      {/* Add-task modal */}
      <AnimatePresence>
        {showAddTask && (
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
            onClick={() => setShowAddTask(false)}
          >
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: 10 }}
              onClick={(e) => e.stopPropagation()}
              className="w-full max-w-md bg-vellum rounded-lg shadow-xl border border-vellum-dark p-5"
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-display text-body-lg text-ink">{t('leaderChat.addTaskTitle')}</h3>
                <button onClick={() => setShowAddTask(false)} className="text-ink-muted hover:text-ink">
                  <X className="w-5 h-5" />
                </button>
              </div>
              <label className="block font-body text-body-sm text-ink-light mb-1">{t('leaderChat.taskTitleLabel')}</label>
              <input
                value={taskForm.title}
                onChange={(e) => setTaskForm((f) => ({ ...f, title: e.target.value }))}
                autoFocus
                placeholder={t('leaderChat.taskTitlePlaceholder')}
                className="w-full mb-3 bg-vellum-deep border border-vellum-dark rounded-md px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-terracotta"
              />
              <label className="block font-body text-body-sm text-ink-light mb-1">{t('leaderChat.taskDescLabel')}</label>
              <textarea
                value={taskForm.description}
                onChange={(e) => setTaskForm((f) => ({ ...f, description: e.target.value }))}
                rows={3}
                placeholder={t('leaderChat.taskDescPlaceholder')}
                className="w-full mb-3 bg-vellum-deep border border-vellum-dark rounded-md px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-terracotta resize-none"
              />
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div>
                  <label className="block font-body text-body-sm text-ink-light mb-1">{t('leaderChat.taskAssigneeLabel')}</label>
                  <select
                    value={taskForm.assigneeId}
                    onChange={(e) => setTaskForm((f) => ({ ...f, assigneeId: e.target.value }))}
                    className="w-full bg-vellum-deep border border-vellum-dark rounded-md px-3 py-2 font-body text-body-md text-ink focus:outline-none focus:border-terracotta"
                  >
                    <option value="">{t('leaderChat.taskAssigneeNone')}</option>
                    {agents.map((a) => (
                      <option key={a.marius_id} value={a.marius_id}>{a.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block font-body text-body-sm text-ink-light mb-1">{t('leaderChat.taskPriorityLabel')}</label>
                  <select
                    value={taskForm.priority}
                    onChange={(e) => setTaskForm((f) => ({ ...f, priority: e.target.value }))}
                    className="w-full bg-vellum-deep border border-vellum-dark rounded-md px-3 py-2 font-body text-body-md text-ink focus:outline-none focus:border-terracotta"
                  >
                    <option value="critical">{t('leaderChat.priorityCritical')}</option>
                    <option value="high">{t('leaderChat.priorityHigh')}</option>
                    <option value="medium">{t('leaderChat.priorityMedium')}</option>
                    <option value="low">{t('leaderChat.priorityLow')}</option>
                  </select>
                </div>
              </div>
              <label className="block font-body text-body-sm text-ink-light mb-1">{t('leaderChat.taskDueDateLabel')}</label>
              <input
                type="date"
                value={taskForm.dueDate}
                onChange={(e) => setTaskForm((f) => ({ ...f, dueDate: e.target.value }))}
                className="w-full mb-3 bg-vellum-deep border border-vellum-dark rounded-md px-3 py-2 font-body text-body-md text-ink focus:outline-none focus:border-terracotta"
              />
              <label className="block font-body text-body-sm text-ink-light mb-1">{t('leaderChat.taskDodLabel')}</label>
              <textarea
                value={taskForm.dod}
                onChange={(e) => setTaskForm((f) => ({ ...f, dod: e.target.value }))}
                rows={2}
                placeholder={t('leaderChat.taskDodPlaceholder')}
                className="w-full mb-4 bg-vellum-deep border border-vellum-dark rounded-md px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-terracotta resize-none"
              />
              <div className="flex justify-end gap-2">
                <button
                  onClick={() => setShowAddTask(false)}
                  className="px-4 py-2 rounded-md font-body text-body-sm text-ink-light hover:text-ink transition-colors"
                >
                  {t('common.cancel')}
                </button>
                <button
                  onClick={submitTask}
                  disabled={!taskForm.title.trim() || addingTask}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-md font-body text-body-sm font-medium bg-terracotta text-white hover:bg-terracotta-dark transition-colors disabled:opacity-40"
                >
                  {addingTask ? <Loader2 className="w-4 h-4 animate-spin" /> : <Plus className="w-4 h-4" />}
                  {t('leaderChat.createTask')}
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function MessageBubble({ role, text, streaming }: { role: 'patron' | 'leader'; text: string; streaming?: boolean }) {
  const isPatron = role === 'patron';
  return (
    <div className={cn('flex', isPatron ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[80%] rounded-lg px-3 py-2 font-body text-body-md whitespace-pre-wrap break-words',
          isPatron
            ? 'bg-terracotta text-white'
            : 'bg-vellum-deep border border-vellum-dark text-ink',
        )}
      >
        {text}
        {streaming && <span className="inline-block w-1.5 h-4 ml-0.5 align-middle bg-current opacity-60 animate-pulse" />}
      </div>
    </div>
  );
}
