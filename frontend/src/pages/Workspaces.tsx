// @ts-nocheck
import { useState } from 'react';
import { useNavigate } from 'react-router';
import { motion } from 'framer-motion';
import {
  Diamond,
  FolderOpen,
  Bot,
  Plus,
  ArrowRight,
} from 'lucide-react';
import { useMockStore } from '@/store/mockStore';
import VellumPanel from '@/components/VellumPanel';
import Modal from '@/components/Modal';
import { cn } from '@/lib/utils';

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
  const workspaces = useMockStore((s) => s.workspaces);
  const projects = useMockStore((s) => s.projects);
  const mariuses = useMockStore((s) => s.mariuses);
  const setActiveWorkspace = useMockStore((s) => s.setActiveWorkspace);
  const createWorkspace = useMockStore((s) => s.createWorkspace);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newWsName, setNewWsName] = useState('');
  const [newWsDesc, setNewWsDesc] = useState('');

  const handleEnter = (wsId: string) => {
    setActiveWorkspace(wsId);
    navigate('/projects');
  };

  const handleCreate = () => {
    if (!newWsName.trim()) return;
    const ws = {
      id: `ws_${Date.now()}`,
      name: newWsName.trim(),
      ownerId: 'u1',
      description: newWsDesc.trim() || undefined,
    };
    createWorkspace(ws);
    setNewWsName('');
    setNewWsDesc('');
    setIsModalOpen(false);
    setActiveWorkspace(ws.id);
    navigate('/projects');
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
          &ldquo;You task. They collaborate. You trace.&rdquo;
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
                  'cursor-pointer h-full flex flex-col',
                  'hover:border-gold-muted hover:shadow-gilt-lg'
                )}
                hover={false}
                onClick={() => handleEnter(ws.id)}
              >
                {/* Workspace name */}
                <h2 className="font-display text-display-md text-ink mb-1">
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
                    {wsProjects.length} projects
                  </span>
                  <span className="text-ink-muted">&middot;</span>
                  <span className="flex items-center gap-1.5">
                    <Bot className="w-4 h-4" />
                    {wsAgents.length} agents
                  </span>
                </div>

                {/* Enter button */}
                <div className="mt-auto flex justify-end">
                  <button
                    className="group flex items-center gap-1 font-body text-body-md font-medium text-terracotta hover:text-terracotta-light transition-colors"
                  >
                    Enter
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
          <span className="font-body text-body-lg font-medium">Create Workspace</span>
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
          <span className="dropcap">Create Workspace</span>
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
              Cancel
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
              Create
            </button>
          </>
        }
      >
        <div className="space-y-4">
          <div>
            <label className="block font-body text-body-sm font-medium text-ink mb-1">
              Workspace Name <span className="text-terracotta">*</span>
            </label>
            <input
              type="text"
              value={newWsName}
              onChange={(e) => setNewWsName(e.target.value)}
              placeholder="e.g., Design Team"
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
              Description
            </label>
            <textarea
              value={newWsDesc}
              onChange={(e) => setNewWsDesc(e.target.value)}
              placeholder="What this workspace is for..."
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
    </div>
  );
}
