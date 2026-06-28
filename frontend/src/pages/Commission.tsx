// @ts-nocheck
import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { motion } from 'framer-motion';
import {
  Send,
  Bot,
  Lock,
  Loader2,
  CheckCircle2,
  Circle,
  Plus,
  X,
  Star,
  ArrowRight,
} from 'lucide-react';
import { useMockStore } from '@/store/mockStore';
import VellumPanel from '@/components/VellumPanel';
import PageTitle from '@/components/PageTitle';
import { cn } from '@/lib/utils';

// ─── Local Commission Session Types ──────────────────────────────────────────

interface CommissionMessage {
  id: string;
  role: 'patron' | 'leader' | 'system';
  content: string;
  timestamp: string;
}

interface LocalDraftTask {
  identifier: string;
  title: string;
  description: string;
  priority: 'P0' | 'P1' | 'P2';
  definitionOfDone: string;
  checklist: { text: string; checked: boolean }[];
  dueDate: string;
  workers: string[];
  dependencies: string[];
}

interface CommissionSession {
  id: string;
  projectId: string;
  messages: CommissionMessage[];
  draftTask: LocalDraftTask | null;
}

const INITIAL_COMMISSION: CommissionSession = {
  id: 'cs-1',
  projectId: 'p1',
  messages: [
    { id: 'msg-1', role: 'leader', content: 'Hello! I\'m Atlas, your Project Leader. What would you like us to work on?', timestamp: '2026-06-28T08:00:00Z' },
  ],
  draftTask: null,
};

// ─── Constants ───────────────────────────────────────────────────────────────

const LEADER_TURN_RESPONSES: Record<number, { content: string; draftTask?: LocalDraftTask }> = {
  1: {
    content: 'Got it. A few clarifying questions to make sure I scope this correctly:\n\n1. Should the dark mode toggle be system-preference-aware or manual only?\n2. Do you have a design system with tokens already, or should I include token creation in the scope?\n3. What\'s the deadline \u2014 is Friday EOD firm?',
  },
  2: {
    content: 'Perfect. I\'ve drafted ARM-44 based on your requirements. Take a look at the preview panel \u2014 I\'ve broken it into 6 checklist items, assigned Vega (FE) and Orion (BE), and set the due date to Friday. The dependency on ARM-40 (the WCAG audit) is included since we need those findings first. Let me know if you\'d like any adjustments!',
    draftTask: {
      identifier: 'ARM-44',
      title: 'Implement responsive navigation menu with system-aware dark mode toggle',
      description: 'Build a responsive navigation component with dark mode toggle that respects system preferences. Must pass WCAG AA contrast checks.',
      priority: 'P1',
      definitionOfDone: 'All WCAG AA contrast checks pass on the settings page. Dark mode toggle respects system preference and persists across sessions. Responsive breakpoints tested at 320px, 768px, 1024px, 1440px.',
      checklist: [
        { text: 'Audit current settings page', checked: false },
        { text: 'Implement dark mode toggle component', checked: false },
        { text: 'Add system preference detection', checked: false },
        { text: 'Run contrast audit tool', checked: false },
        { text: 'Write integration tests', checked: false },
        { text: 'Update user documentation', checked: false },
      ],
      dueDate: '2026-07-11',
      workers: ['m2', 'm3'],
      dependencies: ['t-2'],
    },
  },
  3: {
    content: 'Good call \u2014 I\'ll add a 7th item for responsive breakpoint testing and push the due date to Monday to give more buffer. Updated preview \u2192',
    draftTask: {
      identifier: 'ARM-44',
      title: 'Implement responsive navigation menu with system-aware dark mode toggle',
      description: 'Build a responsive navigation component with dark mode toggle that respects system preferences. Must pass WCAG AA contrast checks.',
      priority: 'P1',
      definitionOfDone: 'All WCAG AA contrast checks pass on the settings page. Dark mode toggle respects system preference and persists across sessions. Responsive breakpoints tested at 320px, 768px, 1024px, 1440px.',
      checklist: [
        { text: 'Audit current settings page', checked: false },
        { text: 'Implement dark mode toggle component', checked: false },
        { text: 'Add system preference detection', checked: false },
        { text: 'Run contrast audit tool', checked: false },
        { text: 'Write integration tests', checked: false },
        { text: 'Update user documentation', checked: false },
        { text: 'Test responsive breakpoints', checked: false },
      ],
      dueDate: '2026-07-14',
      workers: ['m2', 'm3'],
      dependencies: ['t-2'],
    },
  },
  4: {
    content: 'ARM-44 is live! I\'ve woken Vega and Orion with the full context. You\'ll see the task appear on the board shortly. I\'ll monitor progress and report back on any blockers.',
  },
};

