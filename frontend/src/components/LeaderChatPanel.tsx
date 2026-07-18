// Leader chat panel (#82) — the project-level 1-1 conversation with the Leader agent.
//
// The message list is rendered through assistant-ui (useExternalStoreRuntime +
// ThreadPrimitive/MessagePrimitive) so we inherit battle-tested chat mechanics —
// auto-scrolling viewport, message bubbles, and Markdown rendering with a smooth
// streaming animation — instead of hand-rolling them. The existing Hermes-backed
// data layer (getLeaderChat / sendLeaderChatMessage / the leader-chat SSE channel)
// is unchanged: we feed those messages into the external-store runtime and the
// runtime renders whatever we give it.
//
// The composer (textarea + send) stays hand-rolled because it carries domain
// behavior assistant-ui has no opinion about: turn-taking (input locks while the
// Leader replies), offline disabling, the YOLO toggle, and the proposed-task
// approval queue. The widget shell (floating bubble + large panel) lives in
// LeaderChatWidget; this component is just the panel contents.
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Bot, Loader2, WifiOff, Check, X, Sparkles, Zap } from 'lucide-react';
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  MessagePrimitive,
  type AppendMessage,
  type TextMessagePartComponent,
} from '@assistant-ui/react';
import { MarkdownTextPrimitive } from '@assistant-ui/react-markdown';
import VellumPanel from '@/components/VellumPanel';
import { cn } from '@/lib/utils';
import * as api from '@/lib/api';
import { subscribeLeaderChat } from '@/lib/sse';

interface ChatMessage {
  role: 'patron' | 'leader';
  text: string;
  /** True while this leader message is still being streamed (assistant.delta). */
  streaming?: boolean;
}

function toMessages(
  transcript: Array<{ role: string; text: string }> | undefined,
): ChatMessage[] {
  return (transcript ?? []).map((t) => ({
    role: t.role === 'patron' ? 'patron' : 'leader',
    text: t.text,
  }));
}

// assistant-ui markdown renderer. MarkdownTextPrimitive reads the part text from
// context, so the wrapper takes no props — it just satisfies the Text part
// component contract. `smooth` enables the typing animation as tokens stream in.
const MarkdownText: TextMessagePartComponent = () => (
  <MarkdownTextPrimitive smooth />
);

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
  const [state, setState] = useState<'idle' | 'thinking' | 'failed'>('idle');
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [proposed, setProposed] = useState<api.TaskDTO[]>([]);
  const [yoloBusy, setYoloBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const leaderOnline = chat?.leader_online ?? false;
  const yolo = chat?.yolo_mode ?? false;
  const locked = !leaderOnline || state === 'thinking';
  const hasStreamingPartial =
    messages.length > 0 && messages[messages.length - 1].role === 'leader' && !!messages[messages.length - 1].streaming;

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

  // Live stream: the Leader's reply arrives as assistant.delta; chat.state marks
  // the turn. Streaming deltas are folded into a trailing partial leader message
  // so the runtime renders them as a growing bubble; the turn end canonicalizes
  // from the server so partials never linger.
  useEffect(() => {
    if (!projectId) return;
    const disconnect = subscribeLeaderChat(projectId, ({ type, data }) => {
      if (type === 'assistant.delta' && typeof data.text === 'string') {
        const delta = data.text;
        setMessages((m) => {
          const last = m[m.length - 1];
          if (last && last.role === 'leader' && last.streaming) {
            return [...m.slice(0, -1), { ...last, text: last.text + delta }];
          }
          return [...m, { role: 'leader', text: delta, streaming: true }];
        });
      } else if (type === 'leader.message' && typeof data.text === 'string') {
        const final = data.text;
        setMessages((m) => {
          const last = m[m.length - 1];
          if (last && last.role === 'leader' && last.streaming) {
            return [...m.slice(0, -1), { role: 'leader', text: final }];
          }
          if (last && last.role === 'leader' && last.text === final) return m; // de-dup
          return [...m, { role: 'leader', text: final }];
        });
      } else if (type === 'chat.state' && typeof data.state === 'string') {
        const next = data.state as 'idle' | 'thinking' | 'failed';
        setState(next);
        if (next !== 'thinking') {
          refreshProposed(); // the Leader may have proposed a draft during its turn
          api
            .getLeaderChat(projectId)
            .then((dto) => {
              setChat(dto);
              setMessages(toMessages(dto.transcript)); // canonical — drops any un-finalized partial
            })
            .catch(() => {});
        }
        if (next === 'failed') setError(t('leaderChat.turnFailed'));
      }
    });
    return disconnect;
  }, [projectId, refreshProposed, t]);

  const sendMessage = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message || projectId == null) return;
      setError(null);
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
    },
    [projectId],
  );

  // assistant-ui runtime: our messages are the source of truth; the runtime only
  // renders them. onNew mirrors sendMessage in case anything dispatches via the
  // runtime (the hand-rolled composer calls sendMessage directly).
  const runtime = useExternalStoreRuntime({
    messages,
    isRunning: state === 'thinking',
    convertMessage: (m: ChatMessage) => ({
      role: m.role === 'patron' ? ('user' as const) : ('assistant' as const),
      content: m.text,
    }),
    onNew: async (message: AppendMessage) => {
      const text = message.content
        .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
        .map((p) => p.text)
        .join('');
      await sendMessage(text);
    },
  });

  const onSubmit = useCallback(() => {
    if (locked || !input.trim()) return;
    const text = input;
    setInput('');
    void sendMessage(text);
  }, [input, locked, sendMessage]);

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
      <div className="flex items-center justify-between gap-2 border-b border-vellum-dark pb-3 mb-3 px-1">
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
            className="mb-3 flex-shrink-0 px-1"
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
        <div className="mb-3 mx-1 bg-warning-bg border-l-4 border-warning rounded-md px-3 py-2 flex items-center gap-2 flex-shrink-0">
          <WifiOff className="w-4 h-4 text-warning flex-shrink-0" />
          <p className="font-body text-body-xs text-ink">{t('leaderChat.offlineBanner')}</p>
        </div>
      )}

      {/* Conversation (assistant-ui thread; fills remaining height, scrolls internally). */}
      <div className="flex-1 min-h-0 px-1">
        {loading ? (
          <div className="flex items-center justify-center py-10 text-ink-muted">
            <Loader2 className="w-5 h-5 animate-spin" />
          </div>
        ) : (
          <AssistantRuntimeProvider runtime={runtime}>
            <ThreadPrimitive.Root className="flex flex-col h-full min-h-0">
              <ThreadPrimitive.Viewport className="flex-1 min-h-0 overflow-y-auto space-y-2.5 pr-1">
                <ThreadPrimitive.Empty>
                  <div className="flex flex-col items-center justify-center py-10 text-center text-ink-muted">
                    <Bot className="w-8 h-8 mb-2 opacity-50" />
                    <p className="font-body text-body-sm">{t('leaderChat.empty')}</p>
                  </div>
                </ThreadPrimitive.Empty>
                <ThreadPrimitive.Messages>
                  {({ message }) =>
                    message.role === 'user' ? <PatronBubble /> : <LeaderBubble />
                  }
                </ThreadPrimitive.Messages>
                {state === 'thinking' && !hasStreamingPartial && (
                  <div className="flex items-center gap-2 text-ink-muted text-body-sm px-1">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t('leaderChat.thinking')}
                  </div>
                )}
              </ThreadPrimitive.Viewport>
            </ThreadPrimitive.Root>
          </AssistantRuntimeProvider>
        )}
      </div>

      {error && (
        <div className="mt-2 mx-1 text-body-xs text-terracotta flex items-center gap-1.5 flex-shrink-0">
          <X className="w-3 h-3" /> {error}
        </div>
      )}

      {/* Input (hand-rolled — carries turn-taking + offline lock + YOLO gating). */}
      <div className="mt-2 mx-1 flex items-end gap-2 border-t border-vellum-dark pt-3 flex-shrink-0">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              onSubmit();
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
          onClick={onSubmit}
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

