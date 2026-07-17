// @ts-nocheck
import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import {
  Send,
  Bot,
  Lock,
  Loader2,
  Star,
  ArrowRight,
  ChevronLeft,
  WifiOff,
} from 'lucide-react';
import { useMockStore } from '@/store/mockStore';
import VellumPanel from '@/components/VellumPanel';
import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
import { cn, wsHref } from '@/lib/utils';
import * as api from '@/lib/api';

// ─── Transcript message (derived from the real CommissionDTO.transcript) ─────────
// The backend records the Patron's turns on the session; the Leader shapes the draft
// Task itself (surfaced in the preview pane), so the chat shows the request thread plus
// system notes — never a fabricated Leader reply.

interface CommissionMessage {
  id: string;
  role: 'patron' | 'leader' | 'system';
  content: string;
  timestamp: string;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

// Map the real transcript (backend turns) → renderable messages. Unknown roles fall back
// to `leader` so nothing is dropped; the backend uses `patron` for Patron turns.
function transcriptToMessages(
  transcript: Array<{ role: string; text: string }> | undefined,
): CommissionMessage[] {
  return (transcript ?? []).map((turn, i) => ({
    id: `turn-${i}`,
    role: turn.role === 'patron' ? 'patron' : turn.role === 'system' ? 'system' : 'leader',
    content: turn.text,
    timestamp: '',
  }));
}

// ─── Sub-components ──────────────────────────────────────────────────────────

function LeaderAvatar({ label, isThinking }: { label: string; isThinking: boolean }) {
  const initial = (label || 'L').charAt(0).toUpperCase();
  return (
    <div className="flex flex-col items-center gap-1 flex-shrink-0">
      <div
        className={cn(
          'w-8 h-8 rounded-full flex items-center justify-center border-2 bg-vellum-deep font-display text-body-sm text-terracotta',
          isThinking ? 'border-gold animate-pulse' : 'border-gold-muted'
        )}
      >
        {initial}
      </div>
      <span className="font-body text-body-xs text-ink-light max-w-[64px] truncate">{label}</span>
    </div>
  );
}

function ChatMessage({
  role,
  content,
  leaderLabel,
  isThinking,
}: {
  role: 'patron' | 'leader' | 'system';
  content: string;
  leaderLabel: string;
  isThinking?: boolean;
}) {
  const { t } = useTranslation();

  if (role === 'system') {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-center gap-3 my-3"
      >
        <span className="w-10 h-px bg-vellum-dark" />
        <span className="font-body text-body-xs text-ink-muted italic">{content}</span>
        <span className="w-10 h-px bg-vellum-dark" />
      </motion.div>
    );
  }

  const isPatron = role === 'patron';

