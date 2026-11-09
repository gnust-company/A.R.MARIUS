// Where the workspace's host is going to work (spec 003 FR-122, FR-125).
//
// Every ready runtime is one row a person can pick, named by its CLI and its machine: the same
// CLI on two machines is otherwise two identical rows. Runtimes that cannot take work are on
// the list too, greyed out and with the machine's reason beside them, because a list that only
// shows what can be picked tells the person whose CLI is not logged in nothing at all.
//
// The picker holds no choice of its own. What is picked is the parent's, derived through
// `currentRuntimeChoice` on every render, so a runtime that goes away under the person cannot
// stay picked here.

import { useTranslation } from 'react-i18next'
import { Check, Laptop } from 'lucide-react'

import type { MachineDTO, WorkplaceChoiceDTO } from '@/lib/api'
import { unavailableRuntimes } from '@/lib/runtimeChoice'
import { cn } from '@/lib/utils'
import { WithCommands } from '@/components/EntryFrame';

export default function RuntimePicker({
  ready,
  machines,
  chosen,
  onChoose,
  loading = false,
  disabled = false,
}: {
  ready: WorkplaceChoiceDTO[]
  machines: MachineDTO[]
  chosen: string | null
  onChoose: (workplaceId: string) => void
  loading?: boolean
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const unavailable = unavailableRuntimes(machines, ready)

  if (loading && ready.length === 0 && unavailable.length === 0) {
    return <p className="font-body text-body-md text-ink-muted">{t('runtimePicker.loading')}</p>
  }

  return (
    <div className="space-y-2">
      {ready.length === 0 && (
        <div className="rounded-lg border border-dashed border-line-strong px-4 py-3">
          <p className="font-body text-body-md text-ink">{t('runtimePicker.noneReady')}</p>
          <p className="mt-0.5 font-body text-body-sm text-ink-light">
            <WithCommands text={t('runtimePicker.noneReadyHint')} />
          </p>
        </div>
      )}

      {ready.length > 0 && (
        <div role="radiogroup" aria-label={t('runtimePicker.label')} className="space-y-2">
          {ready.map((one) => {
            const on = one.id === chosen
            return (
              <button
                key={one.id}
                type="button"
                role="radio"
                aria-checked={on}
                disabled={disabled}
                onClick={() => onChoose(one.id)}
                className={cn(
                  'flex min-h-[44px] w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors',
                  on
                    ? 'border-ink bg-paper ring-1 ring-ink'
                    : 'border-line bg-paper hover:border-line-strong hover:bg-inset',
                  disabled && 'cursor-not-allowed opacity-60',
                )}
              >
                <span
                  className={cn(
                    'flex h-5 w-5 shrink-0 items-center justify-center rounded-full border-2',
                    on ? 'border-ink bg-ink text-paper' : 'border-line-strong bg-paper',
                  )}
                  aria-hidden
                >
                  {on && <Check className="h-3 w-3" strokeWidth={3} />}
                </span>
                <span className="min-w-0">
                  <span className="block truncate font-mono text-[13px] text-ink">{one.cli_kind}</span>
                  <span className="flex min-w-0 items-center gap-1.5 font-body text-body-sm text-ink-light">
                    <Laptop className="h-3.5 w-3.5 shrink-0" aria-hidden />
                    <span className="truncate">{t('runtimePicker.onMachine', { machine: one.machine_name })}</span>
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}

      {/* Shown, not hidden, so the person whose CLI is not ready learns why — in gold, the
          colour of *needs you*, because it is something they can go and fix. */}
      {unavailable.map((one) => (
        <div
          key={one.id}
          aria-disabled
          className="flex w-full items-start gap-3 rounded-lg border border-dashed border-line-strong bg-inset px-4 py-3"
        >
          <span className="mt-0.5 h-5 w-5 shrink-0 rounded-full border-2 border-line" aria-hidden />
          <span className="min-w-0">
            <span className="block truncate font-mono text-[13px] text-ink-light">{one.cliKind}</span>
            <span className="flex min-w-0 items-center gap-1.5 font-body text-body-sm text-ink-light">
              <Laptop className="h-3.5 w-3.5 shrink-0" aria-hidden />
              <span className="truncate">{t('runtimePicker.onMachine', { machine: one.machineName })}</span>
            </span>
            <span className="mt-1 block font-body text-body-sm text-gold-ink">
              {t(`machines.notReady.${one.reason}`, {
                defaultValue: t('machines.notReady.unknown'),
              })}
            </span>
          </span>
        </div>
      ))}

      {ready.length > 1 && !chosen && (
        <p className="font-body text-body-sm text-ink-light">{t('runtimePicker.chooseOne')}</p>
      )}
      <p className="font-body text-body-sm text-ink-muted">{t('runtimePicker.forLife')}</p>
    </div>
  )
}
