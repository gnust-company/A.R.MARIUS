import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { LandingDemo, PHASE_MS, demoTaskCode } from './landingDemo';

describe('LandingDemo', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  const toWaiting = (demo: LandingDemo) => {
    vi.advanceTimersByTime(PHASE_MS.claim + PHASE_MS.work + PHASE_MS.walk);
    expect(demo.getSnapshot().phase).toBe('waiting');
  };

  it('does nothing until it is on screen', () => {
    const demo = new LandingDemo();
    vi.advanceTimersByTime(60_000);
    expect(demo.getSnapshot().phase).toBe('idle');
  });

  it('plays claim, work and walk, then waits for the visitor without a clock', () => {
    const demo = new LandingDemo();
    demo.setRunning(true);
    expect(demo.getSnapshot().phase).toBe('claim');
    vi.advanceTimersByTime(PHASE_MS.claim);
    expect(demo.getSnapshot().phase).toBe('work');
    vi.advanceTimersByTime(PHASE_MS.work);
    expect(demo.getSnapshot().phase).toBe('walk');
    vi.advanceTimersByTime(PHASE_MS.walk);
    expect(demo.getSnapshot().phase).toBe('waiting');
    vi.advanceTimersByTime(10 * 60_000);
    expect(demo.getSnapshot().phase).toBe('waiting');
  });

  it('approving finishes the task and moves on to the next one', () => {
    const demo = new LandingDemo();
    demo.setRunning(true);
    toWaiting(demo);
    demo.approve();
    expect(demo.getSnapshot()).toMatchObject({ phase: 'approved', approved: 1, task: 0 });
    vi.advanceTimersByTime(PHASE_MS.approved);
    expect(demo.getSnapshot()).toMatchObject({ phase: 'claim', task: 1, revision: 0 });
    expect(demoTaskCode(demo.getSnapshot().task)).toBe('NOCT-15');
  });

  it('sending back returns the same task for rework, then asks again', () => {
    const demo = new LandingDemo();
    demo.setRunning(true);
    toWaiting(demo);
    demo.sendBack();
    expect(demo.getSnapshot()).toMatchObject({ phase: 'returned', sentBack: 1, revision: 1, task: 0 });
    vi.advanceTimersByTime(PHASE_MS.returned);
    expect(demo.getSnapshot().phase).toBe('work');
    vi.advanceTimersByTime(PHASE_MS.work + PHASE_MS.walk);
    expect(demo.getSnapshot()).toMatchObject({ phase: 'waiting', task: 0, revision: 1 });
  });

  it('ignores a decision when nothing is waiting', () => {
    const demo = new LandingDemo();
    demo.setRunning(true);
    demo.approve();
    demo.sendBack();
    expect(demo.getSnapshot()).toMatchObject({ phase: 'claim', approved: 0, sentBack: 0 });
  });

  it('pauses mid-phase and resumes from where it stopped', () => {
    const demo = new LandingDemo();
    demo.setRunning(true);
    vi.advanceTimersByTime(PHASE_MS.claim + 1000);
    demo.setRunning(false);
    const paused = demo.progress();
    vi.advanceTimersByTime(60_000);
    expect(demo.getSnapshot().phase).toBe('work');
    expect(demo.progress()).toBe(paused);
    demo.setRunning(true);
    vi.advanceTimersByTime(PHASE_MS.work - 1000 - 1);
    expect(demo.getSnapshot().phase).toBe('work');
    vi.advanceTimersByTime(1);
    expect(demo.getSnapshot().phase).toBe('walk');
  });

  it('notifies subscribers on every phase change, and not at all while paused', () => {
    const demo = new LandingDemo();
    const listener = vi.fn();
    const unsubscribe = demo.subscribe(listener);
    demo.setRunning(true);
    vi.advanceTimersByTime(PHASE_MS.claim);
    expect(listener).toHaveBeenCalledTimes(2);
    demo.setRunning(false);
    vi.advanceTimersByTime(60_000);
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    demo.setRunning(true);
    vi.advanceTimersByTime(60_000);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});
