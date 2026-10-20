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
    return <p className="text-[13px] text-[#A89880]">{t('runtimePicker.loading')}</p>
  }

  return (
    <div className="space-y-2">
      {ready.length === 0 && (
        <div className="rounded-md border border-dashed border-[#E3D7BC] px-3 py-2.5">
          <p className="text-[13px] text-[#2A2318]">{t('runtimePicker.noneReady')}</p>
          <p className="mt-0.5 text-[12px] text-[#6B5E4E]">{t('runtimePicker.noneReadyHint')}</p>
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
                  'flex w-full items-center gap-3 rounded-md border px-3 py-2.5 text-left transition-colors',
                  on
                    ? 'border-[#C25E3A] bg-[#F3D9D0]/40'
                    : 'border-[#E3D7BC] bg-vellum hover:border-[#C25E3A]/60',
                  disabled && 'opacity-60',
                )}
              >
                <span
                  className={cn(
                    'flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
                    on ? 'border-[#C25E3A] bg-[#C25E3A] text-white' : 'border-[#A89880]',
                  )}
                  aria-hidden
                >
                  {on && <Check className="h-3 w-3" />}
                </span>
                <span className="min-w-0">
                  <span className="block font-mono text-[13px] text-[#2A2318]">{one.cli_kind}</span>
                  <span className="flex items-center gap-1 text-[12px] text-[#6B5E4E]">
                    <Laptop className="h-3 w-3" aria-hidden />
                    {t('runtimePicker.onMachine', { machine: one.machine_name })}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}

      {unavailable.map((one) => (
        <div
          key={one.id}
          aria-disabled
          className="flex w-full items-start gap-3 rounded-md border border-[#E3D7BC] bg-[#EDE4CE]/50 px-3 py-2.5 opacity-80"
        >
          <span className="mt-0.5 h-4 w-4 shrink-0 rounded-full border border-[#D6CBB2]" aria-hidden />
          <span className="min-w-0">
            <span className="block font-mono text-[13px] text-[#6B5E4E]">{one.cliKind}</span>
            <span className="flex items-center gap-1 text-[12px] text-[#6B5E4E]">
              <Laptop className="h-3 w-3" aria-hidden />
              {t('runtimePicker.onMachine', { machine: one.machineName })}
            </span>
            <span className="mt-0.5 block text-[12px] text-[#8A3B22]">
              {t(`machines.notReady.${one.reason}`, {
                defaultValue: t('machines.notReady.unknown'),
              })}
            </span>
          </span>
        </div>
      ))}

      {ready.length > 1 && !chosen && (
        <p className="text-[12px] text-[#6B5E4E]">{t('runtimePicker.chooseOne')}</p>
      )}
      <p className="text-[11px] text-[#A89880]">{t('runtimePicker.forLife')}</p>
    </div>
  )
}
