// The patron's direct conversation with one agent (FR-007p), on the agent's own Overview.
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
    <div className="flex h-[560px] flex-col">
      <div className="mb-3 flex items-center justify-between gap-2 border-b border-[#E3D7BC] pb-3">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#A89880]">
          {t('agentChat.title', { name: agentName })}
        </p>
        <span
          className={
            online
              ? 'inline-flex items-center gap-1 text-[11px] text-[#2A6E3A]'
              : 'inline-flex items-center gap-1 text-[11px] text-[#8B7A6A]'
          }
        >
          {online ? (
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-[#4A9E6B]" />
          ) : (
            <WifiOff className="h-3 w-3" />
          )}
          {online ? t('agentChat.online') : t('agentChat.offline')}
        </span>
      </div>

      {!loading && !online && (
        <div className="mb-3 flex items-center gap-2 rounded-md border-l-4 border-[#D4A843] bg-[#F5E8CC] px-3 py-2">
          <WifiOff className="h-4 w-4 flex-shrink-0 text-[#8B6A28]" />
          <p className="text-[12px] text-[#2A2318]">{t('agentChat.offlineBanner')}</p>
        </div>
      )}

      <div className="min-h-0 flex-1">
        {loading ? (
          <div className="flex items-center justify-center py-10 text-[#A89880]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : (
          <AssistantRuntimeProvider runtime={runtime}>
            <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
              <ThreadPrimitive.Viewport className="min-h-0 flex-1 space-y-2.5 overflow-y-auto pr-1">
                <ThreadPrimitive.Empty>
                  <div className="flex flex-col items-center justify-center py-10 text-center text-[#A89880]">
                    <Bot className="mb-2 h-8 w-8 opacity-50" />
                    <p className="text-[13px]">{t('agentChat.empty', { name: agentName })}</p>
                  </div>
                </ThreadPrimitive.Empty>
                <ThreadPrimitive.Messages>
                  {({ message }) => (message.role === 'user' ? <PatronBubble /> : <AgentBubble />)}
                </ThreadPrimitive.Messages>
                {state === 'thinking' && !hasStreamingPartial && (
                  <div className="flex items-center gap-2 px-1 text-[13px] text-[#A89880]">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t('agentChat.thinking', { name: agentName })}
                  </div>
                )}
              </ThreadPrimitive.Viewport>
            </ThreadPrimitive.Root>
          </AssistantRuntimeProvider>
        )}
      </div>

      {error && (
        <div className="mt-2 flex items-center gap-1.5 text-[12px] text-[#C25E3A]">
          <X className="h-3 w-3" /> {error}
        </div>
      )}

      <div className="mt-2 flex items-end gap-2 border-t border-[#E3D7BC] pt-3">
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
          className="flex-1 resize-none rounded-md border border-[#E3D7BC] bg-[#FBF7EE] px-2.5 py-1.5 text-[13px] text-[#2A2318] placeholder:text-[#A89880] focus:border-[#C25E3A] focus:outline-none disabled:cursor-not-allowed disabled:opacity-60"
        />
        <button
          type="button"
          onClick={onSubmit}
          disabled={locked || !input.trim()}
          aria-label={t('agentChat.send')}
          className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-md bg-[#C25E3A] text-white transition-colors hover:bg-[#D97B5A] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {state === 'thinking' ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </div>
    </div>
  );
}
