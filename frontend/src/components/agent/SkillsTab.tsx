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
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <p className="text-[12px] text-[#6B5E4E]">{t('agentDetail.skillsTab.hint')}</p>
        <button
          type="button"
          onClick={onAdd}
          className="inline-flex shrink-0 items-center gap-1 rounded-md bg-[#E3D7BC] px-2.5 py-1.5 text-[12px] font-medium text-[#6B5E4E] transition-colors hover:bg-[#D9CDB8]"
        >
          <Plus className="h-3.5 w-3.5" aria-hidden /> {t('agentDetail.linkSkills.add')}
        </button>
      </div>

      {carried.length === 0 ? (
        <p className="py-6 text-center text-[13px] text-[#A89880]">
          {t('agentDetail.skillsTab.none')}
        </p>
      ) : (
        <ul className="space-y-2">
          {carried.map((skill) => (
            <li
              key={skill.id}
              className="flex items-center gap-3 rounded-md border border-[#E3D7BC] bg-vellum px-3 py-2"
            >
              <span className="min-w-0 flex-1 truncate text-[13px] text-[#2A2318]">
                {skill.name}
              </span>
              <button
                type="button"
                onClick={() => remove(skill.id)}
                disabled={!canEdit || removing !== null}
                aria-label={t('agentDetail.skillsTab.removeAria', { name: skill.name })}
                title={t('agentDetail.skillsTab.removeAria', { name: skill.name })}
                className={cn(
                  'shrink-0 rounded-md p-1.5 text-[#A89880] transition-colors',
                  'hover:bg-[#F3E4E0] hover:text-[#B84A32] disabled:opacity-40',
                )}
              >
                {removing === skill.id ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
