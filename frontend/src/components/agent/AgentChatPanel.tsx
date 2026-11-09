// The patron's direct conversation with one agent (FR-007p), on the agent's own page.
//
// Built the way the project chat with its Leader is built — assistant-ui renders the thread,
// the composer is hand-rolled because it carries the domain rules (one turn at a time, no
// writing to an agent that cannot be reached) — without the parts that belong to a project:
// there are no proposed tasks here, because nothing said in this chat creates work.
//
// Push, not poll (Constitution IV): the reply arrives on the conversation's own stream, and
// the end of a turn re-reads the transcript so a half-streamed bubble never lingers. Whether the
// agent can be written to at all comes from the page, which keeps it current off the workspace
// channel: read once on open, a box would stay locked for an agent that came online a minute
// later, until somebody reloaded the page.
import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AssistantRuntimeProvider, ThreadPrimitive, useExternalStoreRuntime } from '@assistant-ui/react';
import { Bot, Loader2, Send, WifiOff, X } from 'lucide-react';
import * as api from '@/lib/api';
import { subscribeAgentChat } from '@/lib/sse';
import { errorText } from '@/lib/errors';
import { AgentBubble, PatronBubble } from '@/components/chat/ChatBubbles';
import StatusChip from '@/components/StatusChip';

/** The composer's id, so the page's "Talk to …" button can put the cursor in it when the chat
 *  is already on screen beside the tabs. */
export const AGENT_CHAT_INPUT_ID = 'agent-chat-input';

interface ChatMessage {
  role: 'patron' | 'agent';
  text: string;
  /** True while this reply is still arriving. */
  streaming?: boolean;
}

type ChatState = 'idle' | 'thinking' | 'failed';

function chatStateOf(raw: unknown): ChatState {
  return (raw as ChatState | null | undefined) ?? 'idle';
}

function toMessages(transcript: api.AgentChatTurn[] | undefined): ChatMessage[] {
  return (transcript ?? []).map((turn) => ({
    role: turn.role === 'patron' ? ('patron' as const) : ('agent' as const),
    text: turn.text,
  }));
}

