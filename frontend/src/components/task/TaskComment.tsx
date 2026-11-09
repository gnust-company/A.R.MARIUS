import { motion } from 'framer-motion';
import { useTranslation } from 'react-i18next';
import AgentAvatar from '@/components/AgentAvatar';
import { cn } from '@/lib/utils';
import { relativeTime } from './format';
import { useAppStore } from '@/store/appStore';

/** The patron's mark: a ringed "P", the same shape an agent's avatar has. */
export function PatronMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        'inline-grid place-items-center shrink-0 w-8 h-8 rounded-full border border-line-strong bg-surface-raised font-display text-[15px] text-sapphire-strong',
        className
      )}
    >
      P
    </span>
  );
}

/** Highlight @mentions so a reader sees who a line was addressed to. */
function withMentions(text: string) {
  return text.split(/(@\w+)/g).map((part, i) =>
    part.startsWith('@') ? (
      <span key={i} className="rounded-sm bg-sapphire-soft px-1 font-medium text-sapphire-strong">
        {part}
      </span>
    ) : (
      part
    )
  );
}

/** One line of the task thread: the patron on the right in sapphire, an agent on the left. */
export default function TaskComment({
  authorName,
  authorId,
  authorRole,
  content,
  timestamp,
}: {
  authorName: string;
  authorId: string;
  authorRole: string;
  content: string;
  timestamp: string;
}) {
  const { t } = useTranslation();
  const mariuses = useAppStore((s) => s.mariuses);
  const currentUser = useAppStore((s) => s.currentUser);
  const agent = mariuses.find((m) => m.id === authorId);
  const isPatron = authorId === 'user-patron' || authorId === currentUser?.id;
  const isSystem = authorId.startsWith('system');

  // Nobody said a system line, so it is drawn as a quiet rule rather than a speaker.
  if (isSystem) {
    return (
      <div className="my-4 flex items-center justify-center gap-3">
        <span className="h-px w-10 bg-line" />
        <span className="text-center font-body text-body-xs font-normal italic text-ink-muted">{content}</span>
        <span className="h-px w-10 bg-line" />
      </div>
    );
  }

  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      className={cn('my-4 flex items-start gap-2 sm:my-5 sm:gap-3', isPatron && 'flex-row-reverse')}
    >
      {isPatron ? (
        <PatronMark />
      ) : (
        <AgentAvatar name={agent ? agent.displayName || agent.name : authorName} status={agent?.status} size="sm" />
      )}

      <div
        className={cn(
          'min-w-0 flex-1 border px-3 py-3 sm:px-4 sm:py-3.5',
          isPatron
            ? 'rounded-[13px] rounded-tr-[4px] border-sapphire/30 bg-sapphire-soft'
            : 'rounded-[13px] rounded-tl-[4px] border-line bg-field'
        )}
      >
        <header className="flex items-start justify-between gap-3 sm:items-center">
          <div className="flex min-w-0 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-2">
            <strong className="font-body text-[12px] font-semibold text-ink-strong">{authorName}</strong>
            <small className="truncate font-body text-[10px] text-ink-muted">
              {isPatron ? t('nav.patronRole') : authorRole}
            </small>
          </div>
          <time
            dateTime={timestamp}
            title={new Date(timestamp).toLocaleString()}
            className="whitespace-nowrap font-body text-[10px] text-ink-muted"
          >
            {relativeTime(timestamp, t)}
          </time>
        </header>
        <p className="mt-2 whitespace-pre-wrap break-words font-body text-[13px] leading-[1.7] text-ink sm:text-[14px]">
          {withMentions(content)}
        </p>
      </div>
    </motion.article>
  );
}
