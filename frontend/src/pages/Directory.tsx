import { useState, useMemo, useCallback, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import {
  Users,
  Plus,
  Search,
  Check,
  Star,
  Server,
  Loader2,
  Clock,
  WifiOff,
  Activity,
  Zap,
  AlertTriangle,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { Marius, AgentStatus, WorkplaceChoice } from '@/store/appStore';
import VellumPanel from '@/components/VellumPanel';
import EmptyState from '@/components/EmptyState';
import Modal from '@/components/Modal';
import ConfirmDialog from '@/components/ConfirmDialog';
import RuntimeOptionFields from '@/components/RuntimeOptionFields';
import Dropdown from '@/components/Dropdown';
import PageTitle from '@/components/PageTitle';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { agentsOf } from '@/lib/workspaceScope';
import { useTranslation } from 'react-i18next';

// ─── Animation Variants ──────────────────────────────────────────────────────

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.08, delayChildren: 0.2 },
  },
};

const cardVariants = {
  hidden: { opacity: 0, y: 24, filter: 'blur(2px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  },
};

// ─── Status Configuration ────────────────────────────────────────────────────

const STATUS_CONFIG: Record<
  AgentStatus,
  { color: string; pulse: boolean; label: string; icon: typeof Zap }
> = {
  online: { color: '#3E8F5F', pulse: true, label: 'Online', icon: Zap },
  working: { color: '#3A6EA8', pulse: true, label: 'Working', icon: Activity },
  idle: { color: '#A89A80', pulse: false, label: 'Idle', icon: Clock },
  offline: { color: '#736450', pulse: false, label: 'Offline', icon: WifiOff },
};

// There is no adapter picker any more. It offered three choices of which only one was ever
// registered, and the real answer — which tool runs this agent — follows from the workplace
// the person picks, which is a thing they can actually see and reason about (FR-007g).

// ─── Component: Agent Card ───────────────────────────────────────────────────

/** Which of an agent's tasks says most about what it is doing — running beats waiting. */
const HOLDING_ORDER = ['in_progress', 'in_review', 'blocked', 'todo'];

function AgentCard({ agent }: { agent: Marius }) {
  const { t } = useTranslation();
  const tasks = useAppStore((s) => s.tasks);
  const own = tasks.filter((tk) => tk.assigneeId === agent.id);
  const holding = HOLDING_ORDER.map((st) => own.find((tk) => tk.status === st)).find(Boolean);
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const config = STATUS_CONFIG[agent.status] || STATUS_CONFIG.offline;

  const StatusIcon = config.icon;
  const displayName = agent.displayName || agent.name;
  const agentSkills = agent.skills || [];

  // Click the card → the agent's page, which is where an agent is managed (FR-007o): renaming,
  // settings and removal all live there rather than behind a menu on every card. The one button
  // left on the card stops propagation so acting on an agent never doubles as opening it.
  const openDetail = () => navigate(wsHref(workspaceId, `/agents/${agent.id}`));

  return (
    <motion.div variants={cardVariants} layout>
      <VellumPanel
        className="relative h-full cursor-pointer flex flex-col gap-4"
        onClick={openDetail}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openDetail(); }
        }}
      >
        {/* Top row: status dot + avatar + name + WA badge + menu */}
        <div className="flex items-center gap-3.5">
          {/* Avatar, ringed by liveness — the same ring the sidebar and Home use */}
          <div
            className={cn(
              'w-[52px] h-[52px] rounded-full overflow-hidden flex-shrink-0 flex items-center justify-center font-body text-[19px] font-semibold',
              agent.status === 'offline'
                ? 'bg-vellum text-ink-muted border-2 border-dashed border-ash'
                : 'ring-2 ring-offset-[3px] ring-offset-paper',
              agent.status === 'working' && 'bg-lapis-bg text-lapis-ink ring-lapis',
              (agent.status === 'online' || agent.status === 'idle') && 'bg-verdigris-bg text-verdigris-ink ring-verdigris'
            )}
          >
            {agent.avatar ? (
              <img
                src={agent.avatar}
                alt={displayName}
                className="w-full h-full object-cover"
              />
            ) : (
              displayName.charAt(0).toUpperCase()
            )}
          </div>

          {/* Name + Role */}
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3
                className="font-['Fraunces',Georgia,serif] text-[22px] font-medium text-ink leading-tight"
              >
                {displayName}
              </h3>
              {agent.isWorkspaceAgent === true && (
                <span
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-gold-bg text-gold-ink"
                >
                  <Star className="w-3 h-3" /> {t('directory.workspaceAgent')}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2 mt-1">
              <span
                className="inline-flex items-center gap-1 text-[11px] font-medium"
                style={{ color: config.color }}
              >
                <StatusIcon className="w-3 h-3" />
                {t('directory.status.' + agent.status)}
              </span>
            </div>
          </div>

        </div>

        {/* What it is holding right now — the question a person opens this page to answer. */}
        <div
          className={cn(
            'rounded-lg px-3.5 py-3',
            holding?.status === 'blocked' ? 'bg-vermilion-bg' : 'bg-inset'
          )}
        >
          {holding ? (
            <>
              <div
                className={cn(
                  'font-body text-body-xs font-medium mb-1',
                  holding.status === 'blocked'
                    ? 'text-vermilion-ink'
                    : holding.status === 'in_review'
                      ? 'text-gold-ink'
                      : 'text-ink-muted'
                )}
              >
                {t(`tasks.status.${holding.status}`)}
              </div>
              <div className="font-body text-body-md text-ink truncate">
                {holding.identifier && (
                  <span className="font-mono text-mono-sm text-ink-muted mr-1.5">{holding.identifier}</span>
                )}
                {holding.title}
              </div>
            </>
          ) : (
            <div className="font-body text-body-md text-ink-light">{t('home.agentNoTask')}</div>
          )}
        </div>

        {/* Where it works — the CLI and the machine, which is what tells two agents apart at a
            glance (FR-007o). The status is already said once, beside the name. */}
        <div className="flex items-center gap-1.5 text-[12px] font-mono text-ink-light">
          <Server className="w-3.5 h-3.5 flex-shrink-0" aria-hidden />
          <span className="truncate">
            {agent.runtime
              ? t('agentDetail.runtimeLine', {
                  cli: agent.runtime.cli_kind,
                  machine: agent.runtime.machine_name,
                })
              : t('agentDetail.runtimeNone')}
          </span>
        </div>

        {/* Skills */}
        {agentSkills.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {agentSkills.slice(0, 3).map((skill) => (
              <span
                key={skill}
                className="px-2.5 py-0.5 rounded-full text-[12px] font-medium bg-ash-bg text-ink-light"
              >
                {skill}
              </span>
            ))}
            {agentSkills.length > 3 && (
              <span className="px-2 py-0.5 rounded-full text-[11px] font-medium text-ink-muted">
                {t('directory.moreSkills', { count: agentSkills.length - 3 })}
              </span>
            )}
          </div>
        )}

      </VellumPanel>
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
  const allProjects = useAppStore((s) => s.projects);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  const projectKey = allProjects
    .filter((p) => p.workspaceId === activeWorkspaceId)
    .map((p) => p.id)
    .join(',');
  useEffect(() => {
    projectKey.split(',').filter(Boolean).forEach((id) => void hydrateProject(id).catch(() => {}));
  }, [projectKey, hydrateProject]);

  // Who may become the host: an agent that answers, which an offline one cannot.
  const hostCandidates = useMemo(() => mariuses.filter((m) => m.status !== 'offline'), [mariuses]);
  const [hostPick, setHostPick] = useState('');

  // ── Designate state ────────────────────────────────────────────────────────
  // Renaming, the runtime settings and removal moved to the agent's own page (FR-007o).
  const [designatingAgent, setDesignatingAgent] = useState<Marius | null>(null);

  // ── Filter State ───────────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

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
          (m.adapterType || '').toLowerCase().includes(q) ||
          (m.skills || []).some((s) => s.toLowerCase().includes(q))
      );
    }

    if (statusFilter !== 'all') {
      filtered = filtered.filter((m) => m.status === statusFilter);
    }

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
    // Seating a new host over a sitting one is a swap \u2014 confirm before inviting (#32).
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

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto w-full max-w-[1240px] pb-10">
      {/* Page Header */}
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="flex items-center justify-between mb-6"
      >
        <div className="flex items-center gap-3">
          <PageTitle title={t('directory.pageTitle')} subtitle={t('directory.agentsInWorkspace', { count: mariuses.length })} />
        </div>
        <motion.button
          onClick={handleOpenInvite}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2, duration: 0.3 }}
          className={cn(
            'inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-[15px] font-medium',
            'bg-ink text-white hover:bg-ink/85 transition-all',
            'hover:-translate-y-0.5 hover:shadow-md'
          )}
        >
          <Plus className="w-4 h-4" />
          {t('directory.inviteAgent')}
        </motion.button>
      </motion.div>

      {/* No host yet: one place to pick one, instead of a button on every card */}
      {!currentHost && mariuses.length > 0 && (
        <section className="mb-6 flex flex-wrap items-center gap-4 rounded-xl border border-[#EBCF8A] bg-[#FBF3DF] px-5 py-4">
          <span className="w-12 h-12 shrink-0 rounded-full border-[1.5px] border-dashed border-gold flex items-center justify-center text-gold-ink">
            <Star className="w-5 h-5" />
          </span>
          <div className="flex-[1_1_320px] min-w-0">
            <h2 className="font-display text-[19px] font-medium text-ink">{t('directory.hostBanner.title')}</h2>
            <p className="mt-0.5 font-body text-body-md text-ink-light">
              {hostCandidates.length > 0 ? t('directory.hostBanner.body') : t('directory.hostBanner.noneOnline')}
            </p>
          </div>
          {hostCandidates.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <label htmlFor="host-pick" className="sr-only">{t('directory.hostBanner.pick')}</label>
              <select
                id="host-pick"
                value={hostPick}
                onChange={(e) => setHostPick(e.target.value)}
                className="min-h-[44px] px-3 rounded-md border border-line-strong bg-paper font-body text-body-md text-ink"
              >
                <option value="">{t('directory.hostBanner.pick')}</option>
                {hostCandidates.map((m) => (
                  <option key={m.id} value={m.id}>{m.displayName || m.name}</option>
                ))}
              </select>
              <button
                onClick={() => hostPick && handleDesignate(hostPick)}
                disabled={!hostPick}
                className="min-h-[44px] px-4 rounded-md bg-ink font-body text-body-md font-medium text-paper hover:bg-ink/85 disabled:opacity-50 transition-colors"
              >
                {t('directory.actions.designate')}
              </button>
            </div>
          )}
        </section>
      )}

      {/* Filter Bar */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.2, duration: 0.3 }}
        className="flex flex-col sm:flex-row items-start sm:items-center gap-3 mb-6 flex-wrap"
      >
        {/* Status Filter */}
        <div role="group" aria-label={t('directory.filter.all')} className="flex flex-wrap items-center gap-1.5">
          {(['all', 'working', 'online', 'idle', 'offline'] as const).map((key) => {
            const count = key === 'all' ? mariuses.length : mariuses.filter((m) => m.status === key).length;
            if (key !== 'all' && count === 0) return null;
            const active = statusFilter === key;
            return (
              <button
                key={key}
                onClick={() => setStatusFilter(key)}
                aria-pressed={active}
                className={cn(
                  'min-h-[36px] px-3 rounded-full border font-body text-body-sm font-medium transition-colors',
                  active ? 'bg-ink text-paper border-ink' : 'bg-paper text-ink border-line-strong hover:bg-inset'
                )}
              >
                {key === 'all' ? t('directory.filter.all') : t(`directory.status.${key}`)} {count}
              </button>
            );
          })}
        </div>
        <div className="flex-1" />

        {/* Search */}
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('directory.searchPlaceholder')}
            className={cn(
              'w-full pl-9 pr-4 py-2 rounded-md bg-inset border border-line text-[15px] text-ink',
              'placeholder:text-ink-muted',
              'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
              'transition-all'
            )}
          />
        </div>
      </motion.div>

      {/* Agent Cards Grid */}
      {filteredAgents.length === 0 ? (
        <EmptyState
          icon={Users}
          title={t('directory.noAgentsFound')}
          description={
            searchQuery
              ? t('directory.adjustSearch')
              : t('directory.inviteFirst')
          }
          action={
            !searchQuery && (
              <button
                onClick={handleOpenInvite}
                className={cn(
                  'inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-[15px] font-medium',
                  'bg-ink text-white hover:bg-ink/85 transition-all'
                )}
              >
                <Plus className="w-4 h-4" />
                {t('directory.inviteAgent')}
              </button>
            )
          }
        />
      ) : (
        <motion.div
          className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4 items-stretch"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          {filteredAgents.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </motion.div>
      )}

      {/* ─── Invite Agent Modal ─────────────────────────────────────────────── */}
      <Modal
        isOpen={inviteModalOpen}
        onClose={handleCloseInvite}
        title={
          <span className="font-['Fraunces',Georgia,serif] text-[28px] font-semibold text-ink">
            <span className="title-initial">{t('directory.inviteAgent').charAt(0)}</span>
            {t('directory.inviteAgent').slice(1)}
          </span>
        }
        maxWidth="max-w-xl"
      >
        <div className="space-y-5">
              {/* Agent Name */}
              <div>
                <label className="block text-[13px] font-medium text-ink mb-1">
                  {t('directory.agentName')} <span className="text-terracotta">*</span>
                </label>
                <input
                  type="text"
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder={t('directory.agentNamePlaceholder')}
                  className={cn(
                    'w-full px-4 py-2.5 rounded-md bg-inset border border-line text-[15px] text-ink',
                    'placeholder:text-ink-muted',
                    'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
                    'transition-all'
                  )}
                />
              </div>

              {/* Where this agent will work (FR-007f). Required: the attachment is made once
                  here and never again, so there is no "decide later". */}
              <div>
                <label className="block text-[13px] font-medium text-ink mb-1">
                  {t('directory.workplace')} <span className="text-terracotta">*</span>
                </label>
                {workplacesLoading ? (
                  <p className="text-[13px] text-ink-muted">{t('directory.workplaceLoading')}</p>
                ) : workplaces.length === 0 ? (
                  // Not an error state — nothing is broken, there is simply nowhere to put an
                  // agent yet. Say what to do about it rather than leaving an empty box.
                  <div className="rounded-md border border-line bg-inset p-3">
                    <p className="text-[13px] text-ink">{t('directory.workplaceNone')}</p>
                    <p className="mt-1 text-[11px] text-ink-muted">
                      {t('directory.workplaceNoneHint')}
                    </p>
                  </div>
                ) : (
                  <Dropdown
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
                <p className="mt-1 text-[11px] text-ink-muted">{t('directory.workplaceHint')}</p>
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
                <label className="block text-[13px] font-medium text-ink mb-1">
                  {t('directory.instructions')}
                </label>
                <textarea
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  rows={5}
                  placeholder={t('directory.instructionsPlaceholder')}
                  className={cn(
                    'w-full px-4 py-2.5 rounded-md bg-inset border border-line text-[15px] text-ink',
                    'placeholder:text-ink-muted resize-y',
                    'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
                    'transition-all'
                  )}
                />
                <p className="mt-1 text-[11px] text-ink-muted">{t('directory.instructionsHint')}</p>
              </div>

              {/* What the team calls it. Never sent to the agent (FR-007j). */}
              <div>
                <label className="block text-[13px] font-medium text-ink mb-1">
                  {t('directory.agentDescription')}
                </label>
                <input
                  type="text"
                  value={agentDescription}
                  onChange={(e) => setAgentDescription(e.target.value)}
                  placeholder={t('directory.agentDescriptionPlaceholder')}
                  className={cn(
                    'w-full px-4 py-2.5 rounded-md bg-inset border border-line text-[15px] text-ink',
                    'placeholder:text-ink-muted',
                    'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
                    'transition-all'
                  )}
                />
                <p className="mt-1 text-[11px] text-ink-muted">
                  {t('directory.agentDescriptionHint')}
                </p>
              </div>

              {/* Workspace Agent seat (#32) */}
              <div>
                <label className="flex items-start gap-2.5 cursor-pointer select-none">
                  <input
                    type="checkbox"
                    checked={makeWorkspaceAgent}
                    onChange={(e) => setMakeWorkspaceAgent(e.target.checked)}
                    className="mt-0.5 w-4 h-4 accent-terracotta"
                  />
                  <span>
                    <span className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
                      <Star className="w-3.5 h-3.5 text-gold" />
                      {t('directory.setAsWorkspaceAgent')}
                    </span>
                    <span className="block text-[11px] text-ink-muted">
                      {t('directory.setAsWorkspaceAgentHint')}
                    </span>
                  </span>
                </label>
                {makeWorkspaceAgent && currentHost && (
                  <p className="mt-2 px-3 py-2 rounded-md bg-gold-bg text-[12px] text-gold-ink">
                    {t('directory.replaceHostWarning', {
                      name: currentHost.displayName || currentHost.name,
                    })}
                  </p>
                )}
              </div>

              {/* Skills */}
              <div>
                <label className="block text-[13px] font-medium text-ink mb-1">
                  {t('directory.skills')}
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {/* Only skills people added. The ones every agent carries are never offered:
                      they ride every run whether or not anybody picks them, and the server does
                      not send them (spec 003 FR-123). */}
                  {skills.map((skill) => {
                    const on = selectedSkillIds.includes(skill.id);
                    return (
                      <button
                        key={skill.id}
                        onClick={() => toggleSkill(skill.id)}
                        className={cn(
                          'inline-flex items-center gap-1 px-3 py-1.5 rounded-full text-[11px] font-medium transition-all',
                          on
                            ? 'bg-ink text-white'
                            : 'bg-line text-ink-light hover:bg-line-strong',
                        )}
                      >
                        {on && <Check className="w-3 h-3" />}
                        {skill.name}
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
                <p className="flex items-start gap-1.5 px-3 py-2 rounded-md bg-vermilion-bg text-[12px] text-terracotta-dark border border-[#E3C0B2]">
                  <AlertTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" /> {inviteError}
                </p>
              )}

              {/* Footer buttons */}
              <div className="flex justify-end gap-3 pt-2">
                <button
                  onClick={handleCloseInvite}
                  className="px-4 py-2 rounded-md text-[13px] font-medium bg-paper text-ink border border-line hover:bg-line transition-colors"
                >
                  {t('common.cancel')}
                </button>
                <button
                  onClick={handleInvite}
                  disabled={
                    !agentName.trim() || !workplaceId || sending
                  }
                  className={cn(
                    'inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-all',
                    agentName.trim() && workplaceId && !sending
                      ? 'bg-ink text-white hover:bg-ink/85'
                      : 'bg-line text-ink-muted cursor-not-allowed'
                  )}
                >
                  {sending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {sending ? t('directory.send.sending') : t('directory.invite')}
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
