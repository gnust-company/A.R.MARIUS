// @ts-nocheck
import { useState, useMemo } from 'react';
import { useNavigate, useParams } from 'react-router';
import { motion } from 'framer-motion';
import {
  Wrench,
  Plus,
  Search,
  Settings,
  Palette,
  Github,
  FileText,
  Loader2,
  ChevronRight,
  Trash2,
} from 'lucide-react';
import { useMockStore } from '@/store/mockStore';
import type { Skill } from '@/store/mockStore';
import VellumPanel from '@/components/VellumPanel';
import EmptyState from '@/components/EmptyState';
import Modal from '@/components/Modal';
import ConfirmDialog from '@/components/ConfirmDialog';
import PageTitle from '@/components/PageTitle';
import { cn, wsHref } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

// ─── Animation Variants ──────────────────────────────────────────────────────

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: { staggerChildren: 0.06, delayChildren: 0.15 },
  },
};

const itemVariants = {
  hidden: { opacity: 0, y: 16, filter: 'blur(2px)' },
  visible: {
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: { duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  },
};

// ─── Skill Source Badge ──────────────────────────────────────────────────────

function SourceBadge({ type }: { type: Skill['type'] }) {
  const { t } = useTranslation();
  const config = {
    builtin: { label: t('skills.type.builtin'), icon: Settings, color: 'bg-[#E8E0D8] text-[#8B7A6A]' },
    github: { label: t('skills.imported'), icon: Github, color: 'bg-[#D4E8F0] text-[#2A5A6E]' },
    custom: { label: t('skills.type.manual'), icon: FileText, color: 'bg-[#EAE0CC] text-[#7A6A2A]' },
  };
  const { label, icon: Icon, color } = config[type] || config.custom;
  return (
    <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium', color)}>
      <Icon className="w-3 h-3" />
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
  const skills = useMockStore((s) => s.skills);
  const createSkill = useMockStore((s) => s.createSkill);
  const deleteSkill = useMockStore((s) => s.deleteSkill);

  // Skill pending deletion (confirm before removing).
  const [deletingSkill, setDeletingSkill] = useState<{ id: string; name: string } | null>(null);

  // ── State ──────────────────────────────────────────────────────────────────
  const [activeTab, setActiveTab] = useState<'library' | 'builtin'>('library');
  const [searchQuery, setSearchQuery] = useState('');

  // ── Create Modal State ─────────────────────────────────────────────────────
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [createMode, setCreateMode] = useState<'manual' | 'import'>('manual');
  const [skillName, setSkillName] = useState('');
  const [skillDesc, setSkillDesc] = useState('');
  const [githubUrl, setGithubUrl] = useState('');
  const [creating, setCreating] = useState(false);
  const [importStep, setImportStep] = useState<'input' | 'preview'>('input');
  const [importedFiles, setImportedFiles] = useState<{ path: string; content: string; language: string }[]>([]);

  // ── Filter Skills ──────────────────────────────────────────────────────────
  const filteredSkills = useMemo(() => {
    let filtered = [...skills];

    if (activeTab === 'builtin') {
      filtered = filtered.filter((s) => s.type === 'builtin');
    } else {
      filtered = filtered.filter((s) => s.type !== 'builtin');
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          (s.description || '').toLowerCase().includes(q)
      );
    }

    return filtered;
  }, [skills, activeTab, searchQuery]);

  // ── Handlers ───────────────────────────────────────────────────────────────
  const handleOpenCreate = (mode: 'manual' | 'import') => {
    setCreateMode(mode);
    setSkillName('');
    setSkillDesc('');
    setGithubUrl('');
    setImportStep('input');
    setImportedFiles([]);
    setCreateModalOpen(true);
  };

  const handleCreateManual = async () => {
    if (!skillName.trim()) return;
    setCreating(true);
    try {
      const frontmatter = `---\nname: ${skillName.trim()}\ndescription: ${skillDesc.trim() || 'No description'}\nversion: 1.0.0\n---\n`;
      // Manual skills are `type: 'custom'` (mirrors skillToVM's mapping of source='manual'),
      // never 'github' — that badge belongs to imported skills only.
      const newSkill = await createSkill({
        name: skillName.trim().toLowerCase().replace(/\s+/g, '-'),
        description: skillDesc.trim(),
        type: 'custom',
        files: [
          { path: 'SKILL.md', content: frontmatter + '\n# ' + skillName.trim() + '\n\n## Overview\n\n', language: 'markdown' },
        ],
      });
      setCreateModalOpen(false);
      // Only navigate once we have a real id — never /skills/undefined.
      if (newSkill?.id) navigate(wsHref(workspaceId, `/skills/${newSkill.id}`));
    } finally {
      setCreating(false);
    }
  };

  const handleImport = () => {
    if (!githubUrl.trim()) return;
    setCreating(true);
    setTimeout(() => {
      // Simulate GitHub fetch
      const files = [
        { path: 'SKILL.md', content: `# ${skillName || 'Imported Skill'}\n\n## Overview\n\nImported from GitHub.\n`, language: 'markdown' },
        { path: 'src/index.ts', content: '// Auto-generated\nexport {};\n', language: 'typescript' },
        { path: 'README.md', content: `# README\n\nImported from ${githubUrl}\n`, language: 'markdown' },
      ];
      setImportedFiles(files);
      setImportStep('preview');
      setCreating(false);
    }, 1200);
  };

  const handleConfirmImport = async () => {
    if (importedFiles.length === 0) return;
    const name = skillName.trim() || githubUrl.split('/').pop() || 'imported-skill';
    const newSkill = await createSkill({
      name: name.toLowerCase().replace(/\s+/g, '-'),
      description: skillDesc.trim() || `Imported from ${githubUrl}`,
      type: 'github',
      sourceUrl: githubUrl.trim(),
      files: importedFiles,
    });
    setCreateModalOpen(false);
    if (newSkill?.id) navigate(wsHref(workspaceId, `/skills/${newSkill.id}`));
  };

  const handleSkillClick = (skillId: string) => {
    navigate(wsHref(workspaceId, `/skills/${skillId}`));
  };

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-[100dvh]">
      {/* Page Header */}
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 mb-6"
      >
        <div className="flex items-center gap-3">
          <PageTitle title={t('skills.title')} subtitle={t('skills.subtitle', { count: skills.length })} />
        </div>

        {/* New Skill buttons */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => handleOpenCreate('manual')}
            className={cn(
              'inline-flex items-center gap-2 px-4 py-2.5 rounded-md text-[13px] font-medium',
              'bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC] transition-all'
            )}
          >
            <Plus className="w-3.5 h-3.5" />
            {t('skills.manual')}
          </button>
          <button
            onClick={() => handleOpenCreate('import')}
            className={cn(
              'inline-flex items-center gap-2 px-4 py-2.5 rounded-md text-[13px] font-medium',
              'bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC] transition-all'
            )}
          >
            <Github className="w-3.5 h-3.5" />
            {t('skills.import')}
          </button>
          <button
            onClick={() => handleOpenCreate('manual')}
            className={cn(
              'inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-[15px] font-medium',
              'bg-[#C25E3A] text-white hover:bg-[#D97B5A] transition-all'
            )}
          >
            <Plus className="w-4 h-4" />
            {t('skills.newSkill')}
          </button>
        </div>
      </motion.div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 border-b border-[#E3D7BC]">
        {(['library', 'builtin'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={cn(
              'px-4 py-2.5 text-[13px] font-medium transition-all relative',
              activeTab === tab
                ? 'text-[#C25E3A]'
                : 'text-[#6B5E4E] hover:text-[#2A2318]'
            )}
          >
            {tab === 'library' ? t('skills.tabLibrary') : t('skills.tabBuiltin')}
            {activeTab === tab && (
              <motion.div
                layoutId="skills-tab"
                className="absolute bottom-0 left-0 right-0 h-[2px] bg-[#C25E3A]"
                transition={{ duration: 0.2 }}
              />
            )}
          </button>
        ))}
        {/* Search */}
        <div className="ml-auto mb-2 relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#A89880]" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t('skills.searchPlaceholder')}
            className={cn(
              'pl-9 pr-4 py-2 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[14px] text-[#2A2318]',
              'placeholder:text-[#A89880] w-48',
              'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
              'transition-all'
            )}
          />
        </div>
      </div>

      {/* Skill Cards Grid */}
      {filteredSkills.length === 0 ? (
        <EmptyState
          icon={Wrench}
          title={activeTab === 'builtin' ? t('skills.emptyBuiltinTitle') : t('skills.emptyTitle')}
          description={
            activeTab === 'builtin'
              ? t('skills.emptyBuiltinDescription')
              : t('skills.emptyLibraryDescription')
          }
          action={
            activeTab !== 'builtin' && (
              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleOpenCreate('manual')}
                  className={cn(
                    'inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-[15px] font-medium',
                    'bg-[#C25E3A] text-white hover:bg-[#D97B5A] transition-all'
                  )}
                >
                  <Plus className="w-4 h-4" />
                  {t('skills.createSkill')}
                </button>
              </div>
            )
          }
        />
      ) : (
        <motion.div
          className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
          variants={containerVariants}
          initial="hidden"
          animate="visible"
        >
          {filteredSkills.map((skill) => (
            <motion.div
              key={skill.id}
              variants={itemVariants}
              whileHover={{ y: -2, transition: { duration: 0.2 } }}
              className="cursor-pointer group"
              onClick={() => handleSkillClick(skill.id)}
            >
              <VellumPanel>
                <div className="flex items-start gap-3 mb-3">
                  {skill.type === 'builtin' ? (
                    <Settings className="w-5 h-5 text-[#8B7A6A] flex-shrink-0 mt-0.5" />
                  ) : (
                    <Palette className="w-5 h-5 text-[#D4A843] flex-shrink-0 mt-0.5" />
                  )}
                  <div className="flex-1 min-w-0">
                    <h3 className="font-['Fraunces',Georgia,serif] text-[18px] font-medium text-[#2A2318] leading-tight">
                      {skill.name}
                    </h3>
                  </div>
                  <SourceBadge type={skill.type} />
                </div>

                <p className="text-[13px] text-[#6B5E4E] mb-3 line-clamp-2">
                  {skill.description}
                </p>

                <div className="flex items-center justify-between">
                  <span className="text-[12px] font-mono text-[#A89880]">
                    {t('skills.fileCount', { count: (skill.files || []).length })}
                  </span>
                  <div className="flex items-center gap-1">
                    {skill.type !== 'builtin' && (
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeletingSkill({ id: skill.id, name: skill.name }); }}
                        className="p-1.5 rounded-md text-[#A89880] hover:text-[#C0492B] hover:bg-[#F3D9D0] transition-colors opacity-0 group-hover:opacity-100"
                        aria-label={t('skills.delete')}
                        title={t('skills.delete')}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                    <ChevronRight className="w-4 h-4 text-[#A89880]" />
                  </div>
                </div>
              </VellumPanel>
            </motion.div>
          ))}
        </motion.div>
      )}

      {/* ─── Create/Import Skill Modal ────────────────────────────────────────── */}
      <Modal
        isOpen={createModalOpen}
        onClose={() => setCreateModalOpen(false)}
        title={
          (() => {
            const full = createMode === 'manual' ? t('skills.newSkill') : t('skills.importTitle');
            return (
              <span className="font-['Fraunces',Georgia,serif] text-[28px] font-semibold text-[#2A2318]">
                <span className="title-initial">{full.charAt(0)}</span>
                {full.slice(1)}
              </span>
            );
          })()
        }
        maxWidth="max-w-lg"
        footer={
          createMode === 'manual' ? (
            <>
              <button
                onClick={() => setCreateModalOpen(false)}
                className="px-4 py-2 rounded-md text-[13px] font-medium bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC] transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleCreateManual}
                disabled={!skillName.trim() || creating}
                className={cn(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-all',
                  skillName.trim() && !creating
                    ? 'bg-[#C25E3A] text-white hover:bg-[#D97B5A]'
                    : 'bg-[#E3D7BC] text-[#A89880] cursor-not-allowed'
                )}
              >
                {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {t('skills.createSkill')}
              </button>
            </>
          ) : importStep === 'input' ? (
            <>
              <button
                onClick={() => setCreateModalOpen(false)}
                className="px-4 py-2 rounded-md text-[13px] font-medium bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC] transition-colors"
              >
                {t('common.cancel')}
              </button>
              <button
                onClick={handleImport}
                disabled={!githubUrl.trim() || creating}
                className={cn(
                  'inline-flex items-center gap-2 px-4 py-2 rounded-md text-[13px] font-medium transition-all',
                  githubUrl.trim() && !creating
                    ? 'bg-[#C25E3A] text-white hover:bg-[#D97B5A]'
                    : 'bg-[#E3D7BC] text-[#A89880] cursor-not-allowed'
                )}
              >
                {creating && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                {t('skills.import')}
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setImportStep('input')}
                className="px-4 py-2 rounded-md text-[13px] font-medium bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC] transition-colors"
              >
                {t('common.back')}
              </button>
              <button
                onClick={handleConfirmImport}
                className="px-4 py-2 rounded-md text-[13px] font-medium bg-[#C25E3A] text-white hover:bg-[#D97B5A] transition-colors"
              >
                {t('skills.confirmImport')}
              </button>
            </>
          )
        }
      >
        {createMode === 'manual' ? (
          <div className="space-y-4">
            <div>
              <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                {t('skills.nameLabel')} <span className="text-[#C25E3A]">*</span>
              </label>
              <input
                type="text"
                value={skillName}
                onChange={(e) => setSkillName(e.target.value)}
                placeholder={t('skills.namePlaceholder')}
                className={cn(
                  'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                  'placeholder:text-[#A89880]',
                  'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                  'transition-all'
                )}
                autoFocus
              />
            </div>
            <div>
              <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                {t('skills.descriptionLabel')}
              </label>
              <textarea
                value={skillDesc}
                onChange={(e) => setSkillDesc(e.target.value)}
                placeholder={t('skills.descriptionPlaceholder')}
                rows={3}
                className={cn(
                  'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                  'placeholder:text-[#A89880]',
                  'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                  'transition-all resize-none'
                )}
              />
            </div>
            <p className="text-[11px] text-[#A89880]">
              {t('skills.manualNote')}
            </p>
          </div>
        ) : importStep === 'input' ? (
          <div className="space-y-4">
            <div>
              <label className="block text-[13px] font-medium text-[#2A2318] mb-1">
                {t('skills.githubUrlLabel')} <span className="text-[#C25E3A]">*</span>
              </label>
              <input
                type="text"
                value={githubUrl}
                onChange={(e) => setGithubUrl(e.target.value)}
                placeholder={t('skills.githubUrlPlaceholder')}
                className={cn(
                  'w-full px-4 py-2.5 rounded-md bg-[#F7F0E0] border border-[#E3D7BC] text-[15px] text-[#2A2318]',
                  'placeholder:text-[#A89880]',
                  'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15',
                  'transition-all'
                )}
                autoFocus
              />
            </div>
            {creating && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="flex items-center gap-2 text-[13px] text-[#6B5E4E]"
              >
                <Loader2 className="w-4 h-4 animate-spin text-[#C25E3A]" />
                {t('skills.fetching')}
              </motion.div>
            )}
          </div>
        ) : (
          <div className="space-y-4">
            <p className="text-[13px] text-[#6B5E4E]">
              {t('skills.detectedFiles', { count: importedFiles.length })}{' '}
              <span className="text-[#C25E3A] font-mono text-[12px]">{githubUrl}</span>:
            </p>
            <div className="bg-[#F7F0E0] border border-[#E3D7BC] rounded-md overflow-hidden">
              {importedFiles.map((f, i) => (
                <div
                  key={f.path}
                  className={cn(
                    'flex items-center gap-2 px-3 py-2 text-[13px] font-mono text-[#2A2318]',
                    i < importedFiles.length - 1 && 'border-b border-[#E3D7BC]'
                  )}
                >
                  <FileText className="w-3.5 h-3.5 text-[#A89880] flex-shrink-0" />
                  <span className="truncate">{f.path}</span>
                  <span className="ml-auto text-[11px] text-[#A89880] flex-shrink-0">
                    {f.language}
                  </span>
                </div>
              ))}
            </div>
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
