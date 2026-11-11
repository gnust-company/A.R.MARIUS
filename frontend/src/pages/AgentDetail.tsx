// Single-agent detail view (#72) — the one screen where an agent is managed (FR-007m, FR-007o).
// Opened by clicking an agent card in the Directory. The header and the identity card say who
// the agent is and where it works; three tabs below hold what it is doing (Overview), what it has
// done (Activity — every Run dispatched to it, each expandable to its durable trace) and what can
// be changed about it (Configuration: name, runtime settings, skills, instructions, removal).
// A live run advances in place off the workspace event channel — no timer (T167, FR-080).
// The direct chat with the agent (FR-007p) opens as a drawer from the header's Chat button.
import { useEffect, useLayoutEffect, useRef, useState, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowLeft,
  ArrowUpRight,
  ChevronDown,
  ChevronUp,
  Activity,
  Loader2,
  Cpu,
  Monitor,
  Waves,
  Wrench,
  MessageSquare,
  MessageCircle,
  AlertTriangle,
  Check,
  CheckCircle2,
  Clock,
  Plus,
  ExternalLink,
  SlidersHorizontal,
  Sparkles,
  Settings2,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { AgentStatus, PlacementOption } from '@/store/appStore';
import { listMariusRuns, listRunEvents, type RunDTO, type RunEventDTO } from '@/lib/api';
import Modal from '@/components/Modal';
import StatusChip from '@/components/StatusChip';
import AgentAvatar from '@/components/AgentAvatar';
import PageTitle from '@/components/PageTitle';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { onWorkspaceEvent } from '@/hooks/use-workspace-events';
import InstructionsTab from '@/components/agent/InstructionsTab';
import HostRuntimeChooser from '@/components/agent/HostRuntimeChooser';
import SkillsTab, { type SkillRow } from '@/components/agent/SkillsTab';
import SettingsTab from '@/components/agent/SettingsTab';
import SettingsSection from '@/components/agent/SettingsSection';
import AgentChatDrawer from '@/components/agent/AgentChatDrawer';
import { heldTasks, useHydrateWorkspaceTasks } from '@/components/agent/holding';
import ConfirmDialog from '@/components/ConfirmDialog';

// Run lifecycle → the StatusChip tone that means the same thing: in flight is gold, finished
// well is green, failed is red, and a run that never started or was stopped rests faint.
const RUN_CHIP_STATUS: Record<string, string> = {
  queued: 'todo',
  running: 'in_progress',
  completed: 'done',
  failed: 'blocked',
  timed_out: 'blocked',
  stopped: 'cancelled',
};

const CARD = 'rounded-lg border border-line bg-surface';

// ─── Time helpers ─────────────────────────────────────────────────────────────

function useRelativeTime() {
  const { i18n } = useTranslation();
  return useCallback(
    (iso?: string | null): string => {
      if (!iso) return '—';
      const rtf = new Intl.RelativeTimeFormat(i18n.language || 'en', { numeric: 'auto' });
      const diff = (new Date(iso).getTime() - Date.now()) / 1000;
      const abs = Math.abs(diff);
      if (abs < 60) return rtf.format(Math.round(diff), 'second');
      if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
      if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
      return rtf.format(Math.round(diff / 86400), 'day');
    },
    [i18n.language]
  );
}

function formatAbsolute(iso?: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString();
}

// ─── Identity fact (label above, value with its icon below) ───────────────────

function Fact({ label, icon: Icon, children, title }: { label: string; icon?: typeof Cpu; children: React.ReactNode; title?: string }) {
  return (
    <div className="min-w-0">
      <dt className="mb-1.5 font-body text-[11px] text-ink-muted">{label}</dt>
      <dd className="flex min-w-0 items-center gap-1.5 font-body text-[13px] text-ink" title={title}>
        {Icon && <Icon className="h-4 w-4 shrink-0 text-ink-light" aria-hidden />}
        <span className="min-w-0 truncate">{children}</span>
      </dd>
    </div>
  );
}

// ─── Run event row (the durable per-run trace) ────────────────────────────────

function eventText(ev: RunEventDTO): string {
  const p = ev.payload || {};
  return String(p.content ?? p.delta ?? p.text ?? p.tool_name ?? p.message ?? '');
}

function RunEventList({ runId }: { runId: string }) {
  const { t } = useTranslation();
  const [events, setEvents] = useState<RunEventDTO[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // `loading` starts true and this component remounts per run (keyed by expand), so no
    // need to reset it here — that would only trip the set-state-in-effect lint for nothing.
    let alive = true;
    listRunEvents(runId)
      .then((rows) => { if (alive) setEvents(rows); })
      .catch(() => { if (alive) setEvents([]); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [runId]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 px-4 py-3 font-body text-body-sm text-ink-muted">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> {t('agentDetail.loadingTrace')}
      </div>
    );
  }
  if (!events || events.length === 0) {
    return <div className="px-4 py-3 font-body text-body-sm text-ink-muted">{t('agentDetail.noTrace')}</div>;
  }
  return (
    <div className="space-y-1.5 px-3 py-3">
      {events.map((ev) => {
        const isTool = ev.type.includes('tool');
        const Icon = isTool ? Wrench : MessageSquare;
        const text = eventText(ev);
        return (
          <div key={ev.seq} className="flex gap-2.5 rounded-md border border-line bg-surface px-3 py-2">
            <Icon className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-ink-muted" aria-hidden />
            <div className="min-w-0">
              <span className="font-mono text-mono-sm text-ink-muted">{ev.type}</span>
              {text && <p className="whitespace-pre-wrap break-words font-body text-body-sm text-ink">{text}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Run row (one system→agent dispatch) ──────────────────────────────────────

function RunRow({ run }: { run: RunDTO }) {
  const { t } = useTranslation();
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const rel = useRelativeTime();
  const [open, setOpen] = useState(false);
  const wakeLabel = t(`agentDetail.wakeSource.${run.wake_source}`, { defaultValue: run.wake_source });
  const statusLabel = t(`agentDetail.runStatus.${run.status}`, { defaultValue: run.status });
  // Every cause, worded here rather than on the server: the same wake also went to an
  // agent, and that copy is always English (Hiến pháp VII), so the server stores the code
  // and both sides render it. A run recorded before the codes existed has no causes —
  // it falls back to the sentence it does carry.
  const wakeReason = (run.trigger_causes ?? []).length
    ? (run.trigger_causes ?? [])
        .map((c) => t(`agentDetail.wakeReason.${c.code}`, { ...(c.params ?? {}), defaultValue: c.code }))
        .join(' · ')
    : run.trigger_detail;
  const tone = RUN_CHIP_STATUS[run.status] ?? 'cancelled';

  return (
    <div className="overflow-hidden rounded-md border border-line bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 px-4 py-3.5 text-left transition-colors hover:bg-surface-hover sm:px-5"
      >
        <span
          aria-hidden
          className={cn(
            'mt-[7px] h-2 w-2 shrink-0 rounded-full',
            tone === 'in_progress' ? 'bg-gold' : tone === 'done' ? 'bg-success' : tone === 'blocked' ? 'bg-danger' : 'bg-ink-faint',
          )}
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-body text-[14px] font-semibold text-ink-strong">{wakeLabel}</span>
            <StatusChip status={tone} label={statusLabel} />
          </div>
          {wakeReason && (
            <p className="mt-1 line-clamp-2 break-words font-body text-body-sm text-ink-light">{wakeReason}</p>
          )}
          {run.error && (
            <p className="mt-1 flex items-start gap-1.5 break-words font-body text-body-sm text-danger">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" aria-hidden /> {run.error}
            </p>
          )}
          {run.next_action && (
            <p className="mt-1 break-words font-body text-body-sm text-ink-light">
              <span className="text-ink-muted">{t('agentDetail.nextAction')}: </span>{run.next_action}
            </p>
          )}
          <p className="mt-1 font-mono text-[11px] text-ink-muted" title={formatAbsolute(run.created_at)}>
            {rel(run.created_at)}
          </p>
        </div>
        {open ? (
          <ChevronUp className="mt-1 h-4 w-4 flex-shrink-0 text-ink-muted" aria-hidden />
        ) : (
          <ChevronDown className="mt-1 h-4 w-4 flex-shrink-0 text-ink-muted" aria-hidden />
        )}
      </button>
      {open && (
        <div className="border-t border-line bg-canvas-deep">
          <RunEventList runId={run.id} />
          {/* The panel above is a preview. The whole log — every event, filterable, with the
              long fields openable — is its own page, because answering *what did it do and
              why* is a different act from glancing at a run (FR-016, SC-013). */}
          <div className="px-4 pb-2">
            <Link to={wsHref(workspaceId, `runs/${run.id}`)} className="btn-text">
              <ExternalLink className="h-3.5 w-3.5" aria-hidden /> {t('runTrace.openFullLog')}
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// PAGE
// ═══════════════════════════════════════════════════════════════════════════════

/** The sections of this screen, in the order they are offered: what the agent is doing, what it
 *  has done, and what can be changed about it (FR-007m). Named as one list so the bar and the
 *  panels below cannot drift apart. */
const TABS = [
  { id: 'overview', icon: Sparkles },
  { id: 'activity', icon: Activity },
  { id: 'config', icon: Settings2 },
] as const;
type Tab = (typeof TABS)[number]['id'];

export default function AgentDetail() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rel = useRelativeTime();
  const { workspaceId, id } = useParams();
  const mariuses = useAppStore((s) => s.mariuses);
  const workspaces = useAppStore((s) => s.workspaces);
  const tasks = useAppStore((s) => s.tasks);
  const allSkills = useAppStore((s) => s.skills);
  const installAgentSkills = useAppStore((s) => s.installAgentSkills);
  const updateMarius = useAppStore((s) => s.updateMarius);
  const deleteMarius = useAppStore((s) => s.deleteMarius);
  const listAgentOptions = useAppStore((s) => s.listAgentOptions);
  const agent = mariuses.find((m) => m.id === id);

  // The Overview says what this agent holds, and tasks are loaded per project.
  useHydrateWorkspaceTasks();

  const [tab, setTab] = useState<Tab>('overview');
  const [chatOpen, setChatOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // What the place this agent works at lets a person pick (FR-007k), read for the Configuration tab.
  const [options, setOptions] = useState<PlacementOption[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [runs, setRuns] = useState<RunDTO[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Linking skills to an agent. Nothing is pushed at the agent and nothing is confirmed back:
  // a skill travels down with the work that needs it and is written onto the machine that
  // runs the agent, every run (FR-011b). Linking is the whole of the act, which is why these
  // pills carry no install state any more — there is no moment at which a linked skill is not
  // yet installed (FR-011c).
  const [linkSkillsOpen, setLinkSkillsOpen] = useState(false);
  const [selectedNewIds, setSelectedNewIds] = useState<string[]>([]);
  const [installing, setInstalling] = useState(false);
  const [linkFailed, setLinkFailed] = useState(false);
  const [linked, setLinked] = useState(false);

  // Push, not poll (Constitution IV, FR-080). This screen watches an *agent*, and until
  // T167 no channel spoke about agents — so it re-asked the server every fifteen seconds,
  // forever, whether or not the agent had done anything. The server now announces each run
  // lifecycle change on the workspace channel, which is the connection `Layout` already
  // holds open, so listening costs nothing extra.
  //
  // The event is a **signal**, not the data: on receipt this re-reads the run list rather
  // than trying to patch a row out of the payload (contracts/push-events.md, principle 1).
  //
  // This screen is not remounted when the route moves from one agent to another, so an answer
  // about the agent just left can arrive after the move. `shown` is the agent on screen now;
  // an answer for any other is dropped.
  const shown = useRef(id);
  useLayoutEffect(() => { shown.current = id; }, [id]);

  const loadRuns = useCallback(() => {
    if (!workspaceId || !id) return;
    listMariusRuns(workspaceId, id)
      .then((rows) => { if (shown.current === id) { setRuns(rows); setError(null); } })
      .catch((e) => { if (shown.current === id) setError(errorText(e, t)); });
  }, [workspaceId, id, t]);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const loadOptions = useCallback(() => {
    if (!id) return;
    listAgentOptions(id)
      .then((rows) => { if (shown.current === id) setOptions(rows); })
      .catch(() => { if (shown.current === id) setOptions([]); })
      .finally(() => { if (shown.current === id) setOptionsLoading(false); });
  }, [id, listAgentOptions]);

  useEffect(() => { loadOptions(); }, [loadOptions]);

  // One re-read per burst, not one per event. A single run announces itself three times
  // (opened, started, finished) and several runs can land together, so reacting to each
  // event separately would fire more requests in a busy moment than the 15s timer this
  // replaced. Coalescing keeps the screen honest — the last event in a burst still wins,
  // because the re-read happens after it.
  useEffect(() => {
    if (!workspaceId || !id) return;
    let pending: ReturnType<typeof setTimeout> | null = null;
    const unsubscribe = onWorkspaceEvent((event) => {
      if (event.type !== 'run.status_changed') return;
      // The channel carries every agent in the workspace; only this one's runs are on screen.
      if (event.payload.marius_id !== id) return;
      if (pending) return;
      pending = setTimeout(() => { pending = null; loadRuns(); }, 300);
    });
    return () => {
      if (pending) clearTimeout(pending);
      unsubscribe();
    };
  }, [workspaceId, id, loadRuns]);

  const closeChat = useCallback(() => setChatOpen(false), []);

  const status: AgentStatus = agent?.status || 'offline';
  const statusLabel = t('directory.status.' + status);
  const displayName = agent?.displayName || agent?.name || t('agentDetail.agentFallback');
  const linkedSkillNames = agent?.skills || [];
  const workspace = workspaces.find((w) => w.id === workspaceId);
  // The host with nowhere to work is the one agent that may be given a runtime after it was
  // made (spec 003 FR-128). Read off the workspace's seat, not off a flag on the agent row:
  // the seat is the server's answer to *who is the host*.
  const isHost = agent != null && workspace?.workspaceAgentId === agent.id;
  const needsRuntime = isHost && !agent?.runtime;
  const roleText = isHost || agent?.isWorkspaceAgent ? t('directory.hostRole') : agent?.role || t('directory.noRole');
  const offlineNote = agent?.offlineReason
    ? t('agentDetail.offlineReason.' + agent.offlineReason, {
        defaultValue: t('agentDetail.offlineReason.unknown'),
      })
    : undefined;

  const held = id ? heldTasks(tasks, id) : [];
  const holding = held[0];

  // The picker offers EVERY workspace skill — a linked one can be re-selected to re-push an
  // updated copy of its files (#74/#105), not only newly-linked skills.
  const linkedNameSet = new Set(linkedSkillNames);

  // What this agent carries, as id + name. The ids are what a remove has to send a shorter list
  // of; the names are what a person reads. Resolved against the workspace's skills so a name
  // that changed since it was linked reads as its current one.
  const skillNameById = new Map(allSkills.map((skill) => [skill.id, skill.name]));
  const carriedSkills: SkillRow[] = (agent?.skillIds ?? []).map((skillId, index) => ({
    id: skillId,
    name: skillNameById.get(skillId) ?? linkedSkillNames[index] ?? skillId,
  }));

  const saveInstructions = async (next: string) => {
    if (!agent) return;
    setError(null);
    try {
      await updateMarius(agent.id, { instructions: next });
    } catch (err) {
      setError(errorText(err, t));
      throw err;
    }
  };

  const saveProfile = async (next: { name: string; description: string }) => {
    if (!agent) return;
    setError(null);
    try {
      await updateMarius(agent.id, { name: next.name, description: next.description });
    } catch (err) {
      setError(errorText(err, t));
      throw err;
    }
  };

  const saveRuntimeOptions = async (touched: Record<string, string>) => {
    if (!agent) return;
    setError(null);
    try {
      await updateMarius(agent.id, { runtimeOptions: touched });
    } catch (err) {
      setError(errorText(err, t));
      throw err;
    }
  };

  const removeAgent = async () => {
    if (!agent) return;
    setError(null);
    try {
      await deleteMarius(agent.id);
      navigate(wsHref(workspaceId, '/agents'));
    } catch (err) {
      setError(errorText(err, t));
    }
  };

  // Taking a skill off is sending the list back one shorter — there is no per-skill door, and a
  // whole list is what says *these and no others* (FR-007m).
  const removeSkill = async (skillId: string) => {
    if (!agent) return;
    setError(null);
    try {
      await updateMarius(agent.id, {
        skillIds: (agent.skillIds ?? []).filter((one) => one !== skillId),
      });
    } catch (err) {
      setError(errorText(err, t));
      throw err;
    }
  };

  const toggleNewSkill = (skillId: string) => {
    setSelectedNewIds((prev) =>
      prev.includes(skillId) ? prev.filter((s) => s !== skillId) : [...prev, skillId],
    );
  };

  const openLinkSkills = () => {
    setSelectedNewIds([]);
    setLinkFailed(false);
    setLinked(false);
    setLinkSkillsOpen(true);
  };

  const handleInstallSkills = async () => {
    if (!agent || selectedNewIds.length === 0 || installing) return;
    setInstalling(true);
    setLinkFailed(false);
    try {
      await installAgentSkills(agent.id, selectedNewIds);
      setLinked(true);
      setTimeout(() => {
        setLinkSkillsOpen(false);
        setSelectedNewIds([]);
        setLinked(false);
      }, 900);
    } catch {
      setLinkFailed(true);
    }
    setInstalling(false);
  };

  const eyebrow = isHost || agent?.isWorkspaceAgent
    ? t('agentDetail.eyebrowHost', { workspace: workspace?.name ?? '' })
    : t('agentDetail.eyebrowMember', { role: agent?.role || t('agentDetail.agentFallback'), workspace: workspace?.name ?? '' });

  return (
    <div className="mx-auto w-full max-w-[1240px] pb-10">
      <button
        type="button"
        onClick={() => navigate(wsHref(workspaceId, '/agents'))}
        className="-ml-2 mb-4 inline-flex min-h-[44px] items-center gap-2 rounded-md px-2 font-body text-[14px] text-ink-light transition-colors hover:bg-surface-hover hover:text-ink-strong"
      >
        <ArrowLeft className="h-[18px] w-[18px]" aria-hidden /> {t('agentDetail.backToAll')}
      </button>

      <PageTitle
        eyebrow={eyebrow}
        title={displayName}
        subtitle={agent?.description || undefined}
        actions={
          agent && workspaceId ? (
            <>
              <StatusChip status={status} label={statusLabel} size="md" />
              <button
                type="button"
                onClick={() => setChatOpen(true)}
                aria-haspopup="dialog"
                aria-expanded={chatOpen}
                className="btn btn-secondary"
              >
                <MessageCircle className="h-[18px] w-[18px]" aria-hidden />
                {t('agentDetail.chat')}
              </button>
              <button type="button" onClick={() => setTab('config')} className="btn btn-primary">
                <SlidersHorizontal className="h-[18px] w-[18px]" aria-hidden />
                {t('agentDetail.configure')}
              </button>
            </>
          ) : undefined
        }
      />

      {/* Identity: who this is and where it works, every field a real one. */}
      <section className={cn(CARD, 'mt-6 grid grid-cols-1 gap-5 p-5 sm:p-6 lg:grid-cols-[minmax(240px,0.9fr)_1.5fr] lg:items-center lg:gap-7')}>
        <div className="flex min-w-0 items-center gap-4">
          <AgentAvatar name={displayName} status={status} size="lg" />
          <div className="grid min-w-0 gap-1">
            <strong className="flex min-w-0 items-center gap-1.5 font-body text-[15px] font-semibold text-ink-strong">
              <span className="truncate">{roleText}</span>
              {(isHost || agent?.isWorkspaceAgent) && <Sparkles className="h-4 w-4 shrink-0 text-gold" aria-hidden />}
            </strong>
            <small className="font-body text-[12px] text-ink-light">
              {isHost || agent?.isWorkspaceAgent ? t('agentDetail.identity.hostLine') : t('agentDetail.identity.memberLine')}
            </small>
          </div>
        </div>
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Fact label={t('agentDetail.field.runtime')} icon={Cpu}>
            <span className={cn(agent?.runtime && 'font-mono text-[12px]')}>
              {agent?.runtime ? agent.runtime.cli_kind : t('agentDetail.runtimeNoneShort')}
            </span>
          </Fact>
          <Fact label={t('agentDetail.field.machine')} icon={Monitor}>
            {agent?.runtime ? agent.runtime.machine_name : '—'}
          </Fact>
          <Fact label={t('agentDetail.field.model')} icon={Waves}>
            {agent?.runtimeOptions?.model ? (
              <span className="font-mono text-[12px]">{agent.runtimeOptions.model}</span>
            ) : (
              t('agentDetail.modelDefaultShort')
            )}
          </Fact>
          <Fact label={t('agentDetail.field.lastSeen')} icon={Clock} title={formatAbsolute(agent?.lastSeen)}>
            {agent?.lastSeen ? rel(agent.lastSeen) : t('agentDetail.never')}
          </Fact>
        </dl>
        {offlineNote && (
          <div className="rounded-md border border-warning/30 bg-warning/[0.08] px-3.5 py-3 lg:col-span-2">
            <p className="flex items-start gap-2 font-body text-[13px] font-semibold text-ink">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" aria-hidden />
              {status === 'offline' ? t('agentDetail.offlineReasonTitle') : t('agentDetail.offlineReason.label')}
            </p>
            <p className="mt-1 pl-6 font-body text-body-sm text-ink-light">{offlineNote}</p>
          </div>
        )}
      </section>

      {/* Tabs: sapphire underline on the open one. Scrolls sideways on a narrow phone rather
          than wrapping. */}
      <div role="tablist" aria-label={t('agentDetail.tabsLabel')} className="no-scrollbar mb-6 mt-7 flex gap-0.5 overflow-x-auto border-b border-line sm:gap-1">
        {TABS.map(({ id: tabId, icon: Icon }) => {
          const active = tab === tabId;
          return (
            <button
              key={tabId}
              type="button"
              role="tab"
              aria-selected={active}
              data-tab={tabId}
              onClick={() => setTab(tabId)}
              className={cn(
                '-mb-px inline-flex min-h-[48px] shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-2.5 font-body text-[14px] transition-colors sm:px-3.5',
                active
                  ? 'border-sapphire text-ink-strong'
                  : 'border-transparent text-ink-light hover:text-ink-strong',
              )}
            >
              <Icon className="h-[17px] w-[17px]" aria-hidden />
              {t('agentDetail.tab.' + tabId)}
            </button>
          );
        })}
      </div>

      {/* One place for what went wrong, above whichever tab is open. */}
      {error && (
        <div role="alert" className="mb-5 flex items-start gap-2 rounded-md border border-danger/35 bg-danger/[0.08] px-4 py-3 font-body text-body-sm text-danger">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" aria-hidden /> <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      <AnimatePresence mode="wait" initial={false}>
        {/* ── Overview: what it holds and what it is equipped with ── */}
        {tab === 'overview' && (
          <motion.div
            key="overview"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            className="grid grid-cols-1 gap-5 lg:grid-cols-[1.15fr_0.85fr]"
          >
            {needsRuntime && agent && workspaceId && (
              <section className={cn(CARD, 'p-5 sm:p-7 lg:col-span-2')}>
                <HostRuntimeChooser
                  workspaceId={workspaceId}
                  hostId={agent.id}
                  hostName={displayName}
                />
              </section>
            )}

            <section className={cn(CARD, 'min-w-0 p-5 sm:p-7')}>
              <p className="eyebrow">{t('agentDetail.holding.eyebrow')}</p>
              {holding ? (
                <>
                  <div className="mt-5 flex flex-wrap items-center gap-2">
                    {holding.identifier && <span className="task-code">{holding.identifier}</span>}
                    <StatusChip status={holding.status} label={t(`tasks.status.${holding.status}`)} />
                  </div>
                  <h2 className="mt-2 break-words font-display text-[26px] font-normal leading-snug tracking-[-0.02em] text-ink-strong">
                    {holding.title}
                  </h2>
                  {holding.description && (
                    <p className="mt-2 line-clamp-3 whitespace-pre-line font-body text-[14px] leading-relaxed text-ink-light">
                      {holding.description}
                    </p>
                  )}
                  {holding.cardCounts && (
                    <div className="my-5 flex flex-wrap gap-x-6 gap-y-2 border-y border-line py-4 font-body text-[12px] text-ink-light">
                      <span>
                        <strong className="mr-1 text-[18px] font-medium text-ink-strong">
                          {holding.cardCounts.criteriaPassed}/{holding.cardCounts.criteriaTotal}
                        </strong>
                        {t('agentDetail.holding.criteria')}
                      </span>
                      <span>
                        <strong className="mr-1 text-[18px] font-medium text-ink-strong">{holding.cardCounts.artifacts}</strong>
                        {t('agentDetail.holding.artifacts')}
                      </span>
                      <span>
                        <strong className="mr-1 text-[18px] font-medium text-ink-strong">{holding.cardCounts.comments}</strong>
                        {t('agentDetail.holding.comments')}
                      </span>
                    </div>
                  )}
                  <Link to={wsHref(workspaceId, `/tasks/${holding.id}`)} className={cn('btn btn-secondary', !holding.cardCounts && 'mt-5')}>
                    {t('agentDetail.holding.open')}
                    <ArrowUpRight className="h-[18px] w-[18px]" aria-hidden />
                  </Link>
                  {held.length > 1 && (
                    <div className="mt-6 border-t border-line pt-4">
                      <p className="font-body text-[12px] text-ink-muted">
                        {t('agentDetail.holding.alsoHolding', { count: held.length - 1 })}
                      </p>
                      <ul className="mt-2 grid gap-1">
                        {held.slice(1, 5).map((tk) => (
                          <li key={tk.id} className="min-w-0">
                            <Link
                              to={wsHref(workspaceId, `/tasks/${tk.id}`)}
                              className="flex min-h-[36px] min-w-0 items-center gap-2 rounded-md px-1.5 font-body text-[13px] text-ink hover:bg-surface-hover"
                            >
                              {tk.identifier && <span className="task-code shrink-0">{tk.identifier}</span>}
                              <span className="truncate">{tk.title}</span>
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <h2 className="mt-5 font-display text-[26px] font-normal leading-snug tracking-[-0.02em] text-ink-strong">
                    {t('agentDetail.holding.none')}
                  </h2>
                  <p className="mt-2 font-body text-[14px] leading-relaxed text-ink-light">{t('agentDetail.holding.noneHint')}</p>
                </>
              )}
            </section>

            <section className={cn(CARD, 'min-w-0 p-5 sm:p-7')}>
              <p className="eyebrow">{t('agentDetail.capabilities.eyebrow')}</p>
              <h2 className="mt-5 font-display text-[26px] font-normal leading-snug tracking-[-0.02em] text-ink-strong">
                {t('agentDetail.capabilities.title')}
              </h2>
              <div className="mt-4 flex flex-wrap gap-1.5">
                {linkedSkillNames.length > 0 ? (
                  linkedSkillNames.map((s) => (
                    <span key={s} className="chip max-w-full truncate px-2.5 py-1.5 text-[12px]">{s}</span>
                  ))
                ) : (
                  <p className="font-body text-body-md text-ink-muted">{t('agentDetail.noSkills')}</p>
                )}
              </div>
              {agent && (
                <button type="button" onClick={openLinkSkills} className="btn btn-secondary btn-sm mt-3">
                  <Plus className="h-4 w-4" aria-hidden /> {t('agentDetail.linkSkills.add')}
                </button>
              )}
              <h3 className="mt-6 font-body text-[14px] font-semibold text-ink-strong">
                {t('agentDetail.capabilities.instructions')}
              </h3>
              <p className="mt-2 line-clamp-6 whitespace-pre-line break-words font-body text-[14px] leading-relaxed text-ink-light">
                {agent?.instructions?.trim() || t('agentDetail.capabilities.noInstructions')}
              </p>
              <button type="button" onClick={() => setTab('config')} className="btn-text mt-1">
                {t('agentDetail.capabilities.edit')}
                <ArrowUpRight className="h-4 w-4" aria-hidden />
              </button>
              <p className="mt-4 border-t border-line pt-3 font-mono text-[10px] text-ink-muted">
                <span className="mr-1.5">{t('agentDetail.field.id')}</span>
                <span className="break-all">{id}</span>
              </p>
            </section>
          </motion.div>
        )}

        {/* ── Activity (system↔agent run log) ── */}
        {tab === 'activity' && (
          <motion.section
            key="activity"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            className={cn(CARD, 'p-5 sm:p-7')}
          >
            <header className="mb-5 flex flex-wrap items-end justify-between gap-2">
              <div>
                <p className="eyebrow">{t('agentDetail.activityEyebrow')}</p>
                <h2 className="mt-2 font-display text-[26px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
                  {t('agentDetail.activityTitle')}
                </h2>
              </div>
              {runs !== null && (
                <span className="font-mono text-[11px] text-ink-muted">
                  {t('agentDetail.runCount', { count: runs.length })}
                </span>
              )}
            </header>

            {runs === null ? (
              <div className="flex items-center justify-center gap-2 py-14 font-body text-body-md text-ink-muted">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> {t('agentDetail.loadingActivity')}
              </div>
            ) : runs.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-line-strong px-6 py-12 text-center">
                <Activity className="mb-1 h-7 w-7 text-ink-muted" aria-hidden />
                <p className="font-body text-[15px] font-semibold text-ink-strong">{t('agentDetail.noActivityTitle')}</p>
                <p className="max-w-sm font-body text-body-md text-ink-light">{t('agentDetail.noActivityHint')}</p>
              </div>
            ) : (
              <div className="space-y-2">
                {runs.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </div>
            )}

            {runs !== null && runs.length > 0 && (
              <p className="mt-4 flex items-center gap-1.5 font-body text-body-sm text-ink-muted">
                <CheckCircle2 className="h-3.5 w-3.5" aria-hidden /> {t('agentDetail.liveHint')}
              </p>
            )}
          </motion.section>
        )}

        {/* ── Configuration: every changeable thing, as numbered blocks ── */}
        {tab === 'config' && agent && (
          <motion.div
            key="config"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            className="grid gap-4"
          >
            <SettingsTab
              key={agent.id}
              name={agent.displayName || agent.name}
              description={agent.description ?? ''}
              runtimeOptions={agent.runtimeOptions ?? {}}
              runtime={agent.runtime}
              options={options}
              optionsLoading={optionsLoading}
              canEdit
              onSave={saveProfile}
              onSaveRuntimeOptions={saveRuntimeOptions}
            />

            <SettingsSection
              index="03"
              title={t('agentDetail.config.skillsTitle')}
              hint={t('agentDetail.skillsTab.hint')}
            >
              <SkillsTab
                carried={carriedSkills}
                canEdit
                onRemove={removeSkill}
                onAdd={openLinkSkills}
              />
            </SettingsSection>

            <SettingsSection
              index="04"
              title={t('agentDetail.config.instructionsTitle')}
              hint={t('agentDetail.instructions.ownHint')}
            >
              <InstructionsTab
                key={agent.id}
                instructions={agent.instructions ?? ''}
                systemInstructions={agent.systemInstructions ?? ''}
                canEdit
                onSave={saveInstructions}
              />
            </SettingsSection>

            <SettingsSection
              index="05"
              tone="danger"
              title={t('agentDetail.deleteAgent')}
              hint={t('agentDetail.config.deleteHint')}
            >
              <div>
                <button type="button" onClick={() => setConfirmDelete(true)} className="btn btn-danger">
                  <Trash2 className="h-4 w-4" aria-hidden /> {t('agentDetail.deleteAgent')}
                </button>
              </div>
            </SettingsSection>
          </motion.div>
        )}
      </AnimatePresence>

      {/* The direct line to this agent (FR-007p), as a drawer from the right edge. */}
      {agent && workspaceId && (
        <AgentChatDrawer
          open={chatOpen}
          onClose={closeChat}
          workspaceId={workspaceId}
          mariusId={agent.id}
          agentName={displayName}
          role={roleText}
          status={status}
          cli={agent.runtime?.cli_kind}
          online={status !== 'offline'}
          offlineNote={offlineNote}
        />
      )}

      {/* Link more skills to the agent (#74). */}
      <Modal
        isOpen={linkSkillsOpen}
        onClose={() => setLinkSkillsOpen(false)}
        title={
          <span className="block font-display text-[26px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
            {t('agentDetail.linkSkills.title', { name: displayName })}
          </span>
        }
        footer={
          <>
            <button type="button" onClick={() => setLinkSkillsOpen(false)} className="btn btn-secondary">
              {t('common.cancel')}
            </button>
            <button
              type="button"
              onClick={handleInstallSkills}
              disabled={selectedNewIds.length === 0 || installing}
              className="btn btn-primary"
            >
              {installing && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
              {linkFailed
                ? t('agentDetail.linkSkills.retry')
                : installing
                  ? t('agentDetail.linkSkills.sending')
                  : t('agentDetail.linkSkills.confirm')}
            </button>
          </>
        }
      >
        <p className="mb-4 font-body text-body-md text-ink-light">{t('agentDetail.linkSkills.hint')}</p>
        {allSkills.length === 0 ? (
          <p className="font-body text-body-md text-ink-muted">{t('agentDetail.linkSkills.noneAvailable')}</p>
        ) : (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {allSkills.map((skill) => {
              const isLinked = linkedNameSet.has(skill.name);
              const selected = selectedNewIds.includes(skill.id);
              return (
                <button
                  key={skill.id}
                  type="button"
                  onClick={() => toggleNewSkill(skill.id)}
                  aria-pressed={selected}
                  title={isLinked ? t('agentDetail.linkSkills.reinstallHint') : undefined}
                  className={cn(
                    'flex min-h-[45px] min-w-0 items-center gap-2.5 rounded-md border px-3 py-2 text-left font-mono text-[12px] transition-colors',
                    selected
                      ? 'border-sapphire bg-sapphire-soft text-ink-strong'
                      : 'border-field-line bg-field text-ink-light hover:border-sapphire',
                  )}
                >
                  <span
                    aria-hidden
                    className={cn(
                      'grid h-4 w-4 shrink-0 place-items-center rounded-[4px] border',
                      selected ? 'border-sapphire-strong bg-sapphire-strong text-sapphire-ink' : 'border-line-strong',
                    )}
                  >
                    {selected && <Check className="h-3 w-3" strokeWidth={3} />}
                  </span>
                  <span className="min-w-0 flex-1 break-all">{skill.name}</span>
                  {isLinked && !selected && (
                    <span className="shrink-0 font-body text-[11px] text-ink-muted">
                      {t('agentDetail.linkSkills.linkedTag')}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
        {linked && (
          <p className="mt-4 flex items-center gap-2 rounded-md border border-success/30 bg-success-soft px-3.5 py-2.5 font-body text-body-sm text-success">
            <CheckCircle2 className="h-4 w-4 flex-shrink-0" aria-hidden /> {t('agentDetail.linkSkills.sent')}
          </p>
        )}
        {linkFailed && (
          <p className="mt-4 flex items-center gap-2 rounded-md border border-danger/35 bg-danger/[0.08] px-3.5 py-2.5 font-body text-body-sm text-danger">
            <AlertTriangle className="h-4 w-4 flex-shrink-0" aria-hidden /> {t('agentDetail.linkSkills.sendFailed')}
          </p>
        )}
      </Modal>

      <ConfirmDialog
        isOpen={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onConfirm={removeAgent}
        title={t('agentDetail.deleteTitle')}
        message={t('directory.deleteConfirm', { name: displayName })}
        confirmLabel={t('agentDetail.deleteAgent')}
        danger
      />
    </div>
  );
}