  return (
    <motion.div
      initial={isPatron ? { opacity: 0, y: 10 } : { opacity: 0, x: -15 }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={{ duration: 0.3, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
      className={cn('flex gap-3 mb-4 group', isPatron ? 'flex-row-reverse' : 'flex-row')}
    >
      {!isPatron && <LeaderAvatar label={leaderLabel} isThinking={isThinking ?? false} />}

      <div
        className={cn(
          'relative max-w-[85%] px-4 py-3 font-body text-body-md',
          isPatron
            ? 'bg-terracotta text-white rounded-lg rounded-tr-sm'
            : 'bg-vellum-deep border border-vellum-dark rounded-lg rounded-tl-sm',
          isThinking && 'opacity-70'
        )}
      >
        {isThinking ? (
          <div className="flex items-center gap-2 text-ink-light">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>{t('commission.leaderThinking')}</span>
          </div>
        ) : (
          <div className={cn('whitespace-pre-wrap', !isPatron && 'text-ink')}>{content}</div>
        )}
      </div>
    </motion.div>
  );
}

// ─── Task Preview Pane (reflects the REAL draft Task the Leader is shaping) ───────

function TaskPreview({ draftTask, leaderState }: { draftTask: import('@/store/mockStore').Task | null; leaderState: string }) {
  const { t } = useTranslation();

  if (!draftTask) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-8">
        <Bot className="w-12 h-12 text-ink-muted mb-4" strokeWidth={1.5} />
        <p className="font-body text-body-md text-ink-light mb-1">{t('commission.emptyPreviewTitle')}</p>
        <p className="font-body text-body-sm text-ink-muted">{t('commission.emptyPreviewDescription')}</p>
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
      className="flex flex-col h-full overflow-y-auto"
    >
      {/* Identifier + live status */}
      <div className="mb-4 flex items-center gap-2">
        <span className="font-mono text-mono-md text-terracotta">
          {draftTask.identifier || draftTask.id.slice(0, 8)}
        </span>
        <span className="font-body text-body-xs text-ink-muted">({draftTask.status})</span>
        {leaderState === 'thinking' && (
          <span className="ml-auto inline-flex items-center gap-1 font-body text-body-xs text-gold">
            <Loader2 className="w-3 h-3 animate-spin" />
            {t('commission.shaping')}
          </span>
        )}
      </div>

      <hr className="border-vellum-dark mb-4" />

      {/* Title (as shaped by the Leader — read-only) */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('commission.fieldLabels.title')}
        </label>
        <p className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink">
          {draftTask.title}
        </p>
      </div>

      {/* Description */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('commission.fieldLabels.description')}
        </label>
        <p
          className={cn(
            'w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md whitespace-pre-wrap',
            draftTask.description ? 'text-ink' : 'text-ink-muted italic'
          )}
        >
          {draftTask.description || t('commission.noDescription')}
        </p>
      </div>
    </motion.div>
  );
}

// ─── Main Commission Page ────────────────────────────────────────────────────

export default function Commission() {
  const { id: projectId, workspaceId } = useParams<{ id: string; workspaceId: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const store = useMockStore();

  // Real commission session (from the backend) — null until the first Patron message opens one.
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<import('@/lib/api').CommissionDTO | null>(null);
  const [error, setError] = useState<string | null>(null);

  const project = store.projects.find((p) => p.id === projectId);
  const tasks = store.tasks;
  const draftTask = session?.task_id ? tasks.find((tk) => tk.id === session.task_id) || null : null;

  // Ensure the project (roster/status) is loaded so the locked gate + leader lookup work.
  useEffect(() => {
    if (!projectId) return;
    store.hydrateProject(projectId);
  }, [projectId]);

  // Resolve the REAL seated Leader from the project roster (no hardcoded "Atlas").
  const leaderSeat = (project?.seats || []).find((s) => s.role === 'leader' && s.mariusId);
  const leader = leaderSeat ? store.mariuses.find((m) => m.id === leaderSeat.mariusId) : undefined;
  const leaderLabel = leader?.displayName || leader?.name || t('commission.leaderFallback');
  const leaderState = session?.leader_state ?? 'waiting';

  const messages = transcriptToMessages(session?.transcript);

  const [inputValue, setInputValue] = useState('');
  const [isSending, setIsSending] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom as the transcript grows / the Leader works.
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, leaderState]);

  // While the Leader is shaping (thinking), poll the real session + draft task so the
  // transcript, leader_state and the shaped Task title/description refresh as work lands.
  useEffect(() => {
    if (!sessionId || leaderState !== 'thinking') return;
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const fresh = await api.getCommission(sessionId);
        if (cancelled) return;
        setSession(fresh);
        if (fresh.task_id) store.hydrateTask(fresh.task_id).catch(() => {});
      } catch {
        // transient — keep the last known state and retry on the next tick
      }
    }, 3000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [sessionId, leaderState]);

