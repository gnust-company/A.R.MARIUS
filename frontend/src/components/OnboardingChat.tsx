// Agent-driven project setup — a question-window interview (#61).
//
// The Workspace Agent asks one question at a time, each rendered as a window of tick-select
// options (with an "Other → type it" free-text escape). Answers accumulate into a project +
// roster draft; confirming it creates the project. Each mount opens a FRESH session, so
// re-entering the flow never resurrects stale chat history.

import { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bot, Loader2, Sparkles, AlertCircle, Check, ArrowRight, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore, type OnboardingTurn } from '@/store/appStore';
import { ApiError, type OnboardingQuestion, type OnboardingDraft } from '@/lib/api';

/** An option whose label invites a typed answer (mirrors the backend's is_free_text_option). */
const FREE_TEXT = /i'?ll type|type it|type my|other|custom|free\s*text/i;
const isFreeText = (label: string) => FREE_TEXT.test(label);

interface OnboardingChatProps {
  /** Fired with the created project id once the patron confirms the draft. */
  onCreated: (projectId: string) => void;
}

type Phase = 'starting' | 'ready' | 'finalizing';

export default function OnboardingChat({ onCreated }: OnboardingChatProps) {
  const { t } = useTranslation();
  const session = useAppStore((s) => s.activeOnboarding);
  const startOnboarding = useAppStore((s) => s.startOnboarding);
  const answerOnboarding = useAppStore((s) => s.answerOnboarding);
  const finalizeOnboarding = useAppStore((s) => s.finalizeOnboarding);

  const [phase, setPhase] = useState<Phase>('starting');
  const [error, setError] = useState<string | null>(null);
  // The Workspace Agent is not online (409 at start, or it dropped mid-interview). There is no
  // fallback — show a not-ready panel with Retry instead of a half-built chat (#61, v3).
  const [waOffline, setWaOffline] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const startedRef = useRef(false);

  const tryStart = useCallback(async () => {
    setError(null);
    setWaOffline(false);
    setPhase('starting');
    try {
      await startOnboarding();
    } catch (e) {
      // 409 = the Workspace Agent is not online (or a wake failed). Cancel into the not-ready
      // panel rather than rendering an empty/stuck chat. Other errors are transient (network).
      if (e instanceof ApiError && e.status === 409) setWaOffline(true);
      else setError(t('onboarding.errorStart'));
    } finally {
      setPhase('ready');
    }
  }, [startOnboarding, t]);

  const restart = useCallback(async () => {
    await tryStart();
  }, [tryStart]);

  const submitAnswer = useCallback(
    async (answer: string, otherText?: string) => {
      setError(null);
      try {
        await answerOnboarding(answer, otherText);
      } catch (e) {
        // The agent went offline mid-interview (server abandoned the session) → cancel the chat
        // into the not-ready panel. Any other failure is transient; let the panel retry.
        if (e instanceof ApiError && e.status === 409) {
          setWaOffline(true);
          throw e;
        }
        setError(t('onboarding.errorAnswer'));
        throw new Error('answer failed'); // let the panel re-enable its button
      }
    },
    [answerOnboarding, t],
  );

  // Open a fresh chat once on mount.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void tryStart();
  }, [tryStart]);

  // Keep the newest turn in view as the transcript grows.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [session?.transcript.length, session?.phase]);

  const finalize = useCallback(async () => {
    setPhase('finalizing');
    setError(null);
    try {
      const done = await finalizeOnboarding();
      if (done.createdProjectId) onCreated(done.createdProjectId);
    } catch {
      setError(t('onboarding.errorFinalize'));
      setPhase('ready');
    }
  }, [finalizeOnboarding, onCreated, t]);

  const pending = session?.pendingQuestion ?? null;
  const draft = session?.phase === 'complete' ? session?.draft ?? null : null;
  // The last agent turn IS the pending question — render it as an interactive panel, not a
  // duplicate bubble. Everything before it is scrollback history.
  const turns = session?.transcript ?? [];
  const history =
    pending && turns.length > 0 && turns[turns.length - 1].role === 'agent'
      ? turns.slice(0, -1)
      : turns;

  return (
    <div className="flex flex-col h-[600px] bg-vellum border border-[#E3D7BC] rounded-lg overflow-hidden">
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

      {/* Body */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto px-5 py-4 space-y-3">
        {waOffline ? (
          <NotReadyPanel onRetry={restart} />
        ) : (
          <>
            <AnimatePresence initial={false}>
              {history.map((turn) => (
                <ChatBubble key={turn.id} turn={turn} you={t('onboarding.you')} agent={t('onboarding.agentName')} />
              ))}
            </AnimatePresence>

            {phase === 'starting' && (
              <div className="flex items-center gap-2 font-body text-body-sm text-ink-muted">
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('onboarding.starting')}
              </div>
            )}

            {phase !== 'starting' && draft && (
              <DraftCard draft={draft} finalizing={phase === 'finalizing'} onConfirm={finalize} onRestart={restart} />
            )}

            {phase !== 'starting' && !draft && pending && (
              <QuestionPanel key={pending.key ?? pending.question} question={pending} onSubmit={submitAnswer} />
            )}

            {error && (
              <div className="flex items-center gap-2 font-body text-body-sm text-[#B84A32] bg-[#F5DDD6] border border-[#E9C4BC] rounded-md px-3 py-2">
                <AlertCircle className="w-4 h-4 flex-shrink-0" />
                <span className="flex-1">{error}</span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ─── The tick-select question window ──────────────────────────────────────────
function QuestionPanel({
  question,
  onSubmit,
}: {
  question: OnboardingQuestion;
  onSubmit: (answer: string, otherText?: string) => Promise<void>;
}) {
  const { t } = useTranslation();
  const multi = question.multi === true;
  const [selected, setSelected] = useState<string[]>([]);
  const [otherText, setOtherText] = useState('');
  const [busy, setBusy] = useState(false);

  const toggle = (label: string) => {
    if (multi) {
      setSelected((s) => (s.includes(label) ? s.filter((x) => x !== label) : [...s, label]));
    } else {
      setSelected([label]);
    }
  };

  const freeSelected = selected.some(isFreeText);
  const canSubmit = selected.length > 0 && (!freeSelected || otherText.trim().length > 0) && !busy;

  const submit = async () => {
    if (!canSubmit) return;
    setBusy(true);
    try {
      await onSubmit(selected.join(', '), freeSelected ? otherText.trim() : undefined);
    } catch {
      setBusy(false); // submit failed — let them retry
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-[#F7F0E0] border border-[#E3D7BC] rounded-lg p-4 space-y-3"
    >
      <p className="font-display text-body-lg text-ink">{question.question}</p>
      <p className="font-body text-body-xs text-ink-muted">
        {multi ? t('onboarding.pickMany') : t('onboarding.pickOne')}
      </p>
      <div className="flex flex-wrap gap-2">
        {question.options.map((opt) => {
          const active = selected.includes(opt.label);
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => toggle(opt.label)}
              className={`inline-flex items-center gap-1.5 px-3 py-2 rounded-md border font-body text-body-sm transition-colors ${
                active
                  ? 'bg-[#C25E3A] border-[#C25E3A] text-white'
                  : 'bg-vellum border-[#E3D7BC] text-ink hover:border-[#C25E3A]'
              }`}
            >
              {active && <Check className="w-3.5 h-3.5" />}
              {opt.label}
            </button>
          );
        })}
      </div>
      {freeSelected && (
        <input
          autoFocus
          value={otherText}
          onChange={(e) => setOtherText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void submit();
            }
          }}
          placeholder={t('onboarding.otherPlaceholder')}
          className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors"
        />
      )}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="inline-flex items-center gap-1.5 bg-[#C25E3A] hover:bg-[#D97B5A] disabled:bg-[#A89880] disabled:cursor-not-allowed text-white font-body font-medium text-body-sm px-4 py-2 rounded-md transition-colors"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <ArrowRight className="w-4 h-4" />}
          {t('onboarding.submit')}
        </button>
      </div>
    </motion.div>
  );
}

// ─── The final project + roster draft ─────────────────────────────────────────
function DraftCard({
  draft,
  finalizing,
  onConfirm,
  onRestart,
}: {
  draft: OnboardingDraft;
  finalizing: boolean;
  onConfirm: () => void;
  onRestart: () => void;
}) {
  const { t } = useTranslation();
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-[#F7F0E0] border border-[#D4A843] rounded-lg p-4 space-y-3"
    >
      <div className="flex items-center gap-2">
        <Sparkles className="w-4 h-4 text-[#C25E3A]" />
        <p className="font-display text-body-lg text-ink">{t('onboarding.draftReady')}</p>
      </div>
      <div>
        <p className="font-display text-display-sm text-ink">{draft.name}</p>
        {draft.objective && <p className="font-body text-body-sm text-ink-light mt-1">{draft.objective}</p>}
      </div>
      <div>
        <p className="font-body text-body-xs text-ink-muted mb-1.5">{t('onboarding.draftRoster')}</p>
        <div className="flex flex-wrap gap-1.5">
          {draft.roster.map((role) => (
            <span
              key={role.key ?? role.title}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full font-body text-body-xs ${
                role.is_leader
                  ? 'bg-[#D8EADD] text-[#2F7A4E] border border-[#B8D8C4]'
                  : 'bg-[#EDE4CE] text-ink border border-[#E3D7BC]'
              }`}
            >
              {role.title}
            </span>
          ))}
        </div>
      </div>
      <div className="flex items-center justify-between gap-2 pt-1">
        <button
          type="button"
          onClick={onRestart}
          disabled={finalizing}
          className="inline-flex items-center gap-1.5 font-body text-body-sm text-ink-muted hover:text-ink disabled:opacity-50 transition-colors"
        >
          <RotateCcw className="w-3.5 h-3.5" />
          {t('onboarding.startOver')}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={finalizing}
          className="inline-flex items-center gap-1.5 bg-[#D4A843] hover:bg-[#E8C96A] disabled:bg-[#A89880] disabled:cursor-not-allowed text-ink font-body font-medium text-body-sm px-4 py-2 rounded-md transition-colors"
        >
          {finalizing ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('onboarding.creating')}
            </>
          ) : (
            <>
              <Check className="w-4 h-4" />
              {t('onboarding.confirmCreate')}
            </>
          )}
        </button>
      </div>
    </motion.div>
  );
}

// ─── Not-online panel (no fallback — the agent must be woken/enrolled) ────────
function NotReadyPanel({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation();
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="flex flex-col items-center justify-center text-center gap-3 py-10 px-6"
    >
      <div className="w-12 h-12 rounded-full bg-[#F5DDD6] border border-[#E9C4BC] flex items-center justify-center">
        <AlertCircle className="w-6 h-6 text-[#B84A32]" />
      </div>
      <p className="font-display text-body-lg text-ink">{t('onboarding.waOffline')}</p>
      <p className="font-body text-body-sm text-ink-muted max-w-sm">{t('onboarding.waOfflineHint')}</p>
      <button
        type="button"
        onClick={onRetry}
        className="inline-flex items-center gap-1.5 bg-[#C25E3A] hover:bg-[#D97B5A] text-white font-body font-medium text-body-sm px-4 py-2 rounded-md transition-colors"
      >
        <RotateCcw className="w-4 h-4" />
        {t('onboarding.retry')}
      </button>
    </motion.div>
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
        <p className="font-body text-body-xs mb-1 text-ink-muted">{isAgent ? agent : you}</p>
        <div
          className={`inline-block px-3.5 py-2.5 rounded-lg font-body text-body-md whitespace-pre-wrap text-left ${
            isAgent ? 'bg-[#EDE4CE] border border-[#E3D7BC] text-ink' : 'bg-[#C25E3A] text-white'
          }`}
        >
          {turn.text}
        </div>
      </div>
    </motion.div>
  );
}
