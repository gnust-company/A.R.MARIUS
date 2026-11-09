import { useState, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import {
  Wrench,
  Plus,
  Search,
  Palette,
  Github,
  FileText,
  Loader2,
  ChevronRight,
  Trash2,
  AlertTriangle,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { Skill } from '@/store/appStore';
import Modal from '@/components/Modal';
import ConfirmDialog from '@/components/ConfirmDialog';
import PageTitle from '@/components/PageTitle';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { useTranslation } from 'react-i18next';

// ─── Shared classes ──────────────────────────────────────────────────────────

const primaryButton =
  'inline-flex items-center justify-center gap-2 min-h-[44px] px-[18px] rounded-md bg-ink font-body text-body-md font-medium text-paper hover:bg-ink/85 transition-colors disabled:opacity-50 disabled:cursor-not-allowed';
const secondaryButton =
  'inline-flex items-center justify-center gap-2 min-h-[44px] px-4 rounded-md border border-line-strong bg-paper font-body text-body-md font-medium text-ink hover:bg-inset transition-colors';
const fieldClasses = cn(
  'w-full min-h-[44px] px-3.5 py-2.5 rounded-md bg-inset border border-line font-body text-body-md text-ink',
  'placeholder:text-ink-muted',
  'focus:outline-none focus:border-terracotta focus:ring-2 focus:ring-terracotta/15 transition-colors'
);
const fieldLabel = 'block mb-1.5 font-body text-body-sm font-medium text-ink-light';

// ─── Skill Source Badge ──────────────────────────────────────────────────────

function SourceBadge({ type }: { type: Skill['type'] }) {
  const { t } = useTranslation();
  // Where a skill came from is a fact, not a status, so both read in the same neutral chip;
  // the icon is what tells them apart.
  const config = {
    github: { label: t('skills.imported'), icon: Github },
    custom: { label: t('skills.type.manual'), icon: FileText },
  };
  // A skill with no recorded source reads as manual — same as `skillToVM`'s fallback.
  const { label, icon: Icon } = (type && config[type]) || config.custom;
  return (
    <span className="inline-flex shrink-0 items-center gap-1 px-2 py-0.5 rounded-full border border-line bg-inset font-body text-body-xs font-medium text-ink-light">
      <Icon className="w-3 h-3" aria-hidden />
      {label}
    </span>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE: Skills
// ═══════════════════════════════════════════════════════════════════════════════

export default function Skills() {
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const { t } = useTranslation();
  const skills = useAppStore((s) => s.skills);
  const createSkill = useAppStore((s) => s.createSkill);
  const importSkill = useAppStore((s) => s.importSkill);
  const deleteSkill = useAppStore((s) => s.deleteSkill);

  // Skill pending deletion (confirm before removing).
  const [deletingSkill, setDeletingSkill] = useState<{ id: string; name: string } | null>(null);

  // ── State ──────────────────────────────────────────────────────────────────
  const [searchQuery, setSearchQuery] = useState('');

  // ── Create Modal State ─────────────────────────────────────────────────────
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createMode, setCreateMode] = useState<'manual' | 'import'>('manual');
  const [skillName, setSkillName] = useState('');
  const [skillDesc, setSkillDesc] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [creating, setCreating] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  // ── Filter Skills ──────────────────────────────────────────────────────────
  const filteredSkills = useMemo(() => {
    // Only what people added. The skills the system gives every agent are never listed — not
    // even on a tab of their own: they are not something to look at or decide about, and the
    // server does not send them (spec 003 FR-123).
    let filtered = [...skills];

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          (s.description || '').toLowerCase().includes(q)
      );
    }

    return filtered;
  }, [skills, searchQuery]);

  // ── Handlers ───────────────────────────────────────────────────────────────
  const handleOpenCreate = (mode: 'manual' | 'import') => {
    setCreateMode(mode);
    setSkillName('');
    setSkillDesc('');
    setGithubUrl('');
    setImportError(null);
    setCreateModalOpen(true);
  };

  const handleCreateManual = async () => {
    if (!skillName.trim()) return;
    setCreating(true);
    // Built before the block: the React Compiler has no lowering for a conditional
    // expression (here the `||` fallback) inside try/catch, and drops the whole
    // component when it meets one.
    const described = skillDesc.trim() || 'No description';
    const frontmatter = `---\nname: ${skillName.trim()}\ndescription: ${described}\nversion: 1.0.0\n---\n`;
    let newSkill;
    try {
      // Manual skills are `type: 'custom'` (mirrors skillToVM's mapping of source='manual'),
      // never 'github' — that badge belongs to imported skills only.
      newSkill = await createSkill({
        name: skillName.trim().toLowerCase().replace(/\s+/g, '-'),
        description: skillDesc.trim(),
        type: 'custom',
        files: [
          { path: 'SKILL.md', content: frontmatter + '\n# ' + skillName.trim() + '\n\n## Overview\n\n', language: 'markdown' },
        ],
      });
      setCreateModalOpen(false);
    } catch (e) {
      // Same cleanup on both paths, spelled out rather than in a `finally`: the React
      // Compiler cannot lower `finally` and gives up on the whole component when it
      // meets one. Rethrowing keeps the failure exactly as loud as it was.
      setCreating(false);
      throw e;
    }
    setCreating(false);
    // Only navigate once we have a real id — never /skills/undefined. Outside the block
    // for the same reason: optional chaining is a conditional expression too.
    if (newSkill?.id) navigate(wsHref(workspaceId, `/skills/${newSkill.id}`));
  };

  // Import = the backend really clones the GitHub folder and persists the skill. A bad
  // URL or a folder with no SKILL.md throws (surfaced inline); nothing is created unless
  // the fetch succeeded — no fabricated template (issues #41, #42).
  const handleImport = async () => {
    if (!githubUrl.trim()) return;
    setCreating(true);
    setImportError(null);
    let newSkill;
    try {
      newSkill = await importSkill(githubUrl.trim(), workspaceId);
      setCreateModalOpen(false);
    } catch (e) {
      setImportError(errorText(e, t));
    }
    setCreating(false);
    if (newSkill?.id) navigate(wsHref(workspaceId, `/skills/${newSkill.id}`));
  };

  const handleSkillClick = (skillId: string) => {
    navigate(wsHref(workspaceId, `/skills/${skillId}`));
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="mx-auto w-full max-w-[1240px] flex flex-col gap-6 pb-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle title={t('skills.title')} subtitle={t('skills.subtitle', { count: skills.length })} />
        {/* Two ways in. The old header also carried a "manual" button that opened the very
            same form as "new skill", so it is folded into the primary one. */}
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => handleOpenCreate('import')} className={secondaryButton}>
            <Github className="w-4 h-4" aria-hidden />
            {t('skills.importTitle')}
          </button>
          <button onClick={() => handleOpenCreate('manual')} className={primaryButton}>
            <Plus className="w-4 h-4" aria-hidden />
            {t('skills.newSkill')}
          </button>
        </div>
      </div>

      {/* Search */}
      {skills.length > 0 && (
        <div className="relative w-full sm:w-80">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ink-muted" aria-hidden />
          <input
            type="search"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('skills.searchPlaceholder')}
            aria-label={t('skills.searchPlaceholder')}
            className={cn(fieldClasses, 'pl-9')}
          />
        </div>
      )}

      {/* Skill Cards Grid */}
      {filteredSkills.length === 0 ? (
        <section className="flex flex-col items-center rounded-xl border border-line bg-paper px-5 py-12 text-center sm:px-8">
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-inset text-ink-muted">
            <Wrench className="h-6 w-6" strokeWidth={1.5} aria-hidden />
          </span>
          <h2 className="font-display text-[22px] font-medium text-ink">{t('skills.emptyTitle')}</h2>
          <p className="mt-2 max-w-md font-body text-body-md text-ink-light">{t('skills.emptyLibraryDescription')}</p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2">
            <button onClick={() => handleOpenCreate('import')} className={secondaryButton}>
              <Github className="w-4 h-4" aria-hidden />
              {t('skills.importTitle')}
            </button>
            <button onClick={() => handleOpenCreate('manual')} className={primaryButton}>
              <Plus className="w-4 h-4" aria-hidden />
              {t('skills.createSkill')}
            </button>
          </div>
        </section>
      ) : (
        <motion.div
          className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.2 }}
        >
          {filteredSkills.map((skill) => (
            <article
              key={skill.id}
              className="group relative flex min-w-0 flex-col rounded-xl border border-line bg-paper px-5 py-4 transition-colors hover:border-line-strong cursor-pointer"
              onClick={() => handleSkillClick(skill.id)}
            >
              <div className="flex items-start gap-3">
                <span className="w-10 h-10 shrink-0 rounded-full bg-inset text-ink-light flex items-center justify-center" aria-hidden>
                  <Palette className="w-[18px] h-[18px]" />
                </span>
                <div className="min-w-0 flex-1">
                  {/* A real link inside the card, so keyboard and screen-reader users reach
                      the skill too; the whole card stays clickable for the pointer. */}
                  <a
                    href={wsHref(workspaceId, `/skills/${skill.id}`)}
                    onClick={(e) => {
                      e.preventDefault();
                      e.stopPropagation();
                      handleSkillClick(skill.id);
                    }}
                    className="block font-display text-[18px] font-medium leading-snug text-ink truncate group-hover:text-terracotta transition-colors focus-visible:outline-none focus-visible:underline"
                  >
                    {skill.name}
                  </a>
                  <div className="mt-1">
                    <SourceBadge type={skill.type} />
                  </div>
                </div>
              </div>

              {skill.description && (
                <p className="mt-3 font-body text-body-md text-ink-light line-clamp-2 break-words">
                  {skill.description}
                </p>
              )}

              <div className="mt-auto flex items-center justify-between gap-2 pt-3">
                <span className="font-mono text-mono-sm text-ink-muted">
                  {t('skills.fileCount', { count: (skill.files || []).length })}
                </span>
                <div className="flex items-center gap-1">
                  <button
                    onClick={(e) => { e.stopPropagation(); setDeletingSkill({ id: skill.id, name: skill.name }); }}
                    className="w-10 h-10 inline-flex items-center justify-center rounded-md text-ink-muted hover:text-vermilion-ink hover:bg-vermilion-bg transition-colors"
                    aria-label={t('skills.delete')}
                    title={t('skills.delete')}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                  <ChevronRight className="w-4 h-4 text-ink-muted group-hover:text-ink transition-colors" aria-hidden />
                </div>
              </div>
            </article>
          ))}
        </motion.div>
      )}

      {/* ─── Create/Import Skill Modal ────────────────────────────────────────── */}
      <Modal
        isOpen={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        title={
          <span className="font-display text-[24px] font-medium text-ink">
            {createMode === 'manual' ? t('skills.newSkill') : t('skills.importTitle')}
          </span>
        }
        maxWidth="max-w-lg"
        footer={
          createMode === 'manual' ? (
            <>
              <button onClick={() => setCreateModalOpen(false)} className={secondaryButton}>
                {t('common.cancel')}
              </button>
              <button
                onClick={handleCreateManual}
                disabled={!skillName.trim() || creating}
                className={primaryButton}
              >
                {creating && <Loader2 className="w-4 h-4 animate-spin" />}
                {t('skills.createSkill')}
              </button>
            </>
          ) : (
            <>
              <button onClick={() => setCreateModalOpen(false)} className={secondaryButton}>
                {t('common.cancel')}
              </button>
              <button
                onClick={handleImport}
                disabled={!githubUrl.trim() || creating}
                className={primaryButton}
              >
                {creating && <Loader2 className="w-4 h-4 animate-spin" />}
                {t('skills.import')}
              </button>
            </>
          )
        }
      >
        {createMode === 'manual' ? (
          <div className="space-y-4">
            <div>
              <label className={fieldLabel}>
                {t('skills.nameLabel')} <span className="text-vermilion-ink" aria-hidden>*</span>
              </label>
              <input
                type="text"
                value={skillName}
                onChange={(e) => setSkillName(e.target.value)}
                placeholder={t('skills.namePlaceholder')}
                className={fieldClasses}
                autoFocus
              />
            </div>
            <div>
              <label className={fieldLabel}>
                {t('skills.descriptionLabel')}
              </label>
              <textarea
                value={skillDesc}
                onChange={(e) => setSkillDesc(e.target.value)}
                placeholder={t('skills.descriptionPlaceholder')}
                rows={3}
                className={cn(fieldClasses, 'resize-none')}
              />
            </div>
            <p className="font-body text-body-sm text-ink-muted">{t('skills.manualNote')}</p>
          </div>
        ) : (
          <div className="space-y-4">
            <div>
              <label className={fieldLabel}>
                {t('skills.githubUrlLabel')} <span className="text-vermilion-ink" aria-hidden>*</span>
              </label>
              <input
                type="text"
                value={githubUrl}
                onChange={(e) => { setGithubUrl(e.target.value); setImportError(null); }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !creating) handleImport(); }}
                placeholder={t('skills.githubUrlPlaceholder')}
                className={fieldClasses}
                autoFocus
              />
              <p className="mt-1.5 font-body text-body-sm text-ink-muted">{t('skills.importNote')}</p>
            </div>
            {creating && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-2 font-body text-body-sm text-ink-light"
              >
                <Loader2 className="w-4 h-4 animate-spin text-lapis" />
                {t('skills.fetching')}
              </motion.div>
            )}
            {importError && (
              <div className="flex items-start gap-2 rounded-lg border border-[#EDB8B0] bg-vermilion-bg px-3 py-2.5 font-body text-body-sm text-vermilion-ink" role="alert">
                <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
                <span>{importError}</span>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Delete Skill confirmation */}
      <ConfirmDialog
        isOpen={deletingSkill !== null}
        onClose={() => setDeletingSkill(null)}
        onConfirm={async () => { if (deletingSkill) await deleteSkill(deletingSkill.id); }}
        title={t('skills.deleteTitle')}
        message={t('skills.deleteConfirm', { name: deletingSkill?.name ?? '' })}
        confirmLabel={t('skills.delete')}
      />
    </div>
  );
}
