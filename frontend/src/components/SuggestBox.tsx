// A list to pick from that also takes something typed (spec 003 FR-129; FR-007k).
//
// It replaces an `<input list>` with a `<datalist>`, and the reason is one the owner hit on the
// first try: the browser filters a datalist by whatever is already in the box, so once *sonnet*
// was picked, *sonnet* was the only thing left to pick, and choosing again meant clearing the box
// first. Here the search starts empty every time the list opens, so the whole list is always one
// click away, and typing narrows it only while the person is typing.
//
// What was typed can still be used as it is — a tool that lists models still runs one it did not
// list — and blank stays a real choice: it means the tool's own default.

import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import * as Popover from '@radix-ui/react-popover'
import { Command } from 'cmdk'
import { Check, ChevronDown } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface Suggestion {
  value: string
  /** A readable name. The value is shown beside it when the two differ. */
  label?: string
}

export default function SuggestBox({
  value,
  onChange,
  suggestions,
  blankLabel,
  id,
  ariaLabel,
  disabled,
}: {
  value: string
  onChange: (value: string) => void
  suggestions: Suggestion[]
  /** What blank means here, shown as the first choice and in the closed box when blank. */
  blankLabel: string
  id?: string
  ariaLabel?: string
  disabled?: boolean
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const typed = search.trim()
  const current = suggestions.find((one) => one.value === value)

  function pick(next: string) {
    onChange(next)
    setOpen(false)
  }

  function row(label: ReactNode, raw: string | undefined, on: boolean) {
    return (
      <>
        <span className="min-w-0 flex-1">
          <span className="block truncate">{label}</span>
          {raw && <span className="block truncate font-mono text-[11px] text-[#6B5E4E]">{raw}</span>}
        </span>
        {on && <Check className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />}
      </>
    )
  }

  const itemCls = cn(
    'flex cursor-pointer select-none items-start gap-2 rounded-sm px-2.5 py-1.5 text-[13px] text-[#2A2318] outline-none',
    'data-[selected=true]:bg-[#EDE4CE]',
  )

  return (
    <Popover.Root
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        // Every opening starts from the whole list — the point of this control.
        if (next) setSearch('')
      }}
    >
      <Popover.Trigger asChild disabled={disabled}>
        <button
          type="button"
          id={id}
          aria-label={ariaLabel}
          aria-haspopup="listbox"
          className={cn(
            'flex w-full items-center justify-between gap-2 rounded-md border border-[#E3D7BC] bg-[#F7F0E0] px-4 py-2.5 text-left text-[15px] text-[#2A2318]',
            'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15 transition-all',
            'disabled:cursor-not-allowed disabled:opacity-60',
          )}
        >
          <span className={cn('min-w-0 flex-1 truncate', !value && 'text-[#A89880]')}>
            {value ? (current?.label ?? value) : blankLabel}
            {value && current?.label && current.label !== value && (
              <span className="ml-2 font-mono text-[12px] text-[#6B5E4E]">{value}</span>
            )}
          </span>
          <ChevronDown className="h-4 w-4 shrink-0 text-[#A89880]" aria-hidden />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          sideOffset={4}
          align="start"
          className="z-tooltip w-[var(--radix-popover-trigger-width)] rounded-md border border-[#E3D7BC] bg-[#F7F0E0] shadow-lg"
        >
          <Command loop>
            <Command.Input
              value={search}
              onValueChange={setSearch}
              placeholder={t('choice.searchOrType')}
              className="w-full border-b border-[#E3D7BC] bg-transparent px-3 py-2 text-[13px] text-[#2A2318] placeholder:text-[#A89880] focus:outline-none"
            />
            <Command.List className="max-h-72 overflow-y-auto p-1">
              {!typed && (
                <Command.Item value={`__blank__ ${blankLabel}`} onSelect={() => pick('')} className={itemCls}>
                  {row(blankLabel, undefined, value === '')}
                </Command.Item>
              )}
              {suggestions.map((one) => (
                <Command.Item
                  key={one.value}
                  value={`${one.label ?? ''} ${one.value}`}
                  onSelect={() => pick(one.value)}
                  className={itemCls}
                >
                  {row(one.label ?? one.value, one.label && one.label !== one.value ? one.value : undefined, one.value === value)}
                </Command.Item>
              ))}
              {typed && !suggestions.some((one) => one.value === typed) && (
                <Command.Item forceMount value={`__typed__ ${typed}`} onSelect={() => pick(typed)} className={itemCls}>
                  {row(t('choice.useTyped', { value: typed }), undefined, false)}
                </Command.Item>
              )}
            </Command.List>
          </Command>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
