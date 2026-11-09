// Agent-driven project setup — a question-window interview (#61).
//
// The Workspace Agent asks one question at a time, each rendered as a window of tick-select
// options (with an "Other → type it" free-text escape). Answers accumulate into a project +
// project draft; confirming it creates the project. Each mount opens a FRESH session, so
// re-entering the flow never resurrects stale chat history.
//
// **The answer no longer comes back in the reply.** Each turn of the interview is a run, and
// a run is taken by whichever machine is free (FR-040c) — so `start` and `answer` return
// before the agent has spoken, and what says it has spoken is the workspace channel. This
// panel waits on that channel and re-reads the chat, which is why it can show a turn arriving
// without anything here polling for it.

import { useEffect, useRef, useState, useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bot, Loader2, Sparkles, AlertCircle, Check, ArrowRight, RotateCcw } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore, type OnboardingTurn } from '@/store/appStore';
import { onWorkspaceEvent } from '@/hooks/use-workspace-events';
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
  const hydrateActiveOnboarding = useAppStore((s) => s.hydrateActiveOnboarding);

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
    }
    setPhase('ready');
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

  // The agent's turn happens on a machine, and this is how the browser hears about it. The
  // event carries an id and nothing else, so it is a signal to go and read the chat again —
  // never the chat itself.
  useEffect(
    () =>
      onWorkspaceEvent((event) => {
        if (event.type !== 'onboarding.changed') return;
        void (async () => {
          await hydrateActiveOnboarding();
          // The chat is gone: the turn ended with the agent saying nothing, and the server
          // closed it. Same panel the patron gets when the agent is offline, because it is
          // the same problem — there is nobody to interview with.
          if (useAppStore.getState().activeOnboarding === null) setWaOffline(true);
        })();
      }),
    [hydrateActiveOnboarding],
  );

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
  // The chat is open and the agent owes it a turn. Nothing here is waiting on a reply — the
  // turn is out on a machine — so this is what stands in for the reply that used to arrive
  // inside the call.
  const awaitingAgent = phase === 'ready' && session !== null && !pending && !draft;
  // The last agent turn IS the pending question — render it as an interactive panel, not a
  // duplicate bubble. Everything before it is scrollback history.
  const turns = session?.transcript ?? [];
  const history =
    pending && turns.length > 0 && turns[turns.length - 1].role === 'agent'
      ? turns.slice(0, -1)
      : turns;

  return (
    // Capped by the window as well as by a fixed height, so on a short phone screen the answer
    // buttons at the bottom of the interview stay on screen instead of below the fold.
    <div className="surface flex flex-col h-[600px] max-h-[80dvh] overflow-hidden">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 sm:px-5 py-4 border-b border-line">
        <div className="w-11 h-11 rounded-full border border-line-strong bg-sapphire-soft flex items-center justify-center text-sapphire-strong flex-shrink-0">
          <Bot className="w-5 h-5" aria-hidden />
        </div>
        <div className="min-w-0 flex-[1_1_180px]">
          <p className="font-display font-normal text-[19px] tracking-[-0.01em] text-ink-strong leading-tight">{t('onboarding.agentName')}</p>
          <p className="mt-0.5 font-body text-body-sm text-ink-muted">{t('onboarding.subtitle')}</p>
        </div>
        <span className="status-pill border-gold/40 text-gold">
          <Sparkles className="w-3.5 h-3.5" aria-hidden />
          {t('onboarding.title')}
        </span>
      </div>

      {/* Body */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto bg-canvas/50 px-4 sm:px-5 py-5 space-y-4">
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
              <div className="flex items-center gap-2 font-body text-body-sm text-ink-muted" role="status">
                <Loader2 className="w-4 h-4 animate-spin" aria-hidden />
                {t('onboarding.starting')}
              </div>
            )}

            {phase !== 'starting' && draft && (
              <DraftCard draft={draft} finalizing={phase === 'finalizing'} onConfirm={finalize} onRestart={restart} />
            )}

            {phase !== 'starting' && !draft && pending && (
              <QuestionPanel key={pending.key ?? pending.question} question={pending} onSubmit={submitAnswer} />
            )}

            {awaitingAgent && (
              <div className="flex items-center gap-2 font-body text-body-sm text-ink-light" role="status">
                <Loader2 className="w-4 h-4 animate-spin text-sapphire-strong" aria-hidden />
                {t('onboarding.waiting')}
              </div>
            )}

            {error && (
              <div
                className="flex items-center gap-2 font-body text-body-sm text-danger bg-danger-soft border border-danger/30 rounded-md px-3 py-2"
                role="alert"
              >
                <AlertCircle className="w-4 h-4 flex-shrink-0" aria-hidden />
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
    // The free-text branch is resolved before the block: a conditional expression inside
    // try/catch is one the React Compiler cannot lower, and it drops the whole component.
    const other = freeSelected ? otherText.trim() : undefined;
    try {
      await onSubmit(selected.join(', '), other);
    } catch {
      setBusy(false); // submit failed — let them retry
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="bg-surface border border-line-strong rounded-lg p-4 sm:p-5 space-y-3"
    >
      <p className="font-display font-normal text-[20px] leading-snug tracking-[-0.01em] text-ink-strong">{question.question}</p>
      <p className="eyebrow">
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
              aria-pressed={active}
              className={`inline-flex items-center gap-1.5 min-h-[44px] px-3.5 py-2 rounded-md border font-body text-body-md text-left transition-colors ${
                active
                  ? 'bg-sapphire-soft border-sapphire text-ink-strong'
                  : 'bg-surface border-line-strong text-ink hover:border-sapphire hover:bg-surface-hover'
              }`}
            >
              {active && <Check className="w-3.5 h-3.5 text-sapphire-strong" />}
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
          className="field"
        />
      )}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={submit}
          disabled={!canSubmit}
          className="btn btn-primary"
        >
          {busy ? <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> : <ArrowRight className="w-4 h-4" aria-hidden />}
          {t('onboarding.submit')}
        </button>
      </div>
    </motion.div>
  );
}

