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
  CheckCheck,
  CheckCircle2,
  ExternalLink,
  FileQuestion,
  GitBranch,
  Inbox as InboxIcon,
  PencilLine,
  ScrollText,
  ThumbsDown,
  UserPlus,
  XCircle,
} from 'lucide-react';
import { useTranslation } from 'react-i18next';

import PageTitle from '@/components/PageTitle';
import VellumPanel from '@/components/VellumPanel';
import {
  answerInboxItem,
  getInbox,
  listProjectAgents,
  signTaskApproval,
  type InboxItemDTO,
  type ProjectAgentDTO,
} from '@/lib/api';
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

/** The record of what the system already tried, on an escalation (FR-061).
 *
 * A patron asked "this is stuck, what now?" has to go and reconstruct the history before
 * they can answer. One told "re-woken three times, the Leader was asked, still stuck, here
 * is the question" answers in one read. That gap is what decides whether an escalation is
 * cleared today or next week.
 *
 * Every field is optional on purpose: the dossier is written by the escalator and read
 * here, and a UI that threw on a missing key would take the whole inbox down over a shape
 * change in a background loop. */
function AttemptDossier({ item }: { item: InboxItemDTO }) {
  const { t } = useTranslation();
  const d = (item.attempt_dossier ?? {}) as Record<string, unknown>;
  const cause = typeof d.cause === 'string' ? d.cause : undefined;
  const attempts = typeof d.level1_attempts === 'number' ? d.level1_attempts : 0;
  const leaderAsked = d.leader_asked === true;
  const question = typeof d.question === 'string' ? d.question : undefined;

  if (!cause && !attempts && !leaderAsked && !question) return null;

  return (
    <div className="mt-2 rounded-md bg-[#F6EFE1] px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-[#8B6A28] mb-1">
        {t('inbox.dossier.title')}
      </p>
      <ul className="space-y-0.5 text-xs text-[#6B5E4E]">
        {cause && (
          <li>
            <span className="text-[#8B6A28]">{t('inbox.dossier.cause')}:</span> {cause}
          </li>
        )}
        {attempts > 0 && <li>{t('inbox.dossier.attempts', { count: attempts })}</li>}
        {leaderAsked && <li>{t('inbox.dossier.leaderAsked')}</li>}
      </ul>
      {question && (
        <p className="mt-1.5 text-xs font-medium text-[#2A2318]">
          <span className="text-[#8B6A28]">{t('inbox.dossier.question')}:</span> {question}
        </p>
      )}
    </div>
  );
}

const actionButton =
  'flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-[#6B5E4E] bg-[#EDE4CE] hover:bg-[#E3D7BC] rounded-md transition-colors disabled:opacity-50 cursor-pointer';
const primaryButton =
  'flex items-center gap-1 px-3 py-1.5 text-xs font-medium text-white bg-[#D4A843] hover:bg-[#E8C96A] rounded-md transition-colors disabled:opacity-50 cursor-pointer';
const fieldClasses =
  'w-full rounded-md border border-[#E3D7BC] bg-white px-2.5 py-1.5 text-xs text-[#2A2318] focus:border-[#D4A843] focus:outline-none';

/** Answering an *escalation* in place, where it is asked (FR-061a).
 *
 * The ladder carries a dropped task up to the patron and then stops — past that point the
 * system has no move left. Yet the item used to carry a single *Open* button: it asked
 * three questions and offered none of the answers, so the reader had to go and find the
 * place to reply. That is the hard part, and handing it to the very person the ladder
 * exists to save time for only makes the net fall short later rather than never.
 *
 * Four ways out, and the fourth is a different kind of thing from the first three. Those
 * say *"system, do this for me"*; the fourth says *"I sorted it outside, carry on"* —
 * the patron restarted a hung agent, fixed something on their own machine. Without it
 * they must pretend to pick one of the other three.
 *
 * The thing to hold on to: **the letter closes because the patron answered it**. The
 * stall sweep never touches the inbox (FR-061b), and closing the letter is where the
 * system recomputes whether anything is still about to touch the task (FR-061c). Miss
 * that and the task leaves the net for good.
 *
 * All of which is one server call, not two (FR-061e). The patron made one decision, so it
 * lands as one fact: the server changes the task and closes the letter under a single
 * commit. Acting from here and closing separately would leave a window where the task
 * moved and the question still stood, and a patron who saw that failure and pressed again
 * would run the action twice — waking a new owner a second time for one incident.
 */
