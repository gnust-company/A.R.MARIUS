import { useState } from 'react';
import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import { cn } from '@/lib/utils';
import type { TraceEvent } from '@/store/appStore';
import { formatClock, segment } from './format';

// Same meanings as the run trace page: sapphire = a tool call in flight, success = words and a
// clean finish, danger = failure, faint = bookkeeping.
const TONE_SAPPHIRE = { dot: 'bg-sapphire', chip: 'bg-sapphire-soft text-sapphire-strong' };
const TONE_SUCCESS = { dot: 'bg-success', chip: 'bg-success-soft text-success' };
const TONE_DANGER = { dot: 'bg-danger', chip: 'bg-danger-soft text-danger' };
const TONE_FAINT = { dot: 'bg-ink-faint', chip: 'bg-canvas-deep text-ink-light' };

const TRACE_TONES: Record<string, { dot: string; chip: string }> = {
  'run.delta': TONE_SUCCESS,
  'run.tool': TONE_SAPPHIRE,
  'run.usage': TONE_FAINT,
  'run.complete': TONE_SUCCESS,
  'run.error': TONE_DANGER,
  'agent.comment': TONE_FAINT,
  'agent.status': TONE_FAINT,
};

/** One event of the live wake trace, drawn as a step on a timeline. Click to read it whole. */
export default function TraceEventCard({ event, last }: { event: TraceEvent; last?: boolean }) {
  const { t } = useTranslation();
  const [isExpanded, setIsExpanded] = useState(false);
  const tone = TRACE_TONES[event.type] || TRACE_TONES['run.delta'];

  // The daemon says what went wrong as a code with its details (Constitution VII); the sentence
  // is built here, where the reader's language is known. A code this build has no phrase for
  // still becomes a sentence — showing the raw key would put our own internals on their screen.
  const said = event.code
    ? t(`collaborationRoom.trace.error.${segment(event.code)}`, {
        defaultValue: t('collaborationRoom.trace.error.unknown', { code: event.code }),
        ...event.codeParams,
      })
    : '';
  const body = event.content || said;

  return (
    <motion.li
      initial={{ opacity: 0, y: -6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="relative pb-3 pl-6"
    >
      {/* The spine of the timeline, and this step's dot on it. */}
      {!last && <span aria-hidden="true" className="absolute bottom-0 left-[7px] top-3 w-px bg-line-strong" />}
      <span
        aria-hidden="true"
        className={cn('absolute left-[3px] top-[9px] h-[9px] w-[9px] rounded-full ring-[3px] ring-surface', tone.dot)}
      />

      <div
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
        onClick={() => setIsExpanded(!isExpanded)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsExpanded(!isExpanded);
          }
        }}
        className="cursor-pointer rounded-md border border-line bg-field px-3 py-2 transition-colors hover:border-line-strong"
      >
        <div className="mb-1 flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
          <span className={cn('rounded-[4px] px-1.5 py-0.5 font-mono text-[10px] font-medium', tone.chip)}>
            {event.type}
          </span>
          <span className="font-mono text-[10px] text-ink-muted">{formatClock(event.timestamp)}</span>
        </div>

        {event.model && <div className="mb-1 font-mono text-[10px] text-ink-light">model: {event.model}</div>}

        {event.tokens && (
          <div className="mb-1 font-mono text-[10px] text-ink-light">
            tokens: {event.tokens.used} / {event.tokens.total}
            {event.tokens.prompt !== undefined && (
              <span className="ml-1 text-ink-muted">
                (prompt: {event.tokens.prompt}, completion: {event.tokens.completion})
              </span>
            )}
          </div>
        )}

        {event.toolName && (
          <div className="mb-1 inline-block break-all rounded-[4px] border border-line bg-surface px-1.5 py-0.5 font-mono text-[10px] text-ink">
            {event.toolName}
          </div>
        )}

        {body && (
          <div
            className={cn(
              'whitespace-pre-wrap break-words font-body text-[12px] leading-relaxed text-ink-light',
              !isExpanded && 'line-clamp-3'
            )}
          >
            {body}
          </div>
        )}

        {/* Say what is missing and why, rather than leaving a gap (FR-047). A gap here reads as
            an agent that called no tools — a different and untrue story. */}
        {event.omission && (
          <div className="mt-1 font-mono text-[10px] text-ink-muted">
            {t(`collaborationRoom.trace.omission.${segment(event.omission.reason)}`, {
              defaultValue: t('collaborationRoom.trace.omission.unknown'),
            })}
            {event.omission.originalBytes !== undefined && (
              <span className="ml-1">
                {t('collaborationRoom.trace.omission.size', { bytes: event.omission.originalBytes })}
              </span>
            )}
          </div>
        )}

        {event.redacted && (
          <div className="mt-1 font-mono text-[10px] text-ink-muted">{t('collaborationRoom.trace.redacted')}</div>
        )}

        {event.args && isExpanded && (
          <pre className="mt-1.5 overflow-x-auto rounded-[4px] border border-line bg-canvas-deep p-2 font-mono text-[10px] text-ink-light">
            {JSON.stringify(event.args, null, 2)}
          </pre>
        )}
      </div>
    </motion.li>
  );
}
