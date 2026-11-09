import { useState, useMemo, useCallback } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { cn, wsHref, suggestProjectKey } from '@/lib/utils';
import { ApiError } from '@/lib/api';
import { agentsOf } from '@/lib/workspaceScope';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle, Check, CheckCircle2, Loader2, ArrowLeft, ArrowRight, X, PenLine, Sparkles,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore, type Marius } from '@/store/appStore';
import PageTitle from '@/components/PageTitle';
import AgentAvatar from '@/components/AgentAvatar';
import StatusChip from '@/components/StatusChip';
import Dropdown from '@/components/Dropdown';
import OnboardingChat from '@/components/OnboardingChat';

// ─── Types ───────────────────────────────────────────────────────────────────

interface FormData {
  name: string;
  key: string;
  /** Has the user edited the KEY by hand? Until then it auto-follows the name. */
  keyTouched: boolean;
  objective: string;
  targetDate: string;
  githubUrl: string;
  context: string;
  leaderId: string | null;
  leaderDescription: string;
  assignLeaderLater: boolean;
  /** The agents joining the project besides its Leader.
   *
   *  Ids, and nothing else. This step used to collect role forms — a title, a seat count, a
   *  list of skills and a description of the work — and the patron was writing, by hand, a
   *  second description of behaviour beside the instructions already on each agent (FR-007l).
   */
  memberIds: string[];
  /** How many workers this project is asking for (FR-007n).
   *
   *  Kept as text because it is typed: a number state would turn a half-deleted field into 0
   *  or NaN while somebody is still typing, and the box would fight them. It is read into a
   *  number once, on submit.
   *
   *  This replaces the seat count that used to sit inside a role form. The difference is what
   *  it belongs to: a role's seat count described a job nobody had written down yet, while
   *  this describes the project — how many people it wants — and is the only number left on
   *  this screen (FR-007l, FR-007n). */
  workerCount: string;
}

interface FormErrors {
  name?: string;
  objective?: string;
  members?: string;
  workerCount?: string;
  roster?: string;
  [key: string]: string | undefined;
}

// How many workers a project may ask for. Mirrors the door (`worker_count`, ge=1 le=50): the
// server is the one that refuses, and this pair only lets the screen say so first.
const MIN_WORKERS = 1;
const MAX_WORKERS = 50;

// ─── Animation variants ──────────────────────────────────────────────────────

