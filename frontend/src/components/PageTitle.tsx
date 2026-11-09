import { cn } from '@/lib/utils';

interface PageTitleProps {
  /** Full heading text — the first character becomes the illuminated initial. */
  title: string;
  subtitle?: string;
  /** Extra classes for the <h1>. */
  className?: string;
  subtitleClassName?: string;
  /** Gild the first letter. Kept for the one page that opens the workspace (Home); every
   *  other page uses a plain heading so the initial stays a signature, not wallpaper. */
  illuminated?: boolean;
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
  illuminated = false,
}: PageTitleProps) {
  const first = title.charAt(0);
  const rest = title.slice(1);

  return (
    <div>
      <h1
        className={cn(
          'font-display font-medium text-ink leading-[1.1] tracking-tight',
          illuminated ? 'text-[44px]' : 'text-[30px]',
          className
        )}
      >
        {illuminated ? (
          <>
            <span className="title-initial">{first}</span>
            {rest}
          </>
        ) : (
          title
        )}
      </h1>
      {subtitle && (
        <p className={cn('mt-1.5 font-body text-body-md text-ink-light', subtitleClassName)}>
          {subtitle}
        </p>
      )}
    </div>
  );
}
