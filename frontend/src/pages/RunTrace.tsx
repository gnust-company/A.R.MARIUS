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
import { AlertTriangle, ArrowLeft, Circle, Loader2, MessageSquare, Wrench } from 'lucide-react';

import { getRun, readRunEventInFull, type RunEventDTO } from '@/lib/api';
import { useRunTrace } from '@/hooks/use-run-trace';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import PageTitle from '@/components/PageTitle';

/** A safe i18n key segment: the daemon's codes are snake_case, and anything else is a code this
 *  screen has never heard of rather than a path into the phrase table. */
function segment(code: string): string {
  return /^[a-z0-9_]+$/.test(code) ? code : 'unknown';
}

// One meaning per colour, as everywhere else: sapphire is a tool at work, success is the agent
// saying something, danger is something broken, faint is the bookkeeping in between. Read off
// the type name so a type this screen has not met yet still lands somewhere sensible.
type Tone = 'tool' | 'said' | 'broken' | 'quiet';

function toneOf(event: RunEventDTO): Tone {
  if (/error|fail/.test(event.type) || typeof event.payload?.code === 'string') return 'broken';
  if (event.type.startsWith('tool.')) return 'tool';
  if (event.type === 'assistant.message' || /completed|done|success/.test(event.type)) return 'said';
  return 'quiet';
}

