/**
 * Hộp thư người chủ — đọc thẳng từ máy chủ (spec 001 §11, FR-035, FR-065).
 *
 * Trước đây trang này lọc danh sách đầu việc ở trình duyệt và gọi "hộp thư": nó hiện mọi
 * việc đang *chờ rà soát* của mọi người, kể cả việc không ai hỏi tới người chủ. Hộp thư
 * thật thì ngược lại — máy chủ đặt vào đây đúng những quyết định **thuộc về người này**,
 * và mỗi mục biến mất khi chính hành động nó chờ đã xảy ra, không phải khi ai đó gạt đi.
 *
 * Bậc nhắc (FR-065) hiện ngay trên mục: một mục đã nhắc ba lần trông phải khác một mục
 * vừa tới, nếu không thì "nhắc thưa dần" chỉ là chuyện của máy chủ và người chủ không
 * thấy gì.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  FileQuestion,
  GitBranch,
  Inbox as InboxIcon,
  ScrollText,
  ThumbsDown,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import PageTitle from '@/components/PageTitle';
import VellumPanel from '@/components/VellumPanel';
import { getInbox, signTaskApproval, type InboxItemDTO } from '@/lib/api';
import { wsHref } from '@/lib/utils';
import { useAppStore } from '@/store/appStore';

/** Máy chủ đặt mục theo loại; mỗi loại có biểu tượng và nhãn riêng. */
const KIND_ICONS: Record<string, React.ReactNode> = {
  output_acceptance: <CheckCircle2 size={14} />,
  plan_approval: <ScrollText size={14} />,
  major_change_approval: <GitBranch size={14} />,
  phase_decision: <GitBranch size={14} />,
  escalation: <AlertTriangle size={14} />,
  question: <FileQuestion size={14} />,
};

const tabClasses = (active: boolean) =>
  `px-4 py-2 text-sm font-medium border-b-2 transition-colors cursor-pointer ${
    active
      ? 'border-[#C25E3A] text-[#C25E3A]'
      : 'border-transparent text-[#6B5E4E] hover:text-[#2A2318]'
  }`;

const quillIn = {
  hidden: { opacity: 0, y: 16, filter: 'blur(2px)' },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    filter: 'blur(0px)',
    transition: {
      delay: i * 0.06,
      duration: 0.4,
      ease: [0, 0, 0.2, 1] as [number, number, number, number],
    },
  }),
};

