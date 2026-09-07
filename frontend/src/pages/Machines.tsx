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
  BookOpen,
  Bot,
  Cpu,
  ExternalLink,
  Laptop,
  Loader2,
  Plus,
  RefreshCw,
  Terminal,
  WifiOff,
} from 'lucide-react';
import {
  listMachines,
  updateMachine,
  type MachineDTO,
  type MachineWorkplaceDTO,
} from '@/lib/api';
import EmptyState from '@/components/EmptyState';
import PageTitle from '@/components/PageTitle';
import VellumPanel from '@/components/VellumPanel';
import { DOCS } from '@/lib/docs';
import { cn } from '@/lib/utils';
import { errorText } from '@/lib/errors';

const containerVariants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { staggerChildren: 0.06, delayChildren: 0.1 } },
};

const itemVariants = {
  hidden: { opacity: 0, y: 16, filter: 'blur(2px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  },
};

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
    <div
      className={cn(
        'rounded-lg border px-3 py-2.5',
        place.ready ? 'border-[#E3D7BC] bg-[#FBF6EA]' : 'border-[#E8C4B4] bg-[#FBEEE8]'
      )}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <Terminal className="w-3.5 h-3.5 text-[#8B7A6A]" />
        <span className="text-[13px] font-medium text-[#2A2318]">{place.cli_kind}</span>
        {place.cli_version && (
          <span className="text-[11px] font-mono text-[#A89880]">{place.cli_version}</span>
        )}
        <span
          className={cn(
            'inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium',
            place.ready ? 'bg-[#D8EADD] text-[#2A6E3A]' : 'bg-[#F3D9D0] text-[#8A3B22]'
          )}
        >
          {place.ready ? t('machines.ready') : t('machines.notReadyChip')}
        </span>
      </div>

      {why && <p className="mt-1 text-[12px] text-[#8A3B22]">{why}</p>}

      <div className="mt-2 flex items-center gap-1.5 flex-wrap">
        <Bot className="w-3.5 h-3.5 text-[#A89880]" />
        {place.agents.length > 0 ? (
          place.agents.map((agent) => (
            <span
              key={agent.id}
              className="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-[#E3D7BC] text-[#6B5E4E]"
            >
              {agent.name}
            </span>
          ))
        ) : (
          <span className="text-[12px] text-[#A89880]">{t('machines.noAgentsHere')}</span>
        )}
      </div>
    </div>
  );
}

// ─── One machine ─────────────────────────────────────────────────────────────