const TONE: Record<Tone, { chip: string; icon: typeof Circle }> = {
  tool: { chip: 'bg-sapphire-soft text-sapphire-strong', icon: Wrench },
  said: { chip: 'bg-success-soft text-success', icon: MessageSquare },
  broken: { chip: 'bg-danger-soft text-danger', icon: AlertTriangle },
  quiet: { chip: 'bg-canvas-deep text-ink-light', icon: Circle },
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

function EventRow({ runId, event, first, last }: { runId: string; event: RunEventDTO; first?: boolean; last?: boolean }) {
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
  const tone = TONE[toneOf(event)];
  const Icon = tone.icon;

  return (
    <div
      data-testid="run-trace-event"
      data-seq={event.seq}
      data-type={event.type}
      className="relative flex gap-3 px-3 py-3.5 sm:gap-4 sm:px-5"
    >
      {/* When and which, in mono beside the spine — a log is read down this column. */}
      <div className="hidden w-[78px] shrink-0 pt-1.5 text-right font-mono text-[10px] leading-relaxed text-ink-muted sm:block">
        <div>{formatTime(event.created_at)}</div>
        <div>#{event.seq}</div>
      </div>

      {/* The timeline spine, carried through the row's padding so rows join into one line. */}
      <div className="relative flex w-7 shrink-0 justify-center self-stretch">
        <span
          aria-hidden="true"
          className={cn('absolute w-px bg-line-strong', first ? 'top-3.5' : '-top-3.5', last ? 'bottom-[calc(100%-14px)]' : '-bottom-3.5')}
        />
        <span className={cn('relative grid h-7 w-7 place-items-center rounded-full ring-4 ring-surface', tone.chip)}>
          <Icon className="h-3.5 w-3.5" />
        </span>
      </div>

      <div className="min-w-0 flex-1 pt-0.5">
        <div className="mb-1.5 flex flex-wrap items-center gap-1.5">
          <span className={cn('rounded-[4px] px-1.5 py-0.5 font-mono text-[11px] font-medium', tone.chip)}>
            {event.type}
          </span>
          {name && (
            <span className="break-all rounded-[4px] border border-line px-1.5 py-0.5 font-mono text-[11px] text-ink">
              {name}
            </span>
          )}
          <span className="ml-auto font-mono text-[10px] text-ink-muted sm:hidden">
            #{event.seq} · {formatTime(event.created_at)}
          </span>
        </div>

        {text && (
          <div className="whitespace-pre-wrap break-words font-body text-[14px] leading-relaxed text-ink">
            {whole ?? text}
          </div>
        )}

        {args && (
          <pre className="mt-2 overflow-x-auto rounded-md border border-line bg-canvas-deep p-2.5 font-mono text-[11px] text-ink-light">
            {whole && event.full_field === 'args' ? whole : JSON.stringify(args, null, 2)}
          </pre>
        )}

        {/* Why part of this row is missing, rather than a gap that reads as an agent doing
            nothing (FR-047). Two reasons, told apart on purpose. */}
        {event.omission_reason && (
          <div className="mt-1.5 font-body text-[12px] text-ink-muted">
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
          <div className="mt-1.5 font-body text-[12px] text-ink-muted">
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
            className="btn-text mt-1 min-h-[36px] text-[12px] disabled:cursor-wait"
          >
            {opening && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {whole === null
              ? t('runTrace.openTheWhole', { bytes: event.full_byte_size ?? 0 })
              : t('runTrace.foldItBack')}
          </button>
        )}

        {failed && <div className="mt-1 font-body text-[12px] text-danger">{failed}</div>}
      </div>
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
      className="flex-1 overflow-y-auto rounded-lg border border-line bg-surface py-1.5"
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
            <EventRow runId={runId} event={events[row.index]} first={row.index === 0} last={row.index === events.length - 1} />
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
  // The run itself, read once, and only to explain an EMPTY log. A run that produced nothing is
  // a fact about the run — it timed out, it was refused, it is still starting — and until now
  // this page answered every empty with *no events match this filter*, which blames the filter
  // for something the filter did not do (T171, SC-013). Failure to read it is not worth showing:
  // the page still says the log is empty, just without naming why.
  const [outcome, setOutcome] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let dropped = false;
    void getRun(runId)
      .then((run) => {
        if (!dropped) setOutcome(run.status);
      })
      .catch(() => {});
    return () => {
      dropped = true;
    };
  }, [runId]);

  const shown = useMemo(
    () => (only.length === 0 ? events : events.filter((e) => only.includes(e.type))),
    [events, only],
  );

  function toggle(kind: string) {
    setOnly((chosen) =>
      chosen.includes(kind) ? chosen.filter((k) => k !== kind) : [...chosen, kind],
    );
  }

  // How many rows each type has, so a filter says what it will leave before it is pressed.
  const perKind = useMemo(() => {
    const counted: Record<string, number> = {};
    for (const e of events) counted[e.type] = (counted[e.type] ?? 0) + 1;
    return counted;
  }, [events]);

  const PILL = 'inline-flex min-h-[36px] items-center gap-1.5 rounded-full border px-3 font-mono text-[11px] transition-colors';
  const pillTone = (active: boolean) =>
    active
      ? 'border-sapphire bg-sapphire-soft text-sapphire-strong'
      : 'border-line-strong bg-surface text-ink-light hover:border-sapphire hover:text-ink-strong';
  const NOTE = 'rounded-lg border border-line bg-surface px-5 py-5 font-body text-body-md text-ink-muted';

  return (
    <div className="mx-auto flex h-full w-full max-w-[1240px] flex-col gap-5">
      <div className="flex shrink-0 flex-col gap-4">
        <Link
          to={wsHref(workspaceId, 'agents')}
          className="inline-flex min-h-[44px] items-center gap-2 self-start font-body text-[15px] text-ink transition-colors hover:text-sapphire-strong"
        >
          <ArrowLeft className="h-[18px] w-[18px]" />
          {t('common.back')}
        </Link>

        <PageTitle
          eyebrow={t('runTrace.eyebrow', { id: (runId ?? '').slice(0, 8) })}
          title={t('runTrace.title')}
          subtitle={<span data-testid="run-trace-count">{t('runTrace.count', { count: events.length })}</span>}
          actions={
            live ? (
              <span className="status-pill border-sapphire/40 text-sapphire-strong">
                <span className="status-dot animate-pulse bg-sapphire" />
                {t('runTrace.live')}
              </span>
            ) : undefined
          }
        />

        {kinds.length > 0 && (
          <div className="flex flex-wrap gap-1.5" data-testid="run-trace-filters">
            <button
              onClick={() => setOnly([])}
              aria-pressed={only.length === 0}
              className={cn(PILL, 'font-body text-[12px]', pillTone(only.length === 0))}
            >
              {t('runTrace.everything')}
              <span className="font-mono text-[10px] opacity-70">{events.length}</span>
            </button>
            {kinds.map((kind) => (
              <button
                key={kind}
                data-testid={`run-trace-filter-${kind}`}
                onClick={() => toggle(kind)}
                aria-pressed={only.includes(kind)}
                className={cn(PILL, 'max-w-full break-all', pillTone(only.includes(kind)))}
              >
                {kind}
                <span className="text-[10px] opacity-70">{perKind[kind] ?? 0}</span>
              </button>
            ))}
          </div>
        )}
      </div>

      {loading && events.length === 0 ? (
        <p className={NOTE}>{t('runTrace.loading')}</p>
      ) : error ? (
        <p className="flex items-start gap-2 rounded-lg border border-danger/35 bg-danger-soft px-5 py-4 font-body text-body-md text-danger">
          <AlertTriangle className="mt-0.5 h-[18px] w-[18px] shrink-0" />
          {error}
        </p>
      ) : shown.length === 0 ? (
        <p className={NOTE}>
          {events.length > 0
            ? t('runTrace.nothing')
            : outcome
              ? t('runTrace.noEventsAtAll', { outcome: t('runTrace.outcome.' + outcome, outcome) })
              : t('runTrace.noEventsAtAllUnknown')}
        </p>
      ) : (
        <VirtualLog runId={runId!} events={shown} />
      )}
    </div>
  );
}
