import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import {
  FolderOpen,
  Bot,
  Plus,
  ArrowRight,
  Pencil,
  Trash2,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import EntryFrame from '@/components/EntryFrame';
import PageTitle from '@/components/PageTitle';
import Modal from '@/components/Modal';
import ConfirmDialog from '@/components/ConfirmDialog';
import { cn, wsHref } from '@/lib/utils';
import { agentsOf } from '@/lib/workspaceScope';
import { useTranslation } from 'react-i18next';

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
    navigate(wsHref(wsId, '/home'));
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
    navigate(wsHref(created.id, '/home'));
  };

  const inputCls = cn(
    'w-full min-h-[44px] px-3 py-2.5 rounded-md bg-inset border border-line-strong',
    'font-body text-body-md text-ink placeholder:text-ink-muted',
    'focus:outline-none focus:bg-paper focus:border-terracotta focus:ring-[3px] focus:ring-terracotta/15',
    'transition-colors'
  );
  const labelCls = 'block font-body text-body-sm font-medium text-ink-light mb-1.5';
  const secondaryCls =
    'min-h-[44px] px-4 rounded-md font-body text-body-md font-medium bg-paper text-ink border border-line-strong hover:bg-inset transition-colors';
  const primaryCls = (enabled: boolean) =>
    cn(
      'min-h-[44px] px-4 rounded-md font-body text-body-md font-medium transition-colors',
      enabled ? 'bg-ink text-paper hover:bg-ink/85' : 'bg-line text-ink-muted cursor-not-allowed'
    );

  return (
    <EntryFrame>
      <motion.div
        className="w-full max-w-[1040px]"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
      >
        <div className="mb-7">
          <PageTitle title={t('workspaces.title')} subtitle={t('workspaces.lead')} />
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {workspaces.map((ws) => {
            const wsProjects = projects.filter((p) => p.workspaceId === ws.id);
            const wsAgents = agentsOf(mariuses, ws.id);
            const onlyOne = workspaces.length <= 1;

            return (
              <div
                key={ws.id}
                className={cn(
                  'group relative flex flex-col min-w-0 cursor-pointer',
                  'bg-paper border border-line rounded-xl p-5',
                  'hover:border-line-strong hover:shadow-gilt-lg transition-[border-color,box-shadow]'
                )}
                onClick={() => handleEnter(ws.id)}
              >
                <div className="flex items-start gap-3 min-w-0">
                  {/* The workspace's initial, set like a small seal — enough to tell two cards
                      apart at a glance without inventing an icon per workspace. */}
                  <span
                    className="w-11 h-11 shrink-0 rounded-lg bg-inset border border-line flex items-center justify-center font-display text-[22px] font-medium text-ink"
                    aria-hidden
                  >
                    {ws.name.charAt(0).toUpperCase()}
                  </span>
                  <div className="flex-1 min-w-0 pt-0.5">
                    <h2 className="font-display font-medium text-[20px] leading-snug text-ink truncate" title={ws.name}>
                      {ws.name}
                    </h2>
                    {ws.description && (
                      <p className="mt-0.5 font-body text-body-sm text-ink-light line-clamp-2">
                        {ws.description}
                      </p>
                    )}
                  </div>
                </div>

                <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 font-body text-body-sm text-ink-light">
                  <span className="flex items-center gap-1.5">
                    <FolderOpen className="w-4 h-4 text-ink-muted" aria-hidden />
                    {t('workspaces.projectsCount', { count: wsProjects.length })}
                  </span>
                  <span className="flex items-center gap-1.5">
                    <Bot className="w-4 h-4 text-ink-muted" aria-hidden />
                    {t('workspaces.agentsCount', { count: wsAgents.length })}
                  </span>
                </div>

                <div className="mt-auto pt-4">
                  <div className="-mx-2 pt-2 border-t border-line flex items-center justify-between gap-2">
                    {/* Rename / delete stay visible: on a touch screen there is no hover to
                        reveal them. Clicks stop here so they don't also open the workspace. */}
                    <div className="flex items-center">
                      <button
                        onClick={(e) => { e.stopPropagation(); openEdit(ws); }}
                        className="w-10 h-10 rounded-md flex items-center justify-center text-ink-muted hover:text-ink hover:bg-inset transition-colors"
                        aria-label={t('workspaces.edit')}
                        title={t('workspaces.edit')}
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); setDeletingWs(ws); }}
                        disabled={onlyOne}
                        className={cn(
                          'w-10 h-10 rounded-md flex items-center justify-center transition-colors',
                          onlyOne
                            ? 'text-line-strong cursor-not-allowed'
                            : 'text-ink-muted hover:text-vermilion-ink hover:bg-vermilion-bg'
                        )}
                        aria-label={t('workspaces.delete')}
                        title={onlyOne ? t('workspaces.onlyWorkspaceHint') : t('workspaces.delete')}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                    <button
                      className="inline-flex items-center gap-1 min-h-[44px] px-2 font-body text-body-md font-medium text-terracotta hover:text-terracotta-dark transition-colors"
                    >
                      {t('workspaces.enterButton')}
                      <ArrowRight className="w-4 h-4 transition-transform duration-150 group-hover:translate-x-0.5" aria-hidden />
                    </button>
                  </div>
                </div>
              </div>
            );
          })}

          {/* A new workspace sits in the grid as one more tile, so it is found where the
              workspaces are rather than below the fold on a long list. */}
          <button
            onClick={() => setIsModalOpen(true)}
            className={cn(
              'min-h-[148px] flex flex-col items-center justify-center gap-2 px-5 py-6',
              'border border-dashed border-line-strong rounded-xl',
              'text-ink-light hover:text-ink hover:bg-paper transition-colors'
            )}
          >
            <span className="w-10 h-10 rounded-full border border-line-strong bg-paper flex items-center justify-center">
              <Plus className="w-5 h-5" aria-hidden />
            </span>
            <span className="font-body text-body-md font-medium">{t('workspaces.createTitle')}</span>
          </button>
        </div>
      </motion.div>

      {/* Create Workspace Modal */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => {
          setIsModalOpen(false);
          setNewWsName('');
          setNewWsDesc('');
        }}
        title={t('workspaces.createTitle')}
        footer={
          <>
            <button
              onClick={() => {
                setIsModalOpen(false);
                setNewWsName('');
                setNewWsDesc('');
              }}
              className={secondaryCls}
            >
              {t('workspaces.cancelButton')}
            </button>
            <button
              onClick={handleCreate}
              disabled={!newWsName.trim()}
              className={primaryCls(!!newWsName.trim())}
            >
              {t('workspaces.createButton')}
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label htmlFor="ws-new-name" className={labelCls}>
              {t('workspaces.nameLabel')} <span className="text-ink-muted" aria-hidden>*</span>
            </label>
            <input
              id="ws-new-name"
              type="text"
              value={newWsName}
              onChange={(e) => setNewWsName(e.target.value)}
              placeholder={t('workspaces.namePlaceholder')}
              className={inputCls}
              autoFocus
            />
          </div>
          <div>
            <label htmlFor="ws-new-desc" className={labelCls}>
              {t('workspaces.descriptionLabel')}
            </label>
            <textarea
              id="ws-new-desc"
              value={newWsDesc}
              onChange={(e) => setNewWsDesc(e.target.value)}
              placeholder={t('workspaces.descriptionPlaceholder')}
              rows={3}
              className={cn(inputCls, 'resize-none')}
            />
          </div>
        </div>
      </Modal>

      {/* Rename Workspace Modal */}
      <Modal
        isOpen={editingWs !== null}
        onClose={() => setEditingWs(null)}
        title={t('workspaces.editTitle')}
        footer={
          <>
            <button onClick={() => setEditingWs(null)} className={secondaryCls}>
              {t('workspaces.cancelButton')}
            </button>
            <button
              onClick={handleRename}
              disabled={!editName.trim()}
              className={primaryCls(!!editName.trim())}
            >
              {t('workspaces.saveButton')}
            </button>
          </>
        }
      >
        <div>
          <label htmlFor="ws-edit-name" className={labelCls}>
            {t('workspaces.nameLabel')} <span className="text-ink-muted" aria-hidden>*</span>
          </label>
          <input
            id="ws-edit-name"
            type="text"
            value={editName}
            onChange={(e) => setEditName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleRename(); }}
            className={inputCls}
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
    </EntryFrame>
  );
}