function EscalationActions({
  item,
  busy,
  setBusy,
  onError,
  onDone,
}: {
  item: InboxItemDTO;
  busy: boolean;
  setBusy: (id: string | null) => void;
  onError: (message: string | null) => void;
  onDone: () => void;
}) {
  const { t } = useTranslation();
  const [mode, setMode] = useState<'assign' | 'next' | 'cancel' | null>(null);
  const [agents, setAgents] = useState<ProjectAgentDTO[] | null>(null);
  const [agentId, setAgentId] = useState('');
  const [text, setText] = useState('');
  // The agent list is fetched only once the patron actually opens the *reassign* form.
  // Prefetching it for every item on mount is one request per item, most of them unused.
  useEffect(() => {
    if (mode !== 'assign' || agents !== null || !item.project_id) return;
    let alive = true;
    listProjectAgents(item.project_id)
      .then((rows) => {
        if (alive) setAgents(rows);
      })
      .catch((e: unknown) => {
        if (alive) onError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      alive = false;
    };
  }, [mode, agents, item.project_id, onError]);

  const close = () => {
    setMode(null);
    setAgentId('');
    setText('');
  };

  /** Send the patron's answer. One call: see the note on this component.
   *
   * `answerInboxItem` is also safe to repeat — an already-answered letter means the server
   * does nothing — so a patron who presses again after a network blip cannot act twice. */
  const run = async (
    answer: 'reassign' | 'next_action' | 'cancel' | 'handled',
    extra: { marius_id?: string; text?: string } = {},
  ) => {
    setBusy(item.id);
    onError(null);
    try {
      await answerInboxItem(item.id, { answer, ...extra });
      close();
      onDone();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    }
    setBusy(null);
  };

  const said = text.trim();

  if (mode === null) {
    return (
      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-[#E3D7BC] pt-3">
        <button
          className={actionButton}
          disabled={busy}
          data-testid="escalation-reassign"
          onClick={() => setMode('assign')}
        >
          <UserPlus size={12} /> {t('inbox.escalation.reassign')}
        </button>
        <button
          className={actionButton}
          disabled={busy}
          data-testid="escalation-next-action"
          onClick={() => setMode('next')}
        >
          <PencilLine size={12} /> {t('inbox.escalation.changeNext')}
        </button>
        <button
          className={actionButton}
          disabled={busy}
          data-testid="escalation-cancel-task"
          onClick={() => setMode('cancel')}
        >
          <XCircle size={12} /> {t('inbox.escalation.cancelTask')}
        </button>
        <button
          className={primaryButton}
          disabled={busy}
          title={t('inbox.escalation.handledHint')}
          data-testid="escalation-handled"
          onClick={() => void run('handled')}
        >
          <CheckCheck size={12} /> {t('inbox.escalation.handled')}
        </button>
      </div>
    );
  }

  return (
    <div className="mt-3 space-y-2 border-t border-[#E3D7BC] pt-3">
      {mode === 'assign' && (
        <>
          <label className="block text-[10px] uppercase tracking-wide text-[#8B6A28]">
            {t('inbox.escalation.pickAgent')}
          </label>
          {agents !== null && agents.length === 0 ? (
            <p className="text-xs text-[#6B5E4E]">{t('inbox.escalation.noAgents')}</p>
          ) : (
            <select
              className={fieldClasses}
              value={agentId}
              data-testid="escalation-agent-select"
              onChange={(e) => setAgentId(e.target.value)}
            >
              <option value="">
                {agents === null ? t('common.loading') : t('inbox.escalation.pickAgent')}
              </option>
              {(agents ?? []).map((a) => (
                <option key={a.marius_id} value={a.marius_id}>
                  {a.name}
                </option>
              ))}
            </select>
          )}
        </>
      )}

      <label className="block text-[10px] uppercase tracking-wide text-[#8B6A28]">
        {mode === 'assign'
          ? t('inbox.escalation.transferReason')
          : mode === 'next'
            ? t('inbox.escalation.nextAction')
            : t('inbox.escalation.cancelReason')}
      </label>
      <textarea
        className={fieldClasses}
        rows={2}
        value={text}
        // The server caps this at 2000 characters. Stopping it here means the writer
        // finds out while typing, rather than after a long paragraph and a bare 422.
        maxLength={2000}
        data-testid="escalation-text"
        placeholder={
          mode === 'assign'
            ? t('inbox.escalation.transferReasonPlaceholder')
            : mode === 'next'
              ? t('inbox.escalation.nextActionPlaceholder')
              : t('inbox.escalation.cancelReasonPlaceholder')
        }
        onChange={(e) => setText(e.target.value)}
      />

      <div className="flex items-center gap-2">
        <button
          className={primaryButton}
          data-testid="escalation-confirm"
          // All three paths want words, and not to be awkward: the new owner reads the
          // transfer reason, a cancelled task has to say why (FR-030), and an empty next
          // action is the same as changing nothing.
          disabled={busy || !said || (mode === 'assign' && !agentId)}
          onClick={() => {
            if (mode === 'assign') void run('reassign', { marius_id: agentId, text: said });
            else if (mode === 'next') void run('next_action', { text: said });
            else void run('cancel', { text: said });
          }}
        >
          {t('common.confirm')}
        </button>
        <button className={actionButton} disabled={busy} onClick={close}>
          {t('common.cancel')}
        </button>
      </div>
    </div>
  );
}

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
      // Spelled out rather than `??=`: the compiler has no lowering for that operator yet
      // and drops the whole component when it meets one.
      if (!acc[key]) acc[key] = [];
      acc[key].push(item);
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
    }
    setBusyId(null);
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
                            {/* The record of what was already tried (FR-061). Without it an
                                escalation asks the patron to go and reconstruct the history
                                before they can answer — and that is the difference between
                                a decision made today and one made next week. */}
                            {item.kind === 'escalation' && <AttemptDossier item={item} />}
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
                        {tab === 'pending' && item.kind === 'escalation' && item.task_id && (
                          <EscalationActions
                            item={item}
                            busy={busyId === item.id}
                            setBusy={setBusyId}
                            onError={setError}
                            onDone={reload}
                          />
                        )}
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
