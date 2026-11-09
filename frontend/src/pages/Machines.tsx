// The machines screen (T069, FR-003, FR-007a, FR-033).
//
// A person links a machine and, until now, had nowhere to look at it again. The only list of
// workplaces feeds the "add an agent" form, and that one deliberately shows **ready ones
// only** — right for choosing, wrong for looking: the thing somebody most needs to see is the
// workplace that has just broken, and who is stranded on it.
//
// So this screen shows everything, and says why when something cannot take work. The reason
// arrives as a **code** and is worded here, in the reader's own language (Constitution VI,
// Constitution VII); a code with no phrase still produces a sentence rather than leaking the
// key onto the screen.
//
// Layout follows the Đài quan sát "Máy & runtime" view: a summary strip, then one card per
// machine (identity · last beat · concurrency stepper) over a runtime table.
import { useEffect, useState, useCallback } from 'react';
import { Link, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  Bot,
  CloudOff,
  Cpu,
  ExternalLink,
  HeartPulse,
  Laptop,
  Loader2,
  Minus,
  Plug,
  Plus,
  RefreshCw,
  Terminal,
  Trash2,
  WifiOff,
} from 'lucide-react';
import {
  listMachines,
  removeMachine,
  updateMachine,
  type MachineDTO,
  type MachineWorkplaceDTO,
} from '@/lib/api';
import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
import { DOCS } from '@/lib/docs';
import { cn } from '@/lib/utils';
import { errorText } from '@/lib/errors';

/** The server's bounds for the per-machine ceiling (MIN_CEILING / MAX_CEILING, FR-008). The
 *  server still has the last word — an out-of-range number comes back as its own error. */
const CEILING_MIN = 1;
const CEILING_MAX = 64;

function relative(iso: string | null, language: string): string {
  if (!iso) return '—';
  const rtf = new Intl.RelativeTimeFormat(language || 'en', { numeric: 'auto' });
  const diff = (new Date(iso).getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 60) return rtf.format(Math.round(diff), 'second');
  if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
  if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
  return rtf.format(Math.round(diff / 86400), 'day');
}

/** Put the `commands` a sentence names in code type, so `armarius-daemon start` reads as
 *  something to type rather than as prose. The words themselves come from i18n untouched. */
