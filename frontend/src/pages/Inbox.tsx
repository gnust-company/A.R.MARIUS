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
  ChevronRight,
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
import type { TFunction } from 'i18next';
import { useTranslation } from 'react-i18next';

import PageTitle from '@/components/PageTitle';
import StatusChip from '@/components/StatusChip';
import Dropdown from '@/components/Dropdown';
import {
  answerInboxItem,
  getInbox,
  listProjectAgents,
  signTaskApproval,
  type InboxItemDTO,
  type ProjectAgentDTO,
} from '@/lib/api';
import { cn, wsHref } from '@/lib/utils';
import { errorText } from '@/lib/errors';
import { stallText } from '@/lib/stall';
import { useAppStore } from '@/store/appStore';

/** Máy chủ đặt mục theo loại; mỗi loại có biểu tượng và nhãn riêng. */
const KIND_ICONS: Record<string, React.ReactNode> = {
  output_acceptance: <CheckCircle2 className="w-[18px] h-[18px]" />,
  plan_approval: <ScrollText className="w-[18px] h-[18px]" />,
  major_change_approval: <GitBranch className="w-[18px] h-[18px]" />,
  phase_decision: <GitBranch className="w-[18px] h-[18px]" />,
  escalation: <AlertTriangle className="w-[18px] h-[18px]" />,
  question: <FileQuestion className="w-[18px] h-[18px]" />,
};

/** The tint behind a letter's icon. Gold is "waiting on you"; an escalation is something
 *  already stuck, so it reads as vermilion; a letter that is no longer waiting goes quiet. */
function kindTint(item: InboxItemDTO): string {
  if (item.status !== 'pending') return 'bg-ash-bg text-ink-light';
  if (item.kind === 'escalation') return 'bg-vermilion-bg text-vermilion-ink';
  return 'bg-gold-bg text-gold-ink';
}

function relativeTime(iso: string | null | undefined, t: TFunction): string {
  if (!iso) return '';
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return t('common.justNow');
  if (minutes < 60) return t('common.minutesAgo', { count: minutes });
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return t('common.hoursAgo', { count: hours });
  return t('common.daysAgo', { count: Math.floor(hours / 24) });
}

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
  const tried = Boolean(cause || attempts || leaderAsked);

  // The question is what the patron is being asked to decide, so it is always in view; the
  // history behind it folds away, one tap to open, so a long inbox still scans as decisions.
  return (
    <div className="mt-3 rounded-lg border border-line bg-inset">
      {question && (
        <p className={cn('px-4 pt-3 font-body text-body-md text-ink', tried ? 'pb-1' : 'pb-3')}>
          <span className="font-medium text-gold-ink">{t('inbox.dossier.question')}:</span> {question}
        </p>
      )}
      {tried && (
        <details className="group">
          <summary className="flex min-h-[44px] cursor-pointer list-none items-center gap-2 px-4 font-body text-body-sm font-medium text-ink-light hover:text-ink [&::-webkit-details-marker]:hidden">
            <ChevronRight className="h-4 w-4 shrink-0 transition-transform group-open:rotate-90" aria-hidden />
            {t('inbox.dossier.title')}
          </summary>
          <ul className="space-y-1 px-4 pb-3 pl-10 font-body text-body-sm text-ink-light list-disc marker:text-ink-muted">
            {cause && (
              <li>
                <span className="font-medium text-ink">{t('inbox.dossier.cause')}:</span>{' '}
                {stallText(cause, t) ?? t('board.stalled')}
              </li>
            )}
            {attempts > 0 && <li>{t('inbox.dossier.attempts', { count: attempts })}</li>}
            {leaderAsked && <li>{t('inbox.dossier.leaderAsked')}</li>}
          </ul>
        </details>
      )}
    </div>
  );
}

const buttonBase =
  'inline-flex items-center justify-center gap-1.5 min-h-[44px] px-3.5 sm:px-4 rounded-md font-body text-body-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer';
const actionButton = cn(buttonBase, 'bg-paper border border-line-strong text-ink hover:bg-inset');
const primaryButton = cn(buttonBase, 'bg-ink text-paper hover:bg-ink/85');
const destructiveButton = cn(buttonBase, 'bg-paper border border-[#EDB8B0] text-vermilion-ink hover:bg-vermilion-bg');
const fieldClasses =
  'w-full rounded-md border border-line bg-inset px-3 py-2.5 font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors';