  const handleSend = useCallback(() => {
    if (!inputValue.trim() || isSending) return;
    const sentInput = inputValue.trim();
    setInputValue('');
    setError(null);
    setIsSending(true);

    void (async () => {
      try {
        if (!sessionId) {
          const dto = await api.startCommission({ project_id: projectId, message: sentInput });
          setSessionId(dto.id);
          setSession(dto);
          if (dto.task_id) store.hydrateTask(dto.task_id).catch(() => {});
        } else {
          const dto = await api.refineCommission(sessionId, { message: sentInput });
          setSession(dto);
          if (dto.task_id) store.hydrateTask(dto.task_id).catch(() => {});
        }
      } catch (e) {
        // Surface the REAL backend reason (e.g. "no Leader is seated on this project").
        setError(e instanceof Error ? e.message : t('commission.startError'));
        setInputValue(sentInput); // let the patron retry without retyping
      } finally {
        setIsSending(false);
      }
    })();
  }, [inputValue, isSending, sessionId, projectId, t]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleConfirm = async () => {
    if (!sessionId) return;
    setIsConfirming(true);
    setError(null);
    try {
      await api.confirmCommission(sessionId);
      await store.hydrateProject(projectId);
      navigate(wsHref(workspaceId, `/projects/${projectId}`));
    } catch (e) {
      setError(e instanceof Error ? e.message : t('commission.confirmError'));
      setIsConfirming(false);
    }
  };

  const backToBoard = () => navigate(wsHref(workspaceId, `/projects/${projectId}`));

  // ─── Locked state (real: project still in setup) ───
  if (project?.status === 'setup') {
    return (
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="flex items-center justify-center min-h-[60vh]"
      >
        <VellumPanel className="max-w-md w-full text-center py-16 px-8">
          <motion.div
            animate={{ y: [0, -4, 0] }}
            transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          >
            <Lock className="w-16 h-16 text-ink-muted mx-auto mb-6" strokeWidth={1.5} />
          </motion.div>
          <h2 className="font-display text-display-md text-ink mb-3">{t('commission.lockedTitle')}</h2>
          <p className="font-body text-body-lg text-ink-light mb-8">{t('commission.lockedDescription')}</p>
          <button
            onClick={() => navigate(wsHref(workspaceId, `/projects/${projectId}/roster`))}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-md bg-terracotta text-white font-body text-body-md font-medium hover:bg-terracotta-light transition-colors"
          >
            {t('commission.goToRoster')}
            <ArrowRight className="w-4 h-4" />
          </button>
        </VellumPanel>
      </motion.div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100dvh-140px)] -m-6">
      {/* ─── Page Header ─── */}
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="px-6 pt-6 pb-4 flex-shrink-0"
      >
        <button
          onClick={backToBoard}
          className="inline-flex items-center gap-1 mb-3 px-2.5 py-1.5 rounded-md bg-vellum-deep border border-vellum-dark font-body text-body-sm text-ink hover:bg-vellum-dark transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          {t('commission.backToBoard')}
        </button>
        <PageTitle
          title={t('commission.title')}
          subtitle={t('commission.subtitle', { leaderName: leaderLabel })}
        />
      </motion.div>

      {/* ─── Two-Pane Layout ─── */}
      <div className="flex flex-1 min-h-0 px-6 pb-6 gap-4">
        {/* Left: Chat (58%) */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
          className="flex-[58] flex flex-col min-h-0 bg-vellum border border-vellum-dark rounded-md overflow-hidden"
        >
          {/* Leader-offline banner (real leader_state) */}
          {leaderState === 'leader_offline' && (
            <div className="flex-shrink-0 flex items-center gap-2 px-4 py-2 bg-warning-bg border-b border-warning/20 font-body text-body-sm text-warning">
              <WifiOff className="w-4 h-4 flex-shrink-0" />
              {t('commission.leaderOffline')}
            </div>
          )}

          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {messages.length === 0 && (
              <div className="flex flex-col items-center justify-center h-full text-center px-6">
                <Bot className="w-10 h-10 text-ink-muted mb-3" strokeWidth={1.5} />
                <p className="font-body text-body-md text-ink-light">
                  {t('commission.startPrompt', { leaderName: leaderLabel })}
                </p>
              </div>
            )}
            {messages.map((msg) => (
              <ChatMessage key={msg.id} role={msg.role} content={msg.content} leaderLabel={leaderLabel} />
            ))}
            {leaderState === 'thinking' && (
              <ChatMessage role="leader" content="" leaderLabel={leaderLabel} isThinking />
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Error strip (real backend detail) */}
          {error && (
            <div className="flex-shrink-0 px-4 py-2 bg-error-bg border-t border-error/20 font-body text-body-sm text-error">
              {error}
            </div>
          )}

          {/* Composer */}
          <div className="flex-shrink-0 border-t border-vellum-dark bg-vellum-deep px-4 py-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t('commission.placeholder')}
                rows={1}
                className="flex-1 resize-none px-4 py-2.5 bg-vellum border border-vellum-dark rounded-lg font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors max-h-[120px]"
                style={{ minHeight: '40px' }}
              />
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleSend}
                disabled={!inputValue.trim() || isSending}
                className={cn(
                  'w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 transition-colors',
                  inputValue.trim() && !isSending
                    ? 'bg-terracotta text-white hover:bg-terracotta-light'
                    : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
                )}
              >
                {isSending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
              </motion.button>
            </div>
          </div>
        </motion.div>

        {/* Right: Task Preview (42%) */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
          className="flex-[42] flex flex-col min-h-0 bg-vellum-deep border border-vellum-dark rounded-md overflow-hidden"
        >
          {/* Preview Header */}
          <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-vellum-dark">
            <h2 className="font-display text-display-sm text-ink">{t('commission.previewTitle')}</h2>
            {draftTask && <StatusChip status={draftTask.status} label={draftTask.status} />}
          </div>

          {/* Preview Content */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            <TaskPreview draftTask={draftTask} leaderState={leaderState} />
          </div>

          {/* Action Buttons */}
          {draftTask && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex-shrink-0 flex gap-3 px-4 py-3 border-t border-vellum-dark"
            >
              <button
                onClick={handleConfirm}
                disabled={isConfirming || !draftTask.title}
                className={cn(
                  'flex-1 px-4 py-2.5 rounded-md font-body text-body-md font-medium transition-colors inline-flex items-center justify-center gap-2',
                  isConfirming ? 'bg-gold-muted text-ink cursor-wait' : 'bg-gold text-ink hover:bg-gold-light'
                )}
              >
                {isConfirming ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {t('commission.creating')}
                  </>
                ) : (
                  <>
                    <Star className="w-4 h-4" />
                    {t('commission.confirm')}
                  </>
                )}
              </button>
            </motion.div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
