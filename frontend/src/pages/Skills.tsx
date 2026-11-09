// The skill library (Đài quan sát "Kỹ năng" view).
//
// Two columns on a wide screen: the workspace's library on the left, the chosen skill's files
// on the right. On a narrow one they take turns — the list at `/skills`, a skill at
// `/skills/:id` (the route `SkillEditor` answers, which renders this same page).
import { useState, useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import {
  Plus,
  Search,
  Github,
  FolderOpen,
  Loader2,
  AlertTriangle,
  ScrollText,
  WandSparkles,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import Modal from '@/components/Modal';
import ConfirmDialog from '@/components/ConfirmDialog';
import PageTitle from '@/components/PageTitle';
import SkillViewer from '@/pages/skills/SkillViewer';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { useTranslation } from 'react-i18next';

const fieldLabel = 'mb-1.5 block font-body text-body-sm font-medium text-ink';

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE: Skills
// ═══════════════════════════════════════════════════════════════════════════════

export default function Skills() {
  const navigate = useNavigate();
  const { workspaceId, id: routeId } = useParams();
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

  // The skill in the right-hand pane: the one on the address, else (wide screens only, where
  // both columns show) the first one listed.
  const routeSkill = routeId ? skills.find((s) => s.id === routeId) : undefined;
  const shownSkill = routeId ? routeSkill : (filteredSkills[0] ?? skills[0]);
  const libraryHref = wsHref(workspaceId, '/skills');

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

  // ── Render ─────────────────────────────────────────────────────────────────

  const createButtons = (
    <>
      <button type="button" onClick={() => handleOpenCreate('import')} className="btn btn-secondary">
        <Github className="h-4 w-4" aria-hidden />
        {t('skills.importTitle')}
      </button>
      <button type="button" onClick={() => handleOpenCreate('manual')} className="btn btn-primary">
        <Plus className="h-4 w-4" aria-hidden />
        {t('skills.newSkill')}
      </button>
    </>
  );

  return (
    <div className="mx-auto flex w-full max-w-[1240px] flex-col gap-6 pb-10">
      {/* On a narrow screen with a skill open, the page header steps aside for the skill. */}
      <div className={cn(routeId && 'hidden lg:block')}>
        <PageTitle
          eyebrow={t('skills.eyebrow')}
          title={t('skills.title')}
          subtitle={t('skills.lead')}
          actions={createButtons}
        />
      </div>

      {skills.length === 0 && !routeId ? (
        <section className="surface flex flex-col items-center px-5 py-12 text-center sm:px-8">
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-line bg-canvas-deep text-ink-muted">
            <WandSparkles className="h-6 w-6" strokeWidth={1.5} aria-hidden />
          </span>
          <h2 className="font-display text-display-sm text-ink-strong">{t('skills.emptyTitle')}</h2>
          <p className="mt-2 max-w-md font-body text-body-md text-ink-light">{t('skills.emptyLibraryDescription')}</p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-2.5">{createButtons}</div>
        </section>
      ) : (
        <div className="grid grid-cols-1 items-start gap-[18px] lg:grid-cols-[280px_minmax(0,1fr)] xl:grid-cols-[300px_minmax(0,1fr)]">
          {/* ── Library ── */}
          <aside className={cn('min-w-0 overflow-hidden rounded-lg border border-line bg-surface', routeId && 'hidden lg:block')}>
            <header className="border-b border-line px-5 pb-3.5 pt-[19px]">
              <p className="eyebrow">{t('skills.libraryEyebrow')}</p>
              <p className="mt-[3px] font-display text-[21px] font-normal text-ink-strong">
                {t('skills.librarySummary', { count: skills.length })}
              </p>
              {skills.length > 1 && (
                <div className="relative mt-3">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden />
                  <input
                    type="search"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t('skills.searchPlaceholder')}
                    aria-label={t('skills.searchPlaceholder')}
                    className="field pl-9"
                  />
                </div>
              )}
            </header>
            {filteredSkills.length === 0 ? (
              <p className="px-5 py-8 text-center font-body text-body-sm text-ink-muted">
                {skills.length === 0 ? t('skills.emptyTitle') : t('skills.noMatch')}
              </p>
            ) : (
              <nav aria-label={t('skills.libraryEyebrow')}>
                {filteredSkills.map((skill) => {
                  const active = skill.id === shownSkill?.id;
                  const imported = skill.type === 'github';
                  return (
                    <Link
                      key={skill.id}
                      to={wsHref(workspaceId, `/skills/${skill.id}`)}
                      aria-current={active && routeId ? 'page' : undefined}
                      className={cn(
                        'flex w-full items-start gap-[11px] border-b border-line px-4 py-[17px] text-left transition-colors last:border-b-0',
                        !active && 'hover:bg-surface-hover',
                        active && routeId && 'bg-canvas-deep shadow-[inset_2px_0_0_0_oklch(var(--sapphire-strong))]',
                        // With nothing on the address the first skill is shown only where both
                        // columns are visible — so only there does it read as chosen.
                        active && !routeId && 'hover:bg-surface-hover lg:bg-canvas-deep lg:shadow-[inset_2px_0_0_0_oklch(var(--sapphire-strong))]'
                      )}
                    >
                      <span className="grid h-[34px] w-[34px] shrink-0 place-items-center rounded-full border border-line text-sapphire-strong">
                        <WandSparkles className="h-[18px] w-[18px]" aria-hidden />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate font-mono text-[12px] font-medium text-ink-strong">{skill.name}</span>
                        {skill.description && (
                          <span className="mt-1 line-clamp-2 block break-words font-body text-[12px] leading-[1.45] text-ink-light">
                            {skill.description}
                          </span>
                        )}
                        <span className="mt-2 flex items-center gap-[5px] truncate font-body text-[11px] text-ink-muted">
                          {imported ? <Github className="h-3 w-3 shrink-0" aria-hidden /> : <FolderOpen className="h-3 w-3 shrink-0" aria-hidden />}
                          {imported ? t('skills.imported') : t('skills.type.manual')}
                          {' · '}
                          {t('skills.fileCount', { count: (skill.files || []).length })}
                        </span>
                      </span>
                    </Link>
                  );
                })}
              </nav>
            )}
          </aside>

          {/* ── Viewer ── */}
          <div className={cn('min-w-0', !routeId && 'hidden lg:block')}>
            {shownSkill ? (
              <SkillViewer
                key={shownSkill.id}
                skill={shownSkill}
                backHref={libraryHref}
                onDelete={() => setDeletingSkill({ id: shownSkill.id, name: shownSkill.name })}
              />
            ) : routeId ? (
              <section className="surface flex flex-col items-center px-5 py-12 text-center sm:px-8">
                <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full border border-line bg-canvas-deep text-ink-muted">
                  <ScrollText className="h-6 w-6" strokeWidth={1.5} aria-hidden />
                </span>
                <h1 className="font-display text-display-sm text-ink-strong">{t('skills.editor.notFound')}</h1>
                <p className="mt-2 max-w-md font-body text-body-md text-ink-light">{t('skills.editor.notFoundDesc')}</p>
                <Link to={libraryHref} className="btn btn-secondary mt-6">
                  {t('skills.editor.backToSkills')}
                </Link>
              </section>
            ) : null}
          </div>
        </div>
      )}

      {/* ─── Create/Import Skill Modal ────────────────────────────────────────── */}
      <Modal
        isOpen={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        eyebrow={createMode === 'manual' ? t('skills.createEyebrow') : t('skills.importEyebrow')}
        title={createMode === 'manual' ? t('skills.newSkill') : t('skills.importTitle')}
        maxWidth="sm:max-w-[620px]"
        footer={
          createMode === 'manual' ? (
            <>
              <button type="button" onClick={() => setCreateModalOpen(false)} className="btn btn-secondary">
                {t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={handleCreateManual}
                disabled={!skillName.trim() || creating}
                className="btn btn-primary"
              >
                {creating && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
                {t('skills.createSkill')}
              </button>
            </>
          ) : (
            <>
              <button type="button" onClick={() => setCreateModalOpen(false)} className="btn btn-secondary">
                {t('common.cancel')}
              </button>
              <button
                type="button"
                onClick={handleImport}
                disabled={!githubUrl.trim() || creating}
                className="btn btn-primary"
              >
                {creating && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
                {t('skills.import')}
              </button>
            </>
          )
        }
      >
        {createMode === 'manual' ? (
          <div className="space-y-[17px]">
            <div>
              <label className={fieldLabel} htmlFor="skill-name">
                {t('skills.nameLabel')} <span className="text-danger" aria-hidden>*</span>
              </label>
              <input
                id="skill-name"
                type="text"
                value={skillName}
                onChange={(e) => setSkillName(e.target.value)}
                placeholder={t('skills.namePlaceholder')}
                className="field font-mono text-[13px]"
                autoFocus
              />
            </div>
            <div>
              <label className={fieldLabel} htmlFor="skill-desc">
                {t('skills.descriptionLabel')}
              </label>
              <textarea
                id="skill-desc"
                value={skillDesc}
                onChange={(e) => setSkillDesc(e.target.value)}
                placeholder={t('skills.descriptionPlaceholder')}
                rows={3}
                className="field resize-none py-2.5 leading-relaxed"
              />
            </div>
            <p className="font-body text-body-sm text-ink-muted">{t('skills.manualNote')}</p>
          </div>
        ) : (
          <div className="space-y-[17px]">
            <div>
              <label className={fieldLabel} htmlFor="skill-github">
                {t('skills.githubUrlLabel')} <span className="text-danger" aria-hidden>*</span>
              </label>
              <input
                id="skill-github"
                type="text"
                value={githubUrl}
                onChange={(e) => { setGithubUrl(e.target.value); setImportError(null); }}
                onKeyDown={(e) => { if (e.key === 'Enter' && !creating) handleImport(); }}
                placeholder={t('skills.githubUrlPlaceholder')}
                className="field font-mono text-[13px]"
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
                <Loader2 className="h-4 w-4 animate-spin text-sapphire-strong" aria-hidden />
                {t('skills.fetching')}
              </motion.div>
            )}
            {importError && (
              <div className="flex items-start gap-2 rounded-md border border-danger/30 bg-danger-soft px-3 py-2.5 font-body text-body-sm text-danger" role="alert">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
                <span className="min-w-0">{importError}</span>
              </div>
            )}
          </div>
        )}
      </Modal>

      {/* Delete Skill confirmation */}
      <ConfirmDialog
        isOpen={deletingSkill !== null}
        onClose={() => setDeletingSkill(null)}
        onConfirm={async () => {
          if (!deletingSkill) return;
          await deleteSkill(deletingSkill.id);
          // The pane was showing the skill that is now gone: back to the library.
          if (deletingSkill.id === routeId) navigate(libraryHref);
        }}
        title={t('skills.deleteTitle')}
        message={t('skills.deleteConfirm', { name: deletingSkill?.name ?? '' })}
        confirmLabel={t('skills.delete')}
      />
    </div>
  );
}