// Patron (user) bubble — right-aligned, terracotta. Plain text (patron's own words,
// no markdown rendering).
function PatronBubble() {
  return (
    <MessagePrimitive.Root className="flex justify-end">
      <div className="max-w-[85%] rounded-lg px-3 py-1.5 bg-terracotta text-white font-body text-body-sm whitespace-pre-wrap break-words">
        <MessagePrimitive.Parts />
      </div>
    </MessagePrimitive.Root>
  );
}

// Leader (assistant) bubble — left-aligned, vellum-deep. Text parts render as
// Markdown (code, lists, headings, links) styled to match the brand via arbitrary
// Tailwind variants (no @tailwindcss/typography dependency).
function LeaderBubble() {
  return (
    <MessagePrimitive.Root className="flex justify-start">
      <div
        className={cn(
          'max-w-[90%] rounded-lg px-3 py-1.5 bg-vellum-deep border border-vellum-dark text-ink font-body text-body-sm break-words',
          '[&_p]:my-1 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0',
          '[&_ul]:my-1 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-1 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-0.5',
          '[&_code]:font-mono [&_code]:text-[0.85em] [&_code]:bg-vellum [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded',
          '[&_pre]:my-1 [&_pre]:bg-vellum [&_pre]:border [&_pre]:border-vellum-dark [&_pre]:rounded-md [&_pre]:p-2 [&_pre]:overflow-x-auto [&_pre_code]:bg-transparent [&_pre_code]:p-0',
          '[&_a]:text-terracotta [&_a]:underline [&_h1]:font-display [&_h1]:text-body-md [&_h1]:my-1',
          '[&_h2]:font-display [&_h2]:text-body-sm [&_h3]:font-display [&_h3]:text-body-sm [&_h4]:font-display [&_h4]:text-body-sm',
          '[&_blockquote]:my-1 [&_blockquote]:border-l-2 [&_blockquote]:border-vellum-dark [&_blockquote]:pl-2 [&_blockquote]:text-ink-light',
          '[&_strong]:font-semibold [&_em]:italic [&_hr]:my-2 [&_hr]:border-vellum-dark',
        )}
      >
        <MessagePrimitive.Parts components={{ Text: MarkdownText }} />
      </div>
    </MessagePrimitive.Root>
  );
}