const fieldLabel = 'block font-body text-body-sm font-medium text-ink-light';

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
  frozen,
  setBusy,
  onError,
  onDone,
}: {
  item: InboxItemDTO;
  busy: boolean;
  /** Its project is closed: the letter stays, readable, but nothing on it can be acted
   *  on any more (FR-005). The server refuses these calls too — this only keeps the
   *  patron from being handed a button that answers 409. */
  frozen: boolean;
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
        if (alive) onError(errorText(e, t));
      });
    return () => {
      alive = false;
    };
  }, [mode, agents, item.project_id, onError, t]);

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
      onError(errorText(e, t));
    }
    setBusy(null);
  };

  const said = text.trim();

  if (mode === null) {
    return (
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          className={actionButton}
          disabled={busy || frozen}
          data-testid="escalation-reassign"
          onClick={() => setMode('assign')}
        >
          <UserPlus className="w-4 h-4" aria-hidden /> {t('inbox.escalation.reassign')}
        </button>
        <button
          className={actionButton}
          disabled={busy || frozen}
          data-testid="escalation-next-action"
          onClick={() => setMode('next')}
        >
          <PencilLine className="w-4 h-4" aria-hidden /> {t('inbox.escalation.changeNext')}
        </button>
        <button
          className={destructiveButton}
          disabled={busy || frozen}
          data-testid="escalation-cancel-task"
          onClick={() => setMode('cancel')}
        >
          <XCircle className="w-4 h-4" aria-hidden /> {t('inbox.escalation.cancelTask')}
        </button>
        {/* Not disabled when frozen, unlike the three above it: this one writes nothing
            into the project, only into the patron's own inbox. Freezing it too is what
            once left letters that could never be cleared. */}
        <button
          className={primaryButton}
          disabled={busy}
          title={frozen ? t('inbox.closedProjectHint') : t('inbox.escalation.handledHint')}
          data-testid="escalation-handled"
          onClick={() => void run('handled')}
        >
          <CheckCheck className="w-4 h-4" aria-hidden /> {t('inbox.escalation.handled')}
        </button>
        {frozen && (
          <span className="basis-full font-body text-body-sm text-gold-ink" data-testid="escalation-frozen-note">
            {t('inbox.closedProjectHint')}
          </span>
        )}
      </div>
    );
  }

  return (
    <div className="mt-4 space-y-2 rounded-lg border border-line bg-inset p-4">
      {mode === 'assign' && (
        <>
          <label className={fieldLabel}>
            {t('inbox.escalation.pickAgent')}
          </label>
          {agents !== null && agents.length === 0 ? (
            <p className="font-body text-body-sm text-ink-light">{t('inbox.escalation.noAgents')}</p>
          ) : (
            <Dropdown
              className="min-h-[44px] bg-paper sm:max-w-sm"
              testId="escalation-agent-select"
              value={agentId}
              onChange={setAgentId}
              placeholder={
                agents === null ? t('common.loading') : t('inbox.escalation.pickAgent')
              }
              items={(agents ?? []).map((a) => ({ value: a.marius_id, label: a.name }))}
            />
          )}
        </>
      )}

      <label className={cn(fieldLabel, 'pt-1')}>
        {mode === 'assign'
          ? t('inbox.escalation.transferReason')
          : mode === 'next'
            ? t('inbox.escalation.nextAction')
            : t('inbox.escalation.cancelReason')}
      </label>
      <textarea
        className={cn(fieldClasses, 'bg-paper resize-y')}
        rows={3}
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

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <button
          className={mode === 'cancel' ? cn(buttonBase, 'bg-vermilion-ink text-paper hover:bg-vermilion-ink/90') : primaryButton}
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
  cn(
    '-mb-px min-h-[44px] px-4 font-body text-body-md font-medium border-b-2 transition-colors cursor-pointer',
    active
      ? 'border-terracotta text-terracotta'
      : 'border-transparent text-ink-light hover:text-ink hover:border-line-strong'
  );

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
    // The second tab means *no longer waiting*, which includes letters voided when their
    // project closed — nobody answered those, so the server does not file them under
    // resolved. One call for everything, filtered here, rather than two for one list.
    getInbox({ status: tab === 'pending' ? 'pending' : 'all' })
      .then((rows) => {
        if (!alive) return;
        setItems(tab === 'pending' ? rows : rows.filter((r) => r.status !== 'pending'));
        setError(null);
      })
      .catch((e: unknown) => {
        if (alive) setError(errorText(e, t));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [tab, reloadKey, t]);

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

  /** Its project is closed, so nothing on this letter may touch the task any more (FR-005).
   *
   * The letter is left where it is rather than swept away: it is a record of a question
   * that was asked, and the project is kept precisely so its history can still be read.
   * The server refuses these calls regardless — this is what stops the patron from being
   * offered a button that only ever answers "no".
   *
   * Clearing the letter is deliberately **not** one of them: it writes into the inbox, not
   * into the project, and it is the one thing a patron still needs to be able to do here.
   * Closing a project retires its open letters anyway, so this mostly covers the narrow
   * window where a letter is placed as the project is being closed. */
  const isFrozen = useCallback(
    (id?: string | null) => (projects || []).find((p) => p.id === id)?.status === 'closed',
    [projects],
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
      setError(errorText(e, t));
    }
    setBusyId(null);
  };

  const pendingCount = tab === 'pending' ? items.length : 0;

  return (
    <div className="mx-auto w-full max-w-[1240px] flex flex-col gap-6 pb-10">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageTitle title={t('nav.inbox')} subtitle={t('inbox.subtitle')} />
        {pendingCount > 0 && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-gold-bg px-3 py-1 font-body text-body-sm font-medium text-gold-ink">
            <span className="h-1.5 w-1.5 rounded-full bg-gold" aria-hidden />
            {t('inbox.pendingCount', { count: pendingCount })}
          </span>
        )}
      </div>

      <div className="flex gap-1 border-b border-line" role="tablist">
        <button
          role="tab"
          aria-selected={tab === 'pending'}
          className={tabClasses(tab === 'pending')}
          onClick={() => switchTab('pending')}
        >
          {t('inbox.waiting')}
        </button>
        <button
          role="tab"
          aria-selected={tab === 'resolved'}
          className={tabClasses(tab === 'resolved')}
          onClick={() => switchTab('resolved')}
        >
          {t('inbox.handled')}
        </button>
      </div>

      {error && (
        <div
          className="flex items-start gap-2 rounded-lg border border-[#EDB8B0] bg-vermilion-bg px-4 py-3 font-body text-body-md text-vermilion-ink"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span className="min-w-0">{error}</span>
        </div>
      )}

      {loading ? (
        <p className="font-body text-body-md text-ink-muted">{t('common.loading')}</p>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-line bg-paper px-6 py-16 text-center">
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-inset text-ink-muted">
            <InboxIcon className="h-6 w-6" strokeWidth={1.5} aria-hidden />
          </span>
          <h3 className="font-display text-[22px] font-medium text-ink">{t('inbox.allCaughtUp')}</h3>
          <p className="mt-1 max-w-md font-body text-body-md text-ink-light">{t('inbox.nothingWaiting')}</p>
        </div>
      ) : (
        <AnimatePresence mode="wait">
          <motion.div
            key={tab}
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="flex flex-col gap-7"
          >
            {Object.entries(grouped).map(([name, rows]) => (
              <section key={name} className="flex flex-col gap-3">
                <h2 className="font-display text-[20px] font-medium text-ink">
                  {name}
                  <span className="ml-2 font-body text-body-md font-normal text-ink-muted">{rows.length}</span>
                </h2>
                <div className="divide-y divide-line rounded-xl border border-line bg-paper">
                  {rows.map((item) => {
                    const frozen = isFrozen(item.project_id);
                    const age = relativeTime(item.created_at, t);
                    return (
                      // A grid rather than nested flex rows: the icon keeps its column, the
                      // actions sit to the right from lg, and on a phone the actions and the
                      // escalation well take the card's full width instead of the narrow
                      // column beside the icon.
                      <article
                        key={item.id}
                        className="grid grid-cols-[auto_minmax(0,1fr)] lg:grid-cols-[auto_minmax(0,1fr)_auto] gap-x-3 sm:gap-x-4 gap-y-3 px-4 py-4 sm:px-5"
                      >
                        <span
                          className={cn(
                            'flex h-9 w-9 sm:h-10 sm:w-10 shrink-0 items-center justify-center rounded-full',
                            kindTint(item)
                          )}
                          aria-hidden
                        >
                          {KIND_ICONS[item.kind] ?? <FileQuestion className="w-[18px] h-[18px]" />}
                        </span>

                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span
                              className={cn(
                                'font-body text-body-sm font-medium',
                                item.status !== 'pending'
                                  ? 'text-ink-light'
                                  : item.kind === 'escalation'
                                    ? 'text-vermilion-ink'
                                    : 'text-gold-ink'
                              )}
                            >
                              {t(`inbox.kind.${item.kind}`, { defaultValue: item.kind })}
                            </span>
                            {/* How many times it has been chased only matters while it still waits. */}
                            {item.status === 'pending' && item.reminder_tier > 0 && (
                              <StatusChip
                                status="checking"
                                showDot={false}
                                label={t('inbox.reminderTier', { tier: item.reminder_tier })}
                              />
                            )}
                            {item.status === 'resolved' && (
                              <StatusChip status="done" label={t('inbox.handled')} />
                            )}
                            {(item.status === 'void' || frozen) && (
                              <span
                                className="inline-flex items-center rounded-full bg-ash-bg px-2 py-0.5 font-body text-body-xs font-medium text-ink-light"
                                data-testid="inbox-closed-badge"
                              >
                                {t('inbox.closedProject')}
                              </span>
                            )}
                          </div>
                          <h3 className="mt-1 font-body text-[15px] font-medium leading-snug text-ink break-words">
                            {item.title}
                          </h3>
                          {item.body && (
                            <p className="mt-1 font-body text-body-md text-ink-light whitespace-pre-line break-words">
                              {item.body}
                            </p>
                          )}
                          <p className="mt-1.5 font-body text-body-sm text-ink-muted">
                            {[name, age].filter(Boolean).join(' · ')}
                          </p>
                        </div>

                        {(item.task_id || (tab === 'pending' && item.kind === 'output_acceptance')) && (
                          <div className="col-span-2 sm:col-span-1 sm:col-start-2 lg:col-start-3 lg:row-start-1 flex flex-wrap items-center gap-2 lg:justify-end lg:self-start">
                            {item.task_id && (
                              <button
                                onClick={() => navigate(wsHref(workspaceId, `/tasks/${item.task_id}`))}
                                className={
                                  tab === 'pending' && item.kind === 'output_acceptance'
                                    ? cn(buttonBase, 'text-ink-light hover:text-ink hover:bg-inset')
                                    : actionButton
                                }
                              >
                                <ExternalLink className="w-4 h-4" aria-hidden /> {t('inbox.open')}
                              </button>
                            )}
                            {tab === 'pending' && item.kind === 'output_acceptance' && (
                              <>
                                <button
                                  disabled={busyId === item.id || frozen}
                                  onClick={() => void sign(item, false)}
                                  className={actionButton}
                                >
                                  <ThumbsDown className="w-4 h-4" aria-hidden /> {t('inbox.sendBack')}
                                </button>
                                <button
                                  disabled={busyId === item.id || frozen}
                                  onClick={() => void sign(item, true)}
                                  className={primaryButton}
                                >
                                  <CheckCircle2 className="w-4 h-4" aria-hidden /> {t('inbox.accept')}
                                </button>
                              </>
                            )}
                          </div>
                        )}

                        {/* The record of what was already tried (FR-061). Without it an
                            escalation asks the patron to go and reconstruct the history
                            before they can answer — and that is the difference between
                            a decision made today and one made next week. */}
                        {item.kind === 'escalation' && (
                          <div className="col-span-2 sm:col-span-1 sm:col-start-2 lg:col-span-2 lg:col-start-2 -mt-3 min-w-0">
                            <AttemptDossier item={item} />
                            {tab === 'pending' && item.task_id && (
                              <EscalationActions
                                item={item}
                                busy={busyId === item.id}
                                frozen={frozen}
                                setBusy={setBusyId}
                                onError={setError}
                                onDone={reload}
                              />
                            )}
                          </div>
                        )}
                      </article>
                    );
                  })}
                </div>
              </section>
            ))}
          </motion.div>
        </AnimatePresence>
      )}
    </div>
  );
}