export default function AgentChatPanel({
  workspaceId,
  mariusId,
  agentName,
  online,
}: {
  workspaceId: string;
  mariusId: string;
  agentName: string;
  /** Whether the agent can take a turn right now, as the page last heard it. The server still
   *  decides — a message to an agent that just went away comes back refused. */
  online: boolean;
}) {
  const { t } = useTranslation();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [state, setState] = useState<ChatState>('idle');
  const [input, setInput] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const locked = loading || !online || state === 'thinking';
  const last = messages[messages.length - 1];
  const hasStreamingPartial = !!last && last.role === 'agent' && !!last.streaming;

  const reread = useCallback(async () => {
    const dto = await api.getAgentChat(workspaceId, mariusId);
    setMessages(toMessages(dto.transcript));
    setState(chatStateOf(dto.state));
  }, [workspaceId, mariusId]);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        await reread();
      } catch (e) {
        if (alive) setError(errorText(e, t));
      }
      if (alive) setLoading(false);
    })();
    return () => {
      alive = false;
    };
  }, [reread, t]);

  useEffect(
    () =>
      subscribeAgentChat(workspaceId, mariusId, ({ type, data }) => {
        if (type === 'assistant.delta' && typeof data.text === 'string') {
          const delta = data.text;
          setMessages((m) => {
            const tail = m[m.length - 1];
            if (tail && tail.role === 'agent' && tail.streaming) {
              return [...m.slice(0, -1), { ...tail, text: tail.text + delta }];
            }
            return [...m, { role: 'agent', text: delta, streaming: true }];
          });
        } else if (type === 'chat.state' && typeof data.state === 'string') {
          const next = chatStateOf(data.state);
          setState(next);
          if (next !== 'thinking') {
            // Canonical from the server: drops any partial that was never finalised.
            reread().catch(() => {});
          }
          if (next === 'failed') setError(t('agentChat.turnFailed'));
        }
      }),
    [workspaceId, mariusId, reread, t],
  );

  const sendMessage = useCallback(
    async (raw: string) => {
      const message = raw.trim();
      if (!message) return;
      setError(null);
      setMessages((m) => [...m, { role: 'patron', text: message }]);
      setState('thinking');
      try {
        await api.sendAgentChatMessage(workspaceId, mariusId, message);
      } catch (e) {
        setError(errorText(e, t));
        try {
          await reread();
        } catch {
          setState('idle');
        }
      }
    },
    [workspaceId, mariusId, reread, t],
  );

  const runtime = useExternalStoreRuntime({
    messages,
    isRunning: state === 'thinking',
    convertMessage: (m: ChatMessage) => ({
      role: m.role === 'patron' ? ('user' as const) : ('assistant' as const),
      content: m.text,
    }),
    onNew: async (message) => {
      const text = message.content
        .filter((p): p is { type: 'text'; text: string } => p.type === 'text')
        .map((p) => p.text)
        .join('');
      await sendMessage(text);
    },
  });

  const onSubmit = () => {
    if (locked || !input.trim()) return;
    const text = input;
    setInput('');
    void sendMessage(text);
  };

  return (
    // Fills whatever height the page gives it: a column beside the tabs on wide screens, a
    // bounded panel under the header on narrow ones. The thread scrolls inside; the page does not.
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-paper">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
        <h2 className="min-w-0 truncate font-display text-[18px] font-medium text-ink">
          {t('agentChat.title', { name: agentName })}
        </h2>
        <StatusChip
          status={online ? 'online' : 'offline'}
          label={online ? t('agentChat.online') : t('agentChat.offline')}
        />
      </div>

      {!loading && !online && (
        <div className="mx-4 mt-3 flex items-start gap-2 rounded-lg bg-gold-bg px-3 py-2.5 sm:mx-5">
          <WifiOff className="mt-0.5 h-4 w-4 flex-shrink-0 text-gold-ink" aria-hidden />
          <p className="font-body text-body-sm text-ink">{t('agentChat.offlineBanner')}</p>
        </div>
      )}

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
                  <div className="flex flex-col items-center justify-center px-4 py-10 text-center">
                    <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-inset text-ink-muted">
                      <Bot className="h-6 w-6" aria-hidden />
                    </span>
                    <p className="font-body text-body-md text-ink-light">{t('agentChat.empty', { name: agentName })}</p>
                  </div>
                </ThreadPrimitive.Empty>
                <ThreadPrimitive.Messages>
                  {({ message }) => (message.role === 'user' ? <PatronBubble /> : <AgentBubble />)}
                </ThreadPrimitive.Messages>
                {state === 'thinking' && !hasStreamingPartial && (
                  <div className="flex items-center gap-2 px-1 font-body text-body-sm text-ink-muted">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> {t('agentChat.thinking', { name: agentName })}
                  </div>
                )}
              </ThreadPrimitive.Viewport>
            </ThreadPrimitive.Root>
          </AssistantRuntimeProvider>
        )}
      </div>

      {error && (
        <div role="alert" className="mx-4 mb-2 flex items-start gap-1.5 font-body text-body-sm text-vermilion-ink sm:mx-5">
          <X className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden /> <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      <div className="flex items-end gap-2 border-t border-line bg-inset px-3 py-3 sm:px-4">
        <textarea
          id={AGENT_CHAT_INPUT_ID}
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
          aria-label={t('agentChat.inputLabel', { name: agentName })}
          // Nothing is claimed while the conversation is still being read: an agent is not
          // "offline" for the hundred milliseconds it takes to find out whether it is.
          placeholder={
            loading
              ? ''
              : !online
                ? t('agentChat.inputDisabled')
                : state === 'thinking'
                  ? t('agentChat.inputThinking')
                  : t('agentChat.inputPlaceholder', { name: agentName })
          }
          className="min-h-[44px] min-w-0 flex-1 resize-none rounded-md border border-line bg-paper px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-[3px] focus:ring-terracotta/15 disabled:cursor-not-allowed disabled:bg-inset"
        />
        <button
          type="button"
          onClick={onSubmit}
          disabled={locked || !input.trim()}
          aria-label={t('agentChat.send')}
          className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-md bg-ink text-paper transition-colors hover:bg-ink/85 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {state === 'thinking' ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Send className="h-4 w-4" aria-hidden />}
        </button>
      </div>
    </div>
  );
}
