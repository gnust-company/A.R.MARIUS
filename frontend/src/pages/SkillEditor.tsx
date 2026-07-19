// @ts-nocheck
import { useState, useMemo, useCallback, useEffect } from 'react';
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
  Wrench,
  ArrowLeft,
  X,
  Check,
  ScrollText,
} from 'lucide-react';
import { useAppStore } from '@/store/appStore';
import type { SkillFile } from '@/store/appStore';
import VellumPanel from '@/components/VellumPanel';
import EmptyState from '@/components/EmptyState';
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
  const paddingLeft = 12 + depth * 20;

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
          className={cn(
            'w-full flex items-center gap-1.5 py-1.5 pr-2 text-left transition-colors hover:bg-[#EDE4CE]',
            isSelected && 'bg-[#EDE4CE] border-l-[3px] border-[#D4A843]'
          )}
          style={{ paddingLeft: isSelected ? paddingLeft - 3 : paddingLeft }}
        >
          <motion.span
            animate={{ rotate: node.expanded ? 90 : 0 }}
            transition={{ duration: 0.2 }}
            className="flex-shrink-0"
          >
            <ChevronRight className="w-3 h-3 text-[#A89880]" />
          </motion.span>
          {node.expanded ? (
            <FolderOpen className="w-4 h-4 text-[#D4A843] flex-shrink-0" />
          ) : (
            <Folder className="w-4 h-4 text-[#D4A843] flex-shrink-0" />
          )}
          <span className="font-mono text-[13px] text-[#2A2318] truncate">{node.name}</span>
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
      className={cn(
        'w-full flex items-center gap-2 py-1.5 pr-2 text-left transition-colors',
        isSelected
          ? 'bg-[#EDE4CE] border-l-[3px] border-[#C25E3A]'
          : 'hover:bg-[#EDE4CE] border-l-[3px] border-transparent'
      )}
      style={{ paddingLeft: paddingLeft + 3 }}
    >
      <FileText
        className={cn(
          'w-3.5 h-3.5 flex-shrink-0',
          isSelected ? 'text-[#C25E3A]' : 'text-[#A89880]'
        )}
      />
      <span
        className={cn(
          'font-mono text-[13px] truncate',
          isSelected ? 'text-[#C25E3A] font-medium' : 'text-[#2A2318]'
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
  // hydration). Keyed on id only, so it never clobbers unsaved edits mid-session.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (skill) {
      setDraftFiles(skill.files);
      setHasChanges(false);
      setSelectedIsFolder(false);
    }
  }, [skill?.id]);

  // ── Build Tree ─────────────────────────────────────────────────────────────
  const tree = useMemo(() => buildTree(draftFiles), [draftFiles]);

  // ── Auto-select first file on load ─────────────────────────────────────────
  useEffect(() => {
    if (draftFiles.length > 0 && !selectedPath) {
      setSelectedPath(draftFiles[0].path);
    }
  }, [draftFiles, selectedPath]);

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
  const applyExpanded = (nodes: TreeNode[]): TreeNode[] => {
    return nodes.map((n) => ({
      ...n,
      expanded: n.type === 'folder' ? expandedFolders.has(n.path) : undefined,
      children: n.children ? applyExpanded(n.children) : undefined,
    }));
  };

  const displayTree = useMemo(() => applyExpanded(tree), [tree, expandedFolders]);

  // ── Loading / Not Found ────────────────────────────────────────────────────
  if (!skill) {
    return (
      <div className="min-h-[100dvh] flex items-center justify-center">
        <EmptyState
          icon={ScrollText}
          title={t('skills.editor.notFound')}
          description={t('skills.editor.notFoundDesc')}
          action={
            <button
              onClick={() => navigate(wsHref(workspaceId, '/skills'))}
              className={cn(
                'inline-flex items-center gap-2 px-5 py-2.5 rounded-md text-[15px] font-medium',
                'bg-[#C25E3A] text-white hover:bg-[#D97B5A] transition-all'
              )}
            >
              <ArrowLeft className="w-4 h-4" />
              {t('skills.editor.backToSkills')}
            </button>
          }
        />
      </div>
    );
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-[100dvh] flex flex-col">
      {/* Header */}
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        className="flex items-center justify-between mb-4 flex-shrink-0"
      >
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(wsHref(workspaceId, '/skills'))}
            className="p-2 rounded-md text-[#6B5E4E] hover:text-[#2A2318] hover:bg-[#EDE4CE] transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div>
            <div className="flex items-center gap-2">
              <Wrench className="w-5 h-5 text-[#D4A843]" />
              <h1 className="font-['Fraunces',Georgia,serif] text-[28px] font-semibold text-[#2A2318] leading-tight">
                {skill.name}
              </h1>
            </div>
            {skill.description && (
              <p className="text-[13px] text-[#6B5E4E] mt-0.5">{skill.description}</p>
            )}
          </div>
        </div>

        {/* Editor actions */}
        <div className="flex items-center gap-2">
          {hasChanges && (
            <motion.span
              initial={{ opacity: 0, scale: 0.8 }}
              animate={{ opacity: 1, scale: 1 }}
              className="text-[11px] text-[#C25E3A] font-medium mr-2"
            >
              {t('skills.editor.unsaved')}
            </motion.span>
          )}
          <button
            onClick={handleSave}
            disabled={!hasChanges}
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-[13px] font-medium transition-all',
              hasChanges
                ? 'bg-[#C25E3A] text-white hover:bg-[#D97B5A]'
                : 'bg-[#E3D7BC] text-[#A89880] cursor-not-allowed'
            )}
          >
            <Save className="w-3.5 h-3.5" />
            {t('common.save')}
          </button>
          <button
            onClick={handleDiscard}
            disabled={!hasChanges}
            className={cn(
              'inline-flex items-center gap-1.5 px-3 py-2 rounded-md text-[13px] font-medium transition-all',
              hasChanges
                ? 'bg-[#EDE4CE] text-[#2A2318] border border-[#E3D7BC] hover:bg-[#E3D7BC]'
                : 'bg-[#E3D7BC] text-[#A89880] cursor-not-allowed'
            )}
          >
            <RotateCcw className="w-3.5 h-3.5" />
            {t('skills.editor.discard')}
          </button>
        </div>
      </motion.div>

      {/* Two-pane layout */}
      <div className="flex flex-1 gap-4 min-h-0">
        {/* Left: File Tree */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.3, delay: 0.1 }}
          className="w-72 flex-shrink-0 flex flex-col"
        >
          <VellumPanel className="flex-1 flex flex-col p-0 overflow-hidden" hover={false}>
            {/* Tree actions bar */}
            <div className="flex items-center gap-1 p-2 border-b border-[#E3D7BC]">
              <button
                onClick={() => { setShowAddMenu(true); setNewItemType('file'); }}
                className="p-1.5 rounded-md text-[#6B5E4E] hover:text-[#2A2318] hover:bg-[#EDE4CE] transition-colors"
                title={t('skills.editor.addFile')}
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => { setShowAddMenu(true); setNewItemType('folder'); }}
                className="p-1.5 rounded-md text-[#6B5E4E] hover:text-[#2A2318] hover:bg-[#EDE4CE] transition-colors"
                title={t('skills.editor.addFolder')}
              >
                <FolderOpen className="w-3.5 h-3.5" />
              </button>
              <div className="w-px h-4 bg-[#E3D7BC] mx-1" />
              <button
                onClick={handleDeleteFile}
                disabled={!selectedPath}
                className={cn(
                  'p-1.5 rounded-md transition-colors',
                  selectedPath
                    ? 'text-[#6B5E4E] hover:text-[#8B3A28] hover:bg-[#F5DDD6]'
                    : 'text-[#A89880] cursor-not-allowed'
                )}
                title={t('common.delete')}
              >
                <Trash2 className="w-3.5 h-3.5" />
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
                  className="overflow-hidden border-b border-[#E3D7BC]"
                >
                  <div className="p-2 space-y-1.5">
                    <div className="px-0.5 font-mono text-[10px] text-[#A89880] truncate">
                      {t('skills.editor.creatingIn', {
                        path: targetDir || t('skills.editor.rootLevel'),
                      })}
                    </div>
                    <div className="flex items-center gap-2">
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
                        'flex-1 px-2 py-1 rounded text-[12px] font-mono bg-[#F7F0E0] border border-[#E3D7BC]',
                        'focus:outline-none focus:border-[#C25E3A]'
                      )}
                      autoFocus
                    />
                    <button
                      onClick={handleAddItem}
                      className="p-1 rounded text-[#4A9E6B] hover:bg-[#D8EADD] transition-colors"
                    >
                      <Check className="w-3.5 h-3.5" />
                    </button>
                    <button
                      onClick={() => { setShowAddMenu(false); setNewItemType(null); }}
                      className="p-1 rounded text-[#8B7A6A] hover:bg-[#E8E0D8] transition-colors"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {/* Tree */}
            <div className="flex-1 overflow-y-auto py-1">
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
                <div className="text-center py-8 text-[12px] text-[#A89880]">
                  {t('skills.editor.noFiles')}
                </div>
              )}
            </div>
          </VellumPanel>
        </motion.div>

        {/* Right: Code Editor */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3, delay: 0.2 }}
          className="flex-1 flex flex-col min-w-0"
        >
          {selectedFile ? (
            <VellumPanel className="flex-1 flex flex-col p-0 overflow-hidden" hover={false}>
              {/* Editor header */}
              <div className="flex items-center justify-between px-4 py-2 border-b border-[#E3D7BC] bg-[#F7F0E0]">
                <div className="flex items-center gap-2 text-[12px] font-mono text-[#6B5E4E]">
                  <FileText className="w-3.5 h-3.5 text-[#A89880]" />
                  <span className="truncate">{selectedFile.path}</span>
                </div>
                <span className="text-[11px] font-mono text-[#A89880] px-2 py-0.5 rounded bg-[#EDE4CE]">
                  {selectedFile.language || getLanguage(selectedFile.path)}
                </span>
              </div>

              {/* Editor textarea */}
              <div className="flex-1 relative">
                <textarea
                  value={selectedFile.content ?? ''}
                  onChange={(e) => handleContentChange(e.target.value)}
                  spellCheck={false}
                  className={cn(
                    'w-full h-full p-4 resize-none outline-none',
                    'font-mono text-[14px] leading-[1.6] text-[#2A2318]',
                    'bg-[#F7F0E0]',
                    'selection:bg-[#C25E3A]/20'
                  )}
                />
              </div>
            </VellumPanel>
          ) : (
            <VellumPanel className="flex-1 flex items-center justify-center" hover={false}>
              <EmptyState
                icon={ScrollText}
                title={t('skills.editor.selectFile')}
                description={t('skills.editor.selectFileDesc')}
              />
            </VellumPanel>
          )}
        </motion.div>
      </div>
    </div>
  );
}
