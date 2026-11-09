// Single-agent detail view (#72) — the one screen where an agent is managed (FR-007m, FR-007o).
// Opened by clicking an agent card in the Directory. The header says who the agent is and
// where it works; the tabs below hold what can be read or changed about it; a direct chat with
// it (FR-007p) sits in a column beside the tabs from xl up, and behind the header's button on
// narrower screens. Activity is the system↔agent run log: every Run dispatched to this agent,
// each expandable to its durable trace. A live run advances in place off the workspace event
// channel — no timer (T167, FR-080). Removing the agent lives here too, behind the header's
// menu, rather than on every card of the list.
import { useEffect, useState, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronDown,
  ChevronUp,
  Star,
  Activity,
  Loader2,
  Globe,
  Code,
  Terminal,
  Settings,
  Server,
  Clock,
  Wrench,
  MessageSquare,
  AlertTriangle,
  Check,
  CheckCircle2,
  Plus,
  ExternalLink,
  MoreHorizontal,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { AgentStatus, PlacementOption } from '@/store/appStore';
import { listMariusRuns, listRunEvents, type RunDTO, type RunEventDTO } from '@/lib/api';
import Modal from '@/components/Modal';
import StatusChip from '@/components/StatusChip';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { onWorkspaceEvent } from '@/hooks/use-workspace-events';
import { useViewport } from '@/hooks/use-viewport';
import InstructionsTab from '@/components/agent/InstructionsTab';
import HostRuntimeChooser from '@/components/agent/HostRuntimeChooser';
import SkillsTab, { type SkillRow } from '@/components/agent/SkillsTab';
import SettingsTab from '@/components/agent/SettingsTab';
import AgentChatPanel, { AGENT_CHAT_INPUT_ID } from '@/components/agent/AgentChatPanel';
import ConfirmDialog from '@/components/ConfirmDialog';

// ─── Liveness ring (the same ring the Directory cards, the sidebar and Home use) ──────────────

const AVATAR_TONE: Record<AgentStatus, string> = {
  working: 'bg-lapis-bg text-lapis-ink ring-2 ring-offset-[3px] ring-offset-vellum ring-lapis',
  online: 'bg-verdigris-bg text-verdigris-ink ring-2 ring-offset-[3px] ring-offset-vellum ring-verdigris',
  idle: 'bg-verdigris-bg text-verdigris-ink ring-2 ring-offset-[3px] ring-offset-vellum ring-verdigris',
  offline: 'bg-paper text-ink-muted border-2 border-dashed border-ash',
};

// Run lifecycle → the StatusChip tone that means the same thing: in flight is lapis, finished
// well is verdigris, failed is vermilion, and a run that never started or was stopped rests ash.
const RUN_CHIP_STATUS: Record<string, string> = {
  queued: 'todo',
  running: 'in_progress',
  completed: 'done',
  failed: 'blocked',
  timed_out: 'blocked',
  stopped: 'cancelled',
};

const ADAPTER_ICON: Record<string, typeof Globe> = {
  openclaw_gateway: Settings,
  claude_local: Code,
  echo: Terminal,
};

// Shared button looks, so the header, the cards and the dialog speak with one voice.
const PRIMARY_BTN =
  'inline-flex items-center justify-center gap-2 min-h-[44px] px-4 rounded-md bg-ink font-body text-body-md font-medium text-paper hover:bg-ink/85 transition-colors disabled:opacity-50 disabled:cursor-not-allowed';
const SECONDARY_BTN =
  'inline-flex items-center justify-center gap-1.5 min-h-[44px] px-4 rounded-md border border-line-strong bg-paper font-body text-body-md font-medium text-ink hover:bg-inset transition-colors';
const CARD = 'rounded-xl border border-line bg-paper';

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

// ─── Field row (label · value) ────────────────────────────────────────────────

function Field({ label, children, wide = false }: { label: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className={cn('min-w-0', wide && 'col-span-full')}>
      <dt className="font-body text-body-sm font-medium text-ink-light">{label}</dt>
      <dd className="mt-1 font-body text-body-md text-ink break-words">{children}</dd>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="font-display text-[20px] font-medium leading-tight text-ink">{children}</h2>;
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
        <Loader2 className="w-3.5 h-3.5 animate-spin" /> {t('agentDetail.loadingTrace')}
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
          <div key={ev.seq} className="flex gap-2.5 px-3 py-2 rounded-lg bg-paper border border-line">
            <Icon className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-ink-muted" aria-hidden />
            <div className="min-w-0">
              <span className="font-mono text-mono-sm text-ink-muted">{ev.type}</span>
              {text && <p className="font-body text-body-sm text-ink break-words whitespace-pre-wrap">{text}</p>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Run card (one system→agent dispatch) ─────────────────────────────────────

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

  return (
    <div className={cn(CARD, 'overflow-hidden')}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="w-full flex items-start gap-3 px-4 sm:px-5 py-3.5 text-left hover:bg-inset transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-body text-[15px] font-medium text-ink">{wakeLabel}</span>
            <StatusChip status={RUN_CHIP_STATUS[run.status] ?? 'cancelled'} label={statusLabel} />
          </div>
          {wakeReason && (
            <p className="mt-1 font-body text-body-sm text-ink-light break-words line-clamp-2">{wakeReason}</p>
          )}
          {run.error && (
            <p className="mt-1 flex items-start gap-1.5 font-body text-body-sm text-vermilion-ink break-words">
              <AlertTriangle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" aria-hidden /> {run.error}
            </p>
          )}
          {run.next_action && (
            <p className="mt-1 font-body text-body-sm text-ink-light break-words">
              <span className="text-ink-muted">{t('agentDetail.nextAction')}: </span>{run.next_action}
            </p>
          )}
          <p className="mt-1 font-body text-body-sm text-ink-muted" title={formatAbsolute(run.created_at)}>
            {rel(run.created_at)}
          </p>
        </div>
        {open ? (
          <ChevronUp className="w-4 h-4 text-ink-muted mt-1 flex-shrink-0" aria-hidden />
        ) : (
          <ChevronDown className="w-4 h-4 text-ink-muted mt-1 flex-shrink-0" aria-hidden />
        )}
      </button>
      {open && (
        <div className="border-t border-line bg-inset">
          <RunEventList runId={run.id} />
          {/* The panel above is a preview. The whole log — every event, filterable, with the
              long fields openable — is its own page, because answering *what did it do and
              why* is a different act from glancing at a run (FR-016, SC-013). */}
          <div className="px-4 pb-3">
            <Link
              to={wsHref(workspaceId, `runs/${run.id}`)}
              className="inline-flex items-center gap-1.5 min-h-[44px] font-body text-body-sm font-medium text-terracotta hover:text-terracotta-dark"
            >
              <ExternalLink className="w-3.5 h-3.5" aria-hidden /> {t('runTrace.openFullLog')}
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

/** The sections of this screen, in the order they are offered.
 *
 *  Overview and Activity are what was already here; the other three are where an agent can
 *  actually be changed (FR-007m). Named as one list so the bar and the panels below cannot
 *  drift apart. */
const TABS = ['overview', 'activity', 'instructions', 'skills', 'settings'] as const;
type Tab = (typeof TABS)[number];

export default function AgentDetail() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rel = useRelativeTime();
  const { workspaceId, id } = useParams();
  const mariuses = useAppStore((s) => s.mariuses);
  const workspaces = useAppStore((s) => s.workspaces);
  const allSkills = useAppStore((s) => s.skills);
  const installAgentSkills = useAppStore((s) => s.installAgentSkills);
  const updateMarius = useAppStore((s) => s.updateMarius);
  const deleteMarius = useAppStore((s) => s.deleteMarius);
  const listAgentOptions = useAppStore((s) => s.listAgentOptions);
  const agent = mariuses.find((m) => m.id === id);

  const [tab, setTab] = useState<Tab>('overview');
  // From xl the chat is a column beside the tabs; below it, a panel opened from the header.
  const wide = useViewport() === 'desktop';
  const [chatOpen, setChatOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  // What the place this agent works at lets a person pick (FR-007k), read for the Settings tab.
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
  const loadRuns = useCallback(() => {
    if (!workspaceId || !id) return;
    listMariusRuns(workspaceId, id)
      .then((rows) => { setRuns(rows); setError(null); })
      .catch((e) => setError(errorText(e, t)));
  }, [workspaceId, id, t]);

  useEffect(() => { loadRuns(); }, [loadRuns]);

  const loadOptions = useCallback(() => {
    if (!id) return;
    listAgentOptions(id)
      .then(setOptions)
      .catch(() => setOptions([]))
      .finally(() => setOptionsLoading(false));
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

  const status: AgentStatus = agent?.status || 'offline';
  const displayName = agent?.displayName || agent?.name || t('agentDetail.agentFallback');
  const AdapterIcon = ADAPTER_ICON[agent?.adapterType || ''] || Globe;
  const linkedSkillNames = agent?.skills || [];
  // The host with nowhere to work is the one agent that may be given a runtime after it was
  // made (spec 003 FR-128). Read off the workspace's seat, not off a flag on the agent row:
  // the seat is the server's answer to *who is the host*.
  const isHost =
    agent != null && workspaces.find((w) => w.id === workspaceId)?.workspaceAgentId === agent.id;
  const needsRuntime = isHost && !agent?.runtime;

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

  // The chat column's toggle. Below xl there is no room for a column beside the tabs, so the
  // chat waits behind the header's button; from xl it is always beside the tabs and the same
  // button only puts the cursor in its box.
  const talk = () => {
    if (wide) {
      document.getElementById(AGENT_CHAT_INPUT_ID)?.focus();
      return;
    }
    setChatOpen((was) => !was);
  };

  return (
    <div className="mx-auto w-full max-w-[1240px] pb-10">

      {/* Header and tabs on the left, the chat beside them from xl — beside the header too, so
          the chat starts at the top of the page and its composer fits on screen. Below xl the
          chat is one column with everything else and comes first when opened, so the button
          that opened it is right above it. One AgentChatPanel either way — two would hold two
          streams open. */}
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="min-w-0 xl:col-start-1 xl:row-start-1">
          <button
            onClick={() => navigate(wsHref(workspaceId, '/agents'))}
            className="-ml-2 mb-3 inline-flex items-center gap-1.5 min-h-[44px] px-2 rounded-md font-body text-body-sm font-medium text-ink-light hover:text-ink hover:bg-inset transition-colors"
          >
            <ChevronLeft className="w-4 h-4" aria-hidden /> {t('agentDetail.backToAgents')}
          </button>

          {/* Header: who this is, whether it is alive, where it works — and the two things a
              person does from here, talking to it and (behind the menu) removing it. */}
          <header className="mb-6 flex flex-wrap items-start gap-x-5 gap-y-4">
            <div
              className={cn(
                'w-16 h-16 rounded-full overflow-hidden flex-shrink-0 flex items-center justify-center font-body text-[24px] font-semibold',
                AVATAR_TONE[status] ?? AVATAR_TONE.offline,
              )}
            >
              {agent?.avatar ? (
                <img src={agent.avatar} alt={displayName} className="w-full h-full object-cover" />
              ) : (
                displayName.charAt(0).toUpperCase()
              )}
            </div>
            <div className="flex-[1_1_240px] min-w-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <h1 className="min-w-0 break-words font-display text-[30px] font-medium leading-[1.1] tracking-tight text-ink">
                  {displayName}
                </h1>
                <StatusChip status={status} label={t('directory.status.' + status)} size="md" />
                {agent?.isWorkspaceAgent === true && (
                  <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full font-body text-body-sm font-medium bg-gold-bg text-gold-ink">
                    <Star className="w-3.5 h-3.5" aria-hidden /> {t('directory.workspaceAgent')}
                  </span>
                )}
              </div>
              {agent?.role && (
                <p className="mt-1.5 font-body text-body-md text-ink-light break-words">{agent.role}</p>
              )}
              {/* Mono only for the CLI and machine names themselves; "none chosen" is a sentence. */}
              <p className="mt-1.5 flex items-center gap-1.5 text-ink-light min-w-0">
                <Server className="w-3.5 h-3.5 flex-shrink-0" aria-hidden />
                <span className={cn('truncate', agent?.runtime ? 'font-mono text-mono-sm' : 'font-body text-body-sm')}>
                  {agent?.runtime
                    ? t('agentDetail.runtimeLine', {
                        cli: agent.runtime.cli_kind,
                        machine: agent.runtime.machine_name,
                      })
                    : t('agentDetail.runtimeNone')}
                </span>
              </p>
            </div>
            {agent && workspaceId && (
              <div className="flex items-center gap-2">
                {!wide && (
                <button
                  type="button"
                  onClick={talk}
                  data-chat-toggle
                  aria-controls="agent-chat"
                  aria-expanded={chatOpen}
                  className={PRIMARY_BTN}
                >
                  <MessageSquare className="w-4 h-4" aria-hidden />
                  {chatOpen
                    ? t('agentDetail.hideChat')
                    : t('agentChat.title', { name: displayName })}
                </button>
                )}
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setMenuOpen((open) => !open)}
                    className="w-11 h-11 inline-flex items-center justify-center rounded-md border border-line-strong bg-paper text-ink-light hover:text-ink hover:bg-inset transition-colors"
                    aria-label={t('agentDetail.moreActions')}
                    aria-expanded={menuOpen}
                  >
                    <MoreHorizontal className="w-5 h-5" aria-hidden />
                  </button>
                  {menuOpen && (
                    <>
                      <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                      <div className="absolute right-0 top-full z-20 mt-1.5 w-52 rounded-lg border border-line bg-paper py-1 shadow-gilt">
                        <button
                          type="button"
                          onClick={() => { setMenuOpen(false); setConfirmDelete(true); }}
                          className="flex w-full items-center gap-2 min-h-[44px] px-3.5 text-left font-body text-body-md text-vermilion-ink hover:bg-vermilion-bg transition-colors"
                        >
                          <Trash2 className="w-4 h-4" aria-hidden /> {t('agentDetail.deleteAgent')}
                        </button>
                      </div>
                    </>
                  )}
                </div>
              </div>
            )}
          </header>

          {/* The screen is a set of sections rather than one page, inherited from Multica's
              agent view: what an agent *is* (its text, its skills, its settings) is a different
              question from what it has been *doing*, and one scroll holding both meant the
              editable half had nowhere to live. Their shape is Overview · Work · Capabilities ·
              Settings; ours is the same idea with the tabs we have things to put in. */}
          <div className="no-scrollbar -mx-4 mb-5 flex overflow-x-auto border-b border-line px-4 sm:mx-0 sm:px-0">
            {TABS.map((id) => (
              <button
                key={id}
                type="button"
                data-tab={id}
                onClick={() => setTab(id)}
                aria-current={tab === id ? 'page' : undefined}
                className={cn(
                  '-mb-px shrink-0 whitespace-nowrap border-b-2 min-h-[44px] px-3.5 font-body text-body-md font-medium transition-colors',
                  tab === id
                    ? 'border-terracotta text-ink'
                    : 'border-transparent text-ink-light hover:text-ink',
                )}
              >
                {t('agentDetail.tab.' + id)}
              </button>
            ))}
          </div>

          {/* One place for what went wrong, above whichever tab is open — a save refused on
              the Settings tab used to be written into a box that only the Activity tab showed. */}
          {error && (
            <div className="mb-4 flex items-start gap-2 px-4 py-3 rounded-lg border border-[#EDB8B0] bg-vermilion-bg font-body text-body-sm text-vermilion-ink">
              <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" aria-hidden /> <span className="min-w-0 break-words">{error}</span>
            </div>
          )}

          {tab === 'instructions' && agent && (
            <section className={cn(CARD, 'max-w-3xl p-5 sm:p-6')}>
              <InstructionsTab
                key={agent.id}
                instructions={agent.instructions ?? ''}
                systemInstructions={agent.systemInstructions ?? ''}
                canEdit
                onSave={saveInstructions}
              />
            </section>
          )}

          {tab === 'skills' && agent && (
            <section className={cn(CARD, 'max-w-3xl p-5 sm:p-6')}>
              <SkillsTab
                carried={carriedSkills}
                canEdit
                onRemove={removeSkill}
                onAdd={() => setLinkSkillsOpen(true)}
              />
            </section>
          )}

          {tab === 'settings' && agent && (
            <section className={cn(CARD, 'max-w-3xl p-5 sm:p-6')}>
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
            </section>
          )}

          {/* Overview: what this agent is and where it works. The run log is its own tab and
              is not repeated here — showing it in both places was the same panel twice. The
              details are one card — liveness and last-seen with them. As a second card they
              made two boxes of very different heights side by side. A host still choosing a
              runtime gets its chooser above it. */}
          {tab === 'overview' && (
            <div className="flex flex-wrap items-start gap-5">
              {needsRuntime && agent && workspaceId && (
                <section className={cn(CARD, 'basis-full p-5 sm:p-6')}>
                  <HostRuntimeChooser
                    workspaceId={workspaceId}
                    hostId={agent.id}
                    hostName={displayName}
                  />
                </section>
              )}

              <section className={cn(CARD, 'basis-full min-w-0 p-5 sm:p-6')}>
                <SectionTitle>{t('agentDetail.details')}</SectionTitle>
                <dl className="mt-4 grid grid-cols-1 sm:grid-cols-2 2xl:grid-cols-3 gap-x-8 gap-y-5">
                  <Field label={t('agentDetail.field.runtime')}>
                    <span className="flex items-start gap-1.5 min-w-0">
                      <AdapterIcon className="w-3.5 h-3.5 mt-[5px] flex-shrink-0 text-ink-light" aria-hidden />
                      <span className={cn('break-words', agent?.runtime && 'font-mono text-mono-sm')}>
                        {agent?.runtime
                          ? t('agentDetail.runtimeLine', {
                              cli: agent.runtime.cli_kind,
                              machine: agent.runtime.machine_name,
                            })
                          : t('agentDetail.runtimeNone')}
                      </span>
                    </span>
                  </Field>
                  <Field label={t('agentDetail.field.model')}>
                    {agent?.runtimeOptions?.model ? (
                      <span className="font-mono text-mono-sm">{agent.runtimeOptions.model}</span>
                    ) : (
                      t('agentDetail.modelDefault')
                    )}
                  </Field>
                  <Field label={t('agentDetail.field.liveness')}>
                    <StatusChip status={status} label={t('directory.status.' + status)} />
                  </Field>
                  <Field label={t('agentDetail.field.lastSeen')}>
                    <span title={formatAbsolute(agent?.lastSeen)}>
                      {agent?.lastSeen ? rel(agent.lastSeen) : t('agentDetail.never')}
                    </span>
                  </Field>
                  <Field label={t('agentDetail.field.workspaceAgent')}>
                    {agent?.isWorkspaceAgent ? t('common.yes') : t('common.no')}
                  </Field>
                  {agent?.offlineReason && (
                    <div className="col-span-full rounded-lg bg-gold-bg px-3.5 py-3">
                      <dt className="sr-only">{t('agentDetail.offlineReason.label')}</dt>
                      <dd className="flex items-start gap-1.5 font-body text-body-md text-gold-ink">
                        <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" aria-hidden />
                        <span className="min-w-0">
                          {t('agentDetail.offlineReason.' + agent.offlineReason, {
                            defaultValue: t('agentDetail.offlineReason.unknown'),
                          })}
                        </span>
                      </dd>
                    </div>
                  )}
                  <Field label={t('agentDetail.field.id')} wide>
                    <span className="font-mono text-mono-sm break-all text-ink-light">{id}</span>
                  </Field>
                </dl>

                <div className="mt-5 pt-5 border-t border-line">
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <h3 className="font-body text-body-sm font-medium text-ink-light">
                      {t('agentDetail.field.skills')}
                    </h3>
                    <button onClick={openLinkSkills} className={cn(SECONDARY_BTN, 'px-3 text-body-sm')}>
                      <Plus className="w-4 h-4" aria-hidden /> {t('agentDetail.linkSkills.add')}
                    </button>
                  </div>
                  {linkedSkillNames.length > 0 ? (
                    <div className="flex flex-wrap gap-1.5">
                      {linkedSkillNames.map((s) => (
                        <span
                          key={s}
                          className="inline-flex items-center px-2.5 py-0.5 rounded-full font-body text-body-sm font-medium bg-ash-bg text-ink-light"
                        >
                          {s}
                        </span>
                      ))}
                    </div>
                  ) : (
                    <p className="font-body text-body-md text-ink-muted">{t('agentDetail.noSkills')}</p>
                  )}
                </div>
              </section>

            </div>
          )}

          {/* ── Activity (system↔agent run log) ── */}
          {tab === 'activity' && (
            <section>
              <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-ink-muted" aria-hidden />
                  <SectionTitle>{t('agentDetail.activity')}</SectionTitle>
                </div>
                {runs !== null && (
                  <span className="font-body text-body-sm text-ink-muted">
                    {t('agentDetail.runCount', { count: runs.length })}
                  </span>
                )}
              </div>

              {runs === null ? (
                <div className={cn(CARD, 'flex items-center justify-center gap-2 py-16 font-body text-body-md text-ink-muted')}>
                  <Loader2 className="w-4 h-4 animate-spin" aria-hidden /> {t('agentDetail.loadingActivity')}
                </div>
              ) : runs.length === 0 ? (
                <div className={cn(CARD, 'flex flex-col items-center justify-center gap-2 px-6 py-14 text-center')}>
                  <div className="mb-1 w-12 h-12 rounded-full bg-inset flex items-center justify-center">
                    <Clock className="w-6 h-6 text-ink-muted" aria-hidden />
                  </div>
                  <p className="font-body text-[15px] font-medium text-ink">{t('agentDetail.noActivityTitle')}</p>
                  <p className="font-body text-body-md text-ink-light max-w-sm">{t('agentDetail.noActivityHint')}</p>
                </div>
              ) : (
                <div className="space-y-2.5">
                  {runs.map((run) => (
                    <RunRow key={run.id} run={run} />
                  ))}
                </div>
              )}

              {runs !== null && runs.length > 0 && (
                <p className="mt-4 flex items-center gap-1.5 font-body text-body-sm text-ink-muted">
                  <CheckCircle2 className="w-3.5 h-3.5" aria-hidden /> {t('agentDetail.liveHint')}
                </p>
              )}
            </section>
          )}
        </div>

        {/* The direct line to this agent (FR-007p). Sticky beside the tabs from xl, so it
            stays in reach while the person scrolls a long run log or edits instructions. */}
        {agent && workspaceId && (
          <aside
            id="agent-chat"
            aria-label={t('agentChat.title', { name: displayName })}
            className={cn(
              'min-w-0 order-first xl:order-none xl:col-start-2 xl:row-start-1 xl:sticky xl:top-[72px]',
              !wide && !chatOpen && 'hidden',
            )}
          >
            <div className="h-[min(560px,78dvh)] xl:h-[min(880px,calc(100dvh-7rem))]">
              <AgentChatPanel
                key={agent.id}
                workspaceId={workspaceId}
                mariusId={agent.id}
                agentName={displayName}
                online={status !== 'offline'}
              />
            </div>
          </aside>
        )}
      </div>

      {/* Post-invite skill install (#74) — link more skills + push a one-time install prompt. */}
      <Modal
        isOpen={linkSkillsOpen}
        onClose={() => setLinkSkillsOpen(false)}
        title={t('agentDetail.linkSkills.title', { name: displayName })}
        footer={
          <>
            <button onClick={() => setLinkSkillsOpen(false)} className={SECONDARY_BTN}>
              {t('common.cancel')}
            </button>
            <button
              onClick={handleInstallSkills}
              disabled={selectedNewIds.length === 0 || installing}
              className={PRIMARY_BTN}
            >
              {installing && <Loader2 className="w-4 h-4 animate-spin" aria-hidden />}
              {linkFailed
                ? t('agentDetail.linkSkills.retry')
                : installing
                  ? t('agentDetail.linkSkills.sending')
                  : t('agentDetail.linkSkills.confirm')}
            </button>
          </>
        }
      >
        <p className="font-body text-body-md text-ink-light mb-4">{t('agentDetail.linkSkills.hint')}</p>
        {allSkills.length === 0 ? (
          <p className="font-body text-body-md text-ink-muted">{t('agentDetail.linkSkills.noneAvailable')}</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {allSkills.map((skill) => {
              const linked = linkedNameSet.has(skill.name);
              const selected = selectedNewIds.includes(skill.id);
              return (
                <button
                  key={skill.id}
                  onClick={() => toggleNewSkill(skill.id)}
                  aria-pressed={selected}
                  title={linked ? t('agentDetail.linkSkills.reinstallHint') : undefined}
                  className={cn(
                    'inline-flex max-w-full items-center gap-1.5 min-h-[40px] px-3.5 py-1.5 rounded-[20px] border text-left break-all font-body text-body-sm font-medium transition-colors',
                    selected
                      ? 'bg-ink text-paper border-ink'
                      : 'bg-paper text-ink border-line-strong hover:bg-inset',
                  )}
                >
                  {selected && <Check className="w-3.5 h-3.5" aria-hidden />}
                  {skill.name}
                  {linked && !selected && (
                    <span className="font-body text-body-xs text-ink-muted">
                      {t('agentDetail.linkSkills.linkedTag')}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
        {linked && (
          <p className="mt-4 flex items-center gap-2 px-3.5 py-2.5 rounded-lg bg-verdigris-bg font-body text-body-sm text-verdigris-ink">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" aria-hidden /> {t('agentDetail.linkSkills.sent')}
          </p>
        )}
        {linkFailed && (
          <p className="mt-4 flex items-center gap-2 px-3.5 py-2.5 rounded-lg border border-[#EDB8B0] bg-vermilion-bg font-body text-body-sm text-vermilion-ink">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" aria-hidden /> {t('agentDetail.linkSkills.sendFailed')}
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
