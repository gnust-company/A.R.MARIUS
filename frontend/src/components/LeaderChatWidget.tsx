// Floating Leader-chat widget (#82) — a single bubble anchored bottom-right that
// opens a large chat panel. Rendered ONLY inside a project view (see ProjectHeader)
// so it never reads as a global "system chatbot". The panel is big-but-bounded
// (it fits the viewport with a margin and scrolls internally), so opening it does
// not grow the page or force a full-page scroll as the conversation lengthens.
//
// The bubble stays the always-there entry point; the project header's "Chat with the
// Leader" button opens the same panel, so `open` can be controlled from outside. The
// panel contents are LeaderChatPanel (assistant-ui powered).
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageCircle, X } from 'lucide-react';
import LeaderChatPanel from '@/components/LeaderChatPanel';
import { cn } from '@/lib/utils';

export default function LeaderChatWidget({
  projectId,
  open: controlledOpen,
  onOpenChange,
}: {
  projectId: string;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const { t } = useTranslation();
  const [ownOpen, setOwnOpen] = useState(false);
  const open = controlledOpen ?? ownOpen;
  const setOpen = (next: boolean) => {
    setOwnOpen(next);
    onOpenChange?.(next);
  };

  return (
    // z-[150]: above the top bar (z-sticky, 50) and the navigation (z-sidebar, 100); below the
    // overlays (z-overlay, 200) so a dialog opened from the board still wins.
    //
    // On a phone the bottom navigation bar (64px + the home-indicator inset) owns the bottom of
    // the screen, so the bubble sits above it rather than on top of it.
    <div className="fixed right-4 bottom-[calc(64px+1rem+env(safe-area-inset-bottom))] md:bottom-5 md:right-5 z-[150] flex flex-col items-end gap-3 pointer-events-none">
      <AnimatePresence>
        {open && (
          <motion.div
            key="leader-chat-panel"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 16 }}
            transition={{ duration: 0.2, ease: [0, 0, 0.2, 1] }}
            data-testid="leader-chat-panel"
            // A phone has no room for a floating window: there the panel fills the screen down to
            // the top of the bottom navigation (never over it) and carries its own close button.
            // From md up it floats above the bubble, sized to the window with a margin so it never
            // grows the page — and to the part of the window the navigation leaves (the 68px rail,
            // then the 240px sidebar), so the navigation never sits on the panel's left edge.
            className={cn(
              'pointer-events-auto fixed inset-x-0 top-0 bottom-[calc(64px+env(safe-area-inset-bottom))] overflow-hidden bg-surface border-b border-line',
              'md:static md:inset-auto md:h-[min(840px,calc(100dvh-7rem))] md:w-[min(560px,calc(100vw-68px-2.5rem))]',
              'xl:w-[min(620px,calc(100vw-240px-2.5rem))]',
              'md:rounded-lg md:border md:border-line md:shadow-gilt',
            )}
          >
            <LeaderChatPanel projectId={projectId} onClose={() => setOpen(false)} />
          </motion.div>
        )}
      </AnimatePresence>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        data-testid="leader-chat-fab"
        aria-label={t('leaderChat.title')}
        aria-expanded={open}
        title={t('leaderChat.title')}
        className={cn(
          'pointer-events-auto grid place-items-center w-14 h-14 rounded-full border transition-[background-color,border-color,transform] shadow-gilt active:scale-95',
          // On a phone the open panel has its own close; the bubble would only sit on its composer.
          open
            ? 'hidden md:grid bg-surface text-ink border-line-strong hover:bg-surface-hover'
            : 'bg-sapphire-strong text-sapphire-ink border-sapphire-strong hover:bg-sapphire',
        )}
      >
        {open ? <X className="w-6 h-6" aria-hidden /> : <MessageCircle className="w-6 h-6" aria-hidden />}
      </button>
    </div>
  );
}
