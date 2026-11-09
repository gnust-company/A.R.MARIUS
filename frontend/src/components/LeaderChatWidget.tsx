// Floating Leader-chat widget (#82) — a single bubble anchored bottom-right that
// opens a large chat panel. Rendered ONLY inside a project view (see ProjectBoard)
// so it never reads as a global "system chatbot". The panel is big-but-bounded
// (it fits the viewport with a margin and scrolls internally), so opening it does
// not grow the page or force a full-page scroll as the conversation lengthens.
//
// The bubble is the single entry point (the old in-tab "Chat with Leader" toggle
// and the VS Code-style side dock were removed in favour of this). The panel
// contents are LeaderChatPanel (assistant-ui powered).
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { motion, AnimatePresence } from 'framer-motion';
import { MessageSquare, X } from 'lucide-react';
import LeaderChatPanel from '@/components/LeaderChatPanel';
import { cn } from '@/lib/utils';

export default function LeaderChatWidget({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  return (
    // z-[150]: above the top bar (z-sticky, 50) and the navigation (z-sidebar, 100), so the
    // phone's full-screen panel covers both; below the overlays (z-overlay, 200) so a dialog
    // opened from the board still wins.
    <div className="fixed bottom-4 right-4 sm:bottom-5 sm:right-5 z-[150] flex flex-col items-end gap-3 pointer-events-none">
      <AnimatePresence>
        {open && (
          <motion.div
            key="leader-chat-panel"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 16 }}
            transition={{ duration: 0.2, ease: [0, 0, 0.2, 1] }}
            data-testid="leader-chat-panel"
            // A phone has no room for a floating window: there the panel is the whole screen
            // and carries its own close button. From sm up it floats above the bubble, sized
            // to the window with a margin so it never grows the page — and, from md, to the
            // part of the window the navigation leaves (the 68px rail, then the 240px sidebar),
            // so the navigation never sits on top of the panel's left edge.
            className={cn(
              'pointer-events-auto fixed inset-0 h-[100dvh] w-full overflow-hidden bg-paper',
              'sm:static sm:inset-auto sm:h-[min(840px,calc(100dvh-7rem))] sm:w-[min(880px,calc(100vw-2.5rem))]',
              'md:w-[min(880px,calc(100vw-68px-2.5rem))] xl:w-[min(880px,calc(100vw-240px-2.5rem))]',
              'sm:rounded-xl sm:border sm:border-line sm:shadow-gilt',
            )}
          >
            <LeaderChatPanel projectId={projectId} onClose={() => setOpen(false)} />
          </motion.div>
        )}
      </AnimatePresence>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        data-testid="leader-chat-fab"
        aria-label={t('leaderChat.title')}
        aria-expanded={open}
        title={t('leaderChat.title')}
        className={cn(
          'pointer-events-auto flex items-center justify-center w-14 h-14 rounded-full border transition-colors shadow-gilt',
          // On a phone the open panel covers the screen and has its own close; the bubble
          // would only sit on top of the composer.
          open
            ? 'hidden sm:flex bg-paper text-ink border-line-strong hover:bg-inset'
            : 'bg-ink text-paper border-ink hover:bg-ink/85',
        )}
      >
        {open ? <X className="w-6 h-6" aria-hidden /> : <MessageSquare className="w-6 h-6" aria-hidden />}
      </button>
    </div>
  );
}