function Machine({ machine, onChanged }: { machine: MachineDTO; onChanged: (m: MachineDTO) => void }) {
  const { t, i18n } = useTranslation();
  // What is typed, or nothing typed yet. Held as *the edit* rather than as a copy of the
  // machine, so a reload or somebody else's change corrects the box without an effect
  // reaching in to overwrite it — and dropping the edit is all it takes to follow the server.
  const [typed, setTyped] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [ceilingError, setCeilingError] = useState<string | null>(null);
  const { workspaceId } = useParams();
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
    <motion.div variants={itemVariants}>
      <VellumPanel className="p-4">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div className="flex items-center gap-2 min-w-0">
            <Laptop className="w-4 h-4 text-[#8B7A6A] flex-shrink-0" />
            <h2 className="text-[15px] font-medium text-[#2A2318] truncate">
              {machine.display_name || t('machines.unnamed')}
            </h2>
            <span
              className={cn(
                'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium',
                machine.reachable
                  ? 'bg-[#D8EADD] text-[#2A6E3A]'
                  : 'bg-[#E8E0D8] text-[#8B7A6A]'
              )}
            >
              {!machine.reachable && <WifiOff className="w-3 h-3" />}
              {machine.reachable ? t('machines.online') : t('machines.offline')}
            </span>
          </div>
          <div className="text-[11px] text-[#A89880] text-right">
            <div>
              {machine.platform || '—'} · {t('machines.daemonVersion')}{' '}
              {machine.daemon_version || '—'}
            </div>
            <div>
              {t('machines.lastBeat')} {relative(machine.last_heartbeat_at, i18n.language)}
            </div>
          </div>
        </div>

        {/* The ceiling (FR-008). Beside the machine rather than inside a settings page: it is
            a fact about this machine, and the person setting it is looking at the machine. */}
        <div className="mt-3 flex items-center gap-2 flex-wrap">
          <Cpu className="w-3.5 h-3.5 text-[#8B7A6A]" />
          <label className="text-[12px] text-[#6B5E4E]" htmlFor={`ceiling-${machine.id}`}>
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
            className="w-16 rounded-md border border-[#E3D7BC] bg-[#FBF6EA] px-2 py-1 text-[13px] text-[#2A2318] disabled:opacity-60"
          />
          {saving && <Loader2 className="w-3.5 h-3.5 animate-spin text-[#A89880]" />}
          <span className="text-[11px] text-[#A89880]">{t('machines.ceilingHint')}</span>
        </div>
        {ceilingError && (
          <p className="mt-1 text-[12px] text-[#8A3B22]" role="alert">
            {ceilingError}
          </p>
        )}

        <div className="mt-3 space-y-2">
          {machine.workplaces.length > 0 ? (
            machine.workplaces.map((place) => <Workplace key={place.id} place={place} />)
          ) : (
            // Two ways to have no workplaces, and they need different things done about them.
            // A machine that has never sent a beat was linked and then never started — the
            // discovery that registers workplaces happens in `start`, not in `login`. A machine
            // that *is* beating and still reports nothing has been asked and genuinely found no
            // agent CLI installed. Saying only "this machine has reported no agent CLI" is true of
            // both and useful for neither (FR-008h).
            <p className="text-[12px] text-[#A89880]">
              {machine.last_heartbeat_at === null
                ? t('machines.neverStarted')
                : t('machines.noCliFound')}
            </p>
          )}
        </div>
      </VellumPanel>
    </motion.div>
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
    // No padding and no centring of its own. `Layout` already wraps every page in `p-6`, so the
    // `max-w-4xl mx-auto px-6 py-8` that used to sit here paid the margin twice and pushed this
    // one screen's title into a narrow column while every other title sat at the top left.
    <div className="min-h-[100dvh]">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6">
        <PageTitle title={t('machines.title')} subtitle={t('machines.subtitle')} />
        <div className="flex items-center gap-2">
          <Link
            to="/link"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium text-white bg-[#C25E3A] hover:bg-[#A94E2E] transition-colors"
          >
            <Plus className="w-3.5 h-3.5" />
            {t('machines.linkMachine')}
          </Link>
          <a
            href={DOCS.machines}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium text-[#6B5E4E] border border-[#E3D7BC] hover:bg-[#F3ECDA] transition-colors"
          >
            <BookOpen className="w-3.5 h-3.5" />
            {t('machines.guide')}
            <ExternalLink className="w-3 h-3 opacity-60" />
          </a>
          <button
            onClick={reload}
            disabled={reloading}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium text-[#6B5E4E] border border-[#E3D7BC] hover:bg-[#F3ECDA] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={cn('w-3.5 h-3.5', reloading && 'animate-spin')} />
            {t('machines.refresh')}
          </button>
        </div>
      </div>

      {error && (
        <div className="mb-4 rounded-lg border border-[#E8C4B4] bg-[#FBEEE8] px-4 py-3 text-[13px] text-[#8A3B22]">
          {error}
        </div>
      )}

      {machines === null ? (
        <div className="flex items-center gap-2 py-12 justify-center text-[13px] text-[#A89880]">
          <Loader2 className="w-4 h-4 animate-spin" /> {t('machines.loading')}
        </div>
      ) : machines.length === 0 ? (
        <EmptyState
          icon={Cpu}
          title={t('machines.empty.title')}
          description={t('machines.empty.description')}
          // Two ways out, because the old screen offered none: it named a command and left the
          // reader to work out what a daemon is and where to get one (FR-008h).
          action={
            <div className="flex flex-col sm:flex-row items-center gap-2">
              <Link
                to="/link"
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium text-white bg-[#C25E3A] hover:bg-[#A94E2E] transition-colors"
              >
                <Plus className="w-4 h-4" />
                {t('machines.linkMachine')}
              </Link>
              <a
                href={DOCS.machines}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-md text-[13px] font-medium text-[#6B5E4E] border border-[#E3D7BC] hover:bg-[#F3ECDA] transition-colors"
              >
                <BookOpen className="w-4 h-4" />
                {t('machines.empty.readGuide')}
                <ExternalLink className="w-3.5 h-3.5 opacity-60" />
              </a>
            </div>
          }
        />
      ) : (
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="space-y-4"
        >
          {machines.map((machine) => (
            <Machine
              key={machine.id}
              machine={machine}
              onChanged={(fresh) =>
                setMachines((rows) =>
                  (rows ?? []).map((row) => (row.id === fresh.id ? fresh : row))
                )
              }
            />
          ))}
        </motion.div>
      )}
    </div>
  );
}
