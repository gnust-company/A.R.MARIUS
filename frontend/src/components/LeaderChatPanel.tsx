// Leader chat panel (#82) — the project-level 1-1 conversation with the Leader agent.
//
// The message list is rendered through assistant-ui (useExternalStoreRuntime +
// ThreadPrimitive/MessagePrimitive) so we inherit battle-tested chat mechanics —
// auto-scrolling viewport, message bubbles, and Markdown rendering with a smooth
// streaming animation — instead of hand-rolling them. The existing gateway-backed
// data layer (getLeaderChat / sendLeaderChatMessage / the leader-chat SSE channel)
// is unchanged: we feed those messages into the external-store runtime and the
// runtime renders whatever we give it.
//
// The composer (textarea + send) stays hand-rolled because it carries domain
// behavior assistant-ui has no opinion about: turn-taking (input locks while the
// Leader replies), offline disabling, and the proposed-task
// approval queue. The widget shell (floating bubble + large panel) lives in
// LeaderChatWidget; this component is just the panel contents.
import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { motion, AnimatePresence } from 'framer-motion';
import { Send, Bot, Loader2, WifiOff, Check, X } from 'lucide-react';
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  type AppendMessage,
} from '@assistant-ui/react';
import { AgentBubble, PatronBubble, SystemNotice } from '@/components/chat/ChatBubbles';
import StatusChip from '@/components/StatusChip';
import { cn } from '@/lib/utils';
import * as api from '@/lib/api';
import { subscribeLeaderChat } from '@/lib/sse';
import { errorText } from '@/lib/errors';

interface ChatMessage {
  role: 'patron' | 'leader' | 'system';
  text: string;
  /** True while this leader message is still being streamed (assistant.delta). */
  streaming?: boolean;
}

type ChatState = 'idle' | 'thinking' | 'failed';

/** The panel knows three states; a missing one reads as idle. A module-level function
 *  rather than an inline `??`, because both call sites sit inside a try block and the
 *  React Compiler has no lowering for a conditional expression there — meeting one costs
 *  the optimization of the entire component. */
function chatStateOf(raw: unknown): ChatState {
  return (raw as ChatState | null | undefined) ?? 'idle';
}

/** What a system turn reads as on screen.
 *
 *  A system turn is a wake the platform delivered into this conversation, and it is stored
 *  as a cause **code plus its parameters** rather than a finished sentence: the Leader gets
 *  that same turn in English inside its packet, while the patron reads it here in whichever
 *  language they picked (Constitution VII). The stored English is the fallback, for rows
 *  written before the codes existed. */
function systemText(
  turn: { code?: string | null; params?: Record<string, string> | null; text?: string },
  t: TFunction,
): string {
  if (!turn.code) return turn.text ?? '';
  const key = `agentDetail.wakeReason.${turn.code}`;
  const rendered = t(key, { ...(turn.params ?? {}) });
  return rendered === key ? (turn.text ?? '') : rendered;
}

