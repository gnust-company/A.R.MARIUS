import type { CSSProperties } from 'react';
import { Toaster as Sonner } from 'sonner';
import { useTheme } from '@/hooks/use-theme';
import { useViewport } from '@/hooks/use-viewport';

/**
 * Where the app speaks up about something that happened off-screen (a read that failed).
 * Coloured from the theme tokens, so it follows the light/dark switch like every other surface.
 * On a phone it sits at the top: the bottom edge belongs to the navigation bar.
 */
export default function Toaster() {
  const [theme] = useTheme();
  const viewport = useViewport();
  return (
    <Sonner
      theme={theme}
      position={viewport === 'phone' ? 'top-center' : 'bottom-right'}
      closeButton
      style={
        {
          '--normal-bg': 'oklch(var(--surface-raised))',
          '--normal-text': 'oklch(var(--ink))',
          '--normal-border': 'oklch(var(--line-strong))',
          '--border-radius': '12px',
        } as CSSProperties
      }
      toastOptions={{
        classNames: {
          toast: 'font-body shadow-soft',
          title: 'text-body-sm font-semibold text-ink-strong',
          description: 'text-[13px] leading-snug text-ink-light',
          error: '[&_[data-icon]]:text-danger',
        },
      }}
    />
  );
}
