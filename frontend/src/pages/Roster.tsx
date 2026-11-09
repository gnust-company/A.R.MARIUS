import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Check,
  Bot,
  Crown,
  Lock,
  Hourglass,
  Zap,
  Plus,
  ChevronLeft,
  UserMinus,
} from 'lucide-react';
import { useAppStore, type ProjectSeat, type Marius } from '@/store/appStore';
import StatusChip from '@/components/StatusChip';
import Modal from '@/components/Modal';
import PageTitle from '@/components/PageTitle';
import { cn, wsHref } from '@/lib/utils';
import { agentsOf } from '@/lib/workspaceScope';

// ─── Agent Avatar ────────────────────────────────────────────────────────────

function AgentAvatar({ agent, size = 40 }: { agent: Marius; size?: number }) {
  return (
    <div
      className="rounded-full bg-inset overflow-hidden border border-line flex-shrink-0"
      style={{ width: size, height: size }}
      title={agent.displayName || agent.name}
    >
      {agent.avatar ? (
        <img src={agent.avatar} alt={agent.displayName || agent.name} className="w-full h-full object-cover" />
      ) : (
        <div className="w-full h-full flex items-center justify-center text-ink-muted">
          <Bot className="w-4 h-4" />
        </div>
      )}
    </div>
  );
}

/** An agent's liveness as the shared chip, in the reader's language. */
function AgentStatus({ status }: { status: string }) {
  const { t } = useTranslation();
  return <StatusChip status={status} label={t(`directory.status.${status}`, { defaultValue: status })} />;
}

// ─── Add Agent Modal ─────────────────────────────────────────────────────────

/** Put an agent on this project, or in its leader seat. Two things to say — which agent, and
 *  (by which button opened this) whether it leads — and nothing else.
 *
 *  It used to be a *seat* dialog: the patron had already created a role, given it a title, a
 *  seat count, a description of the work and a list of skills, and this was step two. What an
 *  agent does is written on the agent (FR-007l), so step one is gone and so is this dialog's
 *  half of it. */
function AddAgentModal({
  isOpen,
  onClose,
  asLeader,
  projectId,
}: {
  isOpen: boolean;
  onClose: () => void;
  asLeader: boolean;
  projectId: string;
}) {
  const { t } = useTranslation();
  const mariuses = useAppStore((s) => s.mariuses);
  const project = useAppStore((s) => s.projects.find((p) => p.id === projectId));
  const seatLeader = useAppStore((s) => s.seatLeader);
  const addProjectMember = useAppStore((s) => s.addProjectMember);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);

  // Anyone already on this project is not offered again — the server refuses a second seat,
  // and an option that can only fail is worse than no option.
  const seatedMariusIds = new Set((project?.seats || []).map((s) => s.mariusId).filter(Boolean));
  // Only agents of the project's own workspace can be seated; the server refuses the rest (FR-007q).
  const availableAgents = agentsOf(mariuses, project?.workspaceId).filter(
    (m) => !seatedMariusIds.has(m.id)
  );

  const handleAdd = async () => {
    if (!selectedAgentId) return;
    if (asLeader) await seatLeader(projectId, selectedAgentId);
    else await addProjectMember(projectId, selectedAgentId);
    setSelectedAgentId(null);
    onClose();
  };

  const title = asLeader ? t('roster.seatLeaderTitle') : t('roster.addAgentTitle');

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={<span className="font-display text-[22px] font-medium text-ink">{title}</span>}
      footer={
        <div className="flex flex-wrap justify-end gap-2 w-full">
          <button
            onClick={onClose}
            className="min-h-[44px] px-4 rounded-md font-body text-body-md font-medium bg-paper text-ink border border-line-strong hover:bg-inset transition-colors"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleAdd}
            disabled={!selectedAgentId}
            className={cn(
              'min-h-[44px] px-[18px] rounded-md font-body text-body-md font-medium transition-colors',
              selectedAgentId
                ? 'bg-ink text-paper hover:bg-ink/85'
                : 'bg-line text-ink-muted cursor-not-allowed'
            )}
          >
            {asLeader ? t('roster.seatLeader') : t('roster.addAgent')}
          </button>
        </div>
      }
    >
      <div className="flex flex-col gap-2">
        <p className="font-body text-body-sm font-medium text-ink-light">{t('roster.selectAgent')}</p>
        {availableAgents.length === 0 ? (
          <p className="font-body text-body-md text-ink-muted bg-inset border border-line rounded-lg px-4 py-3">
            {t('roster.noAgentsLeft')}
          </p>
        ) : (
          availableAgents.map((agent) => {
            const selected = selectedAgentId === agent.id;
            return (
              <button
                key={agent.id}
                onClick={() => setSelectedAgentId(agent.id)}
                aria-pressed={selected}
                className={cn(
                  'w-full min-h-[56px] flex items-center gap-3 p-3 rounded-lg border transition-colors text-left',
                  selected
                    ? 'border-ink ring-1 ring-ink bg-paper'
                    : 'border-line bg-paper hover:border-line-strong hover:bg-inset'
                )}
              >
                <AgentAvatar agent={agent} size={36} />
                <div className="flex-1 min-w-0">
                  <div className="font-body text-body-md font-medium text-ink truncate">
                    {agent.displayName || agent.name}
                  </div>
                  <div className="flex flex-wrap items-center gap-2 mt-0.5">
                    <AgentStatus status={agent.status} />
                    <span className="font-mono text-mono-sm text-ink-muted">{agent.adapterType || '—'}</span>
                  </div>
                </div>
                {selected && <Check className="w-4 h-4 text-ink shrink-0" />}
              </button>
            );
          })
        )}
      </div>
    </Modal>
  );
}