// ─── The final project draft ──────────────────────────────────────────────────
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
      className="bg-surface border border-gold/40 rounded-lg p-4 sm:p-5 space-y-3"
    >
      <span className="status-pill border-gold/40 bg-gold-soft text-gold">
        <Sparkles className="w-3.5 h-3.5" aria-hidden />
        {t('onboarding.draftReady')}
      </span>
      <div>
        <p className="font-display font-normal text-display-sm text-ink-strong break-words">{draft.name}</p>
        {draft.objective && <p className="font-body text-body-md text-ink-light mt-1">{draft.objective}</p>}
      </div>
      {/* The team is not part of the draft: the agent interviews about the project, and the
          patron picks who works on it from their own agents once it exists (FR-007l). */}
      <p className="font-body text-body-sm text-ink-muted">{t('onboarding.draftTeamNext')}</p>
      <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
        <button
          type="button"
          onClick={onRestart}
          disabled={finalizing}
          className="btn btn-ghost -ml-3"
        >
          <RotateCcw className="w-4 h-4" aria-hidden />
          {t('onboarding.startOver')}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={finalizing}
          className="btn btn-primary disabled:cursor-wait"
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
      <div className="w-12 h-12 rounded-full border border-danger/30 bg-danger-soft flex items-center justify-center">
        <AlertCircle className="w-6 h-6 text-danger" aria-hidden />
      </div>
      <p className="font-display font-normal text-display-sm text-ink-strong">{t('onboarding.waOffline')}</p>
      <p className="font-body text-body-md text-ink-light max-w-sm">{t('onboarding.waOfflineHint')}</p>
      <button
        type="button"
        onClick={onRetry}
        className="btn btn-primary"
      >
        <RotateCcw className="w-4 h-4" aria-hidden />
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
      <div className={`max-w-[85%] sm:max-w-[80%] min-w-0 ${isAgent ? '' : 'text-right'}`}>
        <p className="eyebrow mb-1.5">{isAgent ? agent : you}</p>
        <div
          className={`inline-block px-3.5 py-2.5 border font-body text-body-md leading-relaxed whitespace-pre-wrap break-words text-left text-ink ${
            isAgent
              ? 'bg-canvas-deep border-line rounded-[3px_12px_12px_12px]'
              : 'bg-sapphire-soft border-sapphire/25 rounded-[12px_3px_12px_12px]'
          }`}
        >
          {turn.text}
        </div>
      </div>
    </motion.div>
  );
}
