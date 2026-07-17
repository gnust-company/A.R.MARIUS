// @ts-nocheck
import { useState, useMemo, useCallback } from 'react';
import { useNavigate, useParams } from 'react-router';
import { wsHref } from '@/lib/utils';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Plus, Trash2, AlertTriangle,
  CheckCircle2, Loader2, ArrowLeft, ArrowRight, X,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useMockStore } from '@/store/mockStore';
import PageTitle from '@/components/PageTitle';
import OnboardingChat from '@/components/OnboardingChat';

// ─── Types ───────────────────────────────────────────────────────────────────

interface WorkerRoleForm {
  id: string;
  title: string;
  description: string;
  skills: string[];
  seats: number;
}

interface FormData {
  name: string;
  objective: string;
  targetDate: string;
  githubUrl: string;
  context: string;
  leaderId: string | null;
  assignLeaderLater: boolean;
  workerRoles: WorkerRoleForm[];
}

interface FormErrors {
  name?: string;
  objective?: string;
  workerRoles?: string;
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

const roleCardVariants = {
  hidden: { opacity: 0, y: -20, scale: 0.98 },
  visible: {
    opacity: 1, y: 0, scale: 1,
    transition: { duration: 0.3, ease: [0.34, 1.56, 0.64, 1] as [number, number, number, number] },
  },
  exit: {
    opacity: 0, y: -10, scale: 0.98,
    transition: { duration: 0.2 },
  },
};

// ─── Helpers ─────────────────────────────────────────────────────────────────

const generateId = () => `wr-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;

const initialFormData: FormData = {
  name: '',
  objective: '',
  targetDate: '',
  githubUrl: '',
  context: '',
  leaderId: null,
  assignLeaderLater: false,
  workerRoles: [],
};

// ─── Component ───────────────────────────────────────────────────────────────

export default function CreateProject() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const createProject = useMockStore((s) => s.createProject);
  const mariuses = useMockStore((s) => s.mariuses);
  const skills = useMockStore((s) => s.skills);
  const activeWorkspaceId = useMockStore((s) => s.activeWorkspaceId);
  const workspaces = useMockStore((s) => s.workspaces);

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
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [formData.name, formData.objective, t]);

  const validateStep2 = useCallback((): boolean => {
    const newErrors: FormErrors = {};

    if (!formData.assignLeaderLater && !formData.leaderId) {
      newErrors.roster = t('createProject.validation.noLeader');
    }

    if (formData.workerRoles.length === 0) {
      newErrors.workerRoles = t('createProject.validation.noWorkerRoles');
    } else {
      const invalidSeats = formData.workerRoles.some((r) => r.seats < 1);
      const invalidTitles = formData.workerRoles.some((r) => !r.title.trim());
      if (invalidSeats) {
        newErrors.workerRoles = t('createProject.validation.workerRoleNoSeats');
      }
      if (invalidTitles) {
        newErrors.workerRoles = t('createProject.validation.workerRoleNoTitle');
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [formData, t]);

  const isRosterValid = useMemo(() => {
    const hasLeaderOrLater = formData.assignLeaderLater || !!formData.leaderId;
    const hasWorkerRoles = formData.workerRoles.length > 0;
    const allValidSeats = formData.workerRoles.every((r) => r.seats >= 1);
    const allValidTitles = formData.workerRoles.every((r) => r.title.trim().length > 0);
    return hasLeaderOrLater && hasWorkerRoles && allValidSeats && allValidTitles;
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

    // Build seats from form data
    const seats = [];

    // Leader seat
    if (formData.leaderId) {
      seats.push({
        roleKey: 'leader',
        roleLabel: 'Project Leader',
        mariusId: formData.leaderId,
        skillsRequired: [] as string[],
      });
    } else {
      seats.push({
        roleKey: 'leader',
        roleLabel: 'Project Leader',
        mariusId: null,
        skillsRequired: [] as string[],
      });
    }

    // Worker role seats
    formData.workerRoles.forEach((role) => {
      for (let i = 0; i < role.seats; i++) {
        seats.push({
          roleKey: `worker_${role.id}_${i}`,
          roleLabel: role.title,
          mariusId: null,
          skillsRequired: role.skills,
        });
      }
    });

    const project = await createProject({
      name: formData.name.trim(),
      description: formData.objective.trim(),
      objective: formData.objective.trim(),
      workspaceId: activeWorkspaceId || undefined,
      leaderId: formData.leaderId || '',
      seats,
    });

    navigate(wsHref(workspaceId, `/projects/${project.id}`));
  };

  // ─── Worker Role Helpers ───────────────────────────────────────────────────

  const addWorkerRole = () => {
    setFormData((prev) => ({
      ...prev,
      workerRoles: [
        ...prev.workerRoles,
        {
          id: generateId(),
          title: '',
          description: '',
          skills: [],
          seats: 1,
        },
      ],
    }));
    setErrors((prev) => ({ ...prev, workerRoles: undefined }));
  };

  const removeWorkerRole = (id: string) => {
    setFormData((prev) => ({
      ...prev,
      workerRoles: prev.workerRoles.filter((r) => r.id !== id),
    }));
  };

  const updateWorkerRole = (id: string, updates: Partial<WorkerRoleForm>) => {
    setFormData((prev) => ({
      ...prev,
      workerRoles: prev.workerRoles.map((r) =>
        r.id === id ? { ...r, ...updates } : r
      ),
    }));
  };

  const toggleSkill = (roleId: string, skillName: string) => {
    setFormData((prev) => ({
      ...prev,
      workerRoles: prev.workerRoles.map((r) => {
        if (r.id !== roleId) return r;
        const hasSkill = r.skills.includes(skillName);
        return {
          ...r,
          skills: hasSkill
            ? r.skills.filter((s) => s !== skillName)
            : [...r.skills, skillName],
        };
      }),
    }));
  };

  // ─── Step Indicator ────────────────────────────────────────────────────────

  const StepIndicator = () => {
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
            setFormData((p) => ({ ...p, name: e.target.value }));
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
                setFormData((p) => ({ ...p, leaderId: val, assignLeaderLater: false }));
              }
              if (errors.roster) setErrors((p) => ({ ...p, roster: undefined }));
            }}
            className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-4 py-2.5 font-body text-body-md text-ink focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors"
          >
            <option value="">{t('createProject.roster.selectAgent')}</option>
            {approvedAgents.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.displayName || agent.name} ({agent.role}) — {agent.status}
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
                    <p className="font-body text-body-sm text-ink-light">{agent.role} &middot; {agent.adapterType}</p>
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

      {/* ─── Worker Roles Section ─── */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-display text-display-sm text-ink">
            {t('createProject.roster.workerRoles')}
          </h3>
          <button
            onClick={addWorkerRole}
            className="inline-flex items-center gap-1.5 bg-[#EDE4CE] hover:bg-[#E3D7BC] border border-[#E3D7BC] text-ink font-body font-medium text-body-sm px-3 py-1.5 rounded-md transition-colors"
          >
            <Plus className="w-4 h-4" />
            {t('createProject.roster.addRoleButton')}
          </button>
        </div>

        {errors.workerRoles && (
          <p className="mb-3 font-body text-body-sm text-[#B84A32]">{errors.workerRoles}</p>
        )}

        <AnimatePresence>
          {formData.workerRoles.map((role) => (
            <motion.div
              key={role.id}
              variants={roleCardVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              className="bg-[#EDE4CE] border border-[#E3D7BC] rounded-md p-4 mb-3"
            >
              {/* Role title + remove */}
              <div className="flex items-center gap-3 mb-3">
                <input
                  type="text"
                  value={role.title}
                  onChange={(e) => updateWorkerRole(role.id, { title: e.target.value })}
                  placeholder={t('createProject.roster.roleTitlePlaceholder')}
                  className="flex-1 bg-vellum border border-[#E3D7BC] rounded-md px-3 py-2 font-body text-body-md text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors"
                />
                <button
                  onClick={() => removeWorkerRole(role.id)}
                  className="p-2 text-ink-muted hover:text-[#B84A32] hover:bg-[#F5DDD6] rounded-md transition-colors"
                  title={t('createProject.roster.removeRole')}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>

              {/* Seats + Skills row */}
              <div className="flex items-start gap-4 mb-3">
                {/* Seats */}
                <div className="w-24">
                  <label className="block font-body text-body-xs font-medium text-ink-light mb-1">
                    {t('createProject.roster.seats')}
                  </label>
                  <input
                    type="number"
                    min={1}
                    value={role.seats}
                    onChange={(e) => updateWorkerRole(role.id, { seats: Math.max(1, parseInt(e.target.value) || 1) })}
                    className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-3 py-2 font-body text-body-md text-ink focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors"
                  />
                </div>

                {/* Skills multi-select */}
                <div className="flex-1">
                  <label className="block font-body text-body-xs font-medium text-ink-light mb-1">
                    {t('createProject.roster.skills')}
                  </label>
                  <div className="flex flex-wrap gap-1.5">
                    {skills.map((skill) => {
                      const isSelected = role.skills.includes(skill.name);
                      return (
                        <button
                          key={skill.id}
                          onClick={() => toggleSkill(role.id, skill.name)}
                          className={`inline-flex items-center gap-1 font-body text-body-xs px-2 py-1 rounded-full transition-colors ${
                            isSelected
                              ? 'bg-[#D4A843] text-ink'
                              : 'bg-[#F7F0E0] text-ink-light border border-[#E3D7BC] hover:border-[#D4A843]'
                          }`}
                        >
                          {skill.name}
                          {isSelected && <X className="w-3 h-3" />}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="block font-body text-body-xs font-medium text-ink-light mb-1">
                  {t('createProject.roster.roleDescription')}
                </label>
                <textarea
                  value={role.description}
                  onChange={(e) => updateWorkerRole(role.id, { description: e.target.value })}
                  placeholder={t('createProject.roster.roleDescriptionPlaceholder')}
                  rows={2}
                  className="w-full bg-vellum border border-[#E3D7BC] rounded-md px-3 py-2 font-body text-body-sm text-ink placeholder:text-ink-muted focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)] transition-colors resize-none"
                />
              </div>
            </motion.div>
          ))}
        </AnimatePresence>

        {formData.workerRoles.length === 0 && (
          <p className="text-center font-body text-body-sm text-ink-muted py-6">
            {t('createProject.validation.noWorkerRoles')}.{' '}
            <button
              onClick={addWorkerRole}
              className="text-[#C25E3A] hover:underline"
            >
              {t('createProject.roster.addRoleButton')}
            </button>
          </p>
        )}
      </div>
    </div>
  );

  // ─── Render Step 3: Review ─────────────────────────────────────────────────

  const renderStep3 = () => {
    const totalSeats = formData.workerRoles.reduce((sum, r) => sum + r.seats, 0) + 1; // +1 for leader
    const selectedLeader = approvedAgents.find((a) => a.id === formData.leaderId);

    return (
      <div className="space-y-6">
        <h2 className="font-display text-display-sm text-ink mb-2">
          {t('createProject.step3Title')}
        </h2>

        {/* Project Summary Card */}
        <div className="bg-[#EDE4CE] border border-[#E3D7BC] rounded-md p-6">
          <h3 className="font-display text-display-md text-ink mb-2">{formData.name}</h3>
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

          {/* Worker Roles */}
          {formData.workerRoles.length > 0 && (
            <div className="bg-[#EDE4CE] border border-[#E3D7BC] rounded-md p-4">
              <p className="font-body text-body-sm font-medium text-ink mb-2">
                {t('createProject.roster.workerRoles')}
              </p>
              <ul className="space-y-2">
                {formData.workerRoles.map((role) => (
                  <li key={role.id} className="flex items-start gap-2">
                    <span className="text-[#C25E3A] mt-1">&bull;</span>
                    <div>
                      <p className="font-body text-body-md text-ink">
                        {t('createProject.review.workerRoleItem', {
                          title: role.title,
                          seats: role.seats,
                        })}
                      </p>
                      {role.skills.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1">
                          {role.skills.map((s) => (
                            <span
                              key={s}
                              className="font-body text-body-xs bg-[#D4A843] text-ink px-2 py-0.5 rounded-full"
                            >
                              {s}
                            </span>
                          ))}
                        </div>
                      )}
                      {role.skills.length === 0 && (
                        <p className="font-body text-body-xs text-ink-muted mt-0.5">
                          {t('createProject.review.noSkills')}
                        </p>
                      )}
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
      <StepIndicator />

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
