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

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-[1_1_260px]">
          <h2 className="font-display text-[20px] font-medium leading-tight text-ink">
            {t('agentDetail.tab.skills')}
          </h2>
          <p className="mt-1 font-body text-body-md text-ink-light">{t('agentDetail.skillsTab.hint')}</p>
        </div>
        <button
          type="button"
          onClick={onAdd}
          className="inline-flex min-h-[44px] shrink-0 items-center gap-1.5 rounded-md border border-line-strong bg-paper px-4 font-body text-body-md font-medium text-ink transition-colors hover:bg-inset"
        >
          <Plus className="h-4 w-4" aria-hidden /> {t('agentDetail.linkSkills.add')}
        </button>
      </div>

      {carried.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line-strong px-4 py-8 text-center font-body text-body-md text-ink-muted">
          {t('agentDetail.skillsTab.none')}
        </p>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
          {carried.map((skill) => (
            <li key={skill.id} className="flex items-center gap-3 bg-paper py-1.5 pl-4 pr-1.5">
              <span className="min-w-0 flex-1 truncate font-body text-body-md text-ink">
                {skill.name}
              </span>
              <button
                type="button"
                onClick={() => remove(skill.id)}
                disabled={!canEdit || removing !== null}
                aria-label={t('agentDetail.skillsTab.removeAria', { name: skill.name })}
                title={t('agentDetail.skillsTab.removeAria', { name: skill.name })}
                className={cn(
                  'flex h-10 w-10 shrink-0 items-center justify-center rounded-md text-ink-light transition-colors',
                  'hover:bg-vermilion-bg hover:text-vermilion-ink disabled:cursor-not-allowed disabled:opacity-40',
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
    </div>
  )
}
