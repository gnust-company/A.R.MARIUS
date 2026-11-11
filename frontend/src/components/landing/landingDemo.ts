/*
 * The landing page's scripted demo: one agent takes a task, works on it, brings the result to
 * the visitor's inbox and waits there until the visitor decides.
 *
 * This is an illustration on scripted data, never a live workspace, and the page says so next to
 * it. One instance drives both the WebGL scene (where the agent is) and the DOM panel (what the
 * inbox shows), so the two cannot disagree. No React and no three.js in here.
 */

export type DemoPhase = 'idle' | 'claim' | 'work' | 'walk' | 'waiting' | 'approved' | 'returned';

export interface DemoSnapshot {
  phase: DemoPhase;
  /** Index of the scripted task in play. The code and title on screen derive from it. */
  task: number;
  /** How many times the task in play was sent back. */
  revision: number;
  /** Totals since the page opened. */
  approved: number;
  sentBack: number;
}

/** Scripted names. Proper nouns, the same in every language. */
export const DEMO_AGENT = 'Livia';
export const DEMO_TASK_TITLES = 3;
const FIRST_TASK_NUMBER = 14;

export function demoTaskCode(task: number): string {
  return `NOCT-${FIRST_TASK_NUMBER + task}`;
}

/** How long each timed phase lasts, in milliseconds. `idle` and `waiting` have no clock. */
export const PHASE_MS: Record<DemoPhase, number> = {
  idle: 0,
  claim: 2400,
  work: 5200,
  walk: 3600,
  waiting: 0,
  approved: 3600,
  returned: 3600,
};

const NEXT: Partial<Record<DemoPhase, DemoPhase>> = {
  claim: 'work',
  work: 'walk',
  walk: 'waiting',
  approved: 'claim',
  returned: 'work',
};

export class LandingDemo {
  private snapshot: DemoSnapshot = { phase: 'idle', task: 0, revision: 0, approved: 0, sentBack: 0 };
  private readonly listeners = new Set<() => void>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private running = false;
  /** Milliseconds of the current phase played before the last pause. */
  private played = 0;
  private resumedAt = 0;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getSnapshot = () => this.snapshot;

  /** The script only advances while the demo is on screen in a visible tab. */
  setRunning(running: boolean) {
    if (running === this.running) return;
    if (!running) {
      this.played = this.elapsed();
      this.running = false;
      this.clear();
      return;
    }
    this.running = true;
    this.resumedAt = Date.now();
    if (this.snapshot.phase === 'idle') this.enter('claim');
    else this.schedule();
  }

  /** How far the current phase has played, 0–1. Phases without a clock read as complete. */
  progress(): number {
    const length = PHASE_MS[this.snapshot.phase];
    return length ? Math.min(Math.max(this.elapsed() / length, 0), 1) : 1;
  }

  /** The visitor's decision. Only meaningful while the agent is waiting; otherwise ignored. */
  approve() {
    if (this.snapshot.phase !== 'waiting') return;
    this.enter('approved', { approved: this.snapshot.approved + 1 });
  }

  sendBack() {
    if (this.snapshot.phase !== 'waiting') return;
    this.enter('returned', { sentBack: this.snapshot.sentBack + 1, revision: this.snapshot.revision + 1 });
  }

  private elapsed(): number {
    return this.played + (this.running ? Date.now() - this.resumedAt : 0);
  }

  private enter(phase: DemoPhase, patch: Partial<DemoSnapshot> = {}) {
    this.snapshot = { ...this.snapshot, ...patch, phase };
    this.played = 0;
    this.resumedAt = Date.now();
    this.listeners.forEach((listener) => listener());
    this.schedule();
  }

  private schedule() {
    this.clear();
    if (!this.running) return;
    const { phase } = this.snapshot;
    const next = NEXT[phase];
    if (!next) return;
    this.timer = setTimeout(() => {
      this.timer = null;
      // An approved task is finished: the agent picks up the next one with a clean slate.
      if (phase === 'approved') this.enter(next, { task: this.snapshot.task + 1, revision: 0 });
      else this.enter(next);
    }, Math.max(PHASE_MS[phase] - this.played, 0));
  }

  private clear() {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
  }
}
