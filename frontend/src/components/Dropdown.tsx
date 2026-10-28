// The one pick-one-of-these control, in the product's own look (spec 003 FR-129).
//
// Every such control used to be the browser's own `<select>`: a grey system list dropped into
// a parchment page, different on every operating system, and impossible to style past its
// closed state. This wraps Radix Select, which the project already carries, so the open list is
// ours too — and it is still a real listbox for the keyboard and for screen readers.
//
// One thing Radix will not do is take an empty string as an item's value, and an empty value is
// a real choice all over this product (*no assignee*, *the tool's own default*). It is swapped
// for a private key on the way in and back on the way out, so callers keep saying ''.

import type { ReactNode } from 'react'
import * as Select from '@radix-ui/react-select'
import { Check, ChevronDown } from 'lucide-react'

import { cn } from '@/lib/utils'

const EMPTY = '__armarius_empty__'

export interface DropdownItem {
  value: string
  label: ReactNode
  /** Plain text for type-ahead when the label is not a string. */
  text?: string
  disabled?: boolean
  /** Why it cannot be picked, or anything else worth a second line. */
  hint?: string
}

const SIZES = {
  md: 'px-4 py-2.5 text-[15px]',
  sm: 'px-3 py-2 text-[13px]',
  xs: 'px-2.5 py-1.5 text-xs',
} as const

export default function Dropdown({
  value,
  onChange,
  items,
  placeholder,
  id,
  ariaLabel,
  disabled,
  size = 'md',
  className,
  testId,
}: {
  value: string
  onChange: (value: string) => void
  items: DropdownItem[]
  placeholder?: string
  id?: string
  ariaLabel?: string
  disabled?: boolean
  size?: keyof typeof SIZES
  /** Extra classes for the closed control, to sit in each form's own spacing. */
  className?: string
  testId?: string
}) {
  const toRadix = (v: string) => (v === '' ? EMPTY : v)
  const offersEmpty = items.some((item) => item.value === '')
  // Radix shows the placeholder for '' — the right thing when blank is not one of the items.
  const shown = value === '' && !offersEmpty ? '' : toRadix(value)

  return (
    <Select.Root
      value={shown}
      onValueChange={(picked) => onChange(picked === EMPTY ? '' : picked)}
      disabled={disabled}
    >
      <Select.Trigger
        id={id}
        aria-label={ariaLabel}
        data-testid={testId}
        className={cn(
          'flex w-full items-center justify-between gap-2 rounded-md border border-[#E3D7BC] bg-[#F7F0E0] text-left text-[#2A2318]',
          'focus:outline-none focus:border-[#C25E3A] focus:ring-[3px] focus:ring-[#C25E3A]/15 transition-all',
          'data-[placeholder]:text-[#A89880] disabled:cursor-not-allowed disabled:opacity-60',
          SIZES[size],
          className,
        )}
      >
        <span className="min-w-0 flex-1 truncate">
          <Select.Value placeholder={placeholder} />
        </span>
        <Select.Icon asChild>
          <ChevronDown className="h-4 w-4 shrink-0 text-[#A89880]" aria-hidden />
        </Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content
          position="popper"
          sideOffset={4}
          className={cn(
            'z-tooltip min-w-[var(--radix-select-trigger-width)] max-h-[min(var(--radix-select-content-available-height),20rem)]',
            'overflow-hidden rounded-md border border-[#E3D7BC] bg-[#F7F0E0] shadow-lg',
          )}
        >
          <Select.Viewport className="p-1">
            {items.map((item) => (
              <Select.Item
                key={toRadix(item.value)}
                value={toRadix(item.value)}
                disabled={item.disabled}
                textValue={item.text ?? (typeof item.label === 'string' ? item.label : undefined)}
                className={cn(
                  'relative flex cursor-pointer select-none items-start gap-2 rounded-sm py-1.5 pl-2.5 pr-8 text-[13px] text-[#2A2318] outline-none',
                  'data-[highlighted]:bg-[#EDE4CE] data-[state=checked]:text-[#C25E3A]',
                  'data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50',
                )}
              >
                <span className="min-w-0">
                  <Select.ItemText>{item.label}</Select.ItemText>
                  {item.hint && (
                    <span className="block text-[11px] text-[#6B5E4E]">{item.hint}</span>
                  )}
                </span>
                <Select.ItemIndicator className="absolute right-2 top-2">
                  <Check className="h-3.5 w-3.5" aria-hidden />
                </Select.ItemIndicator>
              </Select.Item>
            ))}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  )
}
