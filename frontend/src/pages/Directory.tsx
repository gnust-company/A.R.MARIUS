import { useState, useMemo, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import {
  Users,
  Plus,
  Search,
  Check,
  Star,
  Cpu,
  Loader2,
  AlertTriangle,
  ArrowUpRight,
  UserPlus,
  Sparkles,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { Marius, WorkplaceChoice } from '@/store/appStore';
import EmptyState from '@/components/EmptyState';
import Modal from '@/components/Modal';
import ConfirmDialog from '@/components/ConfirmDialog';
import RuntimeOptionFields from '@/components/RuntimeOptionFields';
import Dropdown from '@/components/Dropdown';
import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
import AgentAvatar from '@/components/AgentAvatar';
import { heldTasks, useHydrateWorkspaceTasks } from '@/components/agent/holding';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { agentsOf } from '@/lib/workspaceScope';
import { useTranslation } from 'react-i18next';

// ─── Animation Variants ──────────────────────────────────────────────────────

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.04, delayChildren: 0.05 },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 10 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.35, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  },
};

// There is no adapter picker any more. It offered three choices of which only one was ever
// registered, and the real answer — which tool runs this agent — follows from the workplace
// the person picks, which is a thing they can actually see and reason about (FR-007g).

/** The list's filter: every agent, the ones that answer, or the ones that do not. */
type Filter = 'all' | 'available' | 'offline';
const FILTERS: Filter[] = ['all', 'available', 'offline'];

function matchesFilter(m: Marius, filter: Filter) {
  if (filter === 'all') return true;
  return filter === 'offline' ? m.status === 'offline' : m.status !== 'offline';
}

const LABEL_CLS = 'mb-1.5 block font-body text-[13px] font-semibold text-ink';
const HINT_CLS = 'mt-1.5 font-body text-[12px] leading-relaxed text-ink-muted';

// ─── Component: Agent Card ───────────────────────────────────────────────────

