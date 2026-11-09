import { useState, useMemo, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import { motion, AnimatePresence } from 'framer-motion';
import {
  FileText,
  FolderOpen,
  Folder,
  ChevronRight,
  Plus,
  Trash2,
  Save,
  RotateCcw,
  ArrowLeft,
  X,
  Check,
  ScrollText,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { SkillFile } from '@/store/appStore';
import StatusChip from '@/components/StatusChip';
import { cn, wsHref } from '@/lib/utils';
import { useTranslation } from 'react-i18next';

// ─── Tree Node Types ─────────────────────────────────────────────────────────

interface TreeNode {
  name: string;
  path: string;
  type: 'file' | 'folder';
  children?: TreeNode[];
  file?: SkillFile;
  expanded?: boolean;
}

// ─── Build File Tree ─────────────────────────────────────────────────────────

// Stamp the open/closed flag onto every folder node. Kept at module scope and
// given the open set as an argument so it is the same function on every render —
// a copy rebuilt inside the component would be a dependency the memo below can
// never hold still.
function applyExpanded(nodes: TreeNode[], expanded: Set<string>): TreeNode[] {
  return nodes.map((n) => ({
    ...n,
    expanded: n.type === 'folder' ? expanded.has(n.path) : undefined,
    children: n.children ? applyExpanded(n.children, expanded) : undefined,
  }));
}

function buildTree(files: SkillFile[]): TreeNode[] {
  const root: TreeNode[] = [];

  for (const file of files) {
    const parts = file.path.split('/');
    let current = root;

    for (let i = 0; i < parts.length; i++) {
      const name = parts[i];
      const path = parts.slice(0, i + 1).join('/');
      const isFile = i === parts.length - 1;

      const existing = current.find((n) => n.name === name && n.path === path);
      if (existing) {
        if (!isFile && existing.children) {
          current = existing.children;
        }
        continue;
      }

      const node: TreeNode = {
        name,
        path,
        type: isFile ? 'file' : 'folder',
        ...(isFile ? { file } : { children: [], expanded: true }),
      };
      current.push(node);
      if (!isFile && node.children) {
        current = node.children;
      }
    }
  }

  // Sort: folders first, then files, alphabetically
  const sortNodes = (nodes: TreeNode[]) => {
    nodes.sort((a, b) => {
      if (a.type === 'folder' && b.type === 'file') return -1;
      if (a.type === 'file' && b.type === 'folder') return 1;
      return a.name.localeCompare(b.name);
    });
    nodes.forEach((n) => n.children && sortNodes(n.children));
  };
  sortNodes(root);

  return root;
}

// ─── Get Language from Filename ──────────────────────────────────────────────

function getLanguage(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() || '';
  const map: Record<string, string> = {
    ts: 'typescript', js: 'javascript', jsx: 'jsx', tsx: 'tsx',
    md: 'markdown', json: 'json', py: 'python', rs: 'rust',
    go: 'go', yaml: 'yaml', yml: 'yaml', html: 'html',
    css: 'css', scss: 'scss', sql: 'sql', sh: 'bash',
  };
  return map[ext] || ext || 'text';
}

// ─── Component: File Tree Node ───────────────────────────────────────────────

function FileTreeNode({
  node,
  depth,
  selectedPath,
  onSelect,
  onToggle,
}: {
  node: TreeNode;
  depth: number;
  selectedPath: string;
  onSelect: (node: TreeNode) => void;
  onToggle: (path: string) => void;
}) {
  const isSelected = node.path === selectedPath;
  const paddingLeft = 12 + depth * 18;
  // Rows are 44px where fingers do the pointing and tighten up on a desktop-width screen.
  const row =
    'w-full flex items-center gap-2 min-h-[44px] xl:min-h-[36px] pr-2 rounded-md text-left transition-colors';

  if (node.type === 'folder') {
    return (
      <div>
        <button
          onClick={() => {
            // A folder click both toggles expansion AND selects it as the target for
            // "add file / add folder" — otherwise a fresh folder can never be filled.
            onToggle(node.path);
            onSelect(node);
          }}
          className={cn(row, isSelected ? 'bg-vellum' : 'hover:bg-inset')}
          style={{ paddingLeft }}
          aria-expanded={node.expanded}
        >
          <motion.span
            animate={{ rotate: node.expanded ? 90 : 0 }}
            transition={{ duration: 0.2 }}
            className="flex-shrink-0"
          >
            <ChevronRight className="w-3.5 h-3.5 text-ink-muted" />
          </motion.span>
          {node.expanded ? (
            <FolderOpen className="w-4 h-4 text-ink-muted flex-shrink-0" />
          ) : (
            <Folder className="w-4 h-4 text-ink-muted flex-shrink-0" />
          )}
          <span className={cn('font-mono text-mono-md text-ink truncate', isSelected && 'font-medium')}>{node.name}</span>
        </button>
        <AnimatePresence initial={false}>
          {node.expanded && node.children && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2 }}
              className="overflow-hidden"
            >
              {node.children.map((child) => (
                <FileTreeNode
                  key={child.path}
                  node={child}
                  depth={depth + 1}
                  selectedPath={selectedPath}
                  onSelect={onSelect}
                  onToggle={onToggle}
                />
              ))}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    );
  }

  return (
    <button
      onClick={() => onSelect(node)}
      className={cn(row, isSelected ? 'bg-vellum' : 'hover:bg-inset')}
      style={{ paddingLeft: paddingLeft + 22 }}
      aria-current={isSelected ? 'true' : undefined}
    >
      <FileText
        className={cn('w-4 h-4 flex-shrink-0', isSelected ? 'text-ink' : 'text-ink-muted')}
      />
      <span
        className={cn(
          'font-mono text-mono-md truncate',
          isSelected ? 'text-ink font-medium' : 'text-ink-light'
        )}
      >
        {node.name}
      </span>
    </button>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN PAGE: SkillEditor
// ═══════════════════════════════════════════════════════════════════════════════

export default function SkillEditor() {
  const { id, workspaceId } = useParams<{ id: string; workspaceId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const skills = useAppStore((s) => s.skills);
  const updateSkill = useAppStore((s) => s.updateSkill);

  const skill = useMemo(() => skills.find((s) => s.id === id), [skills, id]);

  // ── Local State ────────────────────────────────────────────────────────────
  // `draftFiles` is a working copy: every edit (content, add, delete) mutates ONLY
  // the draft. Nothing touches the persisted skill until "Save" — so "Discard"
  // truly reverts, and an accidental delete is recoverable until you save.
  const [selectedPath, setSelectedPath] = useState<string>('');
  // Whether the current selection is a folder (a folder can be selected as the target
  // directory for new files/folders — clicking a file clears this).
  const [selectedIsFolder, setSelectedIsFolder] = useState(false);
  const [draftFiles, setDraftFiles] = useState<SkillFile[]>(skill ? skill.files : []);
  const [hasChanges, setHasChanges] = useState(false);
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set());
  const [showAddMenu, setShowAddMenu] = useState(false);
  const [newItemName, setNewItemName] = useState('');
  const [newItemType, setNewItemType] = useState<'file' | 'folder' | null>(null);

  // Re-seed the working copy when the skill identity changes (navigation / late
  // hydration), and open its first file. Compared against the last id we seeded
  // from, so unsaved edits within one skill are never clobbered.
  //
  // Adjusted during render rather than in an effect: React re-runs the component
  // immediately, before anything is painted, so there is no frame showing the
  // previous skill's draft. An effect would paint that frame first, then correct
  // it — which is the cascading render the lint rule is about.
  const [seededSkillId, setSeededSkillId] = useState<string | null>(null);
  if (skill && skill.id !== seededSkillId) {
    setSeededSkillId(skill.id);
    setDraftFiles(skill.files);
    setSelectedPath(skill.files[0]?.path ?? '');
    setSelectedIsFolder(false);
    setHasChanges(false);
  }

  // ── Build Tree ─────────────────────────────────────────────────────────────
  const tree = useMemo(() => buildTree(draftFiles), [draftFiles]);

  // ── Find selected file (from the draft) ────────────────────────────────────
  const selectedFile = useMemo(
    () => draftFiles.find((f) => f.path === selectedPath) || null,
    [draftFiles, selectedPath]
  );

  // The directory new files/folders are created in: the selected folder itself, else
  // the selected file's parent dir, else the tree root. Ends with '/' (or '' for root).
  const targetDir = useMemo(() => {
    if (selectedIsFolder && selectedPath) return selectedPath.replace(/\/+$/, '') + '/';
    if (selectedPath && selectedPath.includes('/'))
      return selectedPath.substring(0, selectedPath.lastIndexOf('/') + 1);
    return '';
  }, [selectedPath, selectedIsFolder]);

  // ── Handlers ───────────────────────────────────────────────────────────────
  const handleSelectFile = useCallback((node: TreeNode) => {
    setSelectedPath(node.path);
    setSelectedIsFolder(node.type === 'folder');
  }, []);

  const handleToggleFolder = useCallback((path: string) => {
    setExpandedFolders((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  }, []);

  const handleContentChange = (value: string) => {
    if (!selectedPath) return;
    setDraftFiles((prev) =>
      prev.map((f) => (f.path === selectedPath ? { ...f, content: value } : f))
    );
    setHasChanges(true);
  };

  // Commit the whole working copy to the store (the only write path).
  const handleSave = () => {
    if (!skill || !hasChanges) return;
    updateSkill(skill.id, { files: draftFiles });
    setHasChanges(false);
  };

  // Revert every unsaved edit — including added/deleted files — back to the store.
  const handleDiscard = () => {
    if (!skill) return;
    setDraftFiles(skill.files);
    setHasChanges(false);
    if (!skill.files.some((f) => f.path === selectedPath)) {
      setSelectedPath(skill.files[0]?.path ?? '');
      setSelectedIsFolder(false);
    }
  };

  // Delete from the draft — recoverable via Discard until you Save. A folder selection
  // removes the whole subtree (its .gitkeep and every file beneath it).
  const handleDeleteFile = () => {
    if (!selectedPath) return;
    const prefix = selectedPath.replace(/\/+$/, '') + '/';
    const remaining = selectedIsFolder
      ? draftFiles.filter((f) => f.path !== selectedPath && !f.path.startsWith(prefix))
      : draftFiles.filter((f) => f.path !== selectedPath);
    setDraftFiles(remaining);
    setSelectedPath(remaining[0]?.path ?? '');
    setSelectedIsFolder(false);
    setHasChanges(true);
  };

  const handleAddItem = () => {
    if (!newItemName.trim() || !newItemType) return;
    // Strip stray slashes off the typed name; combine with the resolved target dir so the
    // new item lands inside the selected folder (or the selected file's dir, or root).
    const name = newItemName.trim().replace(/^\/+|\/+$/g, '');
    if (!name) return;
    const path = targetDir + name;

    if (draftFiles.some((f) => f.path === path)) return;

    if (newItemType === 'file') {
      setDraftFiles((prev) => [...prev, { path, name, content: '', language: getLanguage(name) }]);
      setSelectedPath(path);
      setSelectedIsFolder(false);
      setHasChanges(true);
    } else {
      // Add a .gitkeep file inside the folder so the empty folder renders in the tree,
      // then select+expand the new folder so the next "add file" lands inside it.
      const folderPath = path + '/';
      const keepPath = folderPath + '.gitkeep';
      if (!draftFiles.some((f) => f.path === keepPath)) {
        setDraftFiles((prev) => [...prev, { path: keepPath, name: '.gitkeep', content: '', language: 'text' }]);
        setHasChanges(true);
      }
      setExpandedFolders((prev) => new Set(prev).add(path));
      setSelectedPath(path);
      setSelectedIsFolder(true);
    }

    setNewItemName('');
    setNewItemType(null);
    setShowAddMenu(false);
  };

  // ── Apply expanded state to tree ───────────────────────────────────────────
  const displayTree = useMemo(() => applyExpanded(tree, expandedFolders), [tree, expandedFolders]);

  // ── Loading / Not Found ────────────────────────────────────────────────────
  if (!skill) {
    return (
      <div className="mx-auto w-full max-w-[1240px] pb-10">
        <section className="flex flex-col items-center rounded-xl border border-line bg-paper px-5 py-12 text-center sm:px-8">
          <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-inset text-ink-muted">
            <ScrollText className="h-6 w-6" strokeWidth={1.5} aria-hidden />
          </span>
          <h1 className="font-display text-[22px] font-medium text-ink">{t('skills.editor.notFound')}</h1>
          <p className="mt-2 max-w-md font-body text-body-md text-ink-light">{t('skills.editor.notFoundDesc')}</p>
          <button
            onClick={() => navigate(wsHref(workspaceId, '/skills'))}
            className="mt-6 inline-flex min-h-[44px] items-center gap-2 rounded-md bg-ink px-[18px] font-body text-body-md font-medium text-paper transition-colors hover:bg-ink/85"
          >
            <ArrowLeft className="w-4 h-4" aria-hidden />
            {t('skills.editor.backToSkills')}
          </button>
        </section>
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  const iconButton =
    'w-10 h-10 inline-flex items-center justify-center rounded-md text-ink-light hover:text-ink hover:bg-paper transition-colors';

  return (
    <div className="mx-auto w-full max-w-[1240px] flex flex-col gap-5 pb-10">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex min-w-0 flex-[1_1_320px] items-start gap-2">
          <button
            onClick={() => navigate(wsHref(workspaceId, '/skills'))}
            className="w-11 h-11 shrink-0 -ml-2 inline-flex items-center justify-center rounded-md text-ink-light hover:text-ink hover:bg-inset transition-colors"
            aria-label={t('skills.editor.backToSkills')}
            title={t('skills.editor.backToSkills')}
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="min-w-0 pt-0.5">
            <h1 className="font-display text-[30px] font-medium leading-[1.1] tracking-tight text-ink break-words">
              {skill.name}
            </h1>
            {skill.description && (
              <p className="mt-1.5 font-body text-body-md text-ink-light break-words">{skill.description}</p>
            )}
          </div>
        </div>

        {/* Editor actions */}
        <div className="flex flex-wrap items-center gap-2">
          {hasChanges && (
            <StatusChip status="in_review" label={t('skills.editor.unsaved')} size="md" />
          )}
          <button
            onClick={handleDiscard}
            disabled={!hasChanges}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-md border border-line-strong bg-paper px-4 font-body text-body-md font-medium text-ink transition-colors hover:bg-inset disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-paper"
          >
            <RotateCcw className="w-4 h-4" aria-hidden />
            {t('skills.editor.discard')}
          </button>
          <button
            onClick={handleSave}
            disabled={!hasChanges}
            className="inline-flex min-h-[44px] items-center gap-2 rounded-md bg-ink px-[18px] font-body text-body-md font-medium text-paper transition-colors hover:bg-ink/85 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-ink"
          >
            <Save className="w-4 h-4" aria-hidden />
            {t('common.save')}
          </button>
        </div>
      </div>

      {/* Tree beside the editor only from xl; below that the tree sits on top, capped in
          height, so the editor keeps the full content width on tablets and phones. */}
      <div className="flex flex-col gap-4 xl:flex-row xl:items-stretch xl:min-h-[600px]">
        {/* Left: File Tree */}
        <div className="flex min-w-0 flex-col xl:w-72 xl:shrink-0">
          <div className="flex flex-1 flex-col overflow-hidden rounded-xl border border-line bg-paper">
            {/* Tree actions bar */}
            <div className="flex items-center gap-1 border-b border-line bg-inset px-1.5 py-1">
              <button
                onClick={() => { setShowAddMenu(true); setNewItemType('file'); }}
                className={iconButton}
                title={t('skills.editor.addFile')}
                aria-label={t('skills.editor.addFile')}
              >
                <Plus className="w-4 h-4" />
              </button>
              <button
                onClick={() => { setShowAddMenu(true); setNewItemType('folder'); }}
                className={iconButton}
                title={t('skills.editor.addFolder')}
                aria-label={t('skills.editor.addFolder')}
              >
                <FolderOpen className="w-4 h-4" />
              </button>
              <div className="w-px h-5 bg-line mx-1" />
              <button
                onClick={handleDeleteFile}
                disabled={!selectedPath}
                className={cn(
                  iconButton,
                  'hover:text-vermilion-ink hover:bg-vermilion-bg disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-ink-light'
                )}
                title={t('common.delete')}
                aria-label={t('common.delete')}
              >
                <Trash2 className="w-4 h-4" />
              </button>
            </div>

            {/* New item input */}
            <AnimatePresence>
              {showAddMenu && newItemType && (
                <motion.div
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: 'auto', opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="overflow-hidden border-b border-line"
                >
                  <div className="p-2 space-y-1.5">
                    <div className="px-0.5 font-mono text-mono-sm text-ink-muted truncate">
                      {t('skills.editor.creatingIn', {
                        path: targetDir || t('skills.editor.rootLevel'),
                      })}
                    </div>
                    <div className="flex items-center gap-1">
                    <input
                      type="text"
                      value={newItemName}
                      onChange={(e) => setNewItemName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') handleAddItem();
                        if (e.key === 'Escape') { setShowAddMenu(false); setNewItemType(null); }
                      }}
                      placeholder={newItemType === 'file' ? t('skills.editor.filePlaceholder') : t('skills.editor.folderPlaceholder')}
                      className={cn(
                        'min-w-0 flex-1 min-h-[40px] px-2.5 rounded-md font-mono text-mono-md text-ink bg-inset border border-line',
                        'placeholder:text-ink-muted focus:outline-none focus:border-terracotta focus:ring-2 focus:ring-terracotta/15'
                      )}
                      autoFocus
                    />
                    <button
                      onClick={handleAddItem}
                      className="w-10 h-10 shrink-0 inline-flex items-center justify-center rounded-md text-verdigris-ink hover:bg-verdigris-bg transition-colors"
                      aria-label={newItemType === 'file' ? t('skills.editor.addFile') : t('skills.editor.addFolder')}
                    >
                      <Check className="w-4 h-4" />
                    </button>
                    <button
                      onClick={() => { setShowAddMenu(false); setNewItemType(null); }}
                      className="w-10 h-10 shrink-0 inline-flex items-center justify-center rounded-md text-ink-muted hover:text-ink hover:bg-inset transition-colors"
                      aria-label={t('common.cancel')}
                    >
                      <X className="w-4 h-4" />
                    </button>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Tree */}
            <div className="max-h-[280px] flex-1 overflow-y-auto p-1.5 xl:max-h-none">
              {displayTree.map((node) => (
                <FileTreeNode
                  key={node.path}
                  node={node}
                  depth={0}
                  selectedPath={selectedPath}
                  onSelect={handleSelectFile}
                  onToggle={handleToggleFolder}
                />
              ))}
              {displayTree.length === 0 && (
                <div className="py-8 text-center font-body text-body-sm text-ink-muted">
                  {t('skills.editor.noFiles')}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Right: Code Editor */}
        <div className="flex min-w-0 flex-1 flex-col">
          {selectedFile ? (
            <div className="flex flex-1 flex-col overflow-hidden rounded-xl border border-line bg-paper">
              {/* Editor header */}
              <div className="flex min-h-[44px] items-center justify-between gap-3 border-b border-line bg-inset px-4 py-2">
                <div className="flex min-w-0 items-center gap-2 font-mono text-mono-md text-ink-light">
                  <FileText className="w-4 h-4 shrink-0 text-ink-muted" aria-hidden />
                  <span className="truncate">{selectedFile.path}</span>
                </div>
                <span className="shrink-0 rounded-full border border-line bg-paper px-2 py-0.5 font-mono text-mono-sm text-ink-muted">
                  {selectedFile.language || getLanguage(selectedFile.path)}
                </span>
              </div>

              {/* Editor textarea */}
              <textarea
                value={selectedFile.content ?? ''}
                onChange={(e) => handleContentChange(e.target.value)}
                spellCheck={false}
                aria-label={selectedFile.path}
                className={cn(
                  'block w-full flex-1 min-h-[420px] p-4 resize-y xl:resize-none outline-none',
                  'font-mono text-[14px] leading-[1.6] text-ink',
                  'bg-paper focus-visible:bg-paper',
                  'selection:bg-terracotta/20'
                )}
              />
            </div>
          ) : (
            <div className="flex flex-1 flex-col items-center justify-center rounded-xl border border-line bg-paper px-6 py-16 text-center">
              <span className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-inset text-ink-muted">
                <ScrollText className="h-6 w-6" strokeWidth={1.5} aria-hidden />
              </span>
              <h2 className="font-display text-[22px] font-medium text-ink">{t('skills.editor.selectFile')}</h2>
              <p className="mt-2 max-w-sm font-body text-body-md text-ink-light">{t('skills.editor.selectFileDesc')}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
