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
import { useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import { Bot, Cpu, Laptop, Loader2, RefreshCw, Terminal, WifiOff } from 'lucide-react';
import { listMachines, type MachineDTO, type MachineWorkplaceDTO } from '@/lib/api';
import EmptyState from '@/components/EmptyState';
import PageTitle from '@/components/PageTitle';
import VellumPanel from '@/components/VellumPanel';
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

function Machine({ machine }: { machine: MachineDTO }) {
  const { t, i18n } = useTranslation();

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

        <div className="mt-3 space-y-2">
          {machine.workplaces.length > 0 ? (
            machine.workplaces.map((place) => <Workplace key={place.id} place={place} />)
          ) : (
            <p className="text-[12px] text-[#A89880]">{t('machines.noWorkplaces')}</p>
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
    <div className="max-w-4xl mx-auto px-6 py-8">
      <div className="flex items-start justify-between gap-4 mb-6">
        <PageTitle title={t('machines.title')} subtitle={t('machines.subtitle')} />
        <button
          onClick={reload}
          disabled={reloading}
          className="mt-1 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-[12px] font-medium text-[#6B5E4E] border border-[#E3D7BC] hover:bg-[#F3ECDA] transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn('w-3.5 h-3.5', reloading && 'animate-spin')} />
          {t('machines.refresh')}
        </button>
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
        />
      ) : (
        <motion.div
          variants={containerVariants}
          initial="hidden"
          animate="visible"
          className="space-y-4"
        >
          {machines.map((machine) => (
            <Machine key={machine.id} machine={machine} />
          ))}
        </motion.div>
      )}
    </div>
  );
}
