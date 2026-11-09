import { useState, useEffect } from 'react';
import { useParams, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import { Check, Crown, Lock, Hourglass, Zap, Plus, UserMinus, UserRound } from 'lucide-react';
import { useAppStore, type ProjectSeat, type Marius } from '@/store/appStore';
import StatusChip from '@/components/StatusChip';
import AgentAvatar from '@/components/AgentAvatar';
import Modal from '@/components/Modal';
import ProjectHeader from '@/components/project/ProjectHeader';
import { cn, wsHref } from '@/lib/utils';
import { agentsOf } from '@/lib/workspaceScope';

const agentName = (agent: Marius) => agent.displayName || agent.name;

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
      title={title}
      footer={
        <>
          <button onClick={onClose} className="btn btn-secondary">
            {t('common.cancel')}
          </button>
          <button onClick={handleAdd} disabled={!selectedAgentId} className="btn btn-primary">
            {asLeader ? t('roster.seatLeader') : t('roster.addAgent')}
          </button>
        </>
      }
    >
      <div className="flex flex-col gap-2">
        <p className="font-body text-[13px] font-semibold text-ink">{t('roster.selectAgent')}</p>
        {availableAgents.length === 0 ? (
          <p className="rounded-md border border-dashed border-line-strong px-4 py-3 font-body text-[14px] text-ink-muted">
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
                  'w-full min-h-[60px] flex items-center gap-3 p-3 rounded-md border text-left transition-colors',
                  selected
                    ? 'border-sapphire bg-sapphire-soft'
                    : 'border-line bg-surface hover:border-line-strong hover:bg-surface-hover'
                )}
              >
                <AgentAvatar name={agentName(agent)} status={agent.status} size="sm" />
                <div className="flex-1 min-w-0">
                  <div className="font-body text-[14px] font-semibold text-ink-strong truncate">{agentName(agent)}</div>
                  <div className="flex flex-wrap items-center gap-2 mt-1">
                    <AgentStatus status={agent.status} />
                    {agent.adapterType && <span className="chip">{agent.adapterType}</span>}
                  </div>
                </div>
                {selected && <Check className="w-4 h-4 text-sapphire-strong shrink-0" />}
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
        <h2 className="font-display text-[22px] font-normal text-ink-light">{t('common.loading')}</h2>
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
        <h2 className="font-display text-[22px] font-normal text-ink-light">{t('common.loading')}</h2>
      </div>
    );
  }

  // ─── Roster data calculations ───
  const leaderSeat = project.seats.find((s) => s.role === 'leader');
  const leaderAgent = leaderSeat?.mariusId ? mariuses.find((m) => m.id === leaderSeat.mariusId) : undefined;
  const memberSeats = project.seats.filter((s) => s.role !== 'leader' && s.mariusId);
  // Worker places the project asked for that nobody sits in yet. Drawn as open rows so the
  // team list shows the project's real size, not just who has turned up.
  const openSeats = project.seats.filter((s) => s.role !== 'leader' && !s.mariusId);

  const seatsTotal = project.seats.length;
  const seatsGranted = project.seats.filter((s) => s.mariusId).length;
  const isOnline = (s: ProjectSeat) => {
    if (!s.mariusId) return false;
    const m = mariuses.find((m) => m.id === s.mariusId);
    return m?.status === 'online' || m?.status === 'working';
  };
  const seatsOnline = project.seats.filter(isOnline).length;
  const membersOnline = memberSeats.filter(isOnline).length;

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
    <div className="mx-auto w-full max-w-[1240px] flex flex-col gap-[18px] pb-16">
      <ProjectHeader project={project} active="roster" />

      {/* ─── Seat fill ─── */}
      <section className="surface -mt-[18px] mb-0 px-5 py-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
          <p className="flex flex-wrap items-center gap-x-2 gap-y-1 font-body text-[14px] text-ink">
            <span>{t('roster.progressSummary', { granted: seatsGranted, total: seatsTotal })}</span>
            <span className="text-ink-muted" aria-hidden>&middot;</span>
            <span className={cn(seatsOnline === seatsTotal && seatsTotal > 0 ? 'text-success' : 'text-ink-light')}>
              {t('roster.onlineSummary', { online: seatsOnline, total: seatsTotal })}
            </span>
          </p>
          <span className="font-display text-[26px] font-normal leading-none text-ink-strong">{Math.round(progressPercent)}%</span>
        </div>
        <div className="w-full h-[5px] bg-line rounded-full overflow-hidden">
          <motion.div
            className={cn('h-full rounded-full', isActive || isFullyGranted ? 'bg-success' : 'bg-sapphire')}
            initial={false}
            animate={{ width: `${progressPercent}%` }}
            transition={{ duration: 0.25, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
          />
        </div>
      </section>

      <div className="grid gap-[18px] lg:grid-cols-[320px_minmax(0,1fr)] items-start">
        {/* ─── The Leader's seat ─── */}
        <section className="surface p-6 sm:p-7 text-center">
          <span className="eyebrow">{t('projectView.leaderSeatEyebrow')}</span>
          {leaderAgent ? (
            <>
              <AgentAvatar name={agentName(leaderAgent)} status={leaderAgent.status} size="lg" className="mx-auto mt-5 mb-3" />
              <h2 className="font-display text-[28px] font-normal leading-tight tracking-[-0.02em] text-ink-strong break-words">
                {agentName(leaderAgent)}
              </h2>
              <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
                <span className="inline-flex items-center gap-1 rounded-full border border-gold/35 px-2 min-h-[22px] font-body text-[11px] text-gold">
                  <Crown className="w-3 h-3" />
                  {t('roster.roleBadgeLeader')}
                </span>
                <AgentStatus status={leaderAgent.status} />
              </div>
              {(leaderAgent.description || leaderAgent.role) && (
                <p className="mt-4 font-body text-[13px] leading-relaxed text-ink-light break-words">
                  {leaderAgent.description || leaderAgent.role}
                </p>
              )}
              <dl className="mt-5 text-left">
                <div className="py-2.5 border-t border-line">
                  <dt className="font-body text-[11px] text-ink-muted">{t('projectView.runtime')}</dt>
                  <dd className="mt-0.5 font-body text-[13px] text-ink break-words">
                    {[leaderAgent.runtime?.cli_kind || leaderAgent.adapterType, leaderAgent.runtime?.machine_name]
                      .filter(Boolean)
                      .join(' · ') || '—'}
                  </dd>
                </div>
              </dl>
              <Link to={wsHref(workspaceId, `/agents/${leaderAgent.id}`)} className="btn btn-secondary mt-4 w-full">
                {t('projectView.openProfile')}
              </Link>
            </>
          ) : leaderSeat ? (
            <>
              <span className="mx-auto mt-5 mb-3 grid place-items-center w-[58px] h-[58px] rounded-full border-[1.5px] border-dashed border-line-strong text-ink-muted">
                <UserRound className="w-6 h-6" strokeWidth={1.5} />
              </span>
              <p className="font-body text-[14px] text-ink-light">{t('roster.emptyLeaderSeat')}</p>
              <button onClick={() => setAdding('leader')} className="btn btn-primary mt-5 w-full">
                <Plus className="w-4 h-4" />
                {t('roster.seatLeader')}
              </button>
            </>
          ) : (
            // A roster with no leader role at all — nothing to seat into, so no button; just say
            // so instead of leaving a heading over nothing.
            <p className="mt-4 font-body text-[14px] text-ink-muted">{t('roster.emptyLeaderSeat')}</p>
          )}
        </section>

        {/* ─── The team ─── */}
        <section className="surface px-5 sm:px-6 py-1">
          <header className="flex flex-wrap items-end justify-between gap-3 py-5">
            <div className="min-w-0">
              <span className="eyebrow">{t('projectView.workersEyebrow')}</span>
              <h2 className="mt-1.5 font-display text-[24px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
                {t('roster.team')}
                <span className="ml-2 font-body text-[14px] text-ink-muted">
                  {memberSeats.length}/{memberSeats.length + openSeats.length}
                </span>
              </h2>
              <p className="mt-1 font-body text-[12px] text-ink-light">
                {t('projectView.onlineCount', { count: membersOnline })}
              </p>
            </div>
            <button onClick={() => setAdding('member')} className="btn btn-secondary">
              <Plus className="w-4 h-4" />
              {t('roster.addAgent')}
            </button>
          </header>

          {/* One flat list. There is nothing to group by: an agent is on the project as
              itself, and what it does is written on the agent (FR-007l). */}
          {memberSeats.length === 0 && openSeats.length === 0 ? (
            <p className="border-t border-line py-6 font-body text-[14px] text-ink-muted">{t('roster.noTeamYet')}</p>
          ) : (
            <ul>
              <AnimatePresence initial={false}>
                {memberSeats.map((seat) => (
                  <motion.li
                    key={seat.mariusId}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    transition={{ duration: 0.15 }}
                    className="border-t border-line"
                  >
                    <MemberRow
                      seat={seat}
                      workspaceId={workspaceId}
                      onRemove={teamIsStillOpen ? () => removeProjectMember(project.id, seat.mariusId!) : undefined}
                    />
                  </motion.li>
                ))}
              </AnimatePresence>
              {openSeats.map((seat) => (
                <li key={seat.id} className="border-t border-line">
                  <div className="flex flex-wrap items-center gap-3 py-4">
                    <span className="grid place-items-center w-[42px] h-[42px] shrink-0 rounded-full border-[1.5px] border-dashed border-line-strong text-ink-muted">
                      <Plus className="w-4 h-4" />
                    </span>
                    <span className="flex-[1_1_120px] min-w-0 font-body text-[14px] text-ink-light">{t('roster.openSeat')}</span>
                    <button onClick={() => setAdding('member')} className="btn btn-secondary btn-sm">
                      {t('roster.addAgent')}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      {/* ─── Activation banner ─── */}
      {isActive ? (
        <div className="flex items-center gap-3 rounded-md border border-success/30 bg-success-soft px-5 py-4">
          <Zap className="w-5 h-5 text-success shrink-0" />
          <p className="font-body text-[14px] font-medium text-success">{t('roster.projectActive')}</p>
        </div>
      ) : isFullyGranted ? (
        <div className="flex items-center gap-3 rounded-md border border-line bg-canvas-deep px-5 py-4">
          <Hourglass className="w-5 h-5 text-ink-light shrink-0" />
          <p className="font-body text-[14px] font-medium text-ink-light">{t('roster.waitingOnline')}</p>
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-md border border-gold/30 bg-gold-soft px-5 py-4">
          <Lock className="w-5 h-5 text-gold shrink-0" />
          <p className="font-body text-[14px] font-medium text-ink">{t('roster.allGranted')}</p>
        </div>
      )}

      {/* ─── Add Agent Modal ─── */}
      <AddAgentModal
        isOpen={adding !== null}
        onClose={() => setAdding(null)}
        asLeader={adding === 'leader'}
        projectId={projectId || ''}
      />
    </div>
  );
}

// ─── Member Row ──────────────────────────────────────────────────────────────

// A seated member is identified by who sits in it, not by its index — only the open row
// needs no name.
function MemberRow({
  seat,
  workspaceId,
  onRemove,
}: {
  seat: ProjectSeat;
  workspaceId?: string;
  onRemove?: () => void;
}) {
  const { t } = useTranslation();
  const mariuses = useAppStore((s) => s.mariuses);
  const agent = mariuses.find((m) => m.id === seat.mariusId);

  if (!agent) return null;

  return (
    <div className="flex items-center gap-3.5 py-4">
      <AgentAvatar name={agentName(agent)} status={agent.status} />
      <Link to={wsHref(workspaceId, `/agents/${agent.id}`)} className="group flex-1 min-w-0">
        <strong className="block truncate font-display text-[17px] font-normal text-ink-strong group-hover:text-sapphire-strong transition-colors">
          {agentName(agent)}
        </strong>
        {(agent.description || agent.role) && (
          <p className="truncate font-body text-[12px] text-ink-light">{agent.description || agent.role}</p>
        )}
      </Link>
      <div className="hidden sm:flex items-center gap-2 shrink-0">
        {agent.adapterType && <span className="chip">{agent.adapterType}</span>}
      </div>
      <AgentStatus status={agent.status} />

      {/* Only while the project is still being set up. Past that the team is settled, and
          the way somebody leaves a running project is not a button on this list. */}
      {onRemove && (
        <button
          onClick={onRemove}
          title={t('roster.removeAgent')}
          aria-label={t('roster.removeAgent')}
          className="grid place-items-center w-10 h-10 -mr-2 shrink-0 rounded-md text-ink-muted hover:text-danger hover:bg-danger-soft transition-colors"
        >
          <UserMinus className="w-4 h-4" />
        </button>
      )}
    </div>
  );
}
