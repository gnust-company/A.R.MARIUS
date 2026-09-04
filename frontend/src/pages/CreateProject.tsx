import { useState, useMemo, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router';
import { wsHref, suggestProjectKey } from '@/lib/utils';
import { ApiError } from '@/lib/api';
import { motion, AnimatePresence } from 'framer-motion';
import {
  AlertTriangle, CheckCircle2, Loader2, ArrowLeft, ArrowRight, X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/store/appStore';
import PageTitle from '@/components/PageTitle';
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
}

interface FormErrors {
  name?: string;
  objective?: string;
  members?: string;
  roster?: string;
  [key: string]: string | undefined;
}

// ─── Animation variants ──────────────────────────────────────────────────────

const stepVariants = {
  enter: (direction: number) => ({
    x: direction > 0 ? 20 : -20,
    opacity: 0,
  }),
  center: {
    x: 0,
    opacity: 1,
    transition: { duration: 0.3, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  },
  exit: (direction: number) => ({
    x: direction > 0 ? -20 : 20,
    opacity: 0,
    transition: { duration: 0.2, ease: [0.4, 0, 1, 1] as [number, number, number, number] },
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
  assignLeaderLater: false,
  memberIds: [],
};

/** JIRA-style project KEY: 2–10 uppercase chars, starts with a letter. Mirrors backend. */
const PROJECT_KEY_RE = /^[A-Z][A-Z0-9]{1,9}$/;

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
    <div className="flex items-center justify-center gap-0 mb-8">
      {steps.map((s, i) => {
        const stepNum = i + 1;
        const isCompleted = step > stepNum;
        const isCurrent = step === stepNum;
        
        return (
          <div key={s.key} className="flex items-center">
            <div className="flex flex-col items-center gap-1.5">
              {/* Circle */}
              <motion.div
                className={`w-4 h-4 rounded-full flex items-center justify-center border-2 ${
                  isCompleted
                    ? 'bg-[#C25E3A] border-[#C25E3A]'
                    : isCurrent
                    ? 'bg-[#C25E3A] border-[#C25E3A] ring-2 ring-white ring-offset-1 ring-offset-[#C25E3A]'
                    : 'bg-transparent border-[#A89880]'
                }`}
                animate={{
                  scale: isCurrent ? [0.8, 1] : 1,
                }}
                transition={{ duration: 0.3, ease: [0.34, 1.56, 0.64, 1] as [number, number, number, number] }}
              >
                {isCompleted && (
                  <CheckCircle2 className="w-3 h-3 text-white" />
                )}
                {isCurrent && (
                  <div className="w-1.5 h-1.5 rounded-full bg-white" />
                )}
              </motion.div>
              {/* Label */}
              <span
                className={`font-body text-body-xs ${
                  isCompleted
                    ? 'text-[#C25E3A] font-medium'
                    : isCurrent
                    ? 'text-ink font-semibold'
                    : 'text-ink-muted'
                }`}
              >
                {s.label}
              </span>
            </div>

            {/* Connecting line */}
            {i < steps.length - 1 && (
              <div className="w-16 h-0.5 mx-2 -mt-4 relative">
                <div className="absolute inset-0 bg-[#E3D7BC]" />
                <motion.div
                  className="absolute inset-0 bg-[#C25E3A] origin-left"
                  initial={{ scaleX: 0 }}
                  animate={{ scaleX: isCompleted ? 1 : 0 }}
                  transition={{ duration: 0.3 }}
                />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Component ───────────────────────────────────────────────────────────────

export default function CreateProject() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const createProject = useAppStore((s) => s.createProject);
  const mariuses = useAppStore((s) => s.mariuses);
  const activeWorkspaceId = useAppStore((s) => s.activeWorkspaceId);
  const workspaces = useAppStore((s) => s.workspaces);

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

  // Approved agents (status not 'invited' or 'revoked')
  const approvedAgents = useMemo(
    () => mariuses.filter((m) => m.status !== 'invited' && m.status !== 'revoked'),
    [mariuses]
  );

  // Who the team can be picked from. The Leader is left out because the server refuses an
  // agent that both leads a project and sits on it — better not to offer the refusal.
  const teamCandidates = useMemo(
    () => approvedAgents.filter((m) => m.id !== formData.leaderId),
    [approvedAgents, formData.leaderId]
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

  const validateStep2 = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    if (!formData.assignLeaderLater && !formData.leaderId) {
      newErrors.roster = t('createProject.validation.noLeader');
    }

    // Leader role description is REQUIRED (strict #112) — it reaches the Leader's prompt.
    if (!formData.leaderDescription.trim()) {
      newErrors.leaderDescription = t('createProject.validation.noLeaderDescription');
    }

    // A project needs somebody to do the work. That was the old "at least one worker role"
    // rule, and it is now the plain thing it always meant: at least one agent on the project.
    if (formData.memberIds.length === 0) {
      newErrors.members = t('createProject.validation.noMembers');
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [formData, t]);

  const isRosterValid = useMemo(() => {
    const hasLeaderOrLater = formData.assignLeaderLater || !!formData.leaderId;
    const hasLeaderDescription = formData.leaderDescription.trim().length > 0;
    return hasLeaderOrLater && hasLeaderDescription && formData.memberIds.length > 0;
  }, [formData]);

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
    <div className="space-y-5">
      <h2 className="font-display text-display-sm text-ink mb-4">
        {t('createProject.step1Title')}
      </h2>

      {/* Name */}
      <div>
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('createProject.fields.name')} <span className="text-[#C25E3A]">*</span>
        </label>
        <input
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
          className={`w-full bg-vellum border rounded-md px-4 py-2.5 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors ${
            errors.name ? 'border-[#B84A32]' : 'border-[#E3D7BC]'
          }`}
        />
        {errors.name && (
          <p className="mt-1 font-body text-body-sm text-[#B84A32]">{errors.name}</p>
        )}
      </div>

      {/* Project KEY — JIRA-style prefix of task identifiers "{KEY}-{n}" */}
      <div>
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('createProject.fields.key')}
        </label>
        <input
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
          className={`w-40 bg-vellum border rounded-md px-4 py-2.5 font-mono text-body-md text-ink uppercase tracking-wide placeholder:font-body placeholder:normal-case placeholder:tracking-normal placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors ${
            errors.key ? 'border-[#B84A32]' : 'border-[#E3D7BC]'
          }`}
        />
        <p className="mt-1 font-body text-body-xs text-ink-muted">
          {t('createProject.fields.keyHint')}
        </p>
        {errors.key && (
          <p className="mt-1 font-body text-body-sm text-[#B84A32]">{errors.key}</p>
        )}
      </div>

      {/* Objective */}
      <div>
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('createProject.fields.objective')} <span className="text-[#C25E3A]">*</span>
        </label>
        <textarea
          value={formData.objective}
          onChange={(e) => {
            setFormData((p) => ({ ...p, objective: e.target.value }));
            if (errors.objective) setErrors((p) => ({ ...p, objective: undefined }));
          }}
          placeholder={t('createProject.fields.objectivePlaceholder')}
          rows={3}
          className={`w-full bg-vellum border rounded-md px-4 py-2.5 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors resize-none ${
            errors.objective ? 'border-[#B84A32]' : 'border-[#E3D7BC]'
          }`}
        />
        {errors.objective && (
          <p className="mt-1 font-body text-body-sm text-[#B84A32]">{errors.objective}</p>
        )}
      </div>

      {/* Target Date */}
      <div>
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('createProject.fields.targetDate')}
        </label>
        <input
          type="date"
          value={formData.targetDate}
          onChange={(e) => setFormData((p) => ({ ...p, targetDate: e.target.value }))}
          className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-4 py-2.5 font-body text-body-md text-ink focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors"
        />
      </div>

      {/* GitHub URL */}
      <div>
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('createProject.fields.githubUrl')}
        </label>
        <input
          type="text"
          value={formData.githubUrl}
          onChange={(e) => setFormData((p) => ({ ...p, githubUrl: e.target.value }))}
          placeholder={t('createProject.fields.githubUrlPlaceholder')}
          className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-4 py-2.5 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors"
        />
      </div>

      {/* Context */}
      <div>
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('createProject.fields.context')}
        </label>
        <textarea
          value={formData.context}
          onChange={(e) => setFormData((p) => ({ ...p, context: e.target.value }))}
          placeholder={t('createProject.fields.contextPlaceholder')}
          rows={4}
          className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-4 py-2.5 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors resize-none"
        />
      </div>
    </div>
  );

  // ─── Render Step 2: Roster Builder ─────────────────────────────────────────

  const renderStep2 = () => (
    <div className="space-y-6">
      <h2 className="font-display text-display-sm text-ink mb-2">
        {t('createProject.step2Title')}
      </h2>

      {/* HARD Rule Banner */}
      {!bannerDismissed && (
        <motion.div
          className={`relative p-4 rounded-md border-l-4 ${
            isRosterValid
              ? 'bg-[#D8EADD] border-[#4A9E6B]'
              : 'bg-[#F5E8CC] border-[#C4903A]'
          }`}
          animate={{ backgroundColor: isRosterValid ? '#D8EADD' : '#F5E8CC' }}
          transition={{ duration: 0.4 }}
        >
          <button
            onClick={() => setBannerDismissed(true)}
            className="absolute top-2 right-2 p-0.5 text-ink-muted hover:text-ink transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
          <div className="flex items-start gap-2">
            {isRosterValid ? (
              <CheckCircle2 className="w-4 h-4 text-[#4A9E6B] mt-0.5 flex-shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-[#C4903A] mt-0.5 flex-shrink-0" />
            )}
            <p className="font-body text-body-sm text-ink">
              {isRosterValid
                ? t('createProject.roster.rosterValid')
                : t('createProject.roster.hardRuleBanner')}
            </p>
          </div>
        </motion.div>
      )}

      {/* ─── Project Leader Section ─── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-display text-display-sm text-ink">
            {t('createProject.roster.projectLeader')}
            <span className="text-[#C25E3A] ml-1">*</span>
          </h3>
        </div>

        {/* Agent selector dropdown */}
        <div className="mb-3">
          <select
            value={formData.assignLeaderLater ? 'later' : formData.leaderId || ''}
            onChange={(e) => {
              const val = e.target.value;
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
            className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-4 py-2.5 font-body text-body-md text-ink focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors"
          >
            <option value="">{t('createProject.roster.selectAgent')}</option>
            {approvedAgents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {/* Name and liveness, and nothing in between. There used to be a role in
                    brackets here; the field it read is empty by design, so every agent in
                    this list was offered as "Name () — online". */}
                {agent.displayName || agent.name} — {agent.status}
              </option>
            ))}
            <option value="later">{t('createProject.roster.assignLater')}</option>
          </select>
          {approvedAgents.length === 0 && (
            <p className="mt-1 font-body text-body-sm text-ink-muted">
              {t('createProject.roster.noApprovedAgents')}
            </p>
          )}
        </div>

        {/* Leader role description — reaches the Leader's prompt (#93) */}
        <div className="mb-3">
          <label className="block font-body text-body-xs font-medium text-ink-light mb-1">
            {t('createProject.roster.leaderDescription')}
          </label>
          <textarea
            value={formData.leaderDescription}
            onChange={(e) => setFormData((p) => ({ ...p, leaderDescription: e.target.value }))}
            placeholder={t('createProject.roster.leaderDescriptionPlaceholder')}
            rows={2}
            className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-3 py-2 font-body text-body-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors resize-none"
          />
        </div>

        {/* Selected leader card */}
        {!formData.assignLeaderLater && formData.leaderId && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-[#EDE4CE] border border-[#E3D7BC] rounded-md p-4"
          >
            {(() => {
              const agent = approvedAgents.find((a) => a.id === formData.leaderId);
              if (!agent) return null;
              return (
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-full bg-[#C25E3A] flex items-center justify-center text-white font-display text-sm">
                    {(agent.displayName || agent.name || '?').charAt(0)}
                  </div>
                  <div>
                    <p className="font-body font-medium text-body-md text-ink">{agent.displayName || agent.name}</p>
                    <p className="font-body text-body-sm text-ink-light">{agent.adapterType}</p>
                  </div>
                  <button
                    onClick={() => setFormData((p) => ({ ...p, leaderId: null }))}
                    className="ml-auto p-1 text-ink-muted hover:text-[#B84A32] transition-colors"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
              );
            })()}
          </motion.div>
        )}

        {formData.assignLeaderLater && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-[#E8E0D8] border border-[#E3D7BC] rounded-md p-3"
          >
            <p className="font-body text-body-sm text-ink-light">
              {t('createProject.roster.assignLater')}
            </p>
          </motion.div>
        )}
      </div>

      {/* ─── The team ─── */}
      <div>
        <div className="flex items-baseline justify-between mb-1">
          <h3 className="font-display text-display-sm text-ink">
            {t('createProject.roster.team')}
            <span className="text-[#C25E3A] ml-1">*</span>
          </h3>
          <span className="font-mono text-mono-sm text-ink-muted">
            {t('createProject.roster.teamPicked', { count: formData.memberIds.length })}
          </span>
        </div>
        <p className="mb-3 font-body text-body-sm text-ink-light">
          {t('createProject.roster.teamHint')}
        </p>

        {errors.members && (
          <p className="mb-3 font-body text-body-sm text-[#B84A32]">{errors.members}</p>
        )}

        {teamCandidates.length === 0 ? (
          <p className="text-center font-body text-body-sm text-ink-muted py-6">
            {t('createProject.roster.noApprovedAgents')}
          </p>
        ) : (
          <div className="space-y-2">
            {teamCandidates.map((agent) => {
              const picked = formData.memberIds.includes(agent.id);
              return (
                <button
                  key={agent.id}
                  onClick={() => toggleMember(agent.id)}
                  className={`w-full flex items-center gap-3 p-3 rounded-md border text-left transition-colors ${
                    picked
                      ? 'bg-[#EDE4CE] border-[#C25E3A]'
                      : 'bg-vellum border-[#E3D7BC] hover:border-[#D4A843]'
                  }`}
                >
                  <div className="w-8 h-8 rounded-full bg-[#C25E3A] flex items-center justify-center text-white font-display text-xs flex-shrink-0">
                    {(agent.displayName || agent.name || '?').charAt(0)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-body font-medium text-body-md text-ink truncate">
                      {agent.displayName || agent.name}
                    </p>
                    <p className="font-body text-body-xs text-ink-light truncate">
                      {agent.description || t('createProject.roster.agentNoDescription')}
                    </p>
                  </div>
                  <span className="font-mono text-mono-sm text-ink-muted flex-shrink-0">
                    {agent.status}
                  </span>
                  {picked && <CheckCircle2 className="w-4 h-4 text-[#C25E3A] flex-shrink-0" />}
                </button>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );

  // ─── Render Step 3: Review ─────────────────────────────────────────────────

  const renderStep3 = () => {
    const totalSeats = formData.memberIds.length + 1; // + the Leader
    const selectedLeader = approvedAgents.find((a) => a.id === formData.leaderId);
    const pickedMembers = formData.memberIds
      .map((id) => approvedAgents.find((a) => a.id === id))
      .filter((a): a is NonNullable<typeof a> => Boolean(a));

    return (
      <div className="space-y-6">
        <h2 className="font-display text-display-sm text-ink mb-2">
          {t('createProject.step3Title')}
        </h2>

        {/* Project Summary Card */}
        <div className="bg-[#EDE4CE] border border-[#E3D7BC] rounded-md p-6">
          <div className="flex items-baseline gap-3 mb-2">
            <h3 className="font-display text-display-md text-ink">{formData.name}</h3>
            {formData.key && (
              <span className="font-mono text-mono-md text-terracotta">{formData.key}</span>
            )}
          </div>
          <p className="font-body text-body-md text-ink-light mb-4">{formData.objective}</p>

          <div className="space-y-1 font-body text-body-sm text-ink-light">
            {formData.targetDate && (
              <p>{t('createProject.review.targetDate', { date: formData.targetDate })}</p>
            )}
            {!formData.targetDate && (
              <p>{t('createProject.review.noTargetDate')}</p>
            )}
            {formData.githubUrl && (
              <p className="font-mono">{t('createProject.review.githubUrl', { url: formData.githubUrl })}</p>
            )}
            {!formData.githubUrl && (
              <p>{t('createProject.review.noGithubUrl')}</p>
            )}
            {formData.context && (
              <p className="mt-2 text-ink-light">{formData.context}</p>
            )}
          </div>
        </div>

        {/* Roster Summary */}
        <div>
          <h3 className="font-display text-display-sm text-ink mb-3">
            {t('createProject.review.rosterSummary')}
          </h3>

          {/* Leader */}
          <div className="bg-[#EDE4CE] border border-[#E3D7BC] rounded-md p-4 mb-3">
            <p className="font-body text-body-sm font-medium text-ink mb-1">
              {t('createProject.roster.projectLeader')}
            </p>
            {selectedLeader ? (
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-[#C25E3A] flex items-center justify-center text-white font-display text-xs">
                  {(selectedLeader.displayName || selectedLeader.name || '?').charAt(0)}
                </div>
                <p className="font-body text-body-md text-ink">
                  {t('createProject.review.leaderAssigned', { name: selectedLeader.displayName || selectedLeader.name })}
                </p>
              </div>
            ) : (
              <p className="font-body text-body-md text-ink-light">
                {t('createProject.review.leaderAssignLater')}
              </p>
            )}
          </div>

          {/* The team */}
          {pickedMembers.length > 0 && (
            <div className="bg-[#EDE4CE] border border-[#E3D7BC] rounded-md p-4">
              <p className="font-body text-body-sm font-medium text-ink mb-2">
                {t('createProject.roster.team')}
              </p>
              <ul className="space-y-2">
                {pickedMembers.map((agent) => (
                  <li key={agent.id} className="flex items-start gap-2">
                    <span className="text-[#C25E3A] mt-1">&bull;</span>
                    <div>
                      <p className="font-body text-body-md text-ink">
                        {agent.displayName || agent.name}
                      </p>
                      <p className="font-body text-body-xs text-ink-muted mt-0.5">
                        {agent.description || t('createProject.roster.agentNoDescription')}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="border-t border-[#E3D7BC] mt-3 pt-2">
                <p className="font-body text-body-sm font-medium text-ink">
                  {t('createProject.review.totalSeats', { count: totalSeats })}
                </p>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  // ─── Main Render ───────────────────────────────────────────────────────────

  return (
    <div className="max-w-[720px] mx-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <div>
          <p className="font-body text-body-sm text-ink-light mb-1">
            {t('projects.title')} / {t('createProject.breadcrumb')}
          </p>
          <PageTitle title={t('createProject.title')} />
        </div>
      </div>

      {/* Mode toggle — manual wizard vs. agent-assisted chat (Sprint 7) */}
      <div className="flex flex-col items-center gap-3 mb-6">
        <div className="flex items-center gap-1.5 bg-[#EDE4CE] border border-[#E3D7BC] rounded-lg p-1.5 w-fit mx-auto">
          {(['manual', 'agent'] as const).map((m) => {
            const active = mode === m;
            const disabled = m === 'agent' && !hasWorkspaceAgent;
            return (
              <button
                key={m}
                onClick={() => !disabled && setMode(m)}
                disabled={disabled}
                className={`px-4 py-1.5 rounded-md font-body text-body-sm transition-colors ${
                  active
                    ? 'bg-[#C25E3A] text-white'
                    : disabled
                      ? 'text-ink-muted cursor-not-allowed opacity-60'
                      : 'text-ink hover:bg-[#E3D7BC]'
                }`}
                title={disabled ? t('createProject.mode.agentDisabled') : undefined}
              >
                {t(`createProject.mode.${m}`)}
                <span className={`block font-body text-body-xs ${active ? 'text-white/80' : 'text-ink-muted'}`}>
                  {t(`createProject.mode.${m}Desc`)}
                </span>
              </button>
            );
          })}
        </div>

        {/* Warning message when agent mode is not available */}
        {mode === 'agent' && !hasWorkspaceAgent && (
          <motion.div
            initial={{ opacity: 0, y: -8 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-[#F5E8CC] border border-[#C4903A] rounded-md px-4 py-2 max-w-[600px]"
          >
            <div className="flex items-start gap-2">
              <AlertTriangle className="w-4 h-4 text-[#C4903A] mt-0.5 flex-shrink-0" />
              <div className="font-body text-body-sm text-ink">
                <p className="font-medium">{t('createProject.mode.agentUnavailable')}</p>
                <p className="text-ink-light mt-1">{t('createProject.mode.setupWorkspaceAgent')}</p>
              </div>
            </div>
          </motion.div>
        )}
      </div>

      {mode === 'agent' ? (
        <OnboardingChat onCreated={(pid) => navigate(wsHref(workspaceId, `/projects/${pid}`))} />
      ) : (
      <>
      <p className="text-center font-body text-body-sm text-ink-muted mb-4">
        {t('createProject.stepIndicator', { current: step, total: 3 })}
      </p>

      {/* Step Indicator */}
      <StepIndicator step={step} />

      {/* Step Content */}
      <div className="min-h-[400px]">
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

      {/* Footer buttons */}
      <div className="flex items-center justify-between mt-8 pt-6 border-t border-[#E3D7BC]">
        {step > 1 ? (
          <button
            onClick={goBack}
            className="inline-flex items-center gap-2 bg-[#EDE4CE] hover:bg-[#E3D7BC] border border-[#E3D7BC] text-ink font-body font-medium text-body-md px-4 py-2.5 rounded-md transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            {t('createProject.buttons.back')}
          </button>
        ) : (
          <button
            onClick={() => navigate('/')}
            className="inline-flex items-center gap-2 bg-[#EDE4CE] hover:bg-[#E3D7BC] border border-[#E3D7BC] text-ink font-body font-medium text-body-md px-4 py-2.5 rounded-md transition-colors"
          >
            {t('createProject.buttons.cancel')}
          </button>
        )}

        {step < 3 ? (
          <button
            onClick={goNext}
            className="inline-flex items-center gap-2 bg-[#C25E3A] hover:bg-[#D97B5A] text-white font-body font-medium text-body-md px-4 py-2.5 rounded-md transition-colors"
          >
            {step === 1 ? t('createProject.buttons.nextRoster') : t('createProject.buttons.nextReview')}
            <ArrowRight className="w-4 h-4" />
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={isSubmitting || !isRosterValid}
            className={`inline-flex items-center gap-2 font-body font-medium text-body-md px-6 py-2.5 rounded-md transition-colors ${
              isSubmitting || !isRosterValid
                ? 'bg-[#A89880] text-white cursor-not-allowed'
                : 'bg-[#D4A843] hover:bg-[#E8C96A] text-ink'
            }`}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('createProject.buttons.creating')}
              </>
            ) : (
              <>
                {t('createProject.buttons.createProject')}
              </>
            )}
          </button>
        )}
      </div>
      </>
      )}
    </div>
  );
}