function toMessages(
  transcript: api.LeaderChatTurn[] | undefined,
  t: TFunction,
): ChatMessage[] {
  return (transcript ?? []).map((turn) => {
    // Neither the patron nor the Leader said this — the platform did. Folding it into the
    // Leader's bubble put the Leader's own wake notices in its mouth.
    if (turn.role === 'system') {
      return { role: 'system' as const, text: systemText(turn, t) };
    }
    return {
      role: turn.role === 'patron' ? ('patron' as const) : ('leader' as const),
      text: turn.text,
    };
  });
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
  const [state, setState] = useState<'idle' | 'thinking' | 'failed'>('idle');
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [proposed, setProposed] = useState<api.TaskDTO[]>([]);
  const [loading, setLoading] = useState(true);

  const leaderOnline = chat?.leader_online ?? false;
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
        setMessages(toMessages(dto.transcript, t));
        setState(chatStateOf(dto.state));
        await refreshProposed();
      } catch (e) {
        if (alive) setError(errorText(e, t));
      }
      if (alive) setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [projectId, refreshProposed, t]);

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
      } else if (type === 'system.message') {
        // A wake the platform just delivered. Shown as it lands, so the patron sees why
        // the Leader started thinking instead of watching it stir for no visible reason.
        const notice = systemText(
          {
            code: typeof data.code === 'string' ? data.code : null,
            params: (data.params ?? null) as Record<string, string> | null,
            text: typeof data.text === 'string' ? data.text : '',
          },
          t,
        );
        if (notice) setMessages((m) => [...m, { role: 'system', text: notice }]);
      } else if (type === 'chat.state' && typeof data.state === 'string') {
        const next = data.state as 'idle' | 'thinking' | 'failed';
        setState(next);
        if (next !== 'thinking') {
          refreshProposed(); // the Leader may have proposed a draft during its turn
          api
            .getLeaderChat(projectId)
            .then((dto) => {
              setChat(dto);
              setMessages(toMessages(dto.transcript, t)); // canonical — drops any un-finalized partial
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
        setError(errorText(e, t));
        try {
          const dto = await api.getLeaderChat(projectId);
          setChat(dto);
          setMessages(toMessages(dto.transcript, t));
          setState(chatStateOf(dto.state));
        } catch {
          setState('idle');
        }
      }
    },
    [projectId, t],
  );

  // assistant-ui runtime: our messages are the source of truth; the runtime only
  // renders them. onNew mirrors sendMessage in case anything dispatches via the
  // runtime (the hand-rolled composer calls sendMessage directly).
  const runtime = useExternalStoreRuntime({
    messages,
    isRunning: state === 'thinking',
    convertMessage: (m: ChatMessage) => ({
      role:
        m.role === 'patron'
          ? ('user' as const)
          : m.role === 'system'
            ? ('system' as const)
            : ('assistant' as const),
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

  const decide = useCallback(async (taskId: string, approve: boolean) => {
    try {
      if (approve) await api.approveTask(taskId);
      else await api.rejectTask(taskId);
      setProposed((p) => p.filter((task) => task.id !== taskId));
    } catch (e) {
      setError(errorText(e, t));
    }
  }, [t]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-paper">
      {/* Header */}
      <div className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          {/* Ringed by liveness, the same ring every agent wears elsewhere. */}
          <span
            className={cn(
              'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full',
              leaderOnline
                ? 'bg-verdigris-bg text-verdigris-ink ring-2 ring-verdigris ring-offset-2 ring-offset-paper'
                : 'border-2 border-dashed border-ash bg-inset text-ink-muted',
            )}
          >
            <Bot className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0">
            <h2 className="truncate font-display text-[19px] font-medium leading-tight text-ink">
              {chat?.leader_name || t('leaderChat.leader')}
            </h2>
            <div className="mt-1">
              {!loading && (
                <StatusChip
                  status={leaderOnline ? 'online' : 'offline'}
                  label={leaderOnline ? t('leaderChat.online') : t('leaderChat.offline')}
                />
              )}
            </div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-md text-ink-light transition-colors hover:bg-inset hover:text-ink"
          aria-label={t('common.closeDialog')}
        >
          <X className="h-5 w-5" aria-hidden />
        </button>
      </div>

      {/* Drafts the Leader proposed outside the approved plan — each one is a scope
          widening the patron has to decide on (spec 001 FR-027). Gold: waiting on the patron. */}
      <AnimatePresence>
        {proposed.length > 0 && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: 'auto' }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2 }}
            className="flex-shrink-0 overflow-hidden"
          >
            <div className="mx-4 mt-3 max-h-[40dvh] overflow-y-auto rounded-lg bg-gold-bg px-3.5 py-3 sm:mx-5">
              <p className="mb-2 font-body text-body-sm font-medium text-gold-ink">
                {t('leaderChat.proposedTitle', { count: proposed.length })}
              </p>
              <div className="space-y-2">
                {proposed.map((task) => (
                  <div
                    key={task.id}
                    className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 rounded-lg border border-line bg-paper px-3.5 py-2.5"
                  >
                    <div className="min-w-0 flex-[1_1_220px]">
                      <p className="line-clamp-2 break-words font-body text-[15px] font-medium text-ink">{task.title}</p>
                      {task.description && (
                        <p className="line-clamp-2 font-body text-body-sm text-ink-light">
                          {task.description}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 items-center gap-2">
                      <button
                        onClick={() => decide(task.id, false)}
                        className="inline-flex min-h-[44px] items-center gap-1.5 rounded-md border border-line-strong bg-paper px-3.5 font-body text-body-sm font-medium text-ink transition-colors hover:bg-inset"
                      >
                        <X className="h-4 w-4" aria-hidden /> {t('leaderChat.reject')}
                      </button>
                      <button
                        onClick={() => decide(task.id, true)}
                        className="inline-flex min-h-[44px] items-center gap-1.5 rounded-md bg-ink px-3.5 font-body text-body-sm font-medium text-paper transition-colors hover:bg-ink/85"
                      >
                        <Check className="h-4 w-4" aria-hidden /> {t('leaderChat.approve')}
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
        <div className="mx-4 mt-3 flex flex-shrink-0 items-start gap-2 rounded-lg bg-gold-bg px-3.5 py-2.5 sm:mx-5">
          <WifiOff className="mt-0.5 h-4 w-4 flex-shrink-0 text-gold-ink" aria-hidden />
          <p className="font-body text-body-sm text-ink">{t('leaderChat.offlineBanner')}</p>
        </div>
      )}

      {/* Conversation (assistant-ui thread; fills remaining height, scrolls internally). */}
      <div className="min-h-0 flex-1 px-4 pt-3 sm:px-5">
        {loading ? (
          <div className="flex items-center justify-center py-10 text-ink-muted">
            <Loader2 className="h-5 w-5 animate-spin" aria-hidden />
          </div>
        ) : (
          <AssistantRuntimeProvider runtime={runtime}>
            <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
              <ThreadPrimitive.Viewport className="min-h-0 flex-1 space-y-2.5 overflow-y-auto pb-3 pr-1">
                <ThreadPrimitive.Empty>
                  <div className="flex flex-col items-center justify-center px-4 py-12 text-center">
                    <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-inset text-ink-muted">
                      <Bot className="h-6 w-6" aria-hidden />
                    </span>
                    <p className="font-body text-body-md text-ink-light">{t('leaderChat.empty')}</p>
                  </div>
                </ThreadPrimitive.Empty>
                <ThreadPrimitive.Messages>
                  {({ message }) =>
                    message.role === 'user' ? (
                      <PatronBubble />
                    ) : message.role === 'system' ? (
                      <SystemNotice />
                    ) : (
                      <AgentBubble />
                    )
                  }
                </ThreadPrimitive.Messages>
                {state === 'thinking' && !hasStreamingPartial && (
                  <div className="flex items-center gap-2 px-1 font-body text-body-sm text-ink-muted">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> {t('leaderChat.thinking')}
                  </div>
                )}
              </ThreadPrimitive.Viewport>
            </ThreadPrimitive.Root>
          </AssistantRuntimeProvider>
        )}
      </div>

      {error && (
        <div role="alert" className="mx-4 mb-2 flex flex-shrink-0 items-start gap-1.5 font-body text-body-sm text-vermilion-ink sm:mx-5">
          <X className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden /> <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      {/* Input (hand-rolled — carries turn-taking + the offline lock). The bottom padding
          clears the phone's home indicator when the panel is full-screen. */}
      <div className="flex flex-shrink-0 items-end gap-2 border-t border-line bg-inset px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-4">
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
          aria-label={t('leaderChat.inputPlaceholder')}
          placeholder={
            !leaderOnline
              ? t('leaderChat.inputDisabled')
              : state === 'thinking'
                ? t('leaderChat.inputThinking')
                : t('leaderChat.inputPlaceholder')
          }
          className="min-h-[44px] min-w-0 flex-1 resize-none rounded-md border border-line bg-paper px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-[3px] focus:ring-terracotta/15 disabled:cursor-not-allowed disabled:bg-inset"
        />
        <button
          onClick={onSubmit}
          disabled={locked || !input.trim()}
          aria-label={t('agentChat.send')}
          className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-md bg-ink text-paper transition-colors hover:bg-ink/85 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {state === 'thinking' ? (
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          ) : (
            <Send className="h-4 w-4" aria-hidden />
          )}
        </button>
      </div>
    </div>
  );
}
