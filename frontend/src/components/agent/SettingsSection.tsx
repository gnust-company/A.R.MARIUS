// One numbered block of the agent's configuration: what the block is about on the left, its
// fields on the right. Stacks into one column on a phone.
import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export default function SettingsSection({
  index,
  title,
  hint,
  children,
  tone = 'default',
  className,
}: {
  /** Two-digit position in the list ("01"). */
  index: string;
  title: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  /** `danger` tints the number and border for the one irreversible block. */
  tone?: 'default' | 'danger';
  className?: string;
}) {
  return (
    <section
      className={cn(
        'grid grid-cols-1 gap-5 rounded-lg border bg-surface p-5 sm:p-7',
        'lg:grid-cols-[minmax(200px,0.62fr)_minmax(0,1.38fr)] lg:gap-8',
        tone === 'danger' ? 'border-danger/30' : 'border-line',
        className,
      )}
    >
      <header className="flex min-w-0 items-start gap-3.5">
        <span
          aria-hidden
          className={cn(
            'grid h-[34px] w-[34px] shrink-0 place-items-center rounded-full border font-mono text-[11px]',
            tone === 'danger' ? 'border-danger/40 text-danger' : 'border-line text-sapphire-strong',
          )}
        >
          {index}
        </span>
        <div className="min-w-0">
          <h2 className="font-display text-[22px] font-normal leading-tight tracking-[-0.02em] text-ink-strong">
            {title}
          </h2>
          {hint && <p className="mt-2 font-body text-[13px] leading-relaxed text-ink-light">{hint}</p>}
        </div>
      </header>
      <div className="grid min-w-0 content-start gap-4">{children}</div>
    </section>
  );
}
