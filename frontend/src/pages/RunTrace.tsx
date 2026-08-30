// The whole of one run, in order (T102, FR-016, FR-052, SC-011, SC-013, SC-014).
//
// Not the Room's trace panel with a filter bolted on. That panel is a **conversation**: it maps
// the log into chat bubbles and drops what it cannot draw as one. Right for watching an agent
// work, wrong for answering *what did it do and why* months later, where the events it drops —
// the message the agent was given, a tool call that returned nothing, the line saying a batch
// never arrived — are often the answer. So this page reads the raw log and shows every row.
//
// Three things make a thousand-event run usable. The list is windowed, so what is off screen
// costs nothing (SC-014). The rows are filtered by their real type names, so one tool call among
// a thousand lines is a click rather than a search (FR-052). And a long field is only ever an
// opening slice until somebody opens it, so no single event can drag a megabyte into the page
// (FR-049).

import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ChevronLeft, Loader2, Radio } from 'lucide-react';

import { readRunEventInFull, type RunEventDTO } from '@/lib/api';
import { useRunTrace } from '@/hooks/use-run-trace';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';

/** A safe i18n key segment: the daemon's codes are snake_case, and anything else is a code this
 *  screen has never heard of rather than a path into the phrase table. */
function segment(code: string): string {
  return /^[a-z0-9_]+$/.test(code) ? code : 'unknown';
}

const KIND_COLORS: Record<string, string> = {
  'run.prompt': 'border-l-ink-muted',
  'assistant.message': 'border-l-gold',
  'assistant.thinking': 'border-l-vellum-dark',
  'tool.started': 'border-l-terracotta',
  'tool.completed': 'border-l-terracotta',
  'run.error': 'border-l-error',
};

/** Only scalars, and never the underscored facts about the record — those are drawn as their
 *  own lines, and repeating them inside the error sentence says the same thing twice. */
function paramsOf(payload: Record<string, unknown>): Record<string, unknown> {
  const said: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(payload)) {
    if (key === 'code' || key.startsWith('_')) continue;
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      said[key] = value;
    }
  }
  return said;
}

/** What this row says, in the reader's language where the server sent a code. */
function useBody(event: RunEventDTO): { text: string; args?: Record<string, unknown> } {
  const { t } = useTranslation();
  const p = event.payload ?? {};
  const code = typeof p.code === 'string' ? p.code : undefined;
  if (code) {
    return {
      text: t(`collaborationRoom.trace.error.${segment(code)}`, {
        defaultValue: t('collaborationRoom.trace.error.unknown', { code }),
        ...paramsOf(p),
      }),
    };
  }
  const text = String(p.prompt ?? p.text ?? p.opening ?? p.content ?? p.message ?? '');
  const rawArgs = p.args;
  const args = rawArgs && typeof rawArgs === 'object' ? (rawArgs as Record<string, unknown>) : undefined;
  return { text, args };
}

