// The right-hand pane of the skill library: one skill's files, read-only.
//
// The prototype this screen follows edits SKILL.md in place and has a "save" button. The
// server has no way to change a skill's files after it is created (list / create / import /
// delete only), so a box that looked editable would be a promise nothing keeps. This pane
// shows the files exactly as the server holds them — which is also what travels to an agent.
import { useMemo, useState } from 'react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ArrowLeft, FileCode2, Folder, FolderTree, Github, FolderOpen, Trash2 } from 'lucide-react';
import type { Skill, SkillFile } from '@/store/appStore';
import { cn } from '@/lib/utils';

// ─── File tree ───────────────────────────────────────────────────────────────

interface TreeNode {
  name: string;
  path: string;
  type: 'file' | 'folder';
  children: TreeNode[];
}

function buildTree(files: SkillFile[]): TreeNode[] {
  const root: TreeNode[] = [];
  for (const file of files) {
    const parts = file.path.split('/').filter(Boolean);
    let level = root;
    parts.forEach((name, i) => {
      const path = parts.slice(0, i + 1).join('/');
      const isFile = i === parts.length - 1;
      let node = level.find((n) => n.path === path);
      if (!node) {
        node = { name, path, type: isFile ? 'file' : 'folder', children: [] };
        level.push(node);
      }
      level = node.children;
    });
  }
  // SKILL.md leads its level because it is the one that matters; then folders, then files.
  const sort = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.name === 'SKILL.md') return -1;
      if (b.name === 'SKILL.md') return 1;
      if (a.type !== b.type) return a.type === 'folder' ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
    nodes.forEach((n) => sort(n.children));
  };
  sort(root);
  return root;
}

/** Display name for a file's type, read from its extension (the stored `language` is a guess). */
function languageOf(path: string): string {
  const ext = path.split('.').pop()?.toLowerCase() ?? '';
  const map: Record<string, string> = {
    md: 'Markdown', ts: 'TypeScript', tsx: 'TSX', js: 'JavaScript', jsx: 'JSX', json: 'JSON',
    py: 'Python', go: 'Go', rs: 'Rust', yaml: 'YAML', yml: 'YAML', sh: 'Shell', toml: 'TOML',
    html: 'HTML', css: 'CSS', sql: 'SQL', txt: 'Text',
  };
  return map[ext] ?? (ext ? ext.toUpperCase() : 'Text');
}

function TreeRows({
  nodes,
  depth,
  selected,
  onSelect,
}: {
  nodes: TreeNode[];
  depth: number;
  selected: string;
  onSelect: (path: string) => void;
}) {
  return (
    <>
      {nodes.map((node) =>
        node.type === 'folder' ? (
          <div key={node.path}>
            <div
              className="flex min-h-[32px] items-center gap-[7px] px-[9px] font-mono text-[11px] text-ink-muted"
              style={{ paddingLeft: 9 + depth * 14 }}
            >
              <Folder className="h-[15px] w-[15px] shrink-0" aria-hidden />
              <span className="truncate">{node.name}/</span>
            </div>
            <TreeRows nodes={node.children} depth={depth + 1} selected={selected} onSelect={onSelect} />
          </div>
        ) : (
          <button
            key={node.path}
            type="button"
            onClick={() => onSelect(node.path)}
            aria-current={node.path === selected ? 'true' : undefined}
            className={cn(
              'flex min-h-[38px] w-full items-center gap-[7px] rounded-sm px-[9px] text-left font-mono text-[11px] transition-colors',
              node.path === selected
                ? 'bg-sapphire-soft text-ink-strong'
                : 'text-ink-light hover:bg-surface-hover hover:text-ink-strong'
            )}
            style={{ paddingLeft: 9 + depth * 14 }}
          >
            <FileCode2 className="h-4 w-4 shrink-0" aria-hidden />
            <span className="truncate">{node.name}</span>
          </button>
        )
      )}
    </>
  );
}

// ─── The pane ────────────────────────────────────────────────────────────────

