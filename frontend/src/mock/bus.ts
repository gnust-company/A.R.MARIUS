import type { RunEvent } from "../api";
import { db, nextSeq, setMariusLiveness } from "./store";

// Simulated Hybrid SSE for the mock-data app (FE-1). In the real app these arrive over two
// server→browser channels (workspace control-plane + per-task trace); here we fake them with a
// tiny in-process emitter so the UI feels alive with zero backend.

type Handler = (data: any) => void;

class MockBus {
  private handlers = new Map<string, Set<Handler>>();

  on(type: string, cb: Handler): () => void {
    let set = this.handlers.get(type);
    if (!set) { set = new Set(); this.handlers.set(type, set); }
    set.add(cb);
    return () => set!.delete(cb);
  }
  emit(type: string, data: any): void {
    this.handlers.get(type)?.forEach((cb) => cb(data));
    this.handlers.get("*")?.forEach((cb) => cb({ type, data }));
  }
}

export const bus = new MockBus();

// --- liveness decay simulator: every few seconds, drift an agent's liveness and emit a
//     workspace control-plane event (`marius.liveness`). Demonstrates the "alive" feel. ---
let started = false;
export function ensureSimulator(): void {
  if (started) return;
  started = true;
  const cycle: Record<string, string> = {
    online: "working", working: "idle", idle: "offline", offline: "online",
    checking: "offline", hung: "offline",
  };
  const candidates = db.mariuses.filter((m) => m.id !== "m-leader"); // leader stays online
  let i = 0;
  setInterval(() => {
    const m = candidates[i % candidates.length];
    i++;
    const next = cycle[m.liveness] ?? "online";
    setMariusLiveness(m.id, next);
    bus.emit("marius.liveness", { marius_id: m.id, liveness: next });
  }, 7000);
}

// --- per-task trace simulator: stream a scripted run so the Collaboration Room trace is live. ---
export function streamRunScripted(runId: string, onEvent: (e: RunEvent) => void): () => void {
  const timers: ReturnType<typeof setTimeout>[] = [];
  const ev = (delay: number, type: string, payload: Record<string, any>) => {
    timers.push(setTimeout(() => {
      const e: RunEvent = { seq: nextSeq(), type, payload, created_at: new Date().toISOString() };
      // also persist so runEvents() is consistent
      (db.runEvents[runId] ??= []).push(e);
      onEvent(e);
    }, delay));
  };
  ev(0, "run.started", { adapter: "hermes_gateway", run_id: runId });
  ev(500, "run.tool", { name: "read_file", path: "src/Settings.tsx" });
  ev(1200, "run.delta", { text: "Mapping the old gold tokens to terracotta…" });
  ev(2000, "run.tool", { name: "edit_file", path: "src/index.css" });
  ev(2800, "run.delta", { text: "Applied parchment background + warm glows." });
  ev(3600, "run.usage", { input_tokens: 1840, output_tokens: 920 });
  ev(4200, "run.delta", { text: "Verifying contrast against WCAG AA…" });
  timers.push(setTimeout(() => {
    const e: RunEvent = { seq: nextSeq(), type: "run.completed", payload: { run_id: runId }, created_at: new Date().toISOString() };
    (db.runEvents[runId] ??= []).push(e);
    onEvent({ seq: nextSeq(), type: "run.finished", payload: { run_id: runId }, created_at: new Date().toISOString() });
    onEvent(e);
  }, 4800));
  return () => timers.forEach(clearTimeout);
}
