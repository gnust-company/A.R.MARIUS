// The agent's own text, and the one place it can be changed (FR-007m).
//
// Two boxes, not one, and that is the whole design. Since roles by project were removed,
// `instructions` is the only thing that says how an agent behaves — so it has to be editable,
// or the way to change an agent is to delete it and lose its history with it. But the workspace
// host has a *second* author: the product wrote the job that makes it a host, in English because
// a machine reads it (Constitution VII). One box for both would mean the first owner who edits
// their host deletes that job by accident.
//
// So the product's half is shown above, read-only, folded away; the owner's half is a plain
// editable box below. Inherited from Multica's agent view, which splits it the same way and for
// the same reason.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Save } from 'lucide-react'

import { cn } from '@/lib/utils'
import SystemPromptBlock from './SystemPromptBlock'

export default function InstructionsTab({
  instructions,
  systemInstructions,
  canEdit,
  onSave,
}: {
  instructions: string
  systemInstructions: string
  canEdit: boolean
  onSave: (next: string) => Promise<void>
}) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState(instructions)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Compared against the incoming value, not against a remembered copy of it. There is no
  // effect and no ref here on purpose: an effect that writes the box when the prop changes is a
  // second author for one value, and reading a ref while rendering is the same bug wearing a
  // different hat — ESLint refuses both, and it is right twice. A successful save updates the
  // prop, so this goes quiet by itself. Switching agents is the parent's job: it keys this
  // component by the agent's id, so a different agent is a different component with a fresh box.
  const dirty = draft !== instructions
  const hasSystem = systemInstructions.trim().length > 0

  async function save() {
    setSaving(true)
    try {
      await onSave(draft)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2200)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6">
      {hasSystem && <SystemPromptBlock text={systemInstructions} />}

      <div>
        <label
          htmlFor="agent-instructions"
          className="block text-[13px] font-medium text-[#2A2318]"
        >
          {hasSystem
            ? t('agentDetail.instructions.ownLabelWithSystem')
            : t('agentDetail.instructions.ownLabel')}
        </label>
        <p className="mt-0.5 mb-2 text-[12px] text-[#6B5E4E]">
          {t('agentDetail.instructions.ownHint')}
        </p>
        <textarea
          id="agent-instructions"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          readOnly={!canEdit}
          rows={14}
          placeholder={t('agentDetail.instructions.placeholder')}
          className={cn(
            'w-full rounded-md border border-[#E3D7BC] bg-vellum px-3 py-2',
            'font-mono text-[12px] leading-relaxed text-[#2A2318] placeholder:text-[#A89880]',
            'focus:border-[#C25E3A] focus:outline-none focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)]',
            !canEdit && 'opacity-70',
          )}
        />
        <div className="mt-2 flex items-center gap-3">
          <button
            type="button"
            onClick={save}
            disabled={!canEdit || !dirty || saving}
            className={cn(
              'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors',
              'bg-[#C25E3A] text-white hover:bg-[#D4744C] disabled:opacity-50',
            )}
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
            ) : (
              <Save className="h-3.5 w-3.5" aria-hidden />
            )}
            {t('agentDetail.instructions.save')}
          </button>
          {saved && (
            <span className="text-[12px] text-[#2A6E3A]">
              {t('agentDetail.instructions.savedNextRun')}
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
