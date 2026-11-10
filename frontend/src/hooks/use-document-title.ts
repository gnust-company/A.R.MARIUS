import { useEffect } from 'react'
import { useLocation, useParams } from 'react-router'
import { useTranslation } from 'react-i18next'
import { useAppStore } from '@/store/appStore'
import { NAV_GROUPS, activeNavPath } from '@/lib/nav'

const APP = 'Armarius'

/**
 * Name the browser tab after what is on it, with the number of letters waiting in front.
 *
 * The tab title is the one part of the app a person still sees after switching to another
 * tab, so it is where "something is waiting for you" has to live: "(3) Hộp thư · Armarius".
 * A task, a project or an agent names itself; every other screen takes its sidebar label.
 */
export function useDocumentTitle() {
  const { t } = useTranslation()
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const { pathname } = useLocation()
  const waiting = useAppStore((s) => s.inboxPending)

  const base = `/w/${workspaceId}`
  const sub = pathname.startsWith(base) ? pathname.slice(base.length) || '/' : pathname
  const [, section, id] = sub.split('/')

  // Selectors return a string (not the entity), so the tab only re-titles when the name moves.
  const named = useAppStore((s) => {
    if (!id) return ''
    if (section === 'tasks') {
      const task = s.tasks.find((x) => x.id === id)
      return task ? [task.identifier, task.title].filter(Boolean).join(' ') : ''
    }
    if (section === 'projects') return s.projects.find((x) => x.id === id)?.name ?? ''
    if (section === 'agents') {
      const agent = s.mariuses.find((x) => x.id === id)
      return agent ? agent.displayName || agent.name : ''
    }
    return ''
  })

  const navPath = activeNavPath(sub)
  const navItem = NAV_GROUPS.flatMap((g) => g.items).find((item) => item.path === navPath)
  const screen = named || (navItem ? t(navItem.labelKey) : section === 'account' ? t('nav.account') : '')

  useEffect(() => {
    const count = waiting > 99 ? '99+' : String(waiting)
    document.title = `${waiting > 0 ? `(${count}) ` : ''}${screen ? `${screen} · ` : ''}${APP}`
  }, [waiting, screen])

  // Leaving the workspace (to the launcher, the login screen) leaves no stale name behind.
  useEffect(() => () => void (document.title = APP), [])
}