export default function SkillViewer({
  skill,
  backHref,
  onDelete,
}: {
  skill: Skill;
  /** Where "back to the library" leads on a narrow screen, where list and pane take turns. */
  backHref: string;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  const files = skill.files;
  const tree = useMemo(() => buildTree(files), [files]);
  const sortedPaths = useMemo(() => {
    const out: string[] = [];
    const walk = (nodes: TreeNode[]) =>
      nodes.forEach((n) => (n.type === 'file' ? out.push(n.path) : walk(n.children)));
    walk(tree);
    return out;
  }, [tree]);
  // The parent keys this pane by skill id, so a new skill starts on its first file.
  const [picked, setPicked] = useState<string | null>(null);
  const selectedPath = picked && files.some((f) => f.path === picked) ? picked : (sortedPaths[0] ?? '');
  const file = files.find((f) => f.path === selectedPath) ?? null;
  const content = file?.content ?? '';
  const imported = skill.type === 'github';

  return (
    <section className="min-w-0 overflow-hidden rounded-lg border border-line bg-surface">
      <header className="flex flex-col gap-4 border-b border-line p-[18px] sm:flex-row sm:items-center sm:justify-between sm:gap-[18px] md:min-h-[100px] md:px-[22px] md:py-[19px]">
        <div className="min-w-0">
          <Link
            to={backHref}
            className="btn-text -mt-2 mb-1 min-h-[40px] lg:hidden"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden />
            {t('skills.editor.backToSkills')}
          </Link>
          <p className="eyebrow">{t('skills.viewer.eyebrow')}</p>
          <h2 className="mt-[3px] break-words font-display text-[23px] font-normal leading-tight tracking-[-0.015em] text-ink-strong sm:text-[25px]">
            {skill.name}
          </h2>
          {skill.description && (
            <p className="mt-1 break-words font-body text-[13px] leading-relaxed text-ink-light">{skill.description}</p>
          )}
          <p className="mt-2 flex items-center gap-1.5 font-body text-[11px] text-ink-muted">
            {imported ? <Github className="h-3.5 w-3.5" aria-hidden /> : <FolderOpen className="h-3.5 w-3.5" aria-hidden />}
            {imported ? t('skills.imported') : t('skills.type.manual')}
            {' · '}
            {t('skills.fileCount', { count: files.length })}
          </p>
        </div>
        <button type="button" onClick={onDelete} className="btn btn-danger btn-sm self-start sm:self-center">
          <Trash2 className="h-4 w-4" aria-hidden />
          {t('skills.delete')}
        </button>
      </header>

      {files.length === 0 ? (
        <p className="px-[22px] py-12 text-center font-body text-body-sm text-ink-muted">{t('skills.editor.noFiles')}</p>
      ) : (
        <div className="grid grid-cols-1 md:min-h-[560px] md:grid-cols-[190px_minmax(0,1fr)] xl:grid-cols-[210px_minmax(0,1fr)]">
          {/* Desktop and tablet: the tree beside the file. */}
          <nav
            aria-label={t('skills.viewer.files')}
            className="hidden border-r border-line bg-canvas-deep/30 px-2.5 py-[17px] md:block"
          >
            <p className="eyebrow mb-[13px] flex items-center gap-1.5 px-2">
              <FolderTree className="h-[15px] w-[15px]" aria-hidden />
              {t('skills.viewer.files')}
            </p>
            <TreeRows nodes={tree} depth={0} selected={selectedPath} onSelect={setPicked} />
          </nav>

          {/* Phone: the files as a strip that scrolls sideways, above the content. */}
          <nav
            aria-label={t('skills.viewer.files')}
            className="no-scrollbar flex gap-1 overflow-x-auto border-b border-line bg-canvas-deep/30 p-2 md:hidden"
          >
            {sortedPaths.map((path) => (
              <button
                key={path}
                type="button"
                onClick={() => setPicked(path)}
                aria-current={path === selectedPath ? 'true' : undefined}
                className={cn(
                  'flex min-h-[40px] shrink-0 items-center gap-[7px] rounded-sm px-2.5 font-mono text-[11px] transition-colors',
                  path === selectedPath ? 'bg-sapphire-soft text-ink-strong' : 'text-ink-light'
                )}
              >
                <FileCode2 className="h-4 w-4 shrink-0" aria-hidden />
                {path}
              </button>
            ))}
          </nav>

          <div className="flex min-w-0 flex-col bg-canvas-deep">
            <div className="flex min-h-[45px] items-center gap-[7px] border-b border-line px-[17px] font-mono text-[11px] text-ink-light">
              <FileCode2 className="h-[15px] w-[15px] shrink-0" aria-hidden />
              <span className="min-w-0 truncate">{selectedPath}</span>
              <span className="ml-auto shrink-0 text-ink-muted">{t('skills.viewer.readOnly')}</span>
            </div>
            {content ? (
              <pre
                tabIndex={0}
                aria-label={selectedPath}
                className="min-h-[360px] max-h-[70vh] flex-1 overflow-auto whitespace-pre p-[17px] font-mono text-[11px] leading-[1.8] text-ink [tab-size:2] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-gold/60 md:min-h-[510px] md:p-[22px] md:text-[12px]"
              >
                {content}
              </pre>
            ) : (
              <p className="flex min-h-[360px] flex-1 items-center justify-center p-6 font-body text-body-sm text-ink-muted md:min-h-[510px]">
                {t('skills.viewer.emptyFile')}
              </p>
            )}
            <footer className="flex justify-between gap-3.5 border-t border-line px-4 py-[9px] font-mono text-[10px] text-ink-muted">
              <span>{languageOf(selectedPath)} · UTF-8</span>
              <span>{t('skills.viewer.stats', { lines: content ? content.split('\n').length : 0, chars: content.length })}</span>
            </footer>
          </div>
        </div>
      )}
    </section>
  );
}
