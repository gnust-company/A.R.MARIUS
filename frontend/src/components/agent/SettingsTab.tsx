// What this agent is, as fields rather than as a card to read.
//
// Name and description were both settable exactly once — at creation — and the description was
// not shown anywhere afterwards at all. The runtime settings were worse: the door accepted them
// and nothing displayed them, so what an agent had been set to was invisible (FR-007m).
//
// Inherited from Multica's General tab, which presents every editable value as its own labelled
// row. Their version auto-saves; this one keeps an explicit save, because a name is what other
// screens address this agent by and a half-typed one should not travel.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Save } from 'lucide-react'

import { cn } from '@/lib/utils'

export default function SettingsTab({
  name,
  description,
  runtimeOptions,
  adapterType,
  canEdit,
  onSave,
}: {
  name: string
  description: string
  runtimeOptions: Record<string, string>
  adapterType: string
  canEdit: boolean
  onSave: (next: { name: string; description: string }) => Promise<void>
}) {
  const { t } = useTranslation()
  const [draftName, setDraftName] = useState(name)
  const [draftDescription, setDraftDescription] = useState(description)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  // Against the incoming values, with no effect and no ref — see the note in InstructionsTab.
  // The parent keys this component by the agent's id, so a different agent gets fresh boxes.
  const trimmed = draftName.trim()
  const dirty = trimmed !== name || draftDescription !== description
  const settings = Object.entries(runtimeOptions)

  const fieldCls = cn(
    'w-full rounded-md border border-[#E3D7BC] bg-vellum px-3 py-2',
    'text-[13px] text-[#2A2318] placeholder:text-[#A89880]',
    'focus:border-[#C25E3A] focus:outline-none focus:ring-[3px] focus:ring-[rgba(194,94,58,0.15)]',
  )

  async function save() {
    setSaving(true)
    try {
      await onSave({ name: trimmed, description: draftDescription })
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2200)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <label htmlFor="agent-name" className="block text-[13px] font-medium text-[#2A2318] mb-1">
          {t('agentDetail.settingsTab.nameLabel')}
        </label>
        <input
          id="agent-name"
          value={draftName}
          onChange={(e) => setDraftName(e.target.value)}
          readOnly={!canEdit}
          className={fieldCls}
        />
      </div>

      <div>
        <label
          htmlFor="agent-description"
          className="block text-[13px] font-medium text-[#2A2318] mb-1"
        >
          {t('agentDetail.settingsTab.descriptionLabel')}
        </label>
        <p className="mb-1.5 text-[12px] text-[#6B5E4E]">
          {t('agentDetail.settingsTab.descriptionHint')}
        </p>
        <textarea
          id="agent-description"
          value={draftDescription}
          onChange={(e) => setDraftDescription(e.target.value)}
          readOnly={!canEdit}
          rows={3}
          placeholder={t('agentDetail.settingsTab.descriptionPlaceholder')}
          className={fieldCls}
        />
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={save}
          disabled={!canEdit || !dirty || !trimmed || saving}
          className="inline-flex items-center gap-1.5 rounded-md bg-[#C25E3A] px-3 py-1.5 text-[13px] font-medium text-white transition-colors hover:bg-[#D4744C] disabled:opacity-50"
        >
          {saving ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
          ) : (
            <Save className="h-3.5 w-3.5" aria-hidden />
          )}
          {t('agentDetail.settingsTab.save')}
        </button>
        {saved && (
          <span className="text-[12px] text-[#2A6E3A]">{t('agentDetail.settingsTab.saved')}</span>
        )}
      </div>

      {/* What this agent was set to where it runs. Shown, not edited: which values a tool takes
          is the workplace's answer, and the screen that asks it is where an agent is placed
          (FR-007k). Before this it was written and then never displayed anywhere. */}
      <div className="border-t border-[#E3D7BC] pt-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#A89880] mb-2">
          {t('agentDetail.settingsTab.runtimeHeading')}
        </p>
        <p className="mb-2 text-[12px] text-[#6B5E4E]">
          {t('agentDetail.settingsTab.runtimeHint', { runtime: adapterType || '—' })}
        </p>
        {settings.length === 0 ? (
          <p className="text-[13px] text-[#A89880]">
            {t('agentDetail.settingsTab.runtimeDefaults')}
          </p>
        ) : (
          <dl className="space-y-1.5">
            {settings.map(([key, value]) => (
              <div key={key} className="flex items-baseline gap-3">
                <dt className="min-w-[8rem] font-mono text-[12px] text-[#6B5E4E]">{key}</dt>
                <dd className="font-mono text-[12px] text-[#2A2318]">{value || '—'}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  )
}
