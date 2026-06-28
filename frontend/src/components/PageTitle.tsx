import { cn } from '@/lib/utils';

interface PageTitleProps {
  /** Full heading text — the first character becomes the illuminated initial. */
  title: string;
  subtitle?: string;
  /** Extra classes for the <h1>. */
  className?: string;
  subtitleClassName?: string;
}

/**
 * Page heading with an illuminated (gilt) first letter — the Scriptorium
 * signature initial rendered *inline*, so the letter is never duplicated.
 *
 *   "Projects" → gilt P + "rojects"
 *
 * Replaces the old `<DropCap text="P" /> + <h1>Projects</h1>` pattern, which
 * printed the first letter twice (a standalone 3.5em letter beside a full word).
 */
export default function PageTitle({
  title,
  subtitle,
  className,
  subtitleClassName,
}: PageTitleProps) {
  const first = title.charAt(0);
  const rest = title.slice(1);

  return (
    <div>
      <h1 className={cn('font-display text-[56px] text-ink leading-[1.05] tracking-tight', className)}>
        <span className="title-initial">{first}</span>
        {rest}
      </h1>
      {subtitle && (
        <p className={cn('mt-1 font-body text-body-sm text-ink-light', subtitleClassName)}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
