import { useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate, useParams } from 'react-router';
import { AnimatePresence, motion } from 'framer-motion';
import { ChevronRight, FolderOpen, KanbanSquare, Search, Telescope, Users } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useAppStore } from '@/store/appStore';
import { cn, wsHref } from '@/lib/utils';
import { NAV_GROUPS } from '@/lib/nav';

type Result = {
  id: string;
  kind: 'view' | 'project' | 'agent' | 'task';
  title: string;
  subtitle: string;
  to: string;
};

const KIND_ICON = {
  view: Telescope,
  project: FolderOpen,
  agent: Users,
  task: KanbanSquare,
} as const;

/** "Go anywhere": screens, projects, agents and tasks of this workspace, by name or code. */
export default function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  return createPortal(
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-modal flex items-start justify-center px-4 pt-[12vh] bg-ink-strong/30 backdrop-blur-[3px]"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onMouseDown={(e) => e.target === e.currentTarget && onClose()}
        >
          {/* Mounted per opening, so the query and cursor start fresh every time. */}
          <PaletteBody onClose={onClose} />
        </motion.div>
      )}
    </AnimatePresence>,
    document.body,
  );
}

function PaletteBody({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { workspaceId } = useParams();
  const projects = useAppStore((s) => s.projects);
  const mariuses = useAppStore((s) => s.mariuses);
  const tasks = useAppStore((s) => s.tasks);
  const [query, setQuery] = useState('');
  const [cursor, setCursor] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);

  const results = useMemo<Result[]>(() => {
    const q = query.trim().toLocaleLowerCase(i18n.language);
    const has = (text: string) => !q || text.toLocaleLowerCase(i18n.language).includes(q);
    const inWs = <T extends { workspaceId?: string }>(x: T) => !x.workspaceId || x.workspaceId === workspaceId;
    const views: Result[] = NAV_GROUPS.flatMap((g) => g.items)
      .filter((item) => has(t(item.labelKey)))
      .map((item) => ({
        id: `view-${item.path}`,
        kind: 'view',
        title: t(item.labelKey),
        subtitle: t('command.goToScreen'),
        to: wsHref(workspaceId, item.path),
      }));
    const wsProjects = projects.filter(inWs);
    const projectIds = new Set(wsProjects.map((p) => p.id));
    const projectHits: Result[] = wsProjects
      .filter((p) => has(`${p.name} ${p.key ?? ''}`))
      .map((p) => ({
        id: `project-${p.id}`,
        kind: 'project',
        title: p.name,
        subtitle: t('command.openBoard'),
        to: wsHref(workspaceId, `/projects/${p.id}`),
      }));
    const agentHits: Result[] = mariuses
      .filter((m) => m.workspaceId === workspaceId)
      .filter((m) => has(`${m.displayName || m.name} ${m.role ?? ''}`))
      .map((m) => ({
        id: `agent-${m.id}`,
        kind: 'agent',
        title: m.displayName || m.name,
        subtitle: m.role || t('command.agent'),
        to: wsHref(workspaceId, `/agents/${m.id}`),
      }));
    const taskHits: Result[] = tasks
      .filter((tk) => projectIds.has(tk.projectId))
      .filter((tk) => has(`${tk.identifier ?? ''} ${tk.title}`))
      .map((tk) => ({
        id: `task-${tk.id}`,
        kind: 'task',
        title: tk.title,
        subtitle: tk.identifier || t('command.task'),
        to: wsHref(workspaceId, `/tasks/${tk.id}`),
      }));
    return [...views, ...projectHits, ...agentHits, ...taskHits].slice(0, 9);
  }, [query, projects, mariuses, tasks, workspaceId, t, i18n.language]);

  const active = Math.min(cursor, Math.max(0, results.length - 1));

  const go = (r: Result | undefined) => {
    if (!r) return;
    onClose();
    navigate(r.to);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') onClose();
    else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setCursor((c) => Math.min(results.length - 1, c + 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      go(results[active]);
    }
  };

  return (
    <motion.div
      role="dialog"
      aria-modal="true"
      aria-label={t('command.title')}
      initial={{ opacity: 0, y: 12, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 8, scale: 0.98 }}
      transition={{ duration: 0.18 }}
      onKeyDown={onKeyDown}
      className="w-full max-w-[620px] rounded-xl border border-line-strong bg-surface-raised shadow-soft overflow-hidden"
    >
      <div className="px-5 pt-4">
        <p className="font-mono text-eyebrow uppercase text-ink-muted">{t('command.eyebrow')}</p>
        <h2 className="mt-1 font-display text-display-sm">{t('command.title')}</h2>
      </div>
      <label className="mx-5 mt-4 flex items-center gap-3 px-3 min-h-[48px] rounded-md border border-field-line bg-field focus-within:border-sapphire">
        <Search className="w-5 h-5 text-ink-muted shrink-0" />
        <input
          autoFocus
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setCursor(0);
          }}
          placeholder={t('command.placeholder')}
          className="flex-1 min-w-0 bg-transparent outline-none text-body-md text-ink placeholder:text-ink-muted"
          aria-controls="command-results"
          aria-activedescendant={results[active] ? `cmd-${results[active].id}` : undefined}
        />
      </label>
      <div id="command-results" ref={listRef} role="listbox" className="mt-3 max-h-[50vh] overflow-y-auto px-2 pb-2">
        {results.map((r, i) => {
          const Icon = KIND_ICON[r.kind];
          return (
            <button
              key={r.id}
              id={`cmd-${r.id}`}
              role="option"
              aria-selected={i === active}
              type="button"
              onMouseEnter={() => setCursor(i)}
              onClick={() => go(r)}
              className={cn(
                'w-full flex items-center gap-3 px-3 min-h-[52px] rounded-md text-left transition-colors',
                i === active ? 'bg-sapphire-soft' : 'hover:bg-surface-hover',
              )}
            >
              <span className="grid place-items-center w-8 h-8 rounded-md border border-line text-ink-light shrink-0">
                <Icon className="w-4 h-4" />
              </span>
              <span className="min-w-0 flex-1">
                <strong className="block truncate text-body-sm font-semibold text-ink-strong">{r.title}</strong>
                <small className="block truncate text-[12px] text-ink-muted">{r.subtitle}</small>
              </span>
              <ChevronRight className="w-4 h-4 text-ink-muted shrink-0" />
            </button>
          );
        })}
        {results.length === 0 && (
          <p className="px-3 py-8 text-center text-body-sm text-ink-light">{t('command.empty', { query })}</p>
        )}
      </div>
      <footer className="hidden sm:flex gap-4 px-5 py-3 border-t border-line text-[12px] text-ink-muted">
        <span>
          <kbd className="kbd">↵</kbd> {t('command.hintOpen')}
        </span>
        <span>
          <kbd className="kbd">↑↓</kbd> {t('command.hintMove')}
        </span>
        <span>
          <kbd className="kbd">esc</kbd> {t('command.hintClose')}
        </span>
      </footer>
    </motion.div>
  );
}
