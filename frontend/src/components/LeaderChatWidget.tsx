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
    <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-3 pointer-events-none">
      <AnimatePresence>
        {open && (
          <motion.div
            key="leader-chat-panel"
            initial={{ opacity: 0, y: 24, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 24, scale: 0.96 }}
            transition={{ duration: 0.22, ease: [0, 0, 0.2, 1] }}
            data-testid="leader-chat-panel"
            className="pointer-events-auto w-[min(880px,calc(100vw-2.5rem))] h-[min(840px,calc(100vh-7rem))] rounded-2xl shadow-2xl overflow-hidden border border-vellum-dark bg-vellum"
          >
            <LeaderChatPanel projectId={projectId} onClose={() => setOpen(false)} />
          </motion.div>
        )}
      </AnimatePresence>
      <motion.button
        type="button"
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.95 }}
        onClick={() => setOpen((o) => !o)}
        data-testid="leader-chat-fab"
        aria-label={t('leaderChat.title')}
        title={t('leaderChat.title')}
        className={cn(
          'pointer-events-auto flex items-center justify-center w-14 h-14 rounded-full shadow-xl border-2 transition-colors',
          open
            ? 'bg-vellum-deep text-ink border-vellum-dark'
            : 'bg-terracotta text-white border-terracotta-dark hover:bg-terracotta-dark',
        )}
      >
        {open ? <X className="w-6 h-6" /> : <MessageSquare className="w-6 h-6" />}
      </motion.button>
    </div>
  );
}