export default function Inbox() {
  const { projects } = useAppStore();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const { t } = useTranslation();

  const [items, setItems] = useState<InboxItemDTO[]>([]);
  const [tab, setTab] = useState<'pending' | 'resolved'>('pending');
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Tải trong hiệu ứng, nhưng mọi lần đặt trạng thái đều nằm sau khi lời hứa xong —
  // đặt trạng thái ngay trong thân hiệu ứng sẽ kéo theo một vòng vẽ lại thừa. `alive`
  // chặn một lời hồi đáp về muộn ghi đè lên tab người dùng vừa đổi sang.
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    getInbox({ status: tab })
      .then((rows) => {
        if (!alive) return;
        setItems(rows);
        setError(null);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [tab, reloadKey]);

  const switchTab = (next: 'pending' | 'resolved') => {
    if (next === tab) return;
    setLoading(true);
    setTab(next);
  };

  const projectName = useCallback(
    (id?: string | null) =>
      (projects || []).find((p) => p.id === id)?.name ?? t('inbox.unknownProject'),
    [projects, t],
  );

  const grouped = useMemo(() => {
    const acc: Record<string, InboxItemDTO[]> = {};
    for (const item of items) {
      const key = projectName(item.project_id);
      (acc[key] ??= []).push(item);
    }
    return acc;
  }, [items, projectName]);

  /** Ký công nhận ngay tại hộp thư — mục tự đóng vì việc nó chờ đã xảy ra. */
  const sign = async (item: InboxItemDTO, approve: boolean) => {
    if (!item.task_id) return;
    let reason: string | undefined;
    if (!approve) {
      // Từ chối mà không nói vì sao thì thợ không có gì để sửa (FR-040).
      const said = window.prompt(t('inbox.rejectReasonPrompt'));
      if (!said || !said.trim()) return;
      reason = said.trim();
    }
    setBusyId(item.id);
    try {
      await signTaskApproval(item.task_id, approve, reason);
      reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusyId(null);
    }
  };

  const pendingCount = tab === 'pending' ? items.length : 0;

  return (
    <div>
      <motion.div
        initial={{ opacity: 0, y: -8 }}
        animate={{ opacity: 1, y: 0 }}
        className="flex items-center gap-3 mb-6"
      >
        <div className="flex-1">
          <PageTitle title={t('nav.inbox')} subtitle={t('inbox.subtitle')} />
        </div>
        {pendingCount > 0 && (
          <span className="px-2.5 py-1 text-xs font-medium bg-[#C25E3A] text-white rounded-full">
            {t('inbox.pendingCount', { count: pendingCount })}
          </span>
        )}
      </motion.div>

      <div className="flex gap-1 border-b border-[#E3D7BC] mb-6">
        <button className={tabClasses(tab === 'pending')} onClick={() => switchTab('pending')}>
          {t('inbox.waiting')}
        </button>
        <button className={tabClasses(tab === 'resolved')} onClick={() => switchTab('resolved')}>
          {t('inbox.handled')}
        </button>
      </div>

      {error && (
        <p className="mb-4 text-sm text-[#C25E3A]" role="alert">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-sm text-[#6B5E4E]">{t('common.loading')}</p>
      ) : items.length === 0 ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex flex-col items-center justify-center py-20 text-center"
        >
          <div className="text-[#A89880] mb-3">
            <InboxIcon size={48} strokeWidth={1} />
          </div>
          <h3 className="text-lg font-medium text-[#2A2318] font-[Fraunces]">
            {t('inbox.allCaughtUp')}
          </h3>
          <p className="text-sm text-[#6B5E4E] mt-1">{t('inbox.nothingWaiting')}</p>
        </motion.div>
      ) : (
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.25 }}
            className="space-y-6"
          >
            {Object.entries(grouped).map(([name, rows]) => (
              <div key={name}>
                <h3 className="text-sm font-medium text-[#6B5E4E] mb-3 font-[Fraunces]">{name}</h3>
                <div className="space-y-3">
                  {rows.map((item, i) => (
                    <motion.div
                      key={item.id}
                      custom={i}
                      variants={quillIn}
                      initial="hidden"
                      animate="visible"
                    >
                      <VellumPanel className="border-l-4 border-l-[#D4A843]">
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="inline-flex items-center gap-1 text-xs text-[#8B6A28]">
                                {KIND_ICONS[item.kind] ?? <FileQuestion size={14} />}
                                {t(`inbox.kind.${item.kind}`, {
                                  defaultValue: item.kind,
                                })}
                              </span>
                              {item.reminder_tier > 0 && (
                                <span className="px-1.5 py-0.5 text-[10px] rounded bg-[#F3E2D6] text-[#C25E3A]">
                                  {t('inbox.reminderTier', { tier: item.reminder_tier })}
                                </span>
                              )}
                            </div>
                            <h4 className="font-medium text-[#2A2318] text-sm">{item.title}</h4>
                            {item.body && (
                              <p className="text-xs text-[#6B5E4E] mt-1 whitespace-pre-line">
                                {item.body}
                              </p>
                            )}
                          </div>
                          <div className="flex items-center gap-2 shrink-0">
                            {item.task_id && (
                              <button
                                onClick={() =>
                                  navigate(wsHref(workspaceId, `/tasks/${item.task_id}`))
                                }
                                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-[#6B5E4E] bg-[#EDE4CE] hover:bg-[#E3D7BC] rounded-md transition-colors"
                              >
                                <ExternalLink size={12} /> {t('inbox.open')}
                              </button>
                            )}
                            {tab === 'pending' && item.kind === 'output_acceptance' && (
                              <>
                                <button
                                  disabled={busyId === item.id}
                                  onClick={() => void sign(item, false)}
                                  className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-[#6B5E4E] bg-[#EDE4CE] hover:bg-[#E3D7BC] rounded-md transition-colors disabled:opacity-50"
                                >
                                  <ThumbsDown size={12} /> {t('inbox.sendBack')}
                                </button>
                                <button
                                  disabled={busyId === item.id}
                                  onClick={() => void sign(item, true)}
                                  className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-white bg-[#D4A843] hover:bg-[#E8C96A] rounded-md transition-colors disabled:opacity-50"
                                >
                                  <CheckCircle2 size={12} /> {t('inbox.accept')}
                                </button>
                              </>
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
      )}
    </div>
  );
}
