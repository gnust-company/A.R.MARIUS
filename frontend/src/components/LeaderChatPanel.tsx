// Leader chat panel (#82) — the project-level 1-1 conversation with the Leader agent,
// embedded as a side column on the project board (no longer a separate route). The board
// stays visible while the patron chats; the Leader's reply streams back on the leader-chat
// SSE channel (no agent callback). Input locks while the Leader replies (turn-taking) and
// disables while it is offline.
import { useState, useRef, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Bot, Loader2, WifiOff, Check, X, Sparkles, Zap } from 'lucide-react';
import VellumPanel from '@/components/VellumPanel';
import { cn } from '@/lib/utils';
import * as api from '@/lib/api';
import { subscribeLeaderChat } from '@/lib/sse';

interface ChatMessage {
  role: 'patron' | 'leader';
  text: string;
}

function toMessages(
  transcript: Array<{ role: string; text: string }> | undefined,
): ChatMessage[] {
  return (transcript ?? []).map((t) => ({
    role: t.role === 'patron' ? 'patron' : 'leader',
    text: t.text,
  }));
}

export default function LeaderChatPanel({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
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

  // Initial load: the durable transcript + any pending drafts.
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
    if (!message || projectId == null || locked) return;
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

  return (
    <VellumPanel className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 border-b border-vellum-dark pb-3 mb-3">
        <div className="flex items-center gap-2 min-w-0">
          <div
            className={cn(
              'w-8 h-8 rounded-full flex items-center justify-center border-2 bg-vellum-deep text-terracotta flex-shrink-0',
              leaderOnline ? 'border-gold' : 'border-vellum-dark',
            )}
          >
            <Bot className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <p className="font-display text-body-md text-ink truncate">
              {chat?.leader_name || t('leaderChat.leader')}
            </p>
            <p
              className={cn(
                'text-body-xs flex items-center gap-1',
                leaderOnline ? 'text-success' : 'text-ink-muted',
              )}
            >
              {leaderOnline ? (
                <>
                  <span className="w-1.5 h-1.5 rounded-full bg-success inline-block" />
                  {t('leaderChat.online')}
                </>
              ) : (
                <>
                  <WifiOff className="w-3 h-3" />
                  {t('leaderChat.offline')}
                </>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={toggleYolo}
            disabled={yoloBusy}
            title={t('leaderChat.yoloHint')}
            className={cn(
              'flex items-center gap-1 px-2 py-1 rounded-md font-body text-body-xs font-medium border transition-colors',
              yolo
                ? 'bg-gold/15 border-gold text-gold-dark'
                : 'bg-vellum-deep border-vellum-dark text-ink-light hover:text-ink',
            )}
          >
            {yolo ? <Zap className="w-3 h-3" /> : <Sparkles className="w-3 h-3" />}
            {yolo ? t('leaderChat.on') : t('leaderChat.off')}
          </button>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-ink-muted hover:text-ink hover:bg-vellum-dark transition-colors"
            aria-label={t('common.closeDialog')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Proposed tasks awaiting approval (YOLO off) */}
      <AnimatePresence>
        {proposed.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            className="mb-3 flex-shrink-0"
          >
            <div className="bg-vellum-deep border border-vellum-dark border-l-4 border-l-gold rounded-md px-3 py-2">
              <p className="font-body text-body-xs text-ink-light mb-1.5">
                {t('leaderChat.proposedTitle', { count: proposed.length })}
              </p>
              <div className="space-y-1.5">
                {proposed.map((task) => (
                  <div
                    key={task.id}
                    className="flex items-start justify-between gap-2 bg-vellum rounded-md px-2 py-1.5"
                  >
                    <div className="min-w-0">
                      <p className="font-body text-body-sm text-ink truncate">{task.title}</p>
                      {task.description && (
                        <p className="text-body-xs text-ink-muted line-clamp-2">
                          {task.description}
                        </p>
                      )}
                    </div>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => decide(task.id, true)}
                        className="flex items-center gap-0.5 px-1.5 py-1 rounded-md text-body-xs font-medium bg-success/15 text-success hover:bg-success/25 transition-colors"
                      >
                        <Check className="w-3 h-3" /> {t('leaderChat.approve')}
                      </button>
                      <button
                        onClick={() => decide(task.id, false)}
                        className="flex items-center gap-0.5 px-1.5 py-1 rounded-md text-body-xs font-medium bg-vellum-dark text-ink-light hover:text-ink transition-colors"
                      >
                        <X className="w-3 h-3" /> {t('leaderChat.reject')}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Offline banner */}
      {!loading && !leaderOnline && (
        <div className="mb-3 bg-warning-bg border-l-4 border-warning rounded-md px-3 py-2 flex items-center gap-2 flex-shrink-0">
          <WifiOff className="w-4 h-4 text-warning flex-shrink-0" />
          <p className="font-body text-body-xs text-ink">{t('leaderChat.offlineBanner')}</p>
        </div>
      )}

      {/* Conversation (fills remaining height; messages scroll) */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-2.5 pr-1 min-h-0">
        {loading ? (
          <div className="flex items-center justify-center py-10 text-ink-muted">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        ) : messages.length === 0 && !streaming ? (
          <div className="flex flex-col items-center justify-center py-10 text-center text-ink-muted">
            <Bot className="w-8 h-8 mb-2 opacity-50" />
            <p className="font-body text-body-sm">{t('leaderChat.empty')}</p>
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
        <div className="mt-2 text-body-xs text-terracotta flex items-center gap-1.5 flex-shrink-0">
          <X className="w-3 h-3" /> {error}
        </div>
      )}

      {/* Input */}
      <div className="mt-2 flex items-end gap-2 border-t border-vellum-dark pt-3 flex-shrink-0">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
          disabled={locked}
          rows={2}
          placeholder={
            !leaderOnline
              ? t('leaderChat.inputDisabled')
              : state === 'thinking'
                ? t('leaderChat.inputThinking')
                : t('leaderChat.inputPlaceholder')
          }
          className="flex-1 bg-vellum border border-vellum-dark rounded-md px-2.5 py-1.5 font-body text-body-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-terracotta resize-none disabled:opacity-60 disabled:cursor-not-allowed"
        />
        <button
          onClick={handleSend}
          disabled={locked || !input.trim()}
          className="flex items-center justify-center w-9 h-9 rounded-md bg-terracotta text-white hover:bg-terracotta-dark transition-colors disabled:opacity-40 disabled:cursor-not-allowed flex-shrink-0"
        >
          {state === 'thinking' ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Send className="w-4 h-4" />
          )}
        </button>
      </div>
    </VellumPanel>
  );
}

function MessageBubble({
  role,
  text,
  streaming,
}: {
  role: 'patron' | 'leader';
  text: string;
  streaming?: boolean;
}) {
  const isPatron = role === 'patron';
  return (
    <div className={cn('flex', isPatron ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[85%] rounded-lg px-2.5 py-1.5 font-body text-body-sm whitespace-pre-wrap break-words',
          isPatron
            ? 'bg-terracotta text-white'
            : 'bg-vellum-deep border border-vellum-dark text-ink',
        )}
      >
        {text}
        {streaming && (
          <span className="inline-block w-1.5 h-3.5 ml-0.5 align-middle bg-current opacity-60 animate-pulse" />
        )}
      </div>
    </div>
  );
}
