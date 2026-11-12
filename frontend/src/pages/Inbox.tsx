/**
 * The patron's inbox — read straight from the server (spec 001 §11, FR-035, FR-065).
 *
 * This page used to filter the task list in the browser and call that an inbox: it showed
 * every task *awaiting review* by anyone, including ones nobody had asked the patron about.
 * A real inbox is the other way round — the server places here exactly the decisions that
 * **belong to this person**, and each letter disappears when the action it waits for has
 * happened, not when someone dismisses it.
 *
 * The reminder tier (FR-065) shows on the letter itself: one chased three times has to look
 * different from one that just arrived, or "reminders back off" is only the server's business
 * and the patron sees nothing.
 *
 * Layout (Đài quan sát): on a wide screen, letters grouped by project on the left and the open
 * letter's detail — with every answer the patron can give — on the right. On anything
 * narrower the list comes first and opening a letter turns the page to its detail, with a way
 * back; the selection lives in `?item=` so the browser's back button does the same.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useSearchParams } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, ArrowLeft, ArrowRight, CheckCircle2, Mailbox } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import PageTitle from '@/components/PageTitle';
import InboxDetail from '@/components/inbox/InboxDetail';
import { kindIcon, kindTone, relativeTime } from '@/components/inbox/inbox-utils';
import { getInbox, type InboxItemDTO } from '@/lib/api';
import { lettersOf } from '@/lib/workspaceScope';
import { errorText } from '@/lib/errors';
import { useViewport } from '@/hooks/use-viewport';
import { cn } from '@/lib/utils';
import { useAppStore, type Project } from '@/store/appStore';
import { notifyLoadFailed } from '@/lib/notify';

interface Group {
  id: string;
  project?: Project;
  name: string;
  rows: InboxItemDTO[];
}

const tabClasses = (active: boolean) =>
  cn(
    '-mb-px inline-flex min-h-[44px] items-center gap-2 border-b-2 px-3 sm:px-4 font-body text-body-md font-medium transition-colors cursor-pointer',
    active
      ? 'border-sapphire text-ink-strong'
      : 'border-transparent text-ink-light hover:text-ink-strong hover:border-line-strong'
  );

export default function Inbox() {
  const projects = useAppStore((s) => s.projects);
  const tasks = useAppStore((s) => s.tasks);
  const hydrateProject = useAppStore((s) => s.hydrateProject);
  // Kept true by the one inbox stream under Layout; a change is the signal to re-read.
  const inboxSignal = useAppStore((s) => s.inboxPending);
  const { workspaceId } = useParams();
  const { t } = useTranslation();
  const viewport = useViewport();
  const split = viewport === 'desktop';
  const [params, setParams] = useSearchParams();
  const selectedParam = params.get('item');

  const [items, setItems] = useState<InboxItemDTO[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [tab, setTab] = useState<'pending' | 'resolved'>('pending');
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Loaded in an effect, but every state write happens after the promise settles — writing
  // state in the effect body would cost an extra render. `alive` stops a late reply from
  // overwriting the tab the user has just switched to.
  const [reloadKey, setReloadKey] = useState(0);
  const reload = useCallback(() => setReloadKey((n) => n + 1), []);

  useEffect(() => {
    let alive = true;
    // The second tab means *no longer waiting*, which includes letters voided when their
    // project closed — nobody answered those, so the server does not file them under
    // resolved. One call for everything, filtered here, rather than two for one list.
    getInbox({ status: tab === 'pending' ? 'pending' : 'all' })
      .then((everyone) => {
        if (!alive) return;
        const rows = lettersOf(everyone, workspaceId);
        setItems(tab === 'pending' ? rows : rows.filter((r) => r.status !== 'pending'));
        setPendingCount(rows.filter((r) => r.status === 'pending').length);
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
  }, [tab, reloadKey, inboxSignal, t, workspaceId]);

  // Task codes ("ACME-12") live with each project's tasks, which the workspace slice does not
  // carry. Load each project a letter points at, once per visit.
  const hydrated = useRef(new Set<string>());
  useEffect(() => {
    for (const item of items) {
      const id = item.project_id;
      if (!id || hydrated.current.has(id)) continue;
      hydrated.current.add(id);
      void hydrateProject(id).catch(notifyLoadFailed);
    }
  }, [items, hydrateProject]);

  // Whoever opens a letter on a narrow screen pushed a history entry; going back pops it
  // rather than stacking another one.
  const pushedSelection = useRef(false);
  const select = (id: string) => {
    pushedSelection.current = !split;
    setParams({ item: id }, { replace: split });
  };
  const backToList = () => {
    if (pushedSelection.current) {
      pushedSelection.current = false;
      window.history.back();
    } else {
      setParams({}, { replace: true });
    }
  };

  const switchTab = (next: 'pending' | 'resolved') => {
    if (next === tab) return;
    setLoading(true);
    setTab(next);
    if (selectedParam) setParams({}, { replace: true });
  };

  const projectOf = useCallback(
    (id?: string | null) => (projects || []).find((p) => p.id === id),
    [projects],
  );
  const projectName = useCallback(
    (id?: string | null) => projectOf(id)?.name ?? t('inbox.unknownProject'),
    [projectOf, t],
  );
  const taskCode = (id?: string | null) => (id ? tasks.find((tk) => tk.id === id)?.identifier : undefined);

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
  const isFrozen = (id?: string | null) => projectOf(id)?.status === 'closed';

  const groups = useMemo(() => {
    const acc = new Map<string, Group>();
    for (const item of items) {
      const key = item.project_id ?? '';
      let group = acc.get(key);
      if (!group) {
        group = { id: key, project: projectOf(item.project_id), name: projectName(item.project_id), rows: [] };
        acc.set(key, group);
      }
      group.rows.push(item);
    }
    return [...acc.values()];
  }, [items, projectOf, projectName]);

  // On a wide screen something is always open; on a narrow one only what the patron opened.
  const selected = items.find((i) => i.id === selectedParam) ?? (split ? items[0] : undefined);
  const showList = split || !selected;
  const showDetail = Boolean(selected);

  // A narrow screen turns the page to the letter: bring its top into view, wherever the
  // list had been scrolled to.
  const detailRef = useRef<HTMLDivElement>(null);
  const selectedId = selected?.id;
  useEffect(() => {
    if (!split && selectedId) detailRef.current?.scrollIntoView({ block: 'start' });
  }, [split, selectedId]);

  const list = (
    <nav aria-label={t('inbox.listLabel')} className="flex min-w-0 flex-col gap-6">
      {groups.map((group) => (
        <section key={group.id} className="flex min-w-0 flex-col gap-2">
          <h2 className="flex min-w-0 items-center gap-2 font-body text-body-sm font-medium text-ink-light">
            {group.project?.key && <span className="task-code shrink-0 text-[10px]">{group.project.key}</span>}
            <span className="min-w-0 truncate">{group.name}</span>
            <span className="ml-auto shrink-0 font-mono text-[11px] text-ink-muted">{group.rows.length}</span>
          </h2>
          {group.rows.map((item) => {
            const Icon = kindIcon(item.kind);
            const active = selected?.id === item.id;
            const code = item.task_id ? taskCode(item.task_id) : t('inbox.projectLevel');
            const frozen = isFrozen(item.project_id);
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => select(item.id)}
                aria-current={active ? 'true' : undefined}
                data-testid="inbox-item"
                className={cn(
                  'flex w-full min-w-0 items-center gap-3 rounded-md border bg-surface p-3.5 text-left transition-colors',
                  active && split
                    ? 'border-sapphire bg-surface-hover'
                    : 'border-line hover:border-sapphire/60 hover:bg-surface-hover'
                )}
              >
                <span
                  className={cn(
                    'grid h-10 w-10 shrink-0 place-items-center rounded-full border border-line bg-surface',
                    kindTone(item)
                  )}
                  aria-hidden
                >
                  <Icon className="h-[18px] w-[18px]" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-body text-body-xs text-ink-muted">
                    {t(`inbox.kind.${item.kind}`, { defaultValue: item.kind })} · {relativeTime(item.created_at, t)}
                    {item.status === 'pending' && item.reminder_tier > 0 && (
                      <span className="text-warning"> · {t('inbox.reminderTier', { tier: item.reminder_tier })}</span>
                    )}
                    {(item.status === 'void' || frozen) && <span> · {t('inbox.closedProject')}</span>}
                  </span>
                  <span className="my-0.5 block break-words font-display text-[17px] font-normal leading-snug text-ink-strong line-clamp-2">
                    {item.title}
                  </span>
                  {code && <span className="task-code block truncate text-[10px]">{code}</span>}
                </span>
                <ArrowRight className="h-[18px] w-[18px] shrink-0 text-ink-faint" aria-hidden />
              </button>
            );
          })}
        </section>
      ))}
    </nav>
  );

  return (
    <div className="mx-auto flex w-full max-w-[1280px] min-w-0 flex-col gap-6 pb-10">
      <PageTitle eyebrow={t('inbox.eyebrow')} title={t('nav.inbox')} subtitle={t('inbox.subtitle')} />

      <div className="flex gap-1 border-b border-line" role="tablist">
        <button role="tab" aria-selected={tab === 'pending'} className={tabClasses(tab === 'pending')} onClick={() => switchTab('pending')}>
          {t('inbox.waiting')}
          <span
            className={cn(
              'inline-grid min-w-[20px] place-items-center rounded-full px-1.5 font-mono text-[10px] leading-5',
              pendingCount > 0 ? 'bg-sapphire-soft text-sapphire-strong' : 'bg-canvas-deep text-ink-muted'
            )}
            aria-label={t('inbox.pendingCount', { count: pendingCount })}
          >
            {pendingCount}
          </span>
        </button>
        <button role="tab" aria-selected={tab === 'resolved'} className={tabClasses(tab === 'resolved')} onClick={() => switchTab('resolved')}>
          {t('inbox.handled')}
        </button>
      </div>

      {error && (
        <div
          className="flex items-start gap-2 rounded-md border border-danger/40 bg-danger-soft px-4 py-3 font-body text-body-md text-danger"
          role="alert"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <span className="min-w-0 break-words">{error}</span>
        </div>
      )}

      {loading ? (
        <p className="font-body text-body-md text-ink-muted">{t('common.loading')}</p>
      ) : items.length === 0 ? (
        <motion.div
          key={tab}
          initial={{ opacity: 0, scale: 0.98 }}
          animate={{ opacity: 1, scale: 1 }}
          className="mx-auto my-10 flex max-w-[650px] flex-col items-center px-2 text-center sm:my-16"
        >
          <span className="mb-5 grid h-[88px] w-[88px] place-items-center rounded-full border border-line text-sapphire">
            <Mailbox className="h-10 w-10" strokeWidth={1.25} aria-hidden />
          </span>
          <h2 className="font-display text-[26px] font-normal leading-tight tracking-[-0.02em] text-ink-strong sm:text-[30px]">
            {tab === 'pending' ? t('inbox.allCaughtUp') : t('inbox.emptyResolvedTitle')}
          </h2>
          <p className="mt-3 max-w-[520px] font-body text-body-md text-ink-light">
            {tab === 'pending' ? t('inbox.nothingWaiting') : t('inbox.emptyResolvedBody')}
          </p>
          {tab === 'pending' && <CheckCircle2 className="mt-5 h-6 w-6 text-success" aria-hidden />}
        </motion.div>
      ) : (
        <div
          className={cn(
            'min-w-0',
            split && 'grid grid-cols-[minmax(320px,0.9fr)_minmax(0,1.1fr)] items-start gap-7'
          )}
        >
          {showList && (
            <motion.div key={tab} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }} className="min-w-0">
              {list}
            </motion.div>
          )}
          {showDetail && selected && (
            <div ref={detailRef} className="min-w-0 scroll-mt-20">
              {!split && (
                <button type="button" onClick={backToList} className="btn-text mb-3" data-testid="inbox-back">
                  <ArrowLeft className="h-4 w-4" aria-hidden /> {t('inbox.backToList')}
                </button>
              )}
              <AnimatePresence mode="wait">
                <motion.div
                  key={selected.id}
                  initial={{ opacity: 0, x: 14 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.2 }}
                  className="min-w-0"
                >
                  <InboxDetail
                    item={selected}
                    project={projectOf(selected.project_id)}
                    projectName={projectName(selected.project_id)}
                    taskCode={taskCode(selected.task_id)}
                    workspaceId={workspaceId}
                    frozen={isFrozen(selected.project_id)}
                    busy={busyId === selected.id}
                    setBusy={setBusyId}
                    onError={setError}
                    onDone={reload}
                  />
                </motion.div>
              </AnimatePresence>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
