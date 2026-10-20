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
    <div className={cn('rounded-lg border border-[#E3D7BC] bg-[#EDE4CE] p-4', className)}>
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        aria-expanded={open}
        className="flex w-full items-start gap-2 text-left"
      >
        {open ? (
          <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 text-[#6B5E4E]" aria-hidden />
        ) : (
          <ChevronRight className="mt-0.5 h-4 w-4 shrink-0 text-[#6B5E4E]" aria-hidden />
        )}
        <span className="min-w-0">
          <span className="block text-[13px] font-medium text-[#2A2318]">
            {t('agentDetail.systemPrompt.title')}
          </span>
          <span className="mt-0.5 block text-[12px] text-[#6B5E4E]">
            {t('agentDetail.systemPrompt.hint')}
          </span>
          <span className="mt-0.5 block text-[12px] text-[#6B5E4E]">
            {t('agentDetail.systemPrompt.note')}
          </span>
        </span>
      </button>
      {open && (
        <pre
          lang="en"
          className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap break-words rounded-md border border-[#E3D7BC] bg-vellum p-3 font-mono text-[12px] leading-relaxed text-[#2A2318]"
        >
          {text}
        </pre>
      )}
    </div>
  )
}
