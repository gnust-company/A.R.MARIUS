// The part of an agent's text the product wrote, shown as it is sent (spec 003 FR-123a).
//
// Word for word and in English, inside a frame whose title and note go through i18n. That is
// the exception Constitution VII (2.1.0) makes for showing what the agent receives: read only,
// the frame translated, and none of it a status or a reason. Translating the text itself would
// show the person a second copy of the very thing they asked to see.
//
// One block for the agent page and the first steps alike, so the two cannot drift into saying
// different things about the same text.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight } from 'lucide-react'

import { cn } from '@/lib/utils'

export default function SystemPromptBlock({
  text,
  defaultOpen = false,
  className,
}: {
  text: string
  /** Open on arrival where reading it is the point of the screen; folded where it sits
   *  beside other work. */
  defaultOpen?: boolean
  className?: string
}) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(defaultOpen)

  return (
    <div className={cn('rounded-lg border border-line bg-inset', className)}>
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="flex min-h-[44px] w-full items-start gap-2.5 rounded-lg px-4 py-3.5 text-left transition-colors hover:bg-vellum"
      >
        {open ? (
          <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-ink-light" aria-hidden />
        ) : (
          <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-ink-light" aria-hidden />
        )}
        <span className="min-w-0">
          <span className="block font-body text-[15px] font-medium text-ink">
            {t('agentDetail.systemPrompt.title')}
          </span>
          <span className="mt-0.5 block font-body text-body-sm text-ink-light">
            {t('agentDetail.systemPrompt.hint')}
          </span>
          <span className="mt-0.5 block font-body text-body-sm text-ink-muted">
            {t('agentDetail.systemPrompt.note')}
          </span>
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4">
          <pre
            lang="en"
            className="max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-line bg-paper p-3.5 font-mono text-mono-sm leading-relaxed text-ink"
          >
            {text}
          </pre>
        </div>
      )}
    </div>
  )
}
