import { Moon, Sun } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useTheme, type Theme } from '@/hooks/use-theme';
import { cn } from '@/lib/utils';

/** Light / dark segmented switch (DESIGN §4). `compact` keeps the icons and drops the words. */
export default function ThemeSwitch({ compact, className }: { compact?: boolean; className?: string }) {
  const { t } = useTranslation();
  const [theme, setTheme] = useTheme();
  const options: { value: Theme; icon: typeof Sun; label: string; title: string }[] = [
    { value: 'light', icon: Sun, label: t('theme.light'), title: t('theme.lightTitle') },
    { value: 'dark', icon: Moon, label: t('theme.dark'), title: t('theme.darkTitle') },
  ];
  return (
    <div
      role="group"
      aria-label={t('theme.label')}
      className={cn('flex p-[3px] border border-line-strong rounded-[9px] bg-surface', className)}
    >
      {options.map(({ value, icon: Icon, label, title }) => {
        const active = theme === value;
        return (
          <button
            key={value}
            type="button"
            onClick={() => setTheme(value)}
            aria-pressed={active}
            aria-label={compact ? label : undefined}
            title={title}
            className={cn(
              'flex items-center gap-1.5 min-h-[34px] px-2.5 rounded-[6px] text-[12px] transition-colors',
              active ? 'bg-sapphire-soft text-ink-strong' : 'text-ink-light hover:text-ink-strong'
            )}
          >
            <Icon className="w-[17px] h-[17px]" strokeWidth={1.6} />
            {!compact && <span>{label}</span>}
          </button>
        );
      })}
    </div>
  );
}
