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
        if (alive) setError(e instanceof Error ? e.message : String(e));
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
        setError(e instanceof Error ? e.message : String(e));
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
            onClick={onClose}
            className="p-1 rounded-md text-ink-muted hover:text-ink hover:bg-vellum-dark transition-colors"
            aria-label={t('common.closeDialog')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Drafts the Leader proposed outside the approved plan — each one is a scope
          widening the patron has to decide on (spec 001 FR-027). */}
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
                    message.role === 'user' ? (
                      <PatronBubble />
                    ) : message.role === 'system' ? (
                      <SystemNotice />
                    ) : (
                      <LeaderBubble />
                    )
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

      {/* Input (hand-rolled — carries turn-taking + the offline lock). */}
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

// A wake the platform delivered into the conversation — centred, quiet, and deliberately
// not a bubble: nobody said it, so giving it a speaker's shape would be a lie. It used to
// arrive dressed as the Leader talking to itself.
function SystemNotice() {
  return (
    <MessagePrimitive.Root className="flex justify-center">
      <div className="max-w-[92%] rounded-md px-2.5 py-1 bg-vellum border border-dashed border-vellum-dark text-ink-muted font-body text-body-xs text-center whitespace-pre-wrap break-words">
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