function AgentCard({ agent }: { agent: Marius }) {
  const { t } = useTranslation();
  const tasks = useAppStore((s) => s.tasks);
  const holding = heldTasks(tasks, agent.id)[0];
  const navigate = useNavigate();
  const { workspaceId } = useParams();

  const displayName = agent.displayName || agent.name;
  const agentSkills = agent.skills || [];
  const roleLine = agent.role || agent.description;

  // Click the card → the agent's page, which is where an agent is managed (FR-007o): renaming,
  // settings and removal all live there rather than behind a menu on every card.
  const openDetail = () => navigate(wsHref(workspaceId, `/agents/${agent.id}`));

  return (
    <motion.div variants={cardVariants} layout className="min-w-0">
      <div
        className="group flex h-full min-h-[300px] cursor-pointer flex-col rounded-lg border border-line bg-surface p-5 text-left transition-colors hover:border-sapphire focus-visible:border-sapphire focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/60"
        onClick={openDetail}
        role="link"
        tabIndex={0}
        aria-label={t('directory.openProfileOf', { name: displayName })}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDetail(); }
        }}
      >
        <div className="flex items-start justify-between gap-3">
          <AgentAvatar name={displayName} status={agent.status} size="lg" />
          <StatusChip status={agent.status} label={t('directory.status.' + agent.status)} size="md" />
        </div>

        <h2 className="mt-3.5 flex min-w-0 items-center gap-2 font-display text-[25px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
          <span className="truncate">{displayName}</span>
          {agent.isWorkspaceAgent === true && (
            <Sparkles className="h-4 w-4 shrink-0 text-gold" aria-label={t('directory.workspaceAgent')} />
          )}
        </h2>
        <p className="mt-0.5 truncate font-body text-[12px] text-ink-light">
          {agent.isWorkspaceAgent === true
            ? [t('directory.hostRole'), roleLine].filter(Boolean).join(' · ')
            : roleLine || t('directory.noRole')}
        </p>

        {/* Where it works — the CLI and the machine, which is what tells two agents apart at a
            glance (FR-007o). */}
        <p className="mt-3 flex min-w-0 items-center gap-1.5 font-mono text-[10px] text-ink-muted">
          <Cpu className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="truncate">
            {/* The model beside the runtime, when one was picked: two agents on one CLI
                can differ only in this, and the card is where a team is read at a glance. */}
            {agent.runtime
              ? [agent.runtime.cli_kind, agent.runtimeOptions?.model, agent.runtime.machine_name]
                  .filter(Boolean)
                  .join(' · ')
              : t('agentDetail.runtimeNone')}
          </span>
        </p>

        {/* What it is holding right now — the question a person opens this page to answer. */}
        <div className="my-3.5 border-y border-line py-3">
          {holding ? (
            <>
              <p className="flex min-w-0 items-center gap-1.5 font-mono text-[10px] tracking-[0.06em]">
                {holding.identifier && <span className="text-sapphire-strong">{holding.identifier}</span>}
                <span
                  className={cn(
                    holding.status === 'blocked'
                      ? 'text-danger'
                      : holding.status === 'in_review'
                        ? 'text-sapphire-strong'
                        : 'text-ink-muted',
                  )}
                >
                  {holding.identifier && '· '}
                  {t(`tasks.status.${holding.status}`)}
                </span>
              </p>
              <p className="mt-1 truncate font-body text-[12px] text-ink">{holding.title}</p>
            </>
          ) : (
            <>
              <p className="font-mono text-[10px] tracking-[0.06em] text-ink-muted">{t('directory.holdingNone')}</p>
              <p className="mt-1 truncate font-body text-[12px] text-ink-muted">{t('home.agentNoTask')}</p>
            </>
          )}
        </div>

        {agentSkills.length > 0 && (
          <div className="mb-3.5 flex flex-wrap gap-1.5">
            {agentSkills.slice(0, 3).map((skill) => (
              <span key={skill} className="chip max-w-full truncate">
                {skill}
              </span>
            ))}
            {agentSkills.length > 3 && (
              <span className="chip border-dashed">
                {t('directory.moreSkills', { count: agentSkills.length - 3 })}
              </span>
            )}
          </div>
        )}

        <div className="mt-auto flex items-center justify-between gap-3 border-t border-line pt-3.5 font-body text-[13px] font-medium text-sapphire-strong">
          {t('directory.openProfile')}
          <ArrowUpRight className="h-[18px] w-[18px] transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5" aria-hidden />
        </div>
      </div>
    </motion.div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE: Directory
// ═══════════════════════════════════════════════════════════════════════════════

