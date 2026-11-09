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
import { useEffect, useState, useCallback } from 'react';
import { Link, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import {
  AlertTriangle,
  BookOpen,
  Bot,
  CloudOff,
  Cpu,
  ExternalLink,
  Laptop,
  Loader2,
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
      <code key={i} className="rounded bg-inset border border-line px-1.5 py-px font-mono text-mono-sm text-ink">
        {part}
      </code>
    ) : (
      part
    )
  );
}

// ─── One agent CLI on one machine ────────────────────────────────────────────

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
    <div className="min-w-0 rounded-lg border border-line bg-inset px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5">
        <Terminal className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
        <span className="font-mono text-mono-md text-ink">{place.cli_kind}</span>
        {place.cli_version && (
          <span className="font-mono text-mono-sm text-ink-muted">{place.cli_version}</span>
        )}
        <span className="ml-auto">
          {place.ready ? (
            <StatusChip status="online" label={t('machines.ready')} />
          ) : (
            <StatusChip status="blocked" label={t('machines.notReadyChip')} />
          )}
        </span>
      </div>

      {why && <p className="mt-2 font-body text-body-sm text-vermilion-ink">{why}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <Bot className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
        {place.agents.length > 0 ? (
          place.agents.map((agent) => (
            <span
              key={agent.id}
              className="inline-flex max-w-full items-center truncate rounded-full border border-line bg-paper px-2.5 py-0.5 font-body text-body-sm font-medium text-ink"
            >
              {agent.name}
            </span>
          ))
        ) : (
          <span className="min-w-0 flex-1 font-body text-body-sm text-ink-muted">{t('machines.noAgentsHere')}</span>
        )}
      </div>
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
  // What is typed, or nothing typed yet. Held as *the edit* rather than as a copy of the
  // machine, so a reload or somebody else's change corrects the box without an effect
  // reaching in to overwrite it — and dropping the edit is all it takes to follow the server.
  const [typed, setTyped] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [ceilingError, setCeilingError] = useState<string | null>(null);
  // Removing a machine withdraws its credential, and nothing brings it back — the daemon has
  // to link again. So it asks first, and the question names the machine rather than saying
  // "are you sure": a person with four machines on screen needs to know which one this is.
  const [confirming, setConfirming] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeError, setRemoveError] = useState<string | null>(null);
  const { workspaceId } = useParams();

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
  const ceiling = typed ?? String(machine.max_concurrent);

  function save() {
    const wanted = Number(ceiling);
    if (!workspaceId || !Number.isInteger(wanted) || wanted === machine.max_concurrent) {
      setTyped(null);
      return;
    }
    setSaving(true);
    setCeilingError(null);
    updateMachine(workspaceId, machine.id, { max_concurrent: wanted })
      .then(onChanged)
      .catch((e) => setCeilingError(errorText(e, t)))
      .finally(() => {
        setSaving(false);
        setTyped(null);
      });
  }

  return (
    <motion.article
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className="rounded-xl border border-line bg-paper px-4 py-4 sm:px-5 sm:py-5"
    >
      <div className="flex gap-3.5">
        <span
          className={cn(
            'flex h-10 w-10 shrink-0 items-center justify-center rounded-full',
            machine.reachable ? 'bg-verdigris-bg text-verdigris-ink' : 'bg-ash-bg text-ink-light'
          )}
          aria-hidden
        >
          {machine.reachable ? <Laptop className="h-[18px] w-[18px]" /> : <WifiOff className="h-[18px] w-[18px]" />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
            <h2 className="min-w-0 truncate font-display text-[20px] font-medium text-ink">
              {machine.display_name || t('machines.unnamed')}
            </h2>
            <StatusChip
              status={machine.reachable ? 'online' : 'offline'}
              label={machine.reachable ? t('machines.online') : t('machines.offline')}
            />
          </div>
          <p className="mt-0.5 font-body text-body-sm text-ink-muted">
            <span className="font-mono text-mono-sm">{machine.platform || '—'}</span>
            {' · '}
            {t('machines.daemonVersion')}{' '}
            <span className="font-mono text-mono-sm">{machine.daemon_version || '—'}</span>
            {' · '}
            {t('machines.lastBeat')} {relative(machine.last_heartbeat_at, i18n.language)}
          </p>
        </div>
      </div>

      {/* Why this machine's daemon is not keeping itself current (FR-008n, revised
          2026-10-28). It used to say so only in its own log, which is where the owner's
          machine said it for weeks while nobody looked. A code from the daemon, worded here. */}
      {machine.update_problem && (
        <div
          className="mt-4 flex items-start gap-2.5 rounded-lg border border-[#EBCF8A] bg-gold-bg px-4 py-3 font-body text-body-sm text-gold-ink"
          role="status"
        >
          <CloudOff className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span className="min-w-0">
            {t(`machines.updateProblem.${machine.update_problem}`, {
              defaultValue: t('machines.updateProblem.unknown'),
            })}
          </span>
        </div>
      )}

      <div className="mt-4">
        {machine.workplaces.length > 0 ? (
          <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
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
          <p className="rounded-lg border border-dashed border-line-strong px-4 py-3 font-body text-body-md text-ink-light">
            {withCode(
              machine.last_heartbeat_at === null ? t('machines.neverStarted') : t('machines.noCliFound')
            )}
          </p>
        )}
      </div>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-x-4 gap-y-3 border-t border-line pt-4">
        {/* The ceiling (FR-008). Beside the machine rather than inside a settings page: it is
            a fact about this machine, and the person setting it is looking at the machine. */}
        <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1">
          <Cpu className="h-4 w-4 shrink-0 text-ink-muted" aria-hidden />
          <label className="font-body text-body-sm font-medium text-ink-light" htmlFor={`ceiling-${machine.id}`}>
            {t('machines.ceilingLabel')}
          </label>
          <input
            id={`ceiling-${machine.id}`}
            type="number"
            min={1}
            max={64}
            value={ceiling}
            disabled={saving}
            onChange={(e) => setTyped(e.target.value)}
            onBlur={save}
            onKeyDown={(e) => {
              if (e.key === 'Enter') e.currentTarget.blur();
            }}
            className="min-h-[44px] w-20 rounded-md border border-line bg-inset px-3 font-body text-body-md text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 disabled:opacity-60"
          />
          {saving && <Loader2 className="h-4 w-4 animate-spin text-ink-muted" aria-hidden />}
          <span className="basis-full font-body text-body-sm text-ink-muted sm:basis-auto">{t('machines.ceilingHint')}</span>
        </div>

        {/* Removing a machine is the only way to take its token back, and there is no undo:
            the daemon has to link again. So it asks, and the question names the machine. */}
        {!confirming && (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-md border border-[#EDB8B0] bg-paper px-4 font-body text-body-md font-medium text-vermilion-ink transition-colors hover:bg-vermilion-bg"
          >
            <Trash2 className="h-4 w-4" aria-hidden /> {t('machines.remove')}
          </button>
        )}
      </div>
      {ceilingError && (
        <p className="mt-2 font-body text-body-sm text-vermilion-ink" role="alert">
          {ceilingError}
        </p>
      )}

      {confirming && (
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-[#EDB8B0] bg-vermilion-bg px-4 py-3">
          <span className="min-w-0 flex-[1_1_260px] font-body text-body-md text-vermilion-ink">
            {t('machines.removeConfirm', { name: machine.display_name || machine.id })}
          </span>
          <button
            type="button"
            onClick={() => setConfirming(false)}
            disabled={removing}
            className="inline-flex min-h-[44px] items-center rounded-md border border-line-strong bg-paper px-4 font-body text-body-md font-medium text-ink transition-colors hover:bg-inset disabled:opacity-50"
          >
            {t('machines.removeNo')}
          </button>
          <button
            type="button"
            onClick={remove}
            disabled={removing}
            className="inline-flex min-h-[44px] items-center gap-1.5 rounded-md bg-vermilion-ink px-4 font-body text-body-md font-medium text-paper transition-colors hover:bg-vermilion-ink/90 disabled:opacity-50"
          >
            {removing && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            {t('machines.removeYes')}
          </button>
        </div>
      )}
      {removeError && (
        <p className="mt-2 font-body text-body-sm text-vermilion-ink" role="alert">
          {removeError}
        </p>
      )}
    </motion.article>
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

  return (
    <div className="mx-auto w-full max-w-[1240px] flex flex-col gap-6 pb-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle title={t('machines.title')} subtitle={t('machines.subtitle')} />
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={reload}
            disabled={reloading}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-md px-3 font-body text-body-md font-medium text-ink-light transition-colors hover:bg-inset hover:text-ink disabled:opacity-50"
          >
            <RefreshCw className={cn('h-4 w-4', reloading && 'animate-spin')} aria-hidden />
            {t('machines.refresh')}
          </button>
          <a href={DOCS.machines} target="_blank" rel="noreferrer" className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-line-strong bg-paper px-4 font-body text-body-md font-medium text-ink transition-colors hover:bg-inset">
            <BookOpen className="h-4 w-4" aria-hidden />
            {t('machines.guide')}
            <ExternalLink className="h-3.5 w-3.5 text-ink-muted" aria-hidden />
          </a>
          <Link to="/link" className="inline-flex min-h-[44px] items-center gap-2 rounded-md bg-ink px-[18px] font-body text-body-md font-medium text-paper transition-colors hover:bg-ink/85">
            <Plus className="h-4 w-4" aria-hidden />
            {t('machines.linkMachine')}
          </Link>
        </div>
      </div>

      {error && (
        <div
          className="flex items-start gap-2 rounded-lg border border-[#EDB8B0] bg-vermilion-bg px-4 py-3 font-body text-body-md text-vermilion-ink"
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
        <section className="flex flex-col items-center rounded-xl border border-line bg-paper px-5 py-12 text-center sm:px-8">
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-inset text-ink-muted">
            <Cpu className="h-6 w-6" strokeWidth={1.5} aria-hidden />
          </span>
          <h2 className="font-display text-[22px] font-medium text-ink">{t('machines.empty.title')}</h2>
          <p className="mt-2 max-w-xl font-body text-body-md text-ink-light">{t('machines.empty.description')}</p>
          {/* Two ways out, because the old screen offered none: it named a command and left the
              reader to work out what a daemon is and where to get one (FR-008h). */}
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            <Link to="/link" className="inline-flex min-h-[44px] items-center gap-2 rounded-md bg-ink px-[18px] font-body text-body-md font-medium text-paper transition-colors hover:bg-ink/85">
              <Plus className="h-4 w-4" aria-hidden />
              {t('machines.linkMachine')}
            </Link>
            <a href={DOCS.machines} target="_blank" rel="noreferrer" className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-line-strong bg-paper px-4 font-body text-body-md font-medium text-ink transition-colors hover:bg-inset">
              <BookOpen className="h-4 w-4" aria-hidden />
              {t('machines.empty.readGuide')}
              <ExternalLink className="h-3.5 w-3.5 text-ink-muted" aria-hidden />
            </a>
          </div>
        </section>
      ) : (
        <div className="flex flex-col gap-4">
          {machines.map((machine) => (
            <Machine
              key={machine.id}
              machine={machine}
              onChanged={(fresh) =>
                setMachines((rows) =>
                  (rows ?? []).map((row) => (row.id === fresh.id ? fresh : row))
                )
              }
              onRemoved={(id) =>
                setMachines((rows) => (rows ?? []).filter((row) => row.id !== id))
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