// ─── Main Roster Page ────────────────────────────────────────────────────────

export default function Roster() {
  const { id: projectId, workspaceId } = useParams<{ id: string; workspaceId: string }>();
  const { t } = useTranslation();
  const projects = useAppStore((s) => s.projects);
  const mariuses = useAppStore((s) => s.mariuses);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const removeProjectMember = useAppStore((s) => s.removeProjectMember);
  const hydrateWorkspace = useAppStore((s) => s.hydrateWorkspace);
  const project = projects.find((p) => p.id === projectId);

  // Which door the dialog is open on: the leader seat, the team, or neither.
  const [adding, setAdding] = useState<'leader' | 'member' | null>(null);

  // Load the project roster + the workspace's agents on mount.
  useEffect(() => {
    if (!projectId) return;
    (async () => {
      await hydrateProject(projectId);
      const wsId = useAppStore.getState().projects.find((p) => p.id === projectId)?.workspaceId;
      if (wsId) await hydrateWorkspace(wsId);
    })();
  }, [projectId, hydrateProject, hydrateWorkspace]);

  if (!project) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <h2 className="font-display text-[22px] font-medium text-ink-light">{t('common.loading')}</h2>
      </div>
    );
  }

  // List-level projects (from `projectToVM`) carry no `seats` — only `projectDetailToVM`
  // (run by `hydrateProject`) fills them. On a fresh mount the first render sees a project
  // with `seats === undefined`, before the async hydrate lands; accessing `.find` on it
  // threw a TypeError and — with no ErrorBoundary — blanked the page (#56). Treat the
  // detail-not-yet-loaded state the same as not-loaded: show the loading gate.
  if (!project.seats) {
    return (
      <div className="flex flex-col items-center justify-center py-20">
        <h2 className="font-display text-[22px] font-medium text-ink-light">{t('common.loading')}</h2>
      </div>
    );
  }

  // ─── Roster data calculations ───
  const leaderSeat = project.seats.find((s) => s.role === 'leader');
  const memberSeats = project.seats.filter((s) => s.role !== 'leader' && s.mariusId);
  // Worker places the project asked for that nobody sits in yet. Drawn as open cards so the
  // team grid shows the project's real size, not just who has turned up.
  const openSeats = project.seats.filter((s) => s.role !== 'leader' && !s.mariusId);

  const seatsTotal = project.seats.length;
  const seatsGranted = project.seats.filter((s) => s.mariusId).length;
  const seatsOnline = project.seats.filter((s) => {
    if (!s.mariusId) return false;
    const m = mariuses.find((m) => m.id === s.mariusId);
    return m?.status === 'online' || m?.status === 'working';
  }).length;

  const isFullyGranted = seatsGranted === seatsTotal;
  // Past the setup gate. A project leaves `setup` exactly when its roster is full and every
  // agent on it is online, so "not setup" *is* "the roster did its job" — which is what this
  // page is about. Reading it as operating/maintaining only was a leftover from before the
  // five phases: a project sitting in `planning` with everyone seated and online was drawn as
  // still waiting for them, under a chip that already said Planning.
  const isActive = project.status !== 'setup';
  // The team can still be changed while there is no work to orphan. A real task only exists
  // once the patron has approved the plan (FR-003), so that is the honest line.
  const teamIsStillOpen = project.status === 'setup' || project.status === 'planning';

  const progressPercent = seatsTotal > 0 ? (seatsGranted / seatsTotal) * 100 : 0;

  return (
    <div className="mx-auto w-full max-w-[1240px] flex flex-col gap-7 pb-10">
      {/* ─── Page Header ────────────────────────────────────────────── */}
      <div className="flex flex-col gap-3">
        <Link
          to={wsHref(workspaceId, `/projects/${projectId}`)}
          className="inline-flex items-center gap-1 self-start min-h-[44px] -ml-2 px-2 rounded-md font-body text-body-md text-ink-light hover:text-ink hover:bg-inset transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
          {t('roster.backToBoard')}
        </Link>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <PageTitle title={t('roster.title')} subtitle={project.name} />
          <StatusChip status={project.status} size="md" label={t(`projects.status.${project.status}`)} />
        </div>
      </div>

      {/* ─── Progress Summary ───────────────────────────────────────── */}
      <div className="bg-paper border border-line rounded-xl px-5 py-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-body text-body-md text-ink">
            <span>{t('roster.progressSummary', { granted: seatsGranted, total: seatsTotal })}</span>
            <span className="text-ink-muted" aria-hidden>&middot;</span>
            <span className={cn(seatsOnline === seatsTotal && seatsTotal > 0 ? 'text-verdigris-ink' : 'text-ink-light')}>
              {t('roster.onlineSummary', { online: seatsOnline, total: seatsTotal })}
            </span>
          </p>
          <span className="font-display text-[22px] font-medium text-ink">{Math.round(progressPercent)}%</span>
        </div>

        {/* Progress bar — verdigris is "filled", the inset track is what is still open */}
        <div className="w-full h-2 bg-inset rounded-full overflow-hidden">
          <motion.div
            className={cn('h-full rounded-full', isActive || isFullyGranted ? 'bg-verdigris' : 'bg-lapis')}
            initial={false}
            animate={{ width: `${progressPercent}%` }}
            transition={{ duration: 0.25, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
          />
        </div>
      </div>

      {/* ─── Project Leader Section ─────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <h2 className="font-display text-[22px] font-medium text-ink">{t('roster.projectLeader')}</h2>

        {leaderSeat ? (
          <div className="max-w-[560px]">
            {leaderSeat.mariusId ? (
              <GrantedSeatCard seat={leaderSeat} isLeader />
            ) : (
              <EmptySeatCard
                label={t('roster.emptyLeaderSeat')}
                actionLabel={t('roster.seatLeader')}
                onAdd={() => setAdding('leader')}
              />
            )}
          </div>
        ) : (
          // A roster with no leader role at all — nothing to seat into, so no button; just say
          // so instead of leaving a heading over nothing.
          <p className="max-w-[560px] bg-paper border border-line rounded-xl px-5 py-4 font-body text-body-md text-ink-muted">
            {t('roster.emptyLeaderSeat')}
          </p>
        )}
      </section>

      {/* ─── The team ───────────────────────────────────────────────── */}
      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="font-display text-[22px] font-medium text-ink">
            {t('roster.team')}
            <span className="ml-2 font-body text-body-md font-normal text-ink-muted">
              {memberSeats.length}/{memberSeats.length + openSeats.length}
            </span>
          </h2>
          <button
            onClick={() => setAdding('member')}
            className="inline-flex items-center gap-1.5 min-h-[44px] px-4 rounded-md bg-paper border border-line-strong font-body text-body-md font-medium text-ink hover:bg-inset transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t('roster.addAgent')}
          </button>
        </div>

        {/* One flat grid. There is nothing to group by: an agent is on the project as
            itself, and what it does is written on the agent (FR-007l). */}
        {memberSeats.length === 0 && openSeats.length === 0 ? (
          <p className="bg-paper border border-line rounded-xl px-5 py-5 font-body text-body-md text-ink-muted">
            {t('roster.noTeamYet')}
          </p>
        ) : (
          <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,300px),1fr))]">
            <AnimatePresence initial={false}>
              {memberSeats.map((seat) => (
                <motion.div
                  key={seat.mariusId}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className="min-w-0"
                >
                  <GrantedSeatCard
                    seat={seat}
                    onRemove={
                      teamIsStillOpen
                        ? () => removeProjectMember(project.id, seat.mariusId!)
                        : undefined
                    }
                  />
                </motion.div>
              ))}
            </AnimatePresence>
            {openSeats.map((seat) => (
              <EmptySeatCard
                key={seat.id}
                label={t('roster.openSeat')}
                actionLabel={t('roster.addAgent')}
                onAdd={() => setAdding('member')}
              />
            ))}
          </div>
        )}
      </section>

      {/* ─── Activation Banner ──────────────────────────────────────── */}
      {isActive ? (
        <div className="flex items-center gap-3 rounded-xl bg-verdigris-bg border border-verdigris/30 px-5 py-4">
          <Zap className="w-5 h-5 text-verdigris-ink flex-shrink-0" />
          <p className="font-body text-body-md text-verdigris-ink font-medium">{t('roster.projectActive')}</p>
        </div>
      ) : isFullyGranted ? (
        <div className="flex items-center gap-3 rounded-xl bg-ash-bg border border-line px-5 py-4">
          <Hourglass className="w-5 h-5 text-ink-light flex-shrink-0" />
          <p className="font-body text-body-md text-ink-light font-medium">{t('roster.waitingOnline')}</p>
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-xl bg-gold-bg border border-gold/40 px-5 py-4">
          <Lock className="w-5 h-5 text-gold-ink flex-shrink-0" />
          <p className="font-body text-body-md text-gold-ink font-medium">{t('roster.allGranted')}</p>
        </div>
      )}

      {/* ─── Add Agent Modal ────────────────────────────────────────── */}
      <AddAgentModal
        isOpen={adding !== null}
        onClose={() => setAdding(null)}
        asLeader={adding === 'leader'}
        projectId={projectId || ''}
      />
    </div>
  );
}