export default function Directory() {
  const { t } = useTranslation();
  const everyAgent = useAppStore((s) => s.mariuses);
  const skills = useAppStore((s) => s.skills);
  const inviteNewAgent = useAppStore((s) => s.inviteNewAgent);
  const listWorkplaces = useAppStore((s) => s.listWorkplaces);
  const designateWorkspaceAgent = useAppStore((s) => s.designateWorkspaceAgent);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  // This page is about one workspace: its list, its counts and its host (FR-007q).
  const mariuses = useMemo(
    () => agentsOf(everyAgent, activeWorkspaceId),
    [everyAgent, activeWorkspaceId]
  );

  // The sitting host — designating anyone else is a swap and asks for confirmation (#32).
  // Scoped to the active workspace: the store holds every workspace's mariuses.
  const currentHost = useMemo(
    () =>
      mariuses.find((m) => m.workspaceId === activeWorkspaceId && m.isWorkspaceAgent === true),
    [mariuses, activeWorkspaceId]
  );

  // Cards say what each agent is holding, and tasks are loaded per project.
  useHydrateWorkspaceTasks();

  // Who may become the host: an agent that answers, which an offline one cannot.
  const hostCandidates = useMemo(() => mariuses.filter((m) => m.status !== 'offline'), [mariuses]);
  const [hostPick, setHostPick] = useState('');

  // ── Designate state ────────────────────────────────────────────────────────
  // Renaming, the runtime settings and removal moved to the agent's own page (FR-007o).
  const [designatingAgent, setDesignatingAgent] = useState<Marius | null>(null);

  // ── Filter State ───────────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<Filter>('all');

  // ── Invite Modal State ─────────────────────────────────────────────────────
  const [inviteModalOpen, setInviteModalOpen] = useState(false);
  const [agentName, setAgentName] = useState('');
  // What the agent is told to be, and what the team calls it. Two boxes rather than one
  // because only the first is ever sent to the agent (FR-007i, FR-007j).
  const [instructions, setInstructions] = useState('');
  const [agentDescription, setAgentDescription] = useState('');
  // Where the new agent will work. Read when the form opens rather than held in the store:
  // an agent is attached to one workplace for life (FR-007), so this list has to be the one
  // that is true at the moment of choosing, not one cached from an earlier visit.
  const [workplaces, setWorkplaces] = useState<WorkplaceChoice[]>([]);
  const [workplaceId, setWorkplaceId] = useState('');
  // What the person picked out of what the chosen workplace offers (FR-007k). Keyed by the
  // server's name for each setting, never by a flag: this screen has no idea that one of them
  // becomes `--effort` on the machine, and it must not learn.
  const [runtimeOptions, setRuntimeOptions] = useState<Record<string, string>>({});
  const [workplacesLoading, setWorkplacesLoading] = useState(false);
  // The workplace currently picked, and therefore what it says its tool takes (FR-007k).
  const chosenWorkplace = workplaces.find((w) => w.id === workplaceId);
  // Why a refused invite was refused. The workplace list was true when this form opened;
  // a CLI uninstalled a minute later makes the chosen one stale, and the server says so in
  // a coded refusal. Swallowing it would leave the person clicking a button that does
  // nothing and says nothing.
  const [inviteError, setInviteError] = useState('');
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [makeWorkspaceAgent, setMakeWorkspaceAgent] = useState(false);
  const [inviteSwapConfirmOpen, setInviteSwapConfirmOpen] = useState(false);
  const [sending, setSending] = useState(false);

  // ── Filter Agents ──────────────────────────────────────────────────────────
  const filteredAgents = useMemo(() => {
    let filtered = [...mariuses];

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (m) =>
          (m.displayName || m.name).toLowerCase().includes(q) ||
          m.role.toLowerCase().includes(q) ||
          (m.description || '').toLowerCase().includes(q) ||
          (m.adapterType || '').toLowerCase().includes(q) ||
          (m.skills || []).some((s) => s.toLowerCase().includes(q))
      );
    }

    filtered = filtered.filter((m) => matchesFilter(m, statusFilter));

    // Sort: online/working first, then by name
    filtered.sort((a, b) => {
      const score = (m: Marius) => {
        if (m.status === 'online') return 3;
        if (m.status === 'working') return 2;
        if (m.status === 'idle') return 1;
        return 0;
      };
      return score(b) - score(a) || (a.displayName || a.name).localeCompare(b.displayName || b.name);
    });

    return filtered;
  }, [mariuses, searchQuery, statusFilter]);

  // ── Handlers ───────────────────────────────────────────────────────────────
  const resetInviteForm = () => {
    setAgentName('');
    setInstructions('');
    setAgentDescription('');
    setWorkplaces([]);
    setWorkplaceId('');
    setRuntimeOptions({});
    setInviteError('');
    setSelectedSkillIds([]);
    setMakeWorkspaceAgent(false);
  };

  const handleOpenInvite = () => {
    resetInviteForm();
    setInviteModalOpen(true);
    setWorkplacesLoading(true);
    listWorkplaces()
      .then((rows) => {
        setWorkplaces(rows);
        // One workplace is not a choice, so make it rather than ask for it. More than one
        // stays blank: picking for the patron is picking which of their machines this agent
        // lives on for good, and that is not a decision to make on their behalf.
        setWorkplaceId(rows.length === 1 ? rows[0].id : '');
      })
      .catch(() => setWorkplaces([]))
      .finally(() => setWorkplacesLoading(false));
  };

  const doInvite = async () => {
    if (!agentName.trim() || !workplaceId || sending) return;
    setSending(true);
    setInviteError('');
    try {
      // A name and a workplace is the whole of it (FR-007g). Nothing is dialled out to and
      // nothing is pushed, so there is no send to wait on or report.
      await inviteNewAgent({
        name: agentName.trim(),
        instructions: instructions.trim(),
        description: agentDescription.trim(),
        workplaceId,
        skillIds: selectedSkillIds,
        // Only what was actually chosen. A blank travelling as an empty string would be a
        // key the server has to reason about, when what it means is *nothing was picked*.
        runtimeOptions: Object.fromEntries(
          Object.entries(runtimeOptions).filter(([, value]) => value !== ''),
        ),
        isWorkspaceAgent: makeWorkspaceAgent,
      });
      setInviteModalOpen(false);
    } catch (e) {
      // Same cleanup on both paths instead of a `finally`: the React Compiler cannot
      // lower `finally` and gives up on the whole component when it meets one. The
      // refusal is worded from its code, so the person reads why in their own language
      // rather than watching a button do nothing (FR-084a).
      setSending(false);
      setInviteError(errorText(e, t));
      return;
    }
    setSending(false);
  };

  const handleInvite = () => {
    // Seating a new host over a sitting one is a swap — confirm before inviting (#32).
    if (makeWorkspaceAgent && currentHost) {
      setInviteSwapConfirmOpen(true);
      return;
    }
    void doInvite();
  };

  const handleDesignate = useCallback(
    (id: string) => {
      // Real endpoint via the store (#32). A sitting host makes this a swap — confirm.
      const agent = useAppStore.getState().mariuses.find((m) => m.id === id);
      if (!agent) return;
      const host = useAppStore
        .getState()
        .mariuses.find(
          (m) => m.workspaceId === agent.workspaceId && m.isWorkspaceAgent === true
        );
      if (host && host.id !== id) {
        setDesignatingAgent(agent);
        return;
      }
      void designateWorkspaceAgent(id);
    },
    [designateWorkspaceAgent]
  );

  const handleCloseInvite = () => {
    setInviteModalOpen(false);
  };

  const toggleSkill = (skillId: string) => {
    setSelectedSkillIds((prev) =>
      prev.includes(skillId) ? prev.filter((s) => s !== skillId) : [...prev, skillId]
    );
  };

  const clearFilters = () => {
    setSearchQuery('');
    setStatusFilter('all');
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto w-full max-w-[1240px] pb-10">
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="mb-7"
      >
        <PageTitle
          eyebrow={t('directory.eyebrow')}
          title={t('directory.heading')}
          subtitle={t('directory.lead')}
          actions={
            <button type="button" onClick={handleOpenInvite} className="btn btn-primary">
              <UserPlus className="h-[18px] w-[18px]" aria-hidden />
              {t('directory.createAgent')}
            </button>
          }
        />
      </motion.div>

      {/* No host yet: one place to pick one, instead of a button on every card */}
      {!currentHost && mariuses.length > 0 && (
        <section className="mb-6 flex flex-wrap items-center gap-4 rounded-lg border border-gold/35 bg-gold-soft px-5 py-4">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-full border border-dashed border-gold text-gold">
            <Star className="h-5 w-5" aria-hidden />
          </span>
          <div className="min-w-0 flex-[1_1_300px]">
            <h2 className="font-display text-[20px] font-normal leading-snug tracking-[-0.01em] text-ink-strong">
              {t('directory.hostBanner.title')}
            </h2>
            <p className="mt-0.5 font-body text-body-sm text-ink-light">
              {hostCandidates.length > 0 ? t('directory.hostBanner.body') : t('directory.hostBanner.noneOnline')}
            </p>
          </div>
          {hostCandidates.length > 0 && (
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:flex-nowrap">
              <Dropdown
                id="host-pick"
                ariaLabel={t('directory.hostBanner.pick')}
                value={hostPick}
                onChange={setHostPick}
                placeholder={t('directory.hostBanner.pick')}
                items={hostCandidates.map((m) => ({ value: m.id, label: m.displayName || m.name }))}
                size="sm"
                className="min-h-[44px] min-w-[180px] flex-1 sm:w-[220px] sm:flex-none"
              />
              <button
                type="button"
                onClick={() => hostPick && handleDesignate(hostPick)}
                disabled={!hostPick}
                className="btn btn-primary flex-1 sm:flex-none"
              >
                {t('directory.actions.designate')}
              </button>
            </div>
          )}
        </section>
      )}

      {/* Toolbar: search on the left, the reachability filter beside it */}
      {mariuses.length > 0 && (
        <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:gap-4">
          <label className="relative block w-full sm:min-w-0 sm:max-w-[440px] sm:flex-1">
            <span className="sr-only">{t('directory.searchLabel')}</span>
            <Search className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-ink-muted" aria-hidden />
            <input
              type="search"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder={t('directory.searchPlaceholderLong')}
              className="field bg-surface pl-10 text-[13px]"
            />
          </label>
          <div role="group" aria-label={t('directory.filter.label')} className="no-scrollbar flex shrink-0 gap-1 overflow-x-auto">
            {FILTERS.map((key) => {
              const count = mariuses.filter((m) => matchesFilter(m, key)).length;
              const active = statusFilter === key;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => setStatusFilter(key)}
                  aria-pressed={active}
                  className={cn(
                    'inline-flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-md px-3 font-body text-[12px] transition-colors',
                    active
                      ? 'bg-sapphire-soft text-ink-strong'
                      : 'text-ink-light hover:bg-surface-hover hover:text-ink-strong'
                  )}
                >
                  {t(`directory.filter.${key}`)}
                  <span className={cn('font-mono text-[10px]', active ? 'text-sapphire-strong' : 'text-ink-muted')}>
                    {count}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Agent Cards Grid */}
      {mariuses.length === 0 ? (
        <EmptyState
          icon={Users}
          title={t('directory.noAgentsFound')}
          description={t('directory.inviteFirst')}
          action={
            <button type="button" onClick={handleOpenInvite} className="btn btn-primary">
              <UserPlus className="h-4 w-4" aria-hidden />
              {t('directory.createAgent')}
            </button>
          }
        />
      ) : (
        <motion.div
          className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-2 xl:grid-cols-3"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          {filteredAgents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}

          {filteredAgents.length === 0 && (
            <div className="col-span-full flex min-h-[200px] flex-col items-center justify-center px-5 py-6 text-center text-ink-muted">
              <Search className="h-7 w-7" aria-hidden />
              <h3 className="mt-2.5 font-display text-[22px] font-normal text-ink-strong">{t('directory.noAgentsFound')}</h3>
              <p className="mb-4 mt-1 font-body text-body-sm">{t('directory.adjustSearch')}</p>
              <button type="button" onClick={clearFilters} className="btn btn-secondary">
                {t('directory.clearFilters')}
              </button>
            </div>
          )}

          {/* A new seat, at the end of the list — the same form as the header's button. */}
          <motion.button
            variants={cardVariants}
            type="button"
            onClick={handleOpenInvite}
            className="flex min-h-[200px] flex-col items-center justify-center rounded-lg border border-dashed border-line-strong px-6 py-8 text-center text-ink-muted transition-colors hover:border-sapphire hover:text-sapphire-strong md:min-h-[300px]"
          >
            <Plus className="h-7 w-7" aria-hidden />
            <strong className="mt-3 font-display text-[20px] font-normal text-ink-strong">{t('directory.newSeat')}</strong>
            <span className="mt-1 max-w-[240px] font-body text-[12px]">{t('directory.newSeatHint')}</span>
          </motion.button>
        </motion.div>
      )}

      {/* ─── Create Agent Modal ─────────────────────────────────────────────── */}
      <Modal
        isOpen={inviteModalOpen}
        onClose={handleCloseInvite}
        title={
          <span className="block">
            <span className="eyebrow block">{t('directory.createEyebrow')}</span>
            <span className="mt-1.5 block font-display text-[28px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
              {t('directory.createAgent')}
            </span>
          </span>
        }
        maxWidth="max-w-xl"
      >
        <div className="grid gap-5">
          {/* Agent Name */}
          <div>
            <label htmlFor="new-agent-name" className={LABEL_CLS}>
              {t('directory.agentName')} <span className="text-danger">*</span>
            </label>
            <input
              id="new-agent-name"
              type="text"
              value={agentName}
              onChange={(e) => setAgentName(e.target.value)}
              placeholder={t('directory.agentNamePlaceholder')}
              className="field"
            />
          </div>

          {/* Where this agent will work (FR-007f). Required: the attachment is made once
              here and never again, so there is no "decide later". */}
          <div>
            <label htmlFor="new-agent-workplace" className={LABEL_CLS}>
              {t('directory.workplace')} <span className="text-danger">*</span>
            </label>
            {workplacesLoading ? (
              <p className="font-body text-[13px] text-ink-muted">{t('directory.workplaceLoading')}</p>
            ) : workplaces.length === 0 ? (
              // Not an error state — nothing is broken, there is simply nowhere to put an
              // agent yet. Say what to do about it rather than leaving an empty box.
              <div className="rounded-md border border-dashed border-line-strong bg-canvas-deep p-3">
                <p className="font-body text-[13px] text-ink">{t('directory.workplaceNone')}</p>
                <p className="mt-1 font-body text-[12px] text-ink-muted">
                  {t('directory.workplaceNoneHint')}
                </p>
              </div>
            ) : (
              <Dropdown
                id="new-agent-workplace"
                value={workplaceId}
                onChange={(value) => {
                  setWorkplaceId(value);
                  // The settings belong to the **workplace**, not to the agent: two
                  // workplaces offer different ones, and a value carried over from the
                  // last pick would be a setting the new one never offered — refused by
                  // the server at the far end of a form the person thought was filled in.
                  setRuntimeOptions({});
                }}
                placeholder={t('directory.workplacePlaceholder')}
                items={workplaces.map((w) => ({
                  value: w.id,
                  label: t('directory.workplaceOption', {
                    cliKind: w.cliKind,
                    machineName: w.machineName,
                  }),
                }))}
              />
            )}
            <p className={HINT_CLS}>{t('directory.workplaceHint')}</p>
          </div>

          {/* What this workplace's tool takes, as the tool itself answered it (FR-007k,
              FR-017). Nothing here is keyed on which CLI it is: the list arrives with the
              workplace, and a workplace that offered none simply shows nothing. */}
          <RuntimeOptionFields
            options={chosenWorkplace?.options ?? []}
            chosen={runtimeOptions}
            onChange={(key, value) =>
              setRuntimeOptions((was) => ({ ...was, [key]: value }))
            }
          />

          {/* What the agent is told to be (FR-007i). This is the whole of how it
              behaves: there is no per-project role adding to it later. */}
          <div>
            <label htmlFor="new-agent-instructions" className={LABEL_CLS}>
              {t('directory.instructions')}
            </label>
            <textarea
              id="new-agent-instructions"
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              rows={5}
              placeholder={t('directory.instructionsPlaceholder')}
              className="field resize-y py-2.5 leading-relaxed"
            />
            <p className={HINT_CLS}>{t('directory.instructionsHint')}</p>
          </div>

          {/* What the team calls it. Never sent to the agent (FR-007j). */}
          <div>
            <label htmlFor="new-agent-description" className={LABEL_CLS}>
              {t('directory.agentDescription')}{' '}
              <small className="font-normal text-ink-muted">{t('directory.notSentToAgent')}</small>
            </label>
            <input
              id="new-agent-description"
              type="text"
              value={agentDescription}
              onChange={(e) => setAgentDescription(e.target.value)}
              placeholder={t('directory.agentDescriptionPlaceholder')}
              className="field"
            />
            <p className={HINT_CLS}>{t('directory.agentDescriptionHint')}</p>
          </div>

          {/* Workspace Agent seat (#32) */}
          <div>
            <label className="flex cursor-pointer select-none items-start gap-2.5 rounded-md border border-line bg-canvas-deep p-3">
              <input
                type="checkbox"
                checked={makeWorkspaceAgent}
                onChange={(e) => setMakeWorkspaceAgent(e.target.checked)}
                className="mt-0.5 h-4 w-4 accent-sapphire-strong"
              />
              <span>
                <span className="flex items-center gap-1.5 font-body text-[13px] font-semibold text-ink">
                  <Star className="h-3.5 w-3.5 text-gold" aria-hidden />
                  {t('directory.setAsWorkspaceAgent')}
                </span>
                <span className="mt-0.5 block font-body text-[12px] text-ink-muted">
                  {t('directory.setAsWorkspaceAgentHint')}
                </span>
              </span>
            </label>
            {makeWorkspaceAgent && currentHost && (
              <p className="mt-2 rounded-md border border-gold/35 bg-gold-soft px-3 py-2 font-body text-[12px] text-ink">
                {t('directory.replaceHostWarning', {
                  name: currentHost.displayName || currentHost.name,
                })}
              </p>
            )}
          </div>

          {/* Skills */}
          <div>
            <p className={LABEL_CLS}>{t('directory.skills')}</p>
            <div className="flex flex-wrap gap-1.5">
              {/* Only skills people added. The ones every agent carries are never offered:
                  they ride every run whether or not anybody picks them, and the server does
                  not send them (spec 003 FR-123). */}
              {skills.map((skill) => {
                const on = selectedSkillIds.includes(skill.id);
                return (
                  <button
                    key={skill.id}
                    type="button"
                    onClick={() => toggleSkill(skill.id)}
                    aria-pressed={on}
                    className={cn(
                      'inline-flex min-h-[36px] max-w-full items-center gap-1.5 rounded-md border px-3 font-mono text-[11px] transition-colors',
                      on
                        ? 'border-sapphire bg-sapphire-soft text-ink-strong'
                        : 'border-field-line bg-field text-ink-light hover:border-sapphire',
                    )}
                  >
                    {on && <Check className="h-3 w-3 shrink-0" aria-hidden />}
                    <span className="truncate">{skill.name}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* The server's refusal, worded from its own code — a name already taken, a
              workplace that stopped being able to take work between opening this form
              and submitting it. Swallowing it would leave the person clicking a button
              that does nothing and says nothing. */}
          {inviteError && (
            <p className="flex items-start gap-1.5 rounded-md border border-danger/35 bg-danger/[0.08] px-3 py-2 font-body text-[12px] text-danger">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden /> {inviteError}
            </p>
          )}

          {/* Footer buttons */}
          <div className="flex flex-wrap justify-end gap-2.5 border-t border-line pt-4">
            <button type="button" onClick={handleCloseInvite} className="btn btn-secondary">
              {t('common.cancel')}
            </button>
            <button
              type="button"
              onClick={handleInvite}
              disabled={!agentName.trim() || !workplaceId || sending}
              className="btn btn-primary"
            >
              {sending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <UserPlus className="h-4 w-4" aria-hidden />
              )}
              {sending ? t('directory.send.sending') : t('directory.createAgent')}
            </button>
          </div>
        </div>
      </Modal>

      {/* Designate (swap) confirmation — the sitting host is demoted, kept (#32) */}
      <ConfirmDialog
        isOpen={designatingAgent !== null}
        onClose={() => setDesignatingAgent(null)}
        onConfirm={async () => {
          if (designatingAgent) await designateWorkspaceAgent(designatingAgent.id);
        }}
        title={t('directory.designateConfirmTitle')}
        message={t('directory.designateConfirmMessage', {
          name: designatingAgent?.displayName || designatingAgent?.name || '',
          current: currentHost?.displayName || currentHost?.name || '',
        })}
        confirmLabel={t('directory.actions.designate')}
      />

      {/* Create-as-host confirmation — creating the agent performs the swap (#32) */}
      <ConfirmDialog
        isOpen={inviteSwapConfirmOpen}
        onClose={() => setInviteSwapConfirmOpen(false)}
        onConfirm={async () => {
          setInviteSwapConfirmOpen(false);
          await doInvite();
        }}
        title={t('directory.designateConfirmTitle')}
        message={t('directory.designateConfirmMessage', {
          name: agentName.trim(),
          current: currentHost?.displayName || currentHost?.name || '',
        })}
        confirmLabel={t('directory.createAndSwap')}
      />
    </div>
  );
}