function withCode(text: string) {
  return text.split('`').map((part, i) =>
    i % 2 === 1 ? (
      <code key={i} className="rounded-xs border border-line bg-canvas-deep px-1 py-px font-mono text-mono-sm text-gold">
        {part}
      </code>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

// ─── One agent CLI on one machine: a row of the runtime table ────────────────

function Workplace({ place }: { place: MachineWorkplaceDTO }) {
  const { t } = useTranslation();
  // An unknown code still becomes a sentence. Falling back to the code itself would put a
  // developer's key in front of a patron, which is the thing the code/phrase split exists
  // to prevent.
  const why = place.not_ready_reason
    ? t(`machines.notReady.${place.not_ready_reason}`, {
        defaultValue: t('machines.notReady.unknown'),
      })
    : null;

  return (
    <div className="grid grid-cols-1 gap-3 border-t border-line px-[19px] py-[17px] md:min-h-[72px] md:grid-cols-[1fr_1fr_1.25fr] md:items-center md:gap-5 md:px-6 md:py-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <Terminal className="h-[19px] w-[19px] shrink-0 text-ink-muted" aria-hidden />
        <div className="min-w-0">
          <p className="truncate font-mono text-[13px] font-medium text-ink-strong">{place.cli_kind}</p>
          <p className="truncate font-mono text-[10px] text-ink-muted">{place.cli_version || '—'}</p>
        </div>
      </div>

      <div className="min-w-0">
        {place.ready ? (
          <StatusChip status="online" label={t('machines.ready')} />
        ) : (
          <StatusChip status="blocked" label={t('machines.notReadyChip')} />
        )}
        {why && <p className="mt-1.5 font-body text-[12px] leading-snug text-ink-light">{why}</p>}
      </div>

      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <span className="sr-only">{t('machines.agentsHeading')}</span>
        {place.agents.length > 0 ? (
          place.agents.map((agent) => (
            <span
              key={agent.id}
              className="inline-flex max-w-full items-center gap-1.5 rounded-sm border border-line px-[7px] py-1 font-body text-[11px] text-ink-light"
            >
              <Bot className="h-3.5 w-3.5 shrink-0 text-ink-muted" aria-hidden />
              <span className="truncate">{agent.name}</span>
            </span>
          ))
        ) : (
          <span className="font-body text-[12px] text-ink-muted">{t('machines.noAgentsHere')}</span>
        )}
      </div>
    </div>
  );
}

// ─── The concurrency stepper ─────────────────────────────────────────────────

function CeilingStepper({
  machine,
  onChanged,
}: {
  machine: MachineDTO;
  onChanged: (m: MachineDTO) => void;
}) {
  const { t } = useTranslation();
  const { workspaceId } = useParams();
  // What is typed, or nothing typed yet. Held as *the edit* rather than as a copy of the
  // machine, so a reload or somebody else's change corrects the box without an effect
  // reaching in to overwrite it — and dropping the edit is all it takes to follow the server.
  const [typed, setTyped] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = machine.max_concurrent;
  const shown = typed ?? String(current);
  const name = machine.display_name || t('machines.unnamed');

  function commit(wanted: number) {
    if (!workspaceId || !Number.isInteger(wanted) || wanted === current) {
      setTyped(null);
      return;
    }
    setSaving(true);
    setError(null);
    updateMachine(workspaceId, machine.id, { max_concurrent: wanted })
      .then(onChanged)
      .catch((e) => setError(errorText(e, t)))
      .finally(() => {
        setSaving(false);
        setTyped(null);
      });
  }

  const step =
    'grid h-[38px] w-[38px] place-items-center text-ink-light transition-colors hover:enabled:bg-surface-hover hover:enabled:text-ink-strong disabled:cursor-not-allowed disabled:opacity-40';

  return (
    <div className="min-w-0">
      {/* The ceiling (FR-008). Beside the machine rather than inside a settings page: it is
          a fact about this machine, and the person setting it is looking at the machine. */}
      <label htmlFor={`ceiling-${machine.id}`} className="mb-[5px] block font-body text-[11px] text-ink-muted">
        {t('machines.ceilingLabel')}
      </label>
      <div className="flex items-center gap-2">
        <div className="inline-flex items-center overflow-hidden rounded-md border border-line-strong bg-surface">
          <button
            type="button"
            className={step}
            disabled={saving || current <= CEILING_MIN}
            onClick={() => commit(current - 1)}
            aria-label={t('machines.ceilingDown', { name })}
          >
            <Minus className="h-4 w-4" aria-hidden />
          </button>
          <input
            id={`ceiling-${machine.id}`}
            type="number"
            inputMode="numeric"
            min={CEILING_MIN}
            max={CEILING_MAX}
            value={shown}
            disabled={saving}
            onChange={(e) => setTyped(e.target.value)}
            onBlur={() => commit(Number(shown))}
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.currentTarget.blur();
            }}
            className="h-[38px] w-[46px] border-x border-line bg-transparent text-center font-mono text-[13px] text-ink-strong outline-none [appearance:textfield] focus:bg-canvas-deep disabled:opacity-60 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
          />
          <button
            type="button"
            className={step}
            disabled={saving || current >= CEILING_MAX}
            onClick={() => commit(current + 1)}
            aria-label={t('machines.ceilingUp', { name })}
          >
            <Plus className="h-4 w-4" aria-hidden />
          </button>
        </div>
        {saving && <Loader2 className="h-4 w-4 animate-spin text-ink-muted" aria-hidden />}
      </div>
      {error && (
        <p className="mt-1.5 max-w-[260px] font-body text-[12px] text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

// ─── One machine ─────────────────────────────────────────────────────────────

function Machine({
  machine,
  onChanged,
  onRemoved,
}: {
  machine: MachineDTO;
  onChanged: (m: MachineDTO) => void;
  onRemoved: (id: string) => void;
}) {
  const { t, i18n } = useTranslation();
  // Removing a machine withdraws its credential, and nothing brings it back — the daemon has
  // to link again. So it asks first, and the question names the machine rather than saying
  // "are you sure": a person with four machines on screen needs to know which one this is.
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const { workspaceId } = useParams();
  const online = machine.reachable;

  function remove() {
    if (!workspaceId) return;
    setRemoving(true);
    setRemoveError(null);
    removeMachine(workspaceId, machine.id)
      .then(() => onRemoved(machine.id))
      .catch((e) => {
        setRemoveError(errorText(e, t));
        setRemoving(false);
        setConfirming(false);
      });
  }

  return (
    <motion.section
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn('overflow-hidden rounded-lg border border-line', online ? 'bg-surface' : 'bg-surface/75')}
    >
      <header className="grid grid-cols-1 gap-[18px] p-[19px] md:grid-cols-[minmax(0,1fr)_auto] md:items-center md:gap-6 md:px-6 md:py-[22px] xl:grid-cols-[minmax(0,1fr)_minmax(160px,0.55fr)_auto]">
        <div className="flex min-w-0 items-center gap-3.5">
          {online ? (
            <Laptop className="h-7 w-7 shrink-0 text-sapphire-strong" strokeWidth={1.4} aria-hidden />
          ) : (
            <WifiOff className="h-7 w-7 shrink-0 text-ink-muted" strokeWidth={1.4} aria-hidden />
          )}
          <div className="min-w-0">
            <p className={cn('eyebrow', online && 'text-success')}>
              {online ? t('machines.online') : t('machines.offline')}
            </p>
            <h2 className="mt-[3px] mb-px truncate font-display text-[22px] font-normal leading-tight tracking-[-0.015em] text-ink-strong sm:text-[24px]">
              {machine.display_name || t('machines.unnamed')}
            </h2>
            <p className="truncate font-body text-[12px] text-ink-light">
              <span className="font-mono">{machine.platform || '—'}</span>
              {' · '}
              {t('machines.daemonVersion')} <span className="font-mono">{machine.daemon_version || '—'}</span>
              <span className="hidden md:inline xl:hidden">
                {' · '}
                {t('machines.lastBeat')} {relative(machine.last_heartbeat_at, i18n.language)}
              </span>
            </p>
          </div>
        </div>

        {/* On a phone the last beat and the stepper share one row; from md up they become
            columns of the header grid (`md:contents`). */}
        <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-3 md:contents">
        {/* Last beat: its own column on a wide screen, folded into the subline at md. */}
        <div className="flex items-center gap-2.5 self-center md:hidden xl:flex">
          <span className={cn('status-dot', online ? 'bg-success' : 'bg-ink-faint')} aria-hidden />
          <div className="min-w-0">
            <p className="font-body text-[11px] text-ink-muted">{t('machines.lastBeat')}</p>
            <p className="mt-0.5 font-body text-[12px] font-medium text-ink-light">
              {relative(machine.last_heartbeat_at, i18n.language)}
            </p>
          </div>
        </div>

        <CeilingStepper machine={machine} onChanged={onChanged} />
        </div>
      </header>

      {/* Why this machine's daemon is not keeping itself current (FR-008n, revised
          2026-10-28). It used to say so only in its own log, which is where the owner's
          machine said it for weeks while nobody looked. A code from the daemon, worded here. */}
      {machine.update_problem && (
        <div
          className="mx-[18px] mb-4 flex items-start gap-3 rounded-md border border-warning/30 bg-warning/[0.07] px-[15px] py-[13px] md:mx-6 md:mb-[18px]"
          role="status"
        >
          <CloudOff className="mt-0.5 h-5 w-5 shrink-0 text-warning" aria-hidden />
          <p className="min-w-0 font-body text-[12px] leading-relaxed text-ink">
            {t(`machines.updateProblem.${machine.update_problem}`, {
              defaultValue: t('machines.updateProblem.unknown'),
            })}
          </p>
        </div>
      )}

      {machine.workplaces.length > 0 ? (
        <div>
          <div
            className="hidden border-t border-line bg-canvas-deep/40 px-6 py-3 font-mono text-[9px] uppercase tracking-[0.11em] text-ink-muted md:grid md:grid-cols-[1fr_1fr_1.25fr] md:gap-5"
            aria-hidden
          >
            <span>{t('machines.runtimeColumn')}</span>
            <span>{t('machines.statusColumn')}</span>
            <span>{t('machines.agentsHeading')}</span>
          </div>
          {machine.workplaces.map((place) => (
            <Workplace key={place.id} place={place} />
          ))}
        </div>
      ) : (
        // Two ways to have no workplaces, and they need different things done about them.
        // A machine that has never sent a beat was linked and then never started — the
        // discovery that registers workplaces happens in `start`, not in `login`. A machine
        // that *is* beating and still reports nothing has been asked and genuinely found no
        // agent CLI installed. Saying only "this machine has reported no agent CLI" is true of
        // both and useful for neither (FR-008h).
        <p className="border-t border-line px-[19px] py-4 font-body text-body-sm text-ink-light md:px-6">
          {withCode(machine.last_heartbeat_at === null ? t('machines.neverStarted') : t('machines.noCliFound'))}
        </p>
      )}

      {/* Removing a machine is the only way to take its token back, and there is no undo:
          the daemon has to link again. So it asks, and the question names the machine. */}
      <footer className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-t border-line px-[19px] py-3 md:px-6">
        <p className="min-w-0 flex-[1_1_240px] font-body text-[12px] text-ink-muted">{t('machines.ceilingHint')}</p>
        {!confirming && (
          <button type="button" onClick={() => setConfirming(true)} className="btn btn-ghost btn-sm text-danger hover:enabled:text-danger">
            <Trash2 className="h-4 w-4" aria-hidden /> {t('machines.remove')}
          </button>
        )}
      </footer>

      {confirming && (
        <div className="mx-[18px] mb-4 flex flex-wrap items-center gap-2 rounded-md border border-danger/30 bg-danger-soft px-4 py-3 md:mx-6">
          <span className="min-w-0 flex-[1_1_260px] font-body text-body-sm text-ink">
            {t('machines.removeConfirm', { name: machine.display_name || machine.id })}
          </span>
          <button type="button" onClick={() => setConfirming(false)} disabled={removing} className="btn btn-secondary btn-sm">
            {t('machines.removeNo')}
          </button>
          <button type="button" onClick={remove} disabled={removing} className="btn btn-danger btn-sm">
            {removing && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            {t('machines.removeYes')}
          </button>
        </div>
      )}
      {removeError && (
        <p className="mx-[18px] mb-4 font-body text-body-sm text-danger md:mx-6" role="alert">
          {removeError}
        </p>
      )}
    </motion.section>
  );
}

// ─── The screen ──────────────────────────────────────────────────────────────

export default function Machines() {
  const { workspaceId } = useParams();
  const { t } = useTranslation();
  const [machines, setMachines] = useState<MachineDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloading, setReloading] = useState(false);

  // No state set on the way in, only on the way back: the first read is announced by
  // `machines` still being null, and the spinner on the button belongs to the person who
  // pressed it.
  const load = useCallback(() => {
    if (!workspaceId) return Promise.resolve();
    return listMachines(workspaceId)
      .then((rows) => {
        setMachines(rows);
        setError(null);
      })
      .catch((e) => setError(errorText(e, t)));
  }, [workspaceId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const reload = () => {
    setReloading(true);
    void load().finally(() => setReloading(false));
  };

  const onlineCount = machines?.filter((m) => m.reachable).length ?? 0;
  // Only versions machines actually reported — no "latest release" is known on this side.
  const versions = [...new Set((machines ?? []).map((m) => m.daemon_version).filter(Boolean))];

  const linkButton = (
    <Link to="/link" className="btn btn-primary">
      <Plug className="h-4 w-4" aria-hidden />
      {t('machines.linkMachine')}
    </Link>
  );

  return (
    <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 pb-10">
      <PageTitle
        eyebrow={t('machines.eyebrow')}
        title={t('machines.title')}
        subtitle={t('machines.subtitle')}
        actions={
          <>
            <button type="button" onClick={reload} disabled={reloading} className="btn btn-ghost">
              <RefreshCw className={cn('h-4 w-4', reloading && 'animate-spin')} aria-hidden />
              {t('machines.refresh')}
            </button>
            {linkButton}
          </>
        }
      />

      {error && (
        <div
          className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-4 py-3 font-body text-body-sm text-danger"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span className="min-w-0">{error}</span>
        </div>
      )}

      {machines === null ? (
        <div className="flex items-center justify-center gap-2 py-12 font-body text-body-md text-ink-muted">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {t('machines.loading')}
        </div>
      ) : machines.length === 0 ? (
        <section className="surface flex flex-col items-center px-5 py-12 text-center sm:px-8">
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-line bg-canvas-deep text-ink-muted">
            <Cpu className="h-6 w-6" strokeWidth={1.5} aria-hidden />
          </span>
          <h2 className="font-display text-display-sm text-ink-strong">{t('machines.empty.title')}</h2>
          <p className="mt-2 max-w-xl font-body text-body-md text-ink-light">{t('machines.empty.description')}</p>
          {/* Two ways out, because the old screen offered none: it named a command and left the
              reader to work out what a daemon is and where to get one (FR-008h). */}
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2.5">
            {linkButton}
            <a href={DOCS.machines} target="_blank" rel="noreferrer" className="btn btn-secondary">
              {t('machines.empty.readGuide')}
              <ExternalLink className="h-3.5 w-3.5 text-ink-muted" aria-hidden />
            </a>
          </div>
        </section>
      ) : (
        <>
          <div className="surface flex items-center gap-3.5 px-4 py-4 sm:px-[22px] sm:py-[18px]">
            <HeartPulse className={cn('h-[22px] w-[22px] shrink-0', onlineCount > 0 ? 'text-success' : 'text-ink-muted')} aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="font-display text-[17px] font-normal text-ink-strong sm:text-[19px]">
                {t('machines.summary', { online: onlineCount, total: machines.length })}
              </p>
              <p className="mt-0.5 font-body text-[12px] text-ink-light">{t('machines.summaryHint')}</p>
            </div>
            {versions.length > 0 && (
              <code className="hidden shrink-0 font-mono text-[11px] text-ink-muted md:block">
                armarius-daemon {versions.join(' · ')}
              </code>
            )}
          </div>

          <div className="flex flex-col gap-3.5">
            {machines.map((machine) => (
              <Machine
                key={machine.id}
                machine={machine}
                onChanged={(fresh) =>
                  setMachines((rows) => (rows ?? []).map((row) => (row.id === fresh.id ? fresh : row)))
                }
                onRemoved={(id) => setMachines((rows) => (rows ?? []).filter((row) => row.id !== id))}
              />
            ))}
          </div>

          <section className="flex flex-col gap-3 rounded-lg border border-dashed border-line-strong px-[18px] py-5 sm:flex-row sm:items-center sm:gap-[15px] sm:px-[22px]">
            <Terminal className="h-[23px] w-[23px] shrink-0 text-gold" aria-hidden />
            <div className="min-w-0 flex-1">
              <h3 className="font-display text-[20px] font-normal text-ink-strong">{t('machines.noteTitle')}</h3>
              <p className="mt-1 font-body text-[13px] leading-relaxed text-ink-light">{withCode(t('machines.noteBody'))}</p>
            </div>
            <a href={DOCS.machines} target="_blank" rel="noreferrer" className="btn-text shrink-0">
              {t('machines.guide')}
              <ExternalLink className="h-3.5 w-3.5" aria-hidden />
            </a>
          </section>
        </>
      )}
    </div>
  );
}
