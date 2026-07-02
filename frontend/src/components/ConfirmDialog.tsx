import { useState } from 'react';
import type { ReactNode } from 'react';
import { Loader2, AlertTriangle } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import Modal from './Modal';
import { cn } from '@/lib/utils';

interface ConfirmDialogProps {
  isOpen: boolean;
  onClose: () => void;
  /** May be async. If it rejects, the dialog stays open and shows the error (e.g. a
   * backend constraint like "Built-in skills can't be deleted."). */
  onConfirm: () => void | Promise<void>;
  title: string;
  message: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  /** Terracotta-red confirm button for destructive actions (default true). */
  danger?: boolean;
}

export default function ConfirmDialog({
  isOpen,
  onClose,
  onConfirm,
  title,
  message,
  confirmLabel,
  cancelLabel,
  danger = true,
}: ConfirmDialogProps) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
      setBusy(false);
      onClose();
    } catch (e) {
      setBusy(false);
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const handleClose = () => {
    if (busy) return;
    setError(null);
    onClose();
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={handleClose}
      title={<span className="dropcap">{title}</span>}
      maxWidth="max-w-md"
      footer={
        <>
          <button
            onClick={handleClose}
            disabled={busy}
            className="px-4 py-2 rounded-md font-body text-body-md font-medium bg-vellum-deep text-ink border border-vellum-dark hover:bg-vellum-dark transition-colors disabled:opacity-50"
          >
            {cancelLabel || t('common.cancel')}
          </button>
          <button
            onClick={handleConfirm}
            disabled={busy}
            className={cn(
              'inline-flex items-center gap-2 px-4 py-2 rounded-md font-body text-body-md font-medium transition-colors disabled:opacity-50',
              danger
                ? 'bg-[#C0492B] text-white hover:bg-[#D2664A]'
                : 'bg-terracotta text-white hover:bg-terracotta-light'
            )}
          >
            {busy && <Loader2 className="w-4 h-4 animate-spin" />}
            {confirmLabel || t('common.delete')}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <p className="font-body text-body-md text-ink-light">{message}</p>
        {error && (
          <div className="flex items-start gap-2 text-[13px] text-[#8A3B22] bg-[#F3D9D0] border border-[#E3C0B2] rounded-md px-3 py-2">
            <AlertTriangle className="w-4 h-4 flex-shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
      </div>
    </Modal>
  );
}
