import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

interface PageTitleProps {
  title: string;
  subtitle?: ReactNode;
  /** Mono, wide-tracked line above the title ("CỬA QUYẾT ĐỊNH DUY NHẤT"). */
  eyebrow?: ReactNode;
  /** Buttons on the right, aligned to the bottom of the title block. Wraps under it on a phone. */
  actions?: ReactNode;
  /** Extra classes for the <h1>. */
  className?: string;
  subtitleClassName?: string;
  /** Kept for callers from the earlier design; the editorial title no longer gilds a letter. */
  illuminated?: boolean;
}

/**
 * Page header of the Đài quan sát design (DESIGN §3.2): an eyebrow in mono, a large Lora title
 * at regular weight, a muted description, and the page's actions bottom-aligned on the right.
 */
export default function PageTitle({ title, subtitle, eyebrow, actions, className, subtitleClassName }: PageTitleProps) {
  return (
    <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between md:gap-7">
      <div className="min-w-0 max-w-[760px]">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1
          className={cn(
            'font-display font-normal text-ink-strong leading-[1.06] tracking-[-0.035em] text-[34px] sm:text-[clamp(36px,3.1vw,48px)]',
            eyebrow && 'mt-2',
            className
          )}
        >
          {title}
        </h1>
        {subtitle && (
          <p className={cn('mt-2.5 max-w-[68ch] font-body text-[15px] leading-relaxed text-ink-light', subtitleClassName)}>
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2.5 md:shrink-0 md:justify-end">{actions}</div>}
    </div>
  );
}