// ─── Priority Colors ─────────────────────────────────────────────────────────

const PRIORITY_COLORS: Record<string, { bg: string; text: string }> = {
  P0: { bg: 'bg-terracotta/10', text: 'text-terracotta' },
  P1: { bg: 'bg-gold/10', text: 'text-gold' },
  P2: { bg: 'bg-ink-muted/10', text: 'text-ink-muted' },
};

// ─── Sub-components ──────────────────────────────────────────────────────────

function LeaderAvatar({ isThinking }: { isThinking: boolean }) {
  return (
    <div className="flex flex-col items-center gap-1 flex-shrink-0">
      <div
        className={cn(
          'w-8 h-8 rounded-full overflow-hidden border-2',
          isThinking
            ? 'border-gold animate-pulse'
            : 'border-gold-muted'
        )}
      >
        <img
          src="/agent-avatar-atlas.jpg"
          alt="Atlas"
          className="w-full h-full object-cover"
        />
      </div>
      <span className="font-body text-body-xs text-ink-light">Atlas</span>
    </div>
  );
}

function ChatMessage({
  role,
  content,
  timestamp,
  isThinking,
}: {
  role: 'patron' | 'leader' | 'system';
  content: string;
  timestamp: string;
  isThinking?: boolean;
}) {
  const { t } = useTranslation();

  if (role === 'system') {
    return (
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        className="flex items-center justify-center gap-3 my-3"
      >
        <span className="w-10 h-px bg-vellum-dark" />
        <span className="font-body text-body-xs text-ink-muted italic">
          {content}
        </span>
        <span className="w-10 h-px bg-vellum-dark" />
      </motion.div>
    );
  }

  const isPatron = role === 'patron';
  const timeAgo = formatTimeAgo(new Date(timestamp), t);

  return (
    <motion.div
      initial={isPatron ? { opacity: 0, y: 10 } : { opacity: 0, x: -15 }}
      animate={{ opacity: 1, x: 0, y: 0 }}
      transition={{ duration: 0.3, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
      className={cn(
        'flex gap-3 mb-4 group',
        isPatron ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      {/* Avatar (leader only) */}
      {!isPatron && <LeaderAvatar isThinking={isThinking ?? false} />}

      {/* Bubble */}
      <div
        className={cn(
          'relative max-w-[85%] px-4 py-3 font-body text-body-md',
          isPatron
            ? 'bg-terracotta text-white rounded-lg rounded-tr-sm'
            : 'bg-vellum-deep border border-vellum-dark rounded-lg rounded-tl-sm',
          isThinking && 'opacity-70'
        )}
      >
        {isThinking ? (
          <div className="flex items-center gap-2 text-ink-light">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span>{t('commission.thinking')}</span>
            <span className="flex gap-0.5">
              <span className="w-1 h-1 rounded-full bg-ink-muted animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-1 h-1 rounded-full bg-ink-muted animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-1 h-1 rounded-full bg-ink-muted animate-bounce" style={{ animationDelay: '300ms' }} />
            </span>
          </div>
        ) : (
          <div className={cn('whitespace-pre-wrap', !isPatron && 'text-ink')}>
            {content}
          </div>
        )}

        {/* Timestamp on hover */}
        <div
          className={cn(
            'absolute top-full mt-1 font-body text-body-xs text-ink-muted opacity-0 group-hover:opacity-100 transition-opacity',
            isPatron ? 'right-0' : 'left-0'
          )}
        >
          {timeAgo}
        </div>
      </div>
    </motion.div>
  );
}

function formatTimeAgo(date: Date, _t: (key: string) => string): string {
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return 'Just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ─── Task Preview Pane ───────────────────────────────────────────────────────

function TaskPreview({
  draftTask,
  onUpdate,
}: {
  draftTask: LocalDraftTask | null;
  onUpdate: (task: LocalDraftTask) => void;
}) {
  const { t } = useTranslation();
  const mariuses = useMockStore((s) => s.mariuses);
  const tasks = useMockStore((s) => s.tasks);

  if (!draftTask) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-8">
        <Bot className="w-12 h-12 text-ink-muted mb-4" strokeWidth={1.5} />
        <p className="font-body text-body-md text-ink-light mb-1">
          {t('commission.emptyPreviewTitle')}
        </p>
        <p className="font-body text-body-sm text-ink-muted">
          {t('commission.emptyPreviewDescription')}
        </p>
      </div>
    );
  }

  const handleChecklistToggle = (index: number) => {
    const newChecklist = draftTask.checklist.map((item, i) =>
      i === index ? { ...item, checked: !item.checked } : item
    );
    onUpdate({ ...draftTask, checklist: newChecklist });
  };

  const handleAddChecklistItem = () => {
    onUpdate({
      ...draftTask,
      checklist: [...draftTask.checklist, { text: '', checked: false }],
    });
  };

  const handleRemoveChecklistItem = (index: number) => {
    onUpdate({
      ...draftTask,
      checklist: draftTask.checklist.filter((_, i) => i !== index),
    });
  };

  const handleUpdateChecklistText = (index: number, text: string) => {
    const newChecklist = draftTask.checklist.map((item, i) =>
      i === index ? { ...item, text } : item
    );
    onUpdate({ ...draftTask, checklist: newChecklist });
  };

  const toggleWorker = (mariusId: string) => {
    const has = draftTask.workers.includes(mariusId);
    onUpdate({
      ...draftTask,
      workers: has
        ? draftTask.workers.filter((w) => w !== mariusId)
        : [...draftTask.workers, mariusId],
    });
  };

  const removeDependency = (depId: string) => {
    onUpdate({
      ...draftTask,
      dependencies: draftTask.dependencies.filter((d) => d !== depId),
    });
  };

  const selectedWorkers = mariuses.filter((m) => draftTask.workers.includes(m.id));
  const availableWorkers = mariuses.filter(
    (m) => m.status !== 'invited' && m.status !== 'pending' && m.status !== 'revoked'
  );

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
      className="flex flex-col h-full overflow-y-auto"
    >
      {/* Identifier */}
      <div className="mb-4">
        <span className="font-mono text-mono-md text-terracotta">
          {draftTask.identifier}
        </span>
        <span className="ml-2 font-body text-body-xs text-ink-muted">(draft)</span>
      </div>

      <hr className="border-vellum-dark mb-4" />

      {/* Title */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('commission.fieldLabels.title')}
        </label>
        <input
          type="text"
          value={draftTask.title}
          onChange={(e) => onUpdate({ ...draftTask, title: e.target.value })}
          className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors"
        />
      </div>

      {/* Description */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('commission.fieldLabels.description')}
        </label>
        <textarea
          value={draftTask.description || ''}
          onChange={(e) => onUpdate({ ...draftTask, description: e.target.value })}
          rows={3}
          className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors resize-none"
        />
      </div>

      {/* Priority */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('commission.fieldLabels.priority')}
        </label>
        <select
          value={draftTask.priority}
          onChange={(e) => onUpdate({ ...draftTask, priority: e.target.value as 'P0' | 'P1' | 'P2' })}
          className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors appearance-none cursor-pointer"
        >
          {['P0', 'P1', 'P2'].map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      {/* Definition of Done */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('commission.fieldLabels.definitionOfDone')}
        </label>
        <textarea
          value={draftTask.definitionOfDone}
          onChange={(e) => onUpdate({ ...draftTask, definitionOfDone: e.target.value })}
          rows={3}
          className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors resize-none"
        />
      </div>

      {/* Checklist */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-2">
          {t('commission.fieldLabels.checklist')}
        </label>
        <div className="space-y-1.5">
          {draftTask.checklist.map((item, index) => (
            <motion.div
              key={index}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.04, duration: 0.2 }}
              className="flex items-center gap-2 group"
            >
              <button
                onClick={() => handleChecklistToggle(index)}
                className="flex-shrink-0 text-ink-muted hover:text-terracotta transition-colors"
              >
                {item.checked ? (
                  <CheckCircle2 className="w-4 h-4 text-success" />
                ) : (
                  <Circle className="w-4 h-4" />
                )}
              </button>
              <input
                type="text"
                value={item.text}
                onChange={(e) => handleUpdateChecklistText(index, e.target.value)}
                className={cn(
                  'flex-1 bg-transparent font-body text-body-sm focus:outline-none border-b border-transparent focus:border-terracotta/30 transition-colors',
                  item.checked && 'line-through text-ink-muted'
                )}
              />
              <button
                onClick={() => handleRemoveChecklistItem(index)}
                className="opacity-0 group-hover:opacity-100 text-ink-muted hover:text-error transition-all"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </motion.div>
          ))}
          <button
            onClick={handleAddChecklistItem}
            className="flex items-center gap-1.5 text-ink-muted hover:text-terracotta transition-colors font-body text-body-sm mt-2"
          >
            <Plus className="w-3.5 h-3.5" />
            {t('commission.addItem')}
          </button>
        </div>
      </div>

      {/* Due Date */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-1">
          {t('commission.fieldLabels.dueDate')}
        </label>
        <input
          type="date"
          value={draftTask.dueDate}
          onChange={(e) => onUpdate({ ...draftTask, dueDate: e.target.value })}
          className="w-full px-3 py-2 bg-vellum border border-vellum-dark rounded-md font-body text-body-md text-ink focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors"
        />
      </div>

      {/* Workers */}
      <div className="mb-4">
        <label className="block font-body text-body-sm font-medium text-ink mb-2">
          {t('commission.fieldLabels.workers')}
        </label>
        <div className="flex flex-wrap gap-2">
          {selectedWorkers.map((w) => (
            <span
              key={w.id}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-vellum border border-vellum-dark font-body text-body-sm text-ink"
            >
              <img src={w.avatar} alt={w.displayName || w.name} className="w-4 h-4 rounded-full object-cover" />
              {w.displayName || w.name}
              <button
                onClick={() => toggleWorker(w.id)}
                className="ml-0.5 text-ink-muted hover:text-error"
              >
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
        {/* Worker selector */}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {availableWorkers
            .filter((w) => !draftTask.workers.includes(w.id))
            .map((w) => (
              <button
                key={w.id}
                onClick={() => toggleWorker(w.id)}
                className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-dashed border-vellum-dark hover:border-terracotta hover:bg-terracotta/5 font-body text-body-xs text-ink-light hover:text-terracotta transition-colors"
              >
                <span className={cn('w-1.5 h-1.5 rounded-full', w.status === 'online' || w.status === 'working' ? 'bg-status-online' : 'bg-status-offline')} />
                + {w.displayName || w.name}
              </button>
            ))}
        </div>
      </div>

      {/* Dependencies */}
      <div className="mb-6">
        <label className="block font-body text-body-sm font-medium text-ink mb-2">
          {t('commission.fieldLabels.dependencies')}
        </label>
        <div className="flex flex-wrap gap-2">
          {draftTask.dependencies.map((depId) => {
            const depTask = tasks.find((t) => t.id === depId);
            return (
              <span
                key={depId}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-vellum-deep border border-vellum-dark font-mono text-mono-sm text-ink"
              >
                {depTask?.identifier || depId}
                <button
                  onClick={() => removeDependency(depId)}
                  className="text-ink-muted hover:text-error"
                >
                  <X className="w-3 h-3" />
                </button>
              </span>
            );
          })}
        </div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {tasks
            .filter((t) => !draftTask.dependencies.includes(t.id) && t.id !== 't-new')
            .map((t) => (
              <button
                key={t.id}
                onClick={() =>
                  onUpdate({ ...draftTask, dependencies: [...draftTask.dependencies, t.id] })
                }
                className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-dashed border-vellum-dark hover:border-terracotta hover:bg-terracotta/5 font-mono text-mono-sm text-ink-light hover:text-terracotta transition-colors"
              >
                + {t.identifier}
              </button>
            ))}
        </div>
      </div>
    </motion.div>
  );
}

// ─── Main Commission Page ────────────────────────────────────────────────────

export default function Commission() {
  const { id: projectId } = useParams<{ id: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const store = useMockStore();

  // Local state for commission session (store doesn't have commission support)
  const [session, setSession] = useState<CommissionSession>(INITIAL_COMMISSION);
  const [messages, setMessages] = useState<CommissionMessage[]>(INITIAL_COMMISSION.messages);
  const [draftTask, setDraftTask] = useState<LocalDraftTask | null>(null);

  const project = store.projects.find((p) => p.id === projectId);
  // Find leader by looking for a marius with role containing "Leader" in the project
  const leader = store.mariuses.find((m) => m.projectIds.includes(projectId || '') && m.role.toLowerCase().includes('leader'));

  const [inputValue, setInputValue] = useState('');
  const [isThinking, setIsThinking] = useState(false);
  const [isConfirming, setIsConfirming] = useState(false);
  const [turnCount, setTurnCount] = useState(2);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, isThinking]);

  const addMessage = useCallback((msg: Omit<CommissionMessage, 'id' | 'timestamp'>) => {
    const newMsg: CommissionMessage = {
      ...msg,
      id: `msg-${Date.now()}`,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, newMsg]);
    setSession((prev) => ({ ...prev, messages: [...prev.messages, newMsg] }));
  }, []);

  const handleSend = useCallback(() => {
    if (!inputValue.trim()) return;

    // Send patron message
    addMessage({
      role: 'patron',
      content: inputValue.trim(),
    });

    const sentInput = inputValue.trim();
    setInputValue('');

    // Mock leader response
    setIsThinking(true);
    const responseDelay = 1200 + Math.random() * 800;

    setTimeout(() => {
      setIsThinking(false);

      const response = LEADER_TURN_RESPONSES[turnCount];
      if (response) {
        addMessage({
          role: 'leader',
          content: response.content,
        });
        if (response.draftTask) {
          setDraftTask(response.draftTask);
          setSession((prev) => ({ ...prev, draftTask: response.draftTask || null }));
        }
        setTurnCount((prev) => prev + 1);
      } else {
        // Generic response after scripted turns
        addMessage({
          role: 'leader',
          content: `I've noted that: "${sentInput.substring(0, 60)}${sentInput.length > 60 ? '...' : ''}". Let me know if you'd like any changes to the task preview.`,
        });
      }
    }, responseDelay);
  }, [inputValue, addMessage, turnCount]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleRefine = () => {
    setInputValue('Please revise: ');
    textareaRef.current?.focus();
  };

  const handleConfirm = async () => {
    if (!draftTask) return;

    setIsConfirming(true);

    // Simulate creation delay
    await new Promise((resolve) => setTimeout(resolve, 1000));

    // Create the task in the store using createTask
    store.createTask({
      title: draftTask.title,
      description: draftTask.description,
      priority: draftTask.priority,
      projectId: projectId || 'p1',
      status: 'pending',
      identifier: draftTask.identifier,
      definitionOfDone: draftTask.definitionOfDone,
      checklist: draftTask.checklist.map((item, i) => ({
        id: `chk-${i}`,
        text: item.text,
        done: item.checked,
      })),
      dependencies: draftTask.dependencies,
    });

    // Add confirmation system message
    addMessage({
      role: 'system',
      content: `${draftTask.identifier} has been created and assigned.`,
    });

    setIsConfirming(false);

    // Navigate to board
    navigate(`/projects/${projectId}`);
  };

  // ─── Locked state ───
  if (project?.status === 'setup') {
    return (
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="flex items-center justify-center min-h-[60vh]"
      >
        <VellumPanel className="max-w-md w-full text-center py-16 px-8">
          <motion.div
            animate={{ y: [0, -4, 0] }}
            transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }}
          >
            <Lock className="w-16 h-16 text-ink-muted mx-auto mb-6" strokeWidth={1.5} />
          </motion.div>
          <h2 className="font-display text-display-md text-ink mb-3">
            {t('commission.lockedTitle')}
          </h2>
          <p className="font-body text-body-lg text-ink-light mb-8">
            {t('commission.lockedDescription')}
          </p>
          <button
            onClick={() => navigate(`/projects/${projectId}/roster`)}
            className="inline-flex items-center gap-2 px-6 py-3 rounded-md bg-terracotta text-white font-body text-body-md font-medium hover:bg-terracotta-light transition-colors"
          >
            {t('commission.goToRoster')}
            <ArrowRight className="w-4 h-4" />
          </button>
        </VellumPanel>
      </motion.div>
    );
  }

  return (
    <div className="flex flex-col h-[calc(100dvh-140px)] -m-6">
      {/* ─── Page Header ─── */}
      <motion.div
        initial={{ opacity: 0, y: 24, filter: 'blur(2px)' }}
        animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }}
        transition={{ duration: 0.5, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
        className="px-6 pt-6 pb-4 flex-shrink-0"
      >
        <div className="flex items-center gap-3">
          <PageTitle
            title={t('commission.title')}
            subtitle={t('commission.subtitle', { leaderName: leader?.displayName || 'Atlas' })}
          />
        </div>
      </motion.div>

      {/* ─── Two-Pane Layout ─── */}
      <div className="flex flex-1 min-h-0 px-6 pb-6 gap-4">
        {/* Left: Chat (60%) */}
        <motion.div
          initial={{ opacity: 0, x: -20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
          className="flex-[58] flex flex-col min-h-0 bg-vellum border border-vellum-dark rounded-md overflow-hidden"
        >
          {/* Messages */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            {messages.map((msg) => (
              <ChatMessage
                key={msg.id}
                role={msg.role}
                content={msg.content}
                timestamp={msg.timestamp}
                isThinking={false}
              />
            ))}
            {isThinking && (
              <ChatMessage
                role="leader"
                content=""
                timestamp={new Date().toISOString()}
                isThinking={true}
              />
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Composer */}
          <div className="flex-shrink-0 border-t border-vellum-dark bg-vellum-deep px-4 py-3">
            <div className="flex items-end gap-2">
              <textarea
                ref={textareaRef}
                value={inputValue}
                onChange={(e) => setInputValue(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={t('commission.placeholder')}
                rows={1}
                className="flex-1 resize-none px-4 py-2.5 bg-vellum border border-vellum-dark rounded-lg font-body text-body-md text-ink placeholder:text-ink-muted focus:border-terracotta focus:outline-none focus:ring-2 focus:ring-terracotta/15 transition-colors max-h-[120px]"
                style={{ minHeight: '40px' }}
              />
              <motion.button
                whileTap={{ scale: 0.95 }}
                onClick={handleSend}
                disabled={!inputValue.trim() || isThinking}
                className={cn(
                  'w-9 h-9 rounded-full flex items-center justify-center flex-shrink-0 transition-colors',
                  inputValue.trim() && !isThinking
                    ? 'bg-terracotta text-white hover:bg-terracotta-light'
                    : 'bg-vellum-dark text-ink-muted cursor-not-allowed'
                )}
              >
                <Send className="w-4 h-4" />
              </motion.button>
            </div>
          </div>
        </motion.div>

        {/* Right: Task Preview (40%) */}
        <motion.div
          initial={{ opacity: 0, x: 20 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ duration: 0.4, delay: 0.1, ease: [0, 0, 0.2, 1] as [number, number, number, number] }}
          className="flex-[42] flex flex-col min-h-0 bg-vellum-deep border border-vellum-dark rounded-md overflow-hidden"
        >
          {/* Preview Header */}
          <div className="flex-shrink-0 flex items-center justify-between px-4 py-3 border-b border-vellum-dark">
            <h2 className="font-display text-display-sm text-ink">
              {t('commission.previewTitle')}
            </h2>
            {draftTask && (
              <span className={cn('inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-body text-body-xs font-medium', PRIORITY_COLORS[draftTask?.priority || 'P1']?.bg, PRIORITY_COLORS[draftTask?.priority || 'P1']?.text)}>
                <Star className="w-3 h-3" />
                {draftTask.priority}
              </span>
            )}
          </div>

          {/* Preview Content */}
          <div className="flex-1 overflow-y-auto px-4 py-4">
            <TaskPreview
              draftTask={draftTask}
              onUpdate={(updated) => {
                setDraftTask(updated);
                setSession((prev) => ({ ...prev, draftTask: updated }));
              }}
            />
          </div>

          {/* Action Buttons */}
          {draftTask && (
            <motion.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="flex-shrink-0 flex gap-3 px-4 py-3 border-t border-vellum-dark"
            >
              <button
                onClick={handleRefine}
                disabled={isConfirming}
                className="flex-1 px-4 py-2.5 rounded-md font-body text-body-md font-medium bg-vellum-deep text-ink border border-vellum-dark hover:bg-vellum-dark transition-colors disabled:opacity-50"
              >
                {t('commission.refine')}
              </button>
              <button
                onClick={handleConfirm}
                disabled={isConfirming || !draftTask.title}
                className={cn(
                  'flex-[2] px-4 py-2.5 rounded-md font-body text-body-md font-medium transition-colors inline-flex items-center justify-center gap-2',
                  isConfirming
                    ? 'bg-gold-muted text-ink cursor-wait'
                    : 'bg-gold text-ink hover:bg-gold-light'
                )}
              >
                {isConfirming ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Creating...
                  </>
                ) : (
                  <>
                    <Star className="w-4 h-4" />
                    {t('commission.confirm')}
                  </>
                )}
              </button>
            </motion.div>
          )}
        </motion.div>
      </div>
    </div>
  );
}
