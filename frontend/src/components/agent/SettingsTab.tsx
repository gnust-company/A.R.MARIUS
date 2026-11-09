// What this agent is, as fields rather than as a card to read.
//
// Name and description were both settable exactly once — at creation — and the description was
// not shown anywhere afterwards at all. The runtime settings were worse: the door accepted them
// and nothing displayed them, so what an agent had been set to was invisible (FR-007m).
//
// The model and thinking level are picked here too. They used to be changed from a dialog behind
// a menu on the agents list; that menu is gone (FR-007o), and this is the one screen where an
// agent is managed, so this is where they live.
//
// Inherited from Multica's General tab, which presents every editable value as its own labelled
// row. Their version auto-saves; this one keeps an explicit save, because a name is what other
// screens address this agent by and a half-typed one should not travel.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Save } from 'lucide-react'

import RuntimeOptionFields from '@/components/RuntimeOptionFields'
import type { PlacementOption } from '@/store/appStore'
import { cn } from '@/lib/utils'

export default function SettingsTab({
  name,
  description,
  runtimeOptions,
  runtime,
  options,
  optionsLoading,
  canEdit,
  onSave,
  onSaveRuntimeOptions,
}: {
  name: string
  description: string
  runtimeOptions: Record<string, string>
  /** Where this agent works, or undefined when it works nowhere. */
  runtime?: { cli_kind: string; machine_name: string }
  /** What the place this agent works at lets a person pick (FR-007k). */
  options: PlacementOption[]
  optionsLoading: boolean
  canEdit: boolean
  onSave: (next: { name: string; description: string }) => Promise<void>
  /** Only the settings the person actually moved. */
  onSaveRuntimeOptions: (touched: Record<string, string>) => Promise<void>
}) {
  const { t } = useTranslation()
  const [draftName, setDraftName] = useState(name)
  const [draftDescription, setDraftDescription] = useState(description)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [draftOptions, setDraftOptions] = useState<Record<string, string>>(runtimeOptions)
  const [savingOptions, setSavingOptions] = useState(false)
  const [savedOptions, setSavedOptions] = useState(false)

  // Against the incoming values, with no effect and no ref — see the note in InstructionsTab.
  // The parent keys this component by the agent's id, so a different agent gets fresh boxes.
  const trimmed = draftName.trim()
  const dirty = trimmed !== name || draftDescription !== description
  const settings = Object.entries(runtimeOptions)
  // A setting the person never touched is not re-sent: a value stored back when the tool still
  // offered it must not be dragged into this save and refused.
  const touched = Object.fromEntries(
    Object.entries(draftOptions).filter(([key, value]) => value !== (runtimeOptions[key] ?? '')),
  )
  const optionsDirty = Object.keys(touched).length > 0

  const fieldCls = cn(
    'w-full min-h-[44px] rounded-md border border-line bg-inset px-3.5 py-2.5',
    'font-body text-body-md text-ink placeholder:text-ink-muted',
    'focus:border-terracotta focus:bg-paper focus:outline-none focus:ring-[3px] focus:ring-terracotta/15',
  )
  const labelCls = 'mb-1.5 block font-body text-body-sm font-medium text-ink'
  const saveCls =
    'inline-flex min-h-[44px] items-center gap-2 rounded-md bg-ink px-4 font-body text-body-md font-medium text-paper transition-colors hover:bg-ink/85 disabled:cursor-not-allowed disabled:opacity-50'

  async function save() {
    setSaving(true)
    try {
      await onSave({ name: trimmed, description: draftDescription })
      setSaved(true)
      window.setTimeout(() => setSaved(false), 2200)
    } catch {
      // The page says why, above the tabs; the button simply comes back.
    } finally {
      setSaving(false)
    }
  }

  async function saveOptions() {
    setSavingOptions(true)
    try {
      await onSaveRuntimeOptions(touched)
      setSavedOptions(true)
      window.setTimeout(() => setSavedOptions(false), 2200)
    } catch {
      // The page says why, above the tabs; the button simply comes back.
    } finally {
      setSavingOptions(false)
    }
  }

  return (
    <div className="space-y-8">
      <div className="space-y-5">
        <h2 className="font-display text-[20px] font-medium leading-tight text-ink">
          {t('agentDetail.tab.settings')}
        </h2>
        <div>
          <label htmlFor="agent-name" className={labelCls}>
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
          <label htmlFor="agent-description" className={cn(labelCls, 'mb-0.5')}>
            {t('agentDetail.settingsTab.descriptionLabel')}
          </label>
          <p className="mb-2 font-body text-body-sm text-ink-muted">
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

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={save}
            disabled={!canEdit || !dirty || !trimmed || saving}
            className={saveCls}
          >
            {saving ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            ) : (
              <Save className="h-4 w-4" aria-hidden />
            )}
            {t('agentDetail.settingsTab.save')}
          </button>
          {saved && (
            <span className="font-body text-body-sm text-verdigris-ink" role="status">
              {t('agentDetail.settingsTab.saved')}
            </span>
          )}
        </div>
      </div>

      {/* How this agent runs: where, and on which settings. The settings are the place's
          answer (FR-007k) — a place that offers nothing draws nothing, and the agent runs on its
          tool's own defaults. */}
      <div className="space-y-4 border-t border-line pt-6">
        <div>
          <h2 className="font-display text-[20px] font-medium leading-tight text-ink">
            {t('agentDetail.settingsTab.runtimeHeading')}
          </h2>
          <p className="mt-1 font-body text-body-md text-ink-light">
            {runtime
              ? t('agentDetail.settingsTab.runsOn', {
                  cli: runtime.cli_kind,
                  machine: runtime.machine_name,
                })
              : t('agentDetail.settingsTab.runsNowhere')}
          </p>
        </div>
        {optionsLoading ? (
          <p className="font-body text-body-md text-ink-muted">{t('directory.workplaceLoading')}</p>
        ) : options.length > 0 ? (
          <>
            <RuntimeOptionFields
              options={options}
              chosen={draftOptions}
              onChange={(key, value) => setDraftOptions((was) => ({ ...was, [key]: value }))}
              idPrefix="settings-option"
            />
            <p className="font-body text-body-sm text-ink-muted">{t('directory.optionAppliesNextRun')}</p>
            <div className="flex flex-wrap items-center gap-3">
              <button
                type="button"
                onClick={saveOptions}
                disabled={!canEdit || !optionsDirty || savingOptions}
                className={saveCls}
              >
                {savingOptions ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Save className="h-4 w-4" aria-hidden />
                )}
                {t('agentDetail.settingsTab.saveRuntime')}
              </button>
              {savedOptions && (
                <span className="font-body text-body-sm text-verdigris-ink" role="status">
                  {t('agentDetail.settingsTab.saved')}
                </span>
              )}
            </div>
          </>
        ) : settings.length === 0 ? (
          <p className="font-body text-body-md text-ink-muted">
            {t('agentDetail.settingsTab.runtimeDefaults')}
          </p>
        ) : (
          <dl className="divide-y divide-line rounded-lg border border-line bg-inset">
            {settings.map(([key, value]) => (
              <div key={key} className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 px-4 py-2.5">
                <dt className="min-w-[8rem] font-body text-body-sm text-ink-light">
                  {t(`directory.option.${key}`, { defaultValue: key })}
                </dt>
                <dd className="min-w-0 break-words font-mono text-mono-sm text-ink">{value || '—'}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </div>
  )
}