function formatTime(iso?: string | null): string {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function EventRow({ runId, event }: { runId: string; event: RunEventDTO }) {
  const { t } = useTranslation();
  const { text, args } = useBody(event);
  const [whole, setWhole] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  async function openTheWholeOfIt() {
    setOpening(true);
    setFailed(null);
    try {
      const got = await readRunEventInFull(runId, event.seq);
      setWhole(got.content);
    } catch (e) {
      setFailed(errorText(e, t));
    } finally {
      setOpening(false);
    }
  }

  const name = typeof event.payload?.name === 'string' ? event.payload.name : undefined;

  return (
    <div
      data-testid="run-trace-event"
      data-seq={event.seq}
      data-type={event.type}
      className={cn(
        'border-l-[3px] rounded-sm bg-vellum-deep px-3 py-2 mb-1.5',
        KIND_COLORS[event.type] ?? 'border-l-vellum-dark',
      )}
    >
      <div className="flex items-center justify-between mb-1 gap-2">
        <span className="font-mono text-mono-sm font-medium text-ink-light">
          <span className="text-ink-muted mr-1.5">#{event.seq}</span>
          {event.type}
        </span>
        <span className="font-mono text-mono-sm text-ink-muted">{formatTime(event.created_at)}</span>
      </div>

      {name && (
        <div className="font-mono text-mono-sm rounded-sm px-2 py-0.5 mb-1 inline-block bg-terracotta/10 text-terracotta">
          {name}
        </div>
      )}

      {text && (
        <div className="font-body text-body-xs text-ink-light leading-relaxed whitespace-pre-wrap break-words">
          {whole ?? text}
        </div>
      )}

      {args && (
        <pre className="mt-1.5 p-2 bg-vellum rounded-sm font-mono text-mono-sm text-ink-light overflow-x-auto">
          {whole && event.full_field === 'args' ? whole : JSON.stringify(args, null, 2)}
        </pre>
      )}

      {/* Why part of this row is missing, rather than a gap that reads as an agent doing
          nothing (FR-047). Two reasons, told apart on purpose. */}
      {event.omission_reason && (
        <div className="font-mono text-mono-sm text-ink-muted mt-1">
          {t(`collaborationRoom.trace.omission.${segment(event.omission_reason)}`, {
            defaultValue: t('collaborationRoom.trace.omission.unknown'),
          })}
          {typeof event.original_byte_size === 'number' && (
            <span className="ml-1">
              {t('collaborationRoom.trace.omission.size', { bytes: event.original_byte_size })}
            </span>
          )}
        </div>
      )}

      {event.redacted && (
        <div className="font-mono text-mono-sm text-ink-muted mt-1">
          {t('collaborationRoom.trace.redacted')}
        </div>
      )}

      {/* A *fourth* state, and deliberately not one of the two above: nothing is missing here,
          it is simply not in this response yet (FR-049). Saying it the same way would tell the
          reader not to go and ask for a thing they can have. */}
      {event.full_field && (
        <button
          data-testid={whole === null ? 'run-trace-open-full' : 'run-trace-close-full'}
          onClick={whole === null ? openTheWholeOfIt : () => setWhole(null)}
          disabled={opening}
          className="mt-1.5 inline-flex items-center gap-1.5 font-mono text-mono-sm text-terracotta hover:underline disabled:opacity-60"
        >
          {opening && <Loader2 className="w-3 h-3 animate-spin" />}
          {whole === null
            ? t('runTrace.openTheWhole', { bytes: event.full_byte_size ?? 0 })
            : t('runTrace.foldItBack')}
        </button>
      )}

      {failed && <div className="font-mono text-mono-sm text-error mt-1">{failed}</div>}
    </div>
  );
}

/** The windowed list, on its own so the deopt is on its own.
 *
 *  React Compiler will not memoize a component that uses the virtualizer — the API hands back
 *  functions that cannot be memoized without going stale — so it is kept to the one component
 *  that has to have it, and the header and filters above stay compiled. */
function VirtualLog({ runId, events }: { runId: string; events: RunEventDTO[] }) {
  const scroller = useRef<HTMLDivElement>(null);
  // The list has to be told how tall it is, and nothing above it says. The app shell grows with
  // its content, so `flex-1` here resolves to *as tall as everything inside* — which is a list
  // that never scrolls and a windowed list that renders every row, the one thing windowing was
  // for. Measured against the viewport rather than hard-coded, so the chrome above can change
  // without this quietly going wrong again.
  const [fits, setFits] = useState(0);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const watch = new ResizeObserver(() => {
      setFits(Math.max(240, window.innerHeight - el.getBoundingClientRect().top - 24));
    });
    watch.observe(document.documentElement);
    return () => watch.disconnect();
  }, []);

  const rows = useVirtualizer({
    count: events.length,
    getScrollElement: () => scroller.current,
    // A first guess only — every row is measured once it is drawn, so a card carrying a
    // paragraph and one carrying a single line both scroll true.
    estimateSize: () => 96,
    overscan: 12,
  });

  return (
    <div
      ref={scroller}
      data-testid="run-trace-scroller"
      className="flex-1 overflow-y-auto px-4 py-3"
      style={fits ? { height: fits, flex: 'none' } : undefined}
    >
      <div style={{ height: rows.getTotalSize(), position: 'relative' }}>
        {rows.getVirtualItems().map((row) => (
          <div
            key={events[row.index].seq}
            data-index={row.index}
            ref={rows.measureElement}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              transform: `translateY(${row.start}px)`,
            }}
          >
            <EventRow runId={runId} event={events[row.index]} />
          </div>
        ))}
      </div>
    </div>
  );
}

export default function RunTrace() {
  const { t } = useTranslation();
  const { workspaceId, runId } = useParams<{ workspaceId: string; runId: string }>();
  const { events, kinds, loading, error, live } = useRunTrace(runId);
  const [only, setOnly] = useState<string[]>([]);

  const shown = useMemo(
    () => (only.length === 0 ? events : events.filter((e) => only.includes(e.type))),
    [events, only],
  );

  function toggle(kind: string) {
    setOnly((chosen) =>
      chosen.includes(kind) ? chosen.filter((k) => k !== kind) : [...chosen, kind],
    );
  }

  return (
    <div className="h-full flex flex-col bg-vellum">
      <div className="flex-shrink-0 border-b border-vellum-dark px-4 py-3">
        <div className="flex items-center gap-2">
          <Link
            to={wsHref(workspaceId, 'agents')}
            className="p-1 rounded-md hover:bg-vellum-dark text-ink-muted"
            aria-label={t('common.back')}
          >
            <ChevronLeft className="w-4 h-4" />
          </Link>
          <h1 className="font-display text-body-sm text-ink">{t('runTrace.title')}</h1>
          <span data-testid="run-trace-count" className="font-mono text-mono-sm text-ink-muted">
            {t('runTrace.count', { count: events.length })}
          </span>
          {live && (
            <span className="ml-auto inline-flex items-center gap-1 font-mono text-mono-sm text-status-online">
              <Radio className="w-3 h-3" /> {t('runTrace.live')}
            </span>
          )}
        </div>

        {kinds.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5" data-testid="run-trace-filters">
            <button
              onClick={() => setOnly([])}
              className={cn(
                'rounded-full px-2.5 py-0.5 font-mono text-mono-sm transition-colors',
                only.length === 0 ? 'bg-terracotta text-white' : 'bg-vellum-dark text-ink-light',
              )}
            >
              {t('runTrace.everything')}
            </button>
            {kinds.map((kind) => (
              <button
                key={kind}
                data-testid={`run-trace-filter-${kind}`}
                onClick={() => toggle(kind)}
                className={cn(
                  'rounded-full px-2.5 py-0.5 font-mono text-mono-sm transition-colors',
                  only.includes(kind) ? 'bg-terracotta text-white' : 'bg-vellum-dark text-ink-light',
                )}
              >
                {kind}
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && events.length === 0 ? (
        <p className="px-4 py-3 font-body text-body-xs text-ink-muted">{t('runTrace.loading')}</p>
      ) : error ? (
        <p className="px-4 py-3 font-body text-body-xs text-error">{error}</p>
      ) : shown.length === 0 ? (
        <p className="px-4 py-3 font-body text-body-xs text-ink-muted">{t('runTrace.nothing')}</p>
      ) : (
        <VirtualLog runId={runId!} events={shown} />
      )}
    </div>
  );
}
