// The skills this agent carries — and the half that was missing: taking one off.
//
// Adding already existed. Removing did not, anywhere: a skill handed to an agent was handed to
// it for good, and the only way back was to delete the agent. There is no per-skill door, so a
// remove sends the whole list back one shorter — *these and no others* (FR-007m).
//
// Inherited from Multica's Skills tab, which lists what the agent has with a remove beside each
// one, and keeps adding in a dialog of its own.

import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Loader2, Plus, Trash2 } from 'lucide-react'

import { cn } from '@/lib/utils'

export interface SkillRow {
  id: string
  name: string
}

export default function SkillsTab({
  carried,
  canEdit,
  onRemove,
  onAdd,
}: {
  carried: SkillRow[]
  canEdit: boolean
  onRemove: (skillId: string) => Promise<void>
  onAdd: () => void
}) {
  const { t } = useTranslation()
  // Which row is mid-removal. Kept per id rather than as one boolean so removing two in a row
  // does not grey out the whole list.
  const [removing, setRemoving] = useState<string | null>(null)

  async function remove(skillId: string) {
    setRemoving(skillId)
    try {
      await onRemove(skillId)
    } finally {
      setRemoving(null)
    }
  }

  // The block's title and lead live in the SettingsSection that holds this list.
  return (
    <div className="grid gap-3">
      {carried.length === 0 ? (
        <p className="rounded-md border border-dashed border-line-strong px-4 py-7 text-center font-body text-body-md text-ink-muted">
          {t('agentDetail.skillsTab.none')}
        </p>
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {carried.map((skill) => (
            <li
              key={skill.id}
              className="flex min-h-[46px] items-center gap-2 rounded-md border border-sapphire/35 bg-sapphire-soft py-1 pl-3.5 pr-1"
            >
              <span className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink-strong">
                {skill.name}
              </span>
              <button
                type="button"
                onClick={() => remove(skill.id)}
                disabled={!canEdit || removing !== null}
                aria-label={t('agentDetail.skillsTab.removeAria', { name: skill.name })}
                title={t('agentDetail.skillsTab.removeAria', { name: skill.name })}
                className={cn(
                  'grid h-10 w-10 shrink-0 place-items-center rounded-md text-ink-light transition-colors',
                  'hover:bg-danger/10 hover:text-danger disabled:cursor-not-allowed disabled:opacity-40',
                )}
              >
                {removing === skill.id ? (
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
                ) : (
                  <Trash2 className="h-4 w-4" aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
      <div>
        <button type="button" onClick={onAdd} disabled={!canEdit} className="btn btn-secondary">
          <Plus className="h-4 w-4" aria-hidden /> {t('agentDetail.linkSkills.add')}
        </button>
      </div>
    </div>
  )
}
