// Agent-assisted project-setup chat (Sprint 7 / Phase G).
//
// The Workspace Agent runs a scripted playbook (greet → propose a roster from the objective
// → confirm); `finalize` materialises the plan into a real project + roster. This panel drives
// the store's onboarding actions and reports the new project id back to the host page so it
// can navigate there. Works under MOCK (scripted FE brain) and against the real API alike.

import { useEffect, useRef, useState, useCallback, type FormEvent } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bot, Send, Loader2, Sparkles, AlertCircle, RotateCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useMockStore } from '@/store/mockStore';
import type { OnboardingTurn } from '@/store/mockStore';

interface OnboardingChatProps {
  /** Fired with the created project id once the patron finalizes the plan. */
  onCreated: (projectId: string) => void;
}

type Phase = 'starting' | 'ready' | 'finalizing';

export default function OnboardingChat({ onCreated }: OnboardingChatProps) {
  const { t } = useTranslation();
  const session = useMockStore((s) => s.activeOnboarding);
  const startOnboarding = useMockStore((s) => s.startOnboarding);
  const postOnboardingMessage = useMockStore((s) => s.postOnboardingMessage);
  const finalizeOnboarding = useMockStore((s) => s.finalizeOnboarding);

  const [phase, setPhase] = useState<Phase>('starting');
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scrollRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);

  // Open (or rejoin) the workspace's setup chat once on mount.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    (async () => {
      try {
        await startOnboarding();
        setPhase('ready');
      } catch {
        setError(t('onboarding.errorStart'));
        setPhase('ready');
      }
    })();
  }, [startOnboarding, t]);

  // Keep the latest turn in view as the transcript grows.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [session?.transcript.length, phase]);

  const send = useCallback(
    async (e?: FormEvent) => {
      e?.preventDefault();
      const text = draft.trim();
      if (!text || sending || phase === 'finalizing') return;
      setDraft('');
      setSending(true);
      setError(null);
      try {
        await postOnboardingMessage(text);
      } catch {
        setError(t('onboarding.errorSend'));
      } finally {
        setSending(false);
      }
    },
    [draft, sending, phase, postOnboardingMessage, t],
  );

  const finalize = useCallback(async () => {
    if (phase === 'finalizing' || !session) return;
    setPhase('finalizing');
    setError(null);
    try {
      const finalized = await finalizeOnboarding();
      if (finalized.createdProjectId) {
        onCreated(finalized.createdProjectId);
      }
    } catch {
      setError(t('onboarding.errorFinalize'));
      setPhase('ready');
    }
  }, [phase, session, finalizeOnboarding, onCreated, t]);

  const isOpen = session?.status === 'open';
  const showStartingSpinner = phase === 'starting' && (!session || session.transcript.length === 0);

  return (
    <div className="flex flex-col h-[560px] bg-vellum border border-[#E3D7BC] rounded-lg overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-[#E3D7BC] bg-[#EDE4CE]">
        <div className="w-10 h-10 rounded-full bg-[#C25E3A] flex items-center justify-center text-white flex-shrink-0">
          <Bot className="w-5 h-5" />
        </div>
        <div className="min-w-0">
          <p className="font-display text-body-md text-ink leading-tight">{t('onboarding.agentName')}</p>
          <p className="font-body text-body-xs text-ink-muted truncate">{t('onboarding.subtitle')}</p>
        </div>
        <span className="ml-auto inline-flex items-center gap-1.5 font-body text-body-xs text-[#4A9E6B] bg-[#D8EADD] px-2 py-1 rounded-full">
          <Sparkles className="w-3 h-3" />
          {t('onboarding.title')}
        </span>
      </div>

      {/* Transcript */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {showStartingSpinner && (
          <div className="flex items-center gap-2 font-body text-body-sm text-ink-muted">
            <Loader2 className="w-4 h-4 animate-spin" />
            {t('onboarding.starting')}
          </div>
        )}
        <AnimatePresence initial={false}>
          {(session?.transcript ?? []).map((turn) => (
            <ChatBubble key={turn.id} turn={turn} you={t('onboarding.you')} agent={t('onboarding.agentName')} />
          ))}
        </AnimatePresence>
        {sending && (
          <div className="flex items-center gap-2 font-body text-body-sm text-ink-muted">
            <Loader2 className="w-4 h-4 animate-spin" />
            {t('onboarding.sending')}
          </div>
        )}
        {error && (
          <div className="flex items-center gap-2 font-body text-body-sm text-[#B84A32] bg-[#F5DDD6] border border-[#E9C4BC] rounded-md px-3 py-2">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span className="flex-1">{error}</span>
            <button onClick={() => send()} className="underline hover:no-underline">
              <RotateCw className="w-3.5 h-3.5" />
            </button>
          </div>
        )}
      </div>

      {/* Composer */}
      <form onSubmit={send} className="border-t border-[#E3D7BC] bg-[#F7F0E0] px-4 py-3 space-y-2">
        <div className="flex items-end gap-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            placeholder={t('onboarding.inputPlaceholder')}
            rows={2}
            disabled={!isOpen || phase === 'finalizing'}
            className="flex-1 bg-vellum border border-[#E3D7BC] rounded-md px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors resize-none disabled:opacity-60"
          />
          <button
            type="submit"
            disabled={!draft.trim() || sending || !isOpen || phase === 'finalizing'}
            className="inline-flex items-center justify-center w-10 h-10 rounded-md bg-[#C25E3A] hover:bg-[#D97B5A] disabled:bg-[#A89880] disabled:cursor-not-allowed text-white transition-colors flex-shrink-0"
            title={t('onboarding.send')}
          >
            {sending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
          </button>
        </div>
        <div className="flex items-center justify-between gap-2">
          <p className="font-body text-body-xs text-ink-muted">{t('onboarding.hintConfirm')}</p>
          <button
            type="button"
            onClick={finalize}
            disabled={!isOpen || phase === 'finalizing' || !session}
            className="inline-flex items-center gap-1.5 bg-[#D4A843] hover:bg-[#E8C96A] disabled:bg-[#A89880] disabled:cursor-not-allowed text-ink font-body font-medium text-body-sm px-4 py-2 rounded-md transition-colors"
          >
            {phase === 'finalizing' ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('onboarding.creating')}
              </>
            ) : (
              t('onboarding.createProject')
            )}
          </button>
        </div>
      </form>
    </div>
  );
}

function ChatBubble({ turn, you, agent }: { turn: OnboardingTurn; you: string; agent: string }) {
  const isAgent = turn.role === 'agent';
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={`flex ${isAgent ? 'justify-start' : 'justify-end'}`}
    >
      <div className={`max-w-[80%] ${isAgent ? '' : 'text-right'}`}>
        <p className={`font-body text-body-xs mb-1 ${isAgent ? 'text-ink-muted' : 'text-ink-muted'}`}>
          {isAgent ? agent : you}
        </p>
        <div
          className={`inline-block px-3.5 py-2.5 rounded-lg font-body text-body-md whitespace-pre-wrap text-left ${
            isAgent
              ? 'bg-[#EDE4CE] border border-[#E3D7BC] text-ink'
              : 'bg-[#C25E3A] text-white'
          }`}
        >
          {turn.text}
        </div>
      </div>
    </motion.div>
  );
}