const stepVariants = {
  enter: (direction: number) => ({
    x: direction > 0 ? 20 : -20,
    opacity: 0,
  }),
  center: {
    x: 0,
    opacity: 1,
    transition: { duration: 0.2, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  },
  exit: (direction: number) => ({
    x: direction > 0 ? -20 : 20,
    opacity: 0,
    transition: { duration: 0.15, ease: [0.4, 0, 1, 1] as [number, number, number, number] },
  }),
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

const initialFormData: FormData = {
  name: '',
  key: '',
  keyTouched: false,
  objective: '',
  targetDate: '',
  githubUrl: '',
  context: '',
  leaderId: null,
  leaderDescription: '',
  workerCount: '1',
  assignLeaderLater: false,
  memberIds: [],
};

/** JIRA-style project KEY: 2–10 uppercase chars, starts with a letter. Mirrors backend. */
const PROJECT_KEY_RE = /^[A-Z][A-Z0-9]{1,9}$/;

// ─── Shared field styles ─────────────────────────────────────────────────────

/** Every text box on this form: the shared design field (46px, sapphire focus). */
const FIELD = 'field py-2.5';
const fieldBorder = (hasError: boolean) => (hasError ? 'border-danger' : '');
const LABEL = 'block font-body text-[13px] font-semibold text-ink mb-1.5';
const ERROR = 'mt-1.5 font-body text-[13px] text-danger';
const SECTION_TITLE = 'font-display text-[22px] font-normal tracking-[-0.015em] text-ink-strong';

/** An agent's ringed initial — the same avatar every other screen draws. */
function AgentInitial({ agent, size = 'md' }: { agent: Marius; size?: 'sm' | 'md' }) {
  return <AgentAvatar name={agent.displayName || agent.name || '?'} status={agent.status} size={size} />;
}

/** The three-step rail above the wizard. A module-level component, not one declared
 *  inside the page: a component created during render is a *different* component on
 *  every render, so React unmounts and remounts it — the rail's motion restarts from
 *  scratch each keystroke, and any state it ever gains would be wiped. */
function StepIndicator({ step }: { step: number }) {
  const { t } = useTranslation();

  const steps = [
    { key: 'project', label: t('createProject.steps.project') },
    { key: 'roster', label: t('createProject.steps.roster') },
    { key: 'review', label: t('createProject.steps.review') },
  ];

  return (
    <ol className="flex items-center gap-2 sm:gap-3" aria-label={t('createProject.stepIndicator', { current: step, total: 3 })}>
      {steps.map((s, i) => {
        const stepNum = i + 1;
        const isCompleted = step > stepNum;
        const isCurrent = step === stepNum;

        return (
          <li
            key={s.key}
            aria-current={isCurrent ? 'step' : undefined}
            className={cn('flex items-center gap-2 sm:gap-3 min-w-0', i < steps.length - 1 && 'flex-1')}
          >
            <span
              className={cn(
                'w-7 h-7 shrink-0 rounded-full flex items-center justify-center font-body text-body-sm font-semibold border transition-colors',
                isCompleted && 'bg-success-soft border-success text-success',
                isCurrent && 'bg-sapphire-strong border-sapphire-strong text-sapphire-ink',
                !isCompleted && !isCurrent && 'bg-surface border-line-strong text-ink-muted'
              )}
            >
              {isCompleted ? <Check className="w-3.5 h-3.5" /> : stepNum}
            </span>
            <span
              className={cn(
                'font-body text-body-sm whitespace-nowrap',
                isCurrent ? 'text-ink-strong font-medium' : isCompleted ? 'text-ink-light' : 'text-ink-muted'
              )}
            >
              {s.label}
            </span>
            {/* Connecting line */}
            {i < steps.length - 1 && (
              <span className={cn('h-px flex-1 min-w-3', isCompleted ? 'bg-success' : 'bg-line-strong')} />
            )}
          </li>
        );
      })}
    </ol>
  );
}


// ─── Component ───────────────────────────────────────────────────────────────

export default function CreateProject() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const createProject = useAppStore((s) => s.createProject);
  const everyAgent = useAppStore((s) => s.mariuses);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const workspaces = useAppStore((s) => s.workspaces);
  // The project is created in the active workspace, so only its agents can lead it or join it.
  // The server refuses any other (FR-007q) — better not to offer the refusal.
  const mariuses = useMemo(
    () => agentsOf(everyAgent, activeWorkspaceId),
    [everyAgent, activeWorkspaceId]
  );

  // Get the active workspace to check for Workspace Agent
  const activeWorkspace = useMemo(
    () => workspaces.find((w) => w.id === activeWorkspaceId) || workspaces[0],
    [workspaces, activeWorkspaceId]
  );

  // Check if Workspace Agent exists for this workspace
  const hasWorkspaceAgent = useMemo(
    () => Boolean(activeWorkspace?.workspaceAgentId),
    [activeWorkspace]
  );

  const [step, setStep] = useState(1);
  const [direction, setDirection] = useState(1);
  const [formData, setFormData] = useState<FormData>(initialFormData);
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const [mode, setMode] = useState<'manual' | 'agent'>('manual');

  // Every agent in the directory is a candidate. There was a filter here for the ones still
  // waiting on an approval step; that step is gone, and an agent has been approved from its
  // first second ever since — so the filter was removing nothing (FR-014a).

  // Who the team can be picked from. The Leader is left out because the server refuses an
  // agent that both leads a project and sits on it — better not to offer the refusal.
  const teamCandidates = useMemo(
    () => mariuses.filter((m) => m.id !== formData.leaderId),
    [mariuses, formData.leaderId]
  );

  // ─── Validation ────────────────────────────────────────────────────────────

  const validateStep1 = useCallback((): boolean => {
    const newErrors: FormErrors = {};
    if (!formData.name.trim()) {
      newErrors.name = t('createProject.fields.nameRequired');
    } else if (formData.name.trim().length < 2) {
      newErrors.name = t('createProject.fields.nameMinLength');
    } else if (formData.name.trim().length > 50) {
      newErrors.name = t('createProject.fields.nameMaxLength');
    }
    if (!formData.objective.trim()) {
      newErrors.objective = t('createProject.fields.objectiveRequired');
    }
    // KEY is optional (blank → server derives from name), but if the user typed one it
    // must match the JIRA format. The field auto-fills from the name, so it's rarely blank.
    const key = formData.key.trim().toUpperCase();
    if (key && !PROJECT_KEY_RE.test(key)) {
      newErrors.key = t('createProject.fields.keyInvalid');
    }
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [formData.name, formData.objective, formData.key, t]);

  // The typed number, read once. `parseInt` on a half-typed field is how this stays a text box
  // that behaves: an empty string is not zero, it is *nothing typed yet*, and it fails the
  // range check below rather than silently becoming a project of no workers.
  const workerCount = Number.parseInt(formData.workerCount, 10);
  const workerCountValid =
    Number.isInteger(workerCount) && workerCount >= MIN_WORKERS && workerCount <= MAX_WORKERS;

  const validateStep2 = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    if (!formData.assignLeaderLater && !formData.leaderId) {
      newErrors.roster = t('createProject.validation.noLeader');
    }

    // Leader role description is REQUIRED (strict #112) — it reaches the Leader's prompt.
    if (!formData.leaderDescription.trim()) {
      newErrors.leaderDescription = t('createProject.validation.noLeaderDescription');
    }

    // How many workers this project wants. This is where the old rule lived — *pick at least
    // one agent* — and it was the wrong gate: a new account that skipped the machine step has
    // no agents at all, so the screen refused to create any project, and the only way through
    // was to seat the Workspace Agent as a worker. What a project has to declare is its size;
    // who fills it can come later, and usually does (FR-007n).
    if (!workerCountValid) {
      newErrors.workerCount = t('createProject.validation.badWorkerCount', {
        min: MIN_WORKERS,
        max: MAX_WORKERS,
      });
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [formData, t, workerCountValid]);

  const isRosterValid = useMemo(() => {
    const hasLeaderOrLater = formData.assignLeaderLater || !!formData.leaderId;
    const hasLeaderDescription = formData.leaderDescription.trim().length > 0;
    return hasLeaderOrLater && hasLeaderDescription && workerCountValid;
  }, [formData, workerCountValid]);

  // ─── Navigation ────────────────────────────────────────────────────────────

  const goNext = () => {
    if (step === 1) {
      if (!validateStep1()) return;
      setDirection(1);
      setStep(2);
    } else if (step === 2) {
      if (!validateStep2()) return;
      setDirection(1);
      setStep(3);
    }
  };

  const goBack = () => {
    setDirection(-1);
    if (step === 2) setStep(1);
    else if (step === 3) setStep(2);
  };

  // ─── Submit ────────────────────────────────────────────────────────────────

  const handleSubmit = async () => {
    if (!validateStep1() || !validateStep2()) return;
    setIsSubmitting(true);

    // Assembled before the block: every `||` fallback in it is a conditional expression,
    // and the React Compiler has no lowering for those inside try/catch.
    const payload = {
      name: formData.name.trim(),
      key: formData.key.trim() || undefined,
      description: formData.objective.trim(),
      objective: formData.objective.trim(),
      workspaceId: activeWorkspaceId || undefined,
      leaderId: formData.leaderId || '',
      leaderDescription: formData.leaderDescription,
      memberIds: formData.memberIds,
      workerCount,
    };
    try {
      const project = await createProject(payload);
      navigate(wsHref(workspaceId, `/projects/${project.id}`));
    } catch (err) {
      setIsSubmitting(false);
      // Key collision (409) or malformed key (422) — bounce to step 1 and flag the field.
      if (err instanceof ApiError && (err.status === 409 || err.status === 422)) {
        // Read out here, not inside the updater below: the caught `err` referenced from a
        // closure is both a local and a captured variable, and the React Compiler refuses
        // that shape — it gave up on this whole 960-line component over this one line.
        const keyMessage =
          err.status === 409
            ? t('createProject.fields.keyTaken')
            : t('createProject.fields.keyInvalid');
        setErrors((p) => ({ ...p, key: keyMessage }));
        setDirection(-1);
        setStep(1);
        return;
      }
      throw err;
    }
  };

  // ─── Who is on the project ─────────────────────────────────────────────────

  const toggleMember = (mariusId: string) => {
    setFormData((prev) => ({
      ...prev,
      memberIds: prev.memberIds.includes(mariusId)
        ? prev.memberIds.filter((id) => id !== mariusId)
        : [...prev.memberIds, mariusId],
    }));
    setErrors((prev) => ({ ...prev, members: undefined }));
  };

  // ─── Render Step 1: Project Info ───────────────────────────────────────────

  const renderStep1 = () => (
    <div className="flex flex-col gap-5">
      <h2 className={SECTION_TITLE}>{t('createProject.step1Title')}</h2>

      {/* Name */}
      <div>
        <label htmlFor="cp-name" className={LABEL}>
          {t('createProject.fields.name')} <span className="text-danger">*</span>
        </label>
        <input
          id="cp-name"
          type="text"
          value={formData.name}
          onChange={(e) => {
            const name = e.target.value;
            setFormData((p) => ({
              ...p,
              name,
              // Auto-suggest the KEY from the name until the user edits it by hand.
              key: p.keyTouched ? p.key : suggestProjectKey(name),
            }));
            if (errors.name) setErrors((p) => ({ ...p, name: undefined }));
          }}
          placeholder={t('createProject.fields.namePlaceholder')}
          className={cn(FIELD, fieldBorder(!!errors.name))}
        />
        {errors.name && <p className={ERROR}>{errors.name}</p>}
      </div>

      {/* Project KEY — JIRA-style prefix of task identifiers "{KEY}-{n}" */}
      <div>
        <label htmlFor="cp-key" className={LABEL}>
          {t('createProject.fields.key')}
        </label>
        <input
          id="cp-key"
          type="text"
          value={formData.key}
          onChange={(e) => {
            // Coerce as the user types: uppercase, ASCII alphanumerics only.
            const cleaned = e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
            setFormData((p) => ({ ...p, key: cleaned, keyTouched: true }));
            if (errors.key) setErrors((p) => ({ ...p, key: undefined }));
          }}
          placeholder={t('createProject.fields.keyPlaceholder')}
          maxLength={10}
          className={cn(
            FIELD,
            fieldBorder(!!errors.key),
            '!w-44 font-mono uppercase tracking-wide placeholder:font-body placeholder:normal-case placeholder:tracking-normal'
          )}
        />
        <p className="mt-1.5 font-body text-body-sm text-ink-muted">{t('createProject.fields.keyHint')}</p>
        {errors.key && <p className={ERROR}>{errors.key}</p>}
      </div>

      {/* Objective */}
      <div>
        <label htmlFor="cp-objective" className={LABEL}>
          {t('createProject.fields.objective')} <span className="text-danger">*</span>
        </label>
        <textarea
          id="cp-objective"
          value={formData.objective}
          onChange={(e) => {
            setFormData((p) => ({ ...p, objective: e.target.value }));
            if (errors.objective) setErrors((p) => ({ ...p, objective: undefined }));
          }}
          placeholder={t('createProject.fields.objectivePlaceholder')}
          rows={3}
          className={cn(FIELD, fieldBorder(!!errors.objective), 'resize-none')}
        />
        {errors.objective && <p className={ERROR}>{errors.objective}</p>}
      </div>

      {/* Target date and repository sit side by side once there is room for both */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-5">
        <div className="min-w-0">
          <label htmlFor="cp-target-date" className={LABEL}>
            {t('createProject.fields.targetDate')}
          </label>
          <input
            id="cp-target-date"
            type="date"
            value={formData.targetDate}
            onChange={(e) => setFormData((p) => ({ ...p, targetDate: e.target.value }))}
            className={cn(FIELD, fieldBorder(false))}
          />
        </div>
        <div className="min-w-0">
          <label htmlFor="cp-github" className={LABEL}>
            {t('createProject.fields.githubUrl')}
          </label>
          <input
            id="cp-github"
            type="text"
            value={formData.githubUrl}
            onChange={(e) => setFormData((p) => ({ ...p, githubUrl: e.target.value }))}
            placeholder={t('createProject.fields.githubUrlPlaceholder')}
            className={cn(FIELD, fieldBorder(false))}
          />
        </div>
      </div>

      {/* Context */}
      <div>
        <label htmlFor="cp-context" className={LABEL}>
          {t('createProject.fields.context')}
        </label>
        <textarea
          id="cp-context"
          value={formData.context}
          onChange={(e) => setFormData((p) => ({ ...p, context: e.target.value }))}
          placeholder={t('createProject.fields.contextPlaceholder')}
          rows={4}
          className={cn(FIELD, fieldBorder(false), 'resize-none')}
        />
      </div>
    </div>
  );

  // ─── Render Step 2: Roster Builder ─────────────────────────────────────────

  const renderStep2 = () => (
    <div className="flex flex-col gap-7">
      <h2 className={SECTION_TITLE}>{t('createProject.step2Title')}</h2>

      {/* HARD Rule Banner — gold while something is still missing, success once it is not */}
      {!bannerDismissed && (
        <div
          className={cn(
            'flex items-start gap-3 rounded-lg border pl-4 pr-1 py-1 transition-colors',
            isRosterValid ? 'bg-success-soft border-success/30' : 'bg-gold-soft border-gold/30'
          )}
        >
          {isRosterValid ? (
            <CheckCircle2 className="w-[18px] h-[18px] text-success mt-3 shrink-0" />
          ) : (
            <AlertTriangle className="w-[18px] h-[18px] text-gold mt-3 shrink-0" />
          )}
          <p className="flex-1 py-2.5 font-body text-body-md text-ink">
            {isRosterValid
              ? t('createProject.roster.rosterValid')
              : t('createProject.roster.hardRuleBanner')}
          </p>
          <button
            onClick={() => setBannerDismissed(true)}
            aria-label={t('common.dismiss')}
            className="w-10 h-10 shrink-0 rounded-md flex items-center justify-center text-ink-light hover:text-ink-strong hover:bg-surface/70 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* ─── Project Leader Section ─── */}
      <section className="flex flex-col gap-3">
        <h3 className={SECTION_TITLE}>
          {t('createProject.roster.projectLeader')}
          <span className="text-danger ml-1">*</span>
        </h3>

        {/* Agent selector dropdown */}
        <div>
          <Dropdown
            value={formData.assignLeaderLater ? 'later' : formData.leaderId || ''}
            onChange={(val) => {
              if (val === 'later') {
                setFormData((p) => ({ ...p, leaderId: null, assignLeaderLater: true }));
              } else {
                setFormData((p) => ({
                  ...p,
                  leaderId: val,
                  assignLeaderLater: false,
                  memberIds: p.memberIds.filter((id) => id !== val),
                }));
              }
              if (errors.roster) setErrors((p) => ({ ...p, roster: undefined }));
            }}
            placeholder={t('createProject.roster.selectAgent')}
            items={[
              // Name and liveness, and nothing in between. There used to be a role in brackets
              // here; the field it read is empty by design, so every agent in this list was
              // offered as "Name () — online".
              ...mariuses.map((agent) => ({
                value: agent.id,
                label: `${agent.displayName || agent.name} — ${t(`directory.status.${agent.status}`, { defaultValue: agent.status })}`,
              })),
              { value: 'later', label: t('createProject.roster.assignLater') },
            ]}
          />
          {mariuses.length === 0 && (
            <p className="mt-1.5 font-body text-body-sm text-ink-muted">
              {t('createProject.roster.noApprovedAgents')}
            </p>
          )}
          {errors.roster && <p className={ERROR}>{errors.roster}</p>}
        </div>

        {/* Selected leader card */}
        {!formData.assignLeaderLater && formData.leaderId && (() => {
          const agent = mariuses.find((a) => a.id === formData.leaderId);
          if (!agent) return null;
          return (
            <div className="flex items-center gap-3 bg-canvas-deep border border-line rounded-md pl-3 pr-1 py-1">
              <AgentInitial agent={agent} />
              <div className="flex-1 min-w-0 py-2">
                <p className="font-body font-medium text-body-md text-ink truncate">{agent.displayName || agent.name}</p>
                <p className="font-mono text-mono-sm text-ink-muted truncate">{agent.adapterType}</p>
              </div>
              <StatusChip status={agent.status} label={t(`directory.status.${agent.status}`, { defaultValue: agent.status })} />
              <button
                onClick={() => setFormData((p) => ({ ...p, leaderId: null }))}
                aria-label={t('createProject.roster.clearLeader')}
                className="w-10 h-10 shrink-0 rounded-md flex items-center justify-center text-ink-light hover:text-danger hover:bg-surface transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          );
        })()}

        {formData.assignLeaderLater && (
          <p className="bg-canvas-deep border border-line rounded-md px-4 py-3 font-body text-body-md text-ink-light">
            {t('createProject.roster.assignLater')}
          </p>
        )}

        {/* Leader role description — reaches the Leader's prompt (#93) */}
        <div>
          <label htmlFor="cp-leader-description" className={LABEL}>
            {t('createProject.roster.leaderDescription')} <span className="text-danger">*</span>
          </label>
          <textarea
            id="cp-leader-description"
            value={formData.leaderDescription}
            onChange={(e) => setFormData((p) => ({ ...p, leaderDescription: e.target.value }))}
            placeholder={t('createProject.roster.leaderDescriptionPlaceholder')}
            rows={3}
            className={cn(FIELD, fieldBorder(!!errors.leaderDescription), 'resize-none')}
          />
          {errors.leaderDescription && <p className={ERROR}>{errors.leaderDescription}</p>}
        </div>
      </section>

      {/* ─── How many workers ─── */}
      <section className="flex flex-col gap-1.5">
        <label htmlFor="cp-worker-count" className={SECTION_TITLE}>
          {t('createProject.roster.workerCount')}
          <span className="text-danger ml-1">*</span>
        </label>
        <p className="font-body text-body-md text-ink-light">{t('createProject.roster.workerCountHint')}</p>
        <input
          id="cp-worker-count"
          type="number"
          inputMode="numeric"
          min={MIN_WORKERS}
          max={MAX_WORKERS}
          value={formData.workerCount}
          onChange={(e) => {
            const typed = e.target.value;
            setFormData((prev) => ({ ...prev, workerCount: typed }));
            if (errors.workerCount) setErrors((prev) => ({ ...prev, workerCount: undefined }));
          }}
          className={cn(FIELD, fieldBorder(!!errors.workerCount), '!w-28 mt-1.5 font-mono')}
        />
        {errors.workerCount && <p className={ERROR}>{errors.workerCount}</p>}
      </section>

      {/* ─── The team ─── */}
      <section className="flex flex-col gap-1.5">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h3 className={SECTION_TITLE}>{t('createProject.roster.team')}</h3>
          <span className="font-body text-body-sm text-ink-muted">
            {t('createProject.roster.teamPicked', { count: formData.memberIds.length })}
          </span>
        </div>
        <p className="font-body text-body-md text-ink-light">{t('createProject.roster.teamHint')}</p>

        {teamCandidates.length === 0 ? (
          <p className="mt-1.5 border border-dashed border-line-strong rounded-md px-4 py-5 text-center font-body text-body-md text-ink-muted">
            {t('createProject.roster.noAgentsYet')}
          </p>
        ) : (
          <div className="mt-1.5 grid grid-cols-1 sm:grid-cols-2 gap-2">
            {teamCandidates.map((agent) => {
              const picked = formData.memberIds.includes(agent.id);
              return (
                <button
                  key={agent.id}
                  onClick={() => toggleMember(agent.id)}
                  aria-pressed={picked}
                  className={cn(
                    'min-w-0 min-h-[64px] flex items-center gap-3 p-3 rounded-md border text-left transition-colors',
                    picked
                      ? 'bg-sapphire-soft border-sapphire'
                      : 'bg-surface border-line hover:border-line-strong hover:bg-surface-hover'
                  )}
                >
                  <AgentInitial agent={agent} size="sm" />
                  <div className="flex-1 min-w-0">
                    <p className="font-body font-medium text-body-md text-ink truncate">
                      {agent.displayName || agent.name}
                    </p>
                    <p className="font-body text-body-sm text-ink-muted truncate">
                      {agent.description || t('createProject.roster.agentNoDescription')}
                    </p>
                  </div>
                  <StatusChip status={agent.status} label={t(`directory.status.${agent.status}`, { defaultValue: agent.status })} />
                  <span
                    className={cn(
                      'w-5 h-5 shrink-0 rounded-[5px] border flex items-center justify-center transition-colors',
                      picked ? 'bg-sapphire-strong border-sapphire-strong text-sapphire-ink' : 'bg-surface border-line-strong'
                    )}
                  >
                    {picked && <Check className="w-3.5 h-3.5" />}
                  </span>
                </button>
              );
            })}
          </div>
        )}
      </section>
    </div>
  );

  // ─── Render Step 3: Review ─────────────────────────────────────────────────

  const renderStep3 = () => {
    // Places, not people: the Leader's one, plus however many workers the project asked for —
    // or however many were seated, when that is more. The same *larger of the two* the roster
    // screen reports, so the review does not promise a different number than the project shows
    // a moment later.
    const workerPlaces = Math.max(workerCountValid ? workerCount : MIN_WORKERS, formData.memberIds.length);
    const totalSeats = workerPlaces + 1;
    const selectedLeader = mariuses.find((a) => a.id === formData.leaderId);
    const pickedMembers = formData.memberIds
      .map((id) => mariuses.find((a) => a.id === id))
      .filter((a): a is NonNullable<typeof a> => Boolean(a));

    return (
      <div className="flex flex-col gap-6">
        <h2 className={SECTION_TITLE}>{t('createProject.step3Title')}</h2>

        {/* Project Summary Card */}
        <div className="bg-canvas-deep border border-line rounded-md p-5">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 mb-2">
            <h3 className="font-display text-[24px] font-normal tracking-[-0.015em] text-ink-strong break-words min-w-0">{formData.name}</h3>
            {formData.key && (
              <span className="task-code border border-line rounded px-1.5 py-0.5">
                {formData.key}
              </span>
            )}
          </div>
          <p className="font-body text-body-md text-ink-light mb-4 whitespace-pre-wrap break-words">{formData.objective}</p>

          <dl className="flex flex-col gap-1 font-body text-body-sm text-ink-light">
            <dd>
              {formData.targetDate
                ? t('createProject.review.targetDate', { date: formData.targetDate })
                : t('createProject.review.noTargetDate')}
            </dd>
            <dd className={cn(formData.githubUrl && 'font-mono text-mono-sm break-all')}>
              {formData.githubUrl
                ? t('createProject.review.githubUrl', { url: formData.githubUrl })
                : t('createProject.review.noGithubUrl')}
            </dd>
            {formData.context && (
              <dd className="mt-2 whitespace-pre-wrap break-words">{formData.context}</dd>
            )}
          </dl>
        </div>

        {/* Roster Summary */}
        <section className="flex flex-col gap-3">
          <h3 className={SECTION_TITLE}>{t('createProject.review.rosterSummary')}</h3>

          {/* Leader */}
          <div className="bg-canvas-deep border border-line rounded-md p-4">
            <p className="font-body text-body-sm font-medium text-ink-light mb-2">
              {t('createProject.roster.projectLeader')}
            </p>
            {selectedLeader ? (
              <div className="flex items-center gap-3">
                <AgentInitial agent={selectedLeader} size="sm" />
                <p className="font-body text-body-md text-ink min-w-0 truncate">
                  {t('createProject.review.leaderAssigned', { name: selectedLeader.displayName || selectedLeader.name })}
                </p>
              </div>
            ) : (
              <p className="font-body text-body-md text-ink-light">
                {t('createProject.review.leaderAssignLater')}
              </p>
            )}
          </div>

          {/* The team. Shown even when nobody was picked — the places are the thing being
              created here, and a project of three empty places is a normal thing to review
              (FR-007n). It used to be hidden unless somebody was seated, which is exactly the
              case a person needs to see before pressing create. */}
          <div className="bg-canvas-deep border border-line rounded-md p-4">
            <p className="font-body text-body-sm font-medium text-ink-light mb-1">
              {t('createProject.roster.team')}
            </p>
            <p className="font-body text-body-md text-ink mb-2">
              {t('createProject.review.workerPlaces', {
                places: workerPlaces,
                seated: pickedMembers.length,
              })}
            </p>
            {pickedMembers.length > 0 && (
              <ul className="flex flex-col gap-2.5 mt-3">
                {pickedMembers.map((agent) => (
                  <li key={agent.id} className="flex items-center gap-3 min-w-0">
                    <AgentInitial agent={agent} size="sm" />
                    <div className="min-w-0">
                      <p className="font-body text-body-md text-ink truncate">
                        {agent.displayName || agent.name}
                      </p>
                      <p className="font-body text-body-sm text-ink-muted truncate">
                        {agent.description || t('createProject.roster.agentNoDescription')}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <div className="border-t border-line mt-3 pt-3">
              <p className="font-body text-body-md font-medium text-ink">
                {t('createProject.review.totalSeats', { count: totalSeats })}
              </p>
            </div>
          </div>
        </section>
      </div>
    );
  };

  // ─── Main Render ───────────────────────────────────────────────────────────

  const createDisabled = isSubmitting || !isRosterValid;

  return (
    <div className="mx-auto w-full max-w-3xl flex flex-col gap-6 pb-10">
      {/* Header */}
      <div className="flex flex-col">
        <Link
          to={wsHref(workspaceId, '/projects')}
          className="group inline-flex items-center gap-2 self-start min-h-[42px] -mt-2 mb-3 font-body text-[14px] font-medium text-ink-light hover:text-sapphire-strong transition-colors"
        >
          <ArrowLeft className="w-4 h-4 transition-transform group-hover:-translate-x-0.5" />
          {t('projectView.allProjects')}
        </Link>
        <PageTitle eyebrow={t('projectView.newProjectEyebrow')} title={t('createProject.title')} />
      </div>

      {/* Mode toggle — manual wizard vs. agent-assisted chat (Sprint 7) */}
      <div className="flex flex-col gap-3">
        {/* Two ways in, drawn as choice cards: the selected one carries the sapphire edge and
            a filled mark, the unavailable one is dimmed and says why on hover. */}
        <div role="radiogroup" aria-label={t('createProject.title')} className="grid gap-2.5 sm:grid-cols-2">
          {(['manual', 'agent'] as const).map((m) => {
            const active = mode === m;
            const disabled = m === 'agent' && !hasWorkspaceAgent;
            const Icon = m === 'manual' ? PenLine : Sparkles;
            return (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={active}
                onClick={() => !disabled && setMode(m)}
                disabled={disabled}
                className={cn(
                  'group flex min-h-[76px] items-start gap-3.5 rounded-lg border px-4 py-3.5 text-left transition-colors',
                  active
                    ? 'border-sapphire bg-sapphire-soft'
                    : disabled
                      ? 'cursor-not-allowed border-line bg-surface opacity-60'
                      : 'border-line bg-surface hover:border-line-strong hover:bg-surface-hover'
                )}
                title={disabled ? t('createProject.mode.agentDisabled') : undefined}
              >
                <span
                  className={cn(
                    'grid h-10 w-10 shrink-0 place-items-center rounded-full border',
                    active ? 'border-sapphire bg-surface text-sapphire-strong' : 'border-line-strong text-ink-light'
                  )}
                >
                  <Icon className="h-[18px] w-[18px]" strokeWidth={1.7} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cn('block font-body text-[15px] font-semibold', disabled ? 'text-ink-muted' : 'text-ink-strong')}>
                    {t(`createProject.mode.${m}`)}
                  </span>
                  <span className="mt-0.5 block font-body text-[13px] leading-snug text-ink-light">
                    {t(`createProject.mode.${m}Desc`)}
                  </span>
                </span>
                <span
                  aria-hidden
                  className={cn(
                    'mt-1 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full border-[1.5px]',
                    active ? 'border-sapphire-strong' : 'border-line-strong'
                  )}
                >
                  {active && <span className="h-2 w-2 rounded-full bg-sapphire-strong" />}
                </span>
              </button>
            );
          })}
        </div>

        {/* Warning message when agent mode is not available */}
        {mode === 'agent' && !hasWorkspaceAgent && (
          <div className="flex items-start gap-3 bg-gold-soft border border-gold/30 rounded-md px-4 py-3">
            <AlertTriangle className="w-[18px] h-[18px] text-gold mt-0.5 shrink-0" />
            <div className="font-body text-body-md text-ink">
              <p className="font-medium">{t('createProject.mode.agentUnavailable')}</p>
              <p className="text-ink-light mt-1">{t('createProject.mode.setupWorkspaceAgent')}</p>
            </div>
          </div>
        )}
      </div>

      {mode === 'agent' ? (
        <OnboardingChat onCreated={(pid) => navigate(wsHref(workspaceId, `/projects/${pid}`))} />
      ) : (
      <div className="surface">
        {/* Step Indicator */}
        <div className="px-5 sm:px-7 pt-5 pb-4 border-b border-line flex flex-col gap-2">
          <p className="font-body text-body-sm text-ink-muted">
            {t('createProject.stepIndicator', { current: step, total: 3 })}
          </p>
          <StepIndicator step={step} />
        </div>

        {/* Step Content */}
        <div className="px-5 sm:px-7 py-6 min-h-[400px] overflow-hidden">
          <AnimatePresence mode="wait" custom={direction}>
            <motion.div
              key={step}
              custom={direction}
              variants={stepVariants}
              initial="enter"
              animate="center"
              exit="exit"
            >
              {step === 1 && renderStep1()}
              {step === 2 && renderStep2()}
              {step === 3 && renderStep3()}
            </motion.div>
          </AnimatePresence>
        </div>

        {/* Footer buttons — wrap on phones, primary stays on the right */}
        <div className="flex flex-wrap items-center justify-between gap-2 px-5 sm:px-7 py-4 border-t border-line">
          {step > 1 ? (
            <button onClick={goBack} className="btn btn-secondary">
              <ArrowLeft className="w-4 h-4" />
              {t('createProject.buttons.back')}
            </button>
          ) : (
            <button onClick={() => navigate(wsHref(workspaceId, '/projects'))} className="btn btn-ghost">
              {t('createProject.buttons.cancel')}
            </button>
          )}

          {step < 3 ? (
            <button onClick={goNext} className="btn btn-primary ml-auto">
              {step === 1 ? t('createProject.buttons.nextRoster') : t('createProject.buttons.nextReview')}
              <ArrowRight className="w-4 h-4" />
            </button>
          ) : (
            <button onClick={handleSubmit} disabled={createDisabled} className="btn btn-primary ml-auto">
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  {t('createProject.buttons.creating')}
                </>
              ) : (
                t('createProject.buttons.createProject')
              )}
            </button>
          )}
        </div>
      </div>
      )}
    </div>
  );
}
