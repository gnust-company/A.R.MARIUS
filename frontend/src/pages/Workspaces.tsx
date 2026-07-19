// @ts-nocheck
import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import {
  Diamond,
  FolderOpen,
  Bot,
  Plus,
  ArrowRight,
  Pencil,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import VellumPanel from '@/components/VellumPanel';
import Modal from '@/components/Modal';
import ConfirmDialog from '@/components/ConfirmDialog';
import { cn, wsHref } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.12,
      delayChildren: 0.4,
    },
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

export default function Workspaces() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const workspaces = useAppStore((s) => s.workspaces);
  const projects = useAppStore((s) => s.projects);
  const mariuses = useAppStore((s) => s.mariuses);
  const setActiveWorkspace = useAppStore((s) => s.setActiveWorkspace);
  const createWorkspace = useAppStore((s) => s.createWorkspace);
  const updateWorkspace = useAppStore((s) => s.updateWorkspace);
  const deleteWorkspace = useAppStore((s) => s.deleteWorkspace);
  const hydrateWorkspaces = useAppStore((s) => s.hydrateWorkspaces);
  const hydrateWorkspace = useAppStore((s) => s.hydrateWorkspace);

  // Load the user's workspaces on mount.
  useEffect(() => {
    hydrateWorkspaces();
  }, [hydrateWorkspaces]);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newWsName, setNewWsName] = useState('');
  const [newWsDesc, setNewWsDesc] = useState('');

  // Rename / delete state (edit + delete for each workspace card).
  const [editingWs, setEditingWs] = useState<{ id: string; name: string } | null>(null);
  const [editName, setEditName] = useState('');
  const [deletingWs, setDeletingWs] = useState<{ id: string; name: string } | null>(null);

  const openEdit = (ws: { id: string; name: string }) => {
    setEditingWs(ws);
    setEditName(ws.name);
  };

  const handleRename = async () => {
    if (!editingWs || !editName.trim()) return;
    await updateWorkspace(editingWs.id, editName.trim());
    setEditingWs(null);
  };

  const handleEnter = async (wsId: string) => {
    setActiveWorkspace(wsId);
    await hydrateWorkspace(wsId);
    navigate(wsHref(wsId, '/projects'));
  };

  const handleCreate = async () => {
    if (!newWsName.trim()) return;
    const ws = {
      id: `ws_${Date.now()}`,
      name: newWsName.trim(),
      ownerId: 'u1',
      description: newWsDesc.trim() || undefined,
    };
    const created = await createWorkspace(ws);
    setNewWsName('');
    setNewWsDesc('');
    setIsModalOpen(false);
    setActiveWorkspace(created.id);
    await hydrateWorkspace(created.id);
    navigate(wsHref(created.id, '/projects'));
  };

  return (
    <div className="min-h-[100dvh] bg-vellum flex flex-col items-center justify-center px-6 py-12">
      {/* Background texture overlay */}
      <div
        className="fixed inset-0 pointer-events-none opacity-30"
        style={{ backgroundImage: 'url(/vellum-texture.jpg)', backgroundSize: '200px' }}
      />

      {/* Header */}
      <motion.div
        className="text-center mb-12 relative z-10"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3 }}
      >
        {/* Brand */}
        <motion.div
          className="flex items-baseline justify-center mb-3"
          initial={{ rotateY: 180, opacity: 0 }}
          animate={{ rotateY: 0, opacity: 1 }}
          transition={{ duration: 0.6, ease: 'easeOut' }}
          style={{ perspective: 400 }}
        >
          {/* Illuminated initial "A" + "rmarius" → reads "Armarius" with a single, gilt A */}
          <span style={{ fontFamily: "'Cinzel Decorative', 'Cinzel', serif", fontSize: '52px', color: '#D4A843', fontWeight: 700, lineHeight: 1 }}>A</span>
          <h1 className="font-display text-display-xl text-ink tracking-tight">
            rmarius
          </h1>
        </motion.div>

        {/* Tagline */}
        <motion.p
          className="font-body text-body-lg text-ink-light italic"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.3 }}
        >
          &ldquo;{t('app.tagline')}&rdquo;
        </motion.p>
      </motion.div>

      {/* Workspace Cards */}
      <motion.div
        className="grid grid-cols-1 md:grid-cols-2 gap-6 max-w-3xl w-full relative z-10 mb-6"
        variants={containerVariants}
        initial="hidden"
        animate="visible"
      >
        {workspaces.map((ws) => {
          const wsProjects = projects.filter((p) => p.workspaceId === ws.id);
          const wsAgents = mariuses.filter((m) => m.workspaceId === ws.id);

          return (
            <motion.div
              key={ws.id}
              variants={cardVariants}
              whileHover={{ y: -4, transition: { duration: 0.3 } }}
            >
              <VellumPanel
                className={cn(
                  'cursor-pointer h-full flex flex-col relative group',
                  'hover:border-gold-muted hover:shadow-gilt-lg'
                )}
                hover={false}
                onClick={() => handleEnter(ws.id)}
              >
                {/* Card actions — rename / delete (don't trigger card navigation) */}
                <div className="absolute top-3 right-3 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button
                    onClick={(e) => { e.stopPropagation(); openEdit(ws); }}
                    className="p-1.5 rounded-md text-ink-muted hover:text-ink hover:bg-vellum-dark transition-colors"
                    aria-label={t('workspaces.edit')}
                    title={t('workspaces.edit')}
                  >
                    <Pencil className="w-4 h-4" />
                  </button>
                  <button
                    onClick={(e) => { e.stopPropagation(); setDeletingWs(ws); }}
                    disabled={workspaces.length <= 1}
                    className="p-1.5 rounded-md text-ink-muted hover:text-[#C0492B] hover:bg-[#F3D9D0] transition-colors disabled:opacity-30 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-ink-muted"
                    aria-label={t('workspaces.delete')}
                    title={workspaces.length <= 1 ? t('workspaces.onlyWorkspaceHint') : t('workspaces.delete')}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                {/* Workspace name */}
                <h2 className="font-display text-display-md text-ink mb-1 pr-16">
                  {ws.name}
                </h2>

                {/* Description */}
                <p className="font-body text-body-md text-ink-light mb-4">
                  {ws.description}
                </p>

                {/* Divider */}
                <div className="border-t border-vellum-dark my-4" />

                {/* Stats */}
                <div className="flex items-center gap-4 font-body text-body-sm text-ink-light mb-6">
                  <span className="flex items-center gap-1.5">
                    <FolderOpen className="w-4 h-4" />
                    {t('workspaces.projectsCount', { count: wsProjects.length })}
                  </span>
                  <span className="text-ink-muted">&middot;</span>
                  <span className="flex items-center gap-1.5">
                    <Bot className="w-4 h-4" />
                    {t('workspaces.agentsCount', { count: wsAgents.length })}
                  </span>
                </div>

                {/* Enter button */}
                <div className="mt-auto flex justify-end">
                  <button
                    className="group flex items-center gap-1 font-body text-body-md font-medium text-terracotta hover:text-terracotta-light transition-colors"
                  >
                    {t('workspaces.enterButton')}
                    <ArrowRight className="w-4 h-4 transition-transform duration-200 group-hover:translate-x-1" />
                  </button>
                </div>
              </VellumPanel>
            </motion.div>
          );
        })}
      </motion.div>

      {/* Create Workspace Card */}
      <motion.div
        className="max-w-md w-full relative z-10"
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, delay: 0.7 }}
      >
        <button
          onClick={() => setIsModalOpen(true)}
          className={cn(
            'w-full flex items-center justify-center gap-3 py-8 px-6',
            'border-2 border-dashed border-vellum-dark rounded-xl',
            'text-ink-muted hover:text-terracotta hover:border-terracotta hover:border-solid',
            'transition-all duration-200 cursor-pointer bg-transparent'
          )}
        >
          <Plus className="w-10 h-10" strokeWidth={1.5} />
          <span className="font-body text-body-lg font-medium">{t('workspaces.createTitle')}</span>
        </button>
      </motion.div>

      {/* Create Workspace Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setNewWsName('');
          setNewWsDesc('');
        }}
        title={
          <span className="dropcap">{t('workspaces.createTitle')}</span>
        }
        footer={
          <>
            <button
              onClick={() => {
                setIsModalOpen(false);
                setNewWsName('');
                setNewWsDesc('');
              }}
              className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-vellum-deep text-ink border border-vellum-dark hover:bg-vellum-dark transition-colors"
            >
              {t('workspaces.cancelButton')}
            </button>
            <button
              onClick={handleCreate}
              disabled={!newWsName.trim()}
              className={cn(
                'px-4 py-2 rounded-md font-body text-body-md font-medium transition-colors',
                newWsName.trim()
                  ? 'bg-terracotta text-white hover:bg-terracotta-light'
                  : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
              )}
            >
              {t('workspaces.createButton')}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block font-body text-body-sm font-medium text-ink mb-1">
              {t('workspaces.nameLabel')} <span className="text-terracotta">*</span>
            </label>
            <input
              type="text"
              value={newWsName}
              onChange={(e) => setNewWsName(e.target.value)}
              placeholder={t('workspaces.namePlaceholder')}
              className={cn(
                'w-full px-4 py-2.5 rounded-md bg-vellum border border-vellum-dark',
                'font-body text-body-md text-ink placeholder:text-ink-muted',
                'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
                'transition-all'
              )}
              autoFocus
            />
          </div>
          <div>
            <label className="block font-body text-body-sm font-medium text-ink mb-1">
              {t('workspaces.descriptionLabel')}
            </label>
            <textarea
              value={newWsDesc}
              onChange={(e) => setNewWsDesc(e.target.value)}
              placeholder={t('workspaces.descriptionPlaceholder')}
              rows={3}
              className={cn(
                'w-full px-4 py-2.5 rounded-md bg-vellum border border-vellum-dark',
                'font-body text-body-md text-ink placeholder:text-ink-muted',
                'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
                'transition-all resize-none'
              )}
            />
          </div>
        </div>
      </Modal>

      {/* Rename Workspace Modal */}
      <Modal
        isOpen={editingWs !== null}
        onClose={() => setEditingWs(null)}
        title={<span className="dropcap">{t('workspaces.editTitle')}</span>}
        footer={
          <>
            <button
              onClick={() => setEditingWs(null)}
              className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-vellum-deep text-ink border border-vellum-dark hover:bg-vellum-dark transition-colors"
            >
              {t('workspaces.cancelButton')}
            </button>
            <button
              onClick={handleRename}
              disabled={!editName.trim()}
              className={cn(
                'px-4 py-2 rounded-md font-body text-body-md font-medium transition-colors',
                editName.trim()
                  ? 'bg-terracotta text-white hover:bg-terracotta-light'
                  : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
              )}
            >
              {t('workspaces.saveButton')}
            </button>
          </>
        }
      >
        <div>
          <label className="block font-body text-body-sm font-medium text-ink mb-1">
            {t('workspaces.nameLabel')} <span className="text-terracotta">*</span>
          </label>
          <input
            type="text"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleRename(); }}
            className={cn(
              'w-full px-4 py-2.5 rounded-md bg-vellum border border-vellum-dark',
              'font-body text-body-md text-ink placeholder:text-ink-muted',
              'focus:outline-none focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
              'transition-all'
            )}
            autoFocus
          />
        </div>
      </Modal>

      {/* Delete Workspace confirmation */}
      <ConfirmDialog
        isOpen={deletingWs !== null}
        onClose={() => setDeletingWs(null)}
        onConfirm={async () => { if (deletingWs) await deleteWorkspace(deletingWs.id); }}
        title={t('workspaces.deleteTitle')}
        message={t('workspaces.deleteConfirm', { name: deletingWs?.name ?? '' })}
        confirmLabel={t('workspaces.delete')}
      />
    </div>
  );
}
