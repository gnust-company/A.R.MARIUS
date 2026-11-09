// The direct chat with one agent (FR-007p), as a drawer from the right edge of the window.
//
// Portalled to <body> so no page container can clip it, above the phone's bottom bar so the
// composer is never covered, and full width on a phone. Closed by Esc, the close button or a
// click on the backdrop; focus goes back to whatever opened it. The panel inside is mounted only
// while the drawer is open, so the page holds at most one chat stream.
import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { X } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import AgentAvatar from '@/components/AgentAvatar';
import StatusChip from '@/components/StatusChip';
import AgentChatPanel from './AgentChatPanel';

export default function AgentChatDrawer({
  open,
  onClose,
  workspaceId,
  mariusId,
  agentName,
  role,
  status,
  cli,
  online,
  offlineNote,
}: {
  open: boolean;
  onClose: () => void;
  workspaceId: string;
  mariusId: string;
  agentName: string;
  role?: string;
  status: string;
  /** The agent CLI it runs on, for the eyebrow; undefined when it has no runtime. */
  cli?: string;
  online: boolean;
  /** Why the agent cannot be reached, already worded. */
  offlineNote?: string;
}) {
  const { t } = useTranslation();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      opener?.focus?.();
    };
  }, [open, onClose]);

  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          key="agent-chat-drawer"
          className="fixed inset-0 z-modal"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
        >
          <div
            className="absolute inset-0 bg-scrim/45 backdrop-blur-[6px]"
            onMouseDown={onClose}
            aria-hidden
          />
          <motion.aside
            role="dialog"
            aria-modal="true"
            aria-labelledby="agent-chat-drawer-title"
            className="absolute inset-y-0 right-0 flex w-full flex-col border-l border-line bg-surface shadow-2xl sm:w-[min(520px,100%)] sm:rounded-l-xl"
            initial={{ x: '100%' }}
            animate={{ x: 0 }}
            exit={{ x: '100%' }}
            transition={{ duration: 0.28, ease: [0.22, 0.8, 0.3, 1] }}
          >
            <header className="flex shrink-0 items-start justify-between gap-4 border-b border-line px-5 pb-4 pt-[max(1.25rem,env(safe-area-inset-top))] sm:px-6">
              <div className="min-w-0">
                <p className="eyebrow">
                  {cli
                    ? t('agentDetail.chatDrawer.eyebrow', { cli })
                    : t('agentDetail.chatDrawer.eyebrowNoRuntime')}
                </p>
                <h2
                  id="agent-chat-drawer-title"
                  className="mt-1.5 truncate font-display text-[28px] font-normal leading-tight tracking-[-0.02em] text-ink-strong"
                >
                  {agentName}
                </h2>
              </div>
              <button
                ref={closeRef}
                type="button"
                onClick={onClose}
                aria-label={t('common.close')}
                className="grid h-11 w-11 shrink-0 place-items-center rounded-md border border-line text-ink-light transition-colors hover:bg-surface-hover hover:text-ink-strong"
              >
                <X className="h-5 w-5" aria-hidden />
              </button>
            </header>

            <div className="flex shrink-0 items-center gap-3 border-b border-line px-5 py-3.5 sm:px-6">
              <AgentAvatar name={agentName} status={status} />
              <div className="min-w-0">
                {role && <p className="truncate font-body text-[13px] font-semibold text-ink">{role}</p>}
                <div className={role ? 'mt-1' : undefined}>
                  <StatusChip status={status} label={t('directory.status.' + status)} />
                </div>
              </div>
            </div>

            <div className="min-h-0 flex-1">
              <AgentChatPanel
                workspaceId={workspaceId}
                mariusId={mariusId}
                agentName={agentName}
                online={online}
                offlineNote={offlineNote}
              />
            </div>
          </motion.aside>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