// ─── Granted Seat Card ───────────────────────────────────────────────────────

// A granted seat is identified by who sits in it, not by its index — only the
// empty card needs a number to refer to.
function GrantedSeatCard({
  seat,
  isLeader = false,
  onRemove,
}: {
  seat: ProjectSeat;
  isLeader?: boolean;
  onRemove?: () => void;
}) {
  const { t } = useTranslation();
  const mariuses = useAppStore((s) => s.mariuses);
  const agent = mariuses.find((m) => m.id === seat.mariusId);

  if (!agent) return null;

  return (
    <div className="h-full flex items-start gap-3 bg-paper border border-line rounded-xl p-4">
      <AgentAvatar agent={agent} />

      <div className="flex-1 min-w-0 flex flex-col gap-1.5">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 min-w-0">
          <span className="font-body text-[15px] font-medium text-ink truncate">
            {agent.displayName || agent.name}
          </span>
          {isLeader && (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-inset border border-line font-body text-body-xs font-medium text-ink-light">
              <Crown className="w-3 h-3" />
              {t('roster.roleBadgeLeader')}
            </span>
          )}
        </div>
        {agent.role && <span className="font-body text-body-sm text-ink-light truncate">{agent.role}</span>}
        <div className="flex flex-wrap items-center gap-2">
          <AgentStatus status={agent.status} />
          <span className="font-mono text-mono-sm text-ink-muted">{agent.adapterType || '—'}</span>
        </div>
      </div>

      {/* Only while the project is still being set up. Past that the team is settled, and
          the way somebody leaves a running project is not a button on this list. */}
      {onRemove && (
        <button
          onClick={onRemove}
          title={t('roster.removeAgent')}
          aria-label={t('roster.removeAgent')}
          className="w-10 h-10 -mr-1 -mt-1 shrink-0 rounded-md flex items-center justify-center text-ink-muted hover:text-vermilion-ink hover:bg-vermilion-bg transition-colors"
        >
          <UserMinus className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}

// ─── Empty Seat Card ─────────────────────────────────────────────────────────

function EmptySeatCard({
  label,
  actionLabel,
  onAdd,
}: {
  label: string;
  actionLabel: string;
  onAdd: () => void;
}) {
  return (
    <div className="h-full min-w-0 flex flex-wrap items-center gap-3 p-4 border-[1.5px] border-dashed border-line-strong rounded-xl">
      <span className="w-10 h-10 shrink-0 rounded-full border-[1.5px] border-dashed border-ash flex items-center justify-center text-ink-muted">
        <Plus className="w-4 h-4" />
      </span>
      <span className="flex-[1_1_96px] min-w-0 font-body text-body-md text-ink-light">{label}</span>
      <button
        onClick={onAdd}
        className="min-h-[44px] px-4 rounded-md bg-paper border border-line-strong font-body text-body-md font-medium text-ink hover:bg-inset transition-colors"
      >
        {actionLabel}
      </button>
    </div>
  );
}
