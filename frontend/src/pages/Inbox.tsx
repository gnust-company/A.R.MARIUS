// @ts-nocheck
import { useMockStore } from '@/store/mockStore';
import { useNavigate } from 'react-router';
import { motion, AnimatePresence } from 'framer-motion';
import {
  CheckCircle2, AlertTriangle, MessageSquare, ExternalLink,
  FileText, Link2
} from 'lucide-react';
import VellumPanel from '@/components/VellumPanel';
import StatusChip from '@/components/StatusChip';
import PageTitle from '@/components/PageTitle';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

const tabClasses = (active: boolean) =>
  `px-4 py-2 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
    active
      ? 'border-[#C25E3A] text-[#C25E3A]'
      : 'border-transparent text-[#6B5E4E] hover:text-[#2A2318]'
  }`;

const quillIn = {
  hidden: { opacity: 0, y: 16, filter: 'blur(2px)' },
  visible: (i: number) => ({
    opacity: 1, y: 0, filter: 'blur(0px)',
    transition: { delay: i * 0.06, duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] },
  }),
};

export default function Inbox() {
  const { tasks, projects, mariuses, updateTask } = useMockStore();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState<'review' | 'blocked'>('review');

  const safeTasks = tasks || [];
  const safeProjects = projects || [];
  const safeMariuses = mariuses || [];

  const reviewTasks = safeTasks.filter((t) => t.status === 'in_review');
  const blockedTasks = safeTasks.filter((t) => t.status === 'blocked');

  const handleApprove = (taskId: string) => {
    updateTask(taskId, { status: 'done' });
  };

  const renderTaskGroup = (list: typeof tasks, emptyIcon: React.ReactNode, emptyTitle: string) => {
    if (list.length === 0) {
      return (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center justify-center py-20 text-center"
        >
          <div className="text-[#A89880] mb-3">{emptyIcon}</div>
          <h3 className="text-lg font-medium text-[#2A2318] font-[Fraunces]">{emptyTitle}</h3>
          <p className="text-sm text-[#6B5E4E] mt-1">{t('inbox.allGood')}</p>
        </motion.div>
      );
    }

    const grouped = list.reduce<Record<string, typeof list>>((acc, task) => {
      const proj = safeProjects.find((p) => p.id === task.projectId);
      const key = proj?.name || t('inbox.unknownProject');
      if (!acc[key]) acc[key] = [];
      acc[key].push(task);
      return acc;
    }, {});

    return (
      <AnimatePresence mode="wait">
        <motion.div
          key={activeTab}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: -8 }}
          transition={{ duration: 0.25 }}
          className="space-y-6"
        >
          {Object.entries(grouped).map(([projName, projTasks]) => (
            <div key={projName}>
              <h3 className="text-sm font-medium text-[#6B5E4E] mb-3 font-[Fraunces]">{projName}</h3>
              <div className="space-y-3">
                {projTasks.map((task, i) => (
                  <motion.div key={task.id} custom={i} variants={quillIn} initial="hidden" animate="visible">
                    <VellumPanel className="border-l-4 border-l-[#D4A843]">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-mono text-xs text-[#A89880]">{task.identifier}</span>
                            <StatusChip status={task.status} />
                          </div>
                          <h4 className="font-medium text-[#2A2318] text-sm truncate">{task.title}</h4>
                          <p className="text-xs text-[#6B5E4E] mt-1 line-clamp-1">{task.description}</p>
                          <div className="flex items-center gap-3 mt-2">
                            <div className="flex -space-x-1.5">
                              {task.participants?.slice(0, 3).map((agentId) => {
                                const agent = safeMariuses.find((m) => m.id === agentId);
                                return (
                                  <img
                                    key={agentId}
                                    src={agent?.avatar || '/agent-avatar-atlas.jpg'}
                                    alt={agent?.name || agentId}
                                    className="w-5 h-5 rounded-full border border-[#F7F0E0]"
                                  />
                                );
                              })}
                            </div>
                            <div className="flex items-center gap-2 text-[#A89880]">
                              {task.artifacts?.some((a) => a.type === 'file') && <FileText size={12} />}
                              {task.artifacts?.some((a) => a.type === 'link') && <Link2 size={12} />}
                              <span className="text-xs flex items-center gap-1">
                                <MessageSquare size={12} /> {task.comments?.length || 0}
                              </span>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          <button
                            onClick={() => navigate(`/tasks/${task.id}`)}
                            className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-[#6B5E4E] bg-[#EDE4CE] hover:bg-[#E3D7BC] rounded-md transition-colors"
                          >
                            <ExternalLink size={12} /> {t('inbox.open')}
                          </button>
                          {task.status === 'in_review' && (
                            <button
                              onClick={() => handleApprove(task.id)}
                              className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-white bg-[#D4A843] hover:bg-[#E8C96A] rounded-md transition-colors"
                            >
                              <CheckCircle2 size={12} /> {t('inbox.approve')}
                            </button>
                          )}
                        </div>
                      </div>
                    </VellumPanel>
                  </motion.div>
                ))}
              </div>
            </div>
          ))}
        </motion.div>
      </AnimatePresence>
    );
  };

  return (
    <div>
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3 mb-6"
      >
        <div className="flex-1">
          <PageTitle title={t('nav.inbox')} subtitle={t('inbox.subtitle')} />
        </div>
        {reviewTasks.length > 0 && (
          <span className="px-2.5 py-1 text-xs font-medium bg-[#C25E3A] text-white rounded-full">
            {t('inbox.pendingCount', { count: reviewTasks.length })}
          </span>
        )}
      </motion.div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-[#E3D7BC] mb-6">
        <button className={tabClasses(activeTab === 'review')} onClick={() => setActiveTab('review')}>
          {t('inbox.needsReview')} {reviewTasks.length > 0 && `(${reviewTasks.length})`}
        </button>
        <button className={tabClasses(activeTab === 'blocked')} onClick={() => setActiveTab('blocked')}>
          {t('inbox.blocked')} {blockedTasks.length > 0 && `(${blockedTasks.length})`}
        </button>
      </div>

      {/* Content */}
      {activeTab === 'review'
        ? renderTaskGroup(reviewTasks, <CheckCircle2 size={48} strokeWidth={1} />, t('inbox.allCaughtUp'))
        : renderTaskGroup(blockedTasks, <AlertTriangle size={48} strokeWidth={1} />, t('inbox.noBlocked'))}
    </div>
  );
}
