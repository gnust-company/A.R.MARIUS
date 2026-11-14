import type { LoungeSpot, StationKind } from './officePlan';

/*
 * What idle agents do in the lounge, minute by minute.
 *
 * The floor plan says who is idle and lays the room out; this decides which sofa, counter,
 * table or reading chair each idle agent is at right now, and when it gets up for something
 * else. It is a handful of rules rather than a simulation, and it invents nothing about the
 * agents: an agent in the lounge is idle, and how it passes the time is set dressing that
 * says "idle" better than a row of figures frozen on one sofa.
 *
 * The rules:
 *  1. An agent that has just come off work goes to the snack bar first.
 *  2. Nobody does the same thing twice in a row, and each agent has one thing it likes best.
 *  3. Table tennis takes two. A lone player waits a little for a partner — who is then far
 *     more likely to come — and gives up if nobody does.
 *  4. Someone sitting down prefers a sofa that already has company.
 *  5. People get up one at a time, never all at once.
 *
 * Choices are drawn from a hash of the agent's id and how many turns it has had, so a scene
 * replays the same way and a test can assert on it; no clock and no `Math.random` in here.
 */

interface Stay {
  spot: number;
  /** When this agent is due to move on; unset while it is still walking to its spot. */
  until?: number;
  /** When it reached a table with nobody on the other side. */
  aloneSince?: number;
  turns: number;
  last: StationKind | null;
}

export interface IdleAgent {
  id: string;
  /** The spot the floor plan starts this agent at. */
  start: number;
  /** It walked in from another zone while the scene was open, rather than being found here. */
  cameOffWork: boolean;
}

const KINDS: StationKind[] = ['sofa', 'bar', 'table', 'nook'];
const WEIGHT: Record<StationKind, number> = { sofa: 3, bar: 2, table: 2, nook: 2 };
/** How long a visit lasts, in seconds: shortest, and how much longer it can run. */
const STAY: Record<StationKind, [min: number, spread: number]> = { sofa: [40, 40], bar: [15, 15], table: [35, 25], nook: [45, 45] };
const PARTNER_PATIENCE = 14;
/** Seconds between one agent getting up and the next being allowed to. */
const STAGGER = 3;

/** A stable number in [0, 1) from an agent and a counter. */
export function draw(id: string, turn: number, salt = 0): number {
  let value = 2166136261 ^ (turn * 374761393 + salt * 668265263);
  for (let index = 0; index < id.length; index++) value = Math.imul(value ^ id.charCodeAt(index), 16777619);
  value ^= value >>> 15;
  value = Math.imul(value, 2246822519);
  value ^= value >>> 13;
  return ((value >>> 0) % 100000) / 100000;
}

export class LoungeLife {
  private stays = new Map<string, Stay>();
  private nextMove = 0;
  private spots: readonly LoungeSpot[];

  constructor(spots: readonly LoungeSpot[]) {
    this.spots = spots;
  }

  /** The spot an agent is at or walking to. */
  spotOf(id: string): number | undefined {
    return this.stays.get(id)?.spot;
  }

  /** The engine saw this agent sit down or step up to its spot: its visit starts counting now. */
  arrived(id: string, now: number) {
    const stay = this.stays.get(id);
    if (!stay || stay.until !== undefined) return;
    const kind = this.spots[stay.spot].kind;
    const [min, spread] = STAY[kind];
    stay.until = now + min + draw(id, stay.turns, 1) * spread;
    stay.aloneSince = kind === 'table' && !this.partnerAt(stay.spot, id) ? now : undefined;
  }

  /** Both sides of this table are taken by agents who have arrived. */
  rallyAt(station: number): boolean {
    let ready = 0;
    for (const stay of this.stays.values()) if (this.spots[stay.spot].station === station && stay.until !== undefined) ready += 1;
    return ready >= 2;
  }

  /** Bring the room up to date. Call it every frame; it does nothing most of the time. */
  step(now: number, idle: readonly IdleAgent[]) {
    const present = new Set(idle.map((agent) => agent.id));
    for (const id of [...this.stays.keys()]) if (!present.has(id)) this.stays.delete(id);

    for (const agent of idle) {
      if (this.stays.has(agent.id)) continue;
      const bar = agent.cameOffWork ? this.freeSpots('bar')[0] : undefined;
      const spot = bar ?? (this.isFree(agent.start) ? agent.start : this.anyFreeSpot() ?? agent.start);
      this.stays.set(agent.id, { spot, turns: 0, last: null });
    }

    // A player whose partner has come is no longer waiting; one still alone runs out of patience.
    for (const [id, stay] of this.stays) {
      if (this.spots[stay.spot].kind !== 'table' || stay.until === undefined) continue;
      if (this.partnerAt(stay.spot, id)) stay.aloneSince = undefined;
      else if (stay.aloneSince === undefined) stay.aloneSince = now;
      else if (now - stay.aloneSince > PARTNER_PATIENCE) stay.until = Math.min(stay.until, now);
    }

    if (now < this.nextMove) return;
    const due = [...this.stays.entries()]
      .filter(([, stay]) => stay.until !== undefined && now >= stay.until)
      .sort(([, a], [, b]) => (a.until ?? 0) - (b.until ?? 0))[0];
    if (!due) return;
    const [id, stay] = due;
    const next = this.choose(id, stay, idle.length);
    if (next === undefined) {
      // Nowhere else to go: stay put for another visit.
      stay.until = undefined;
      stay.turns += 1;
      this.arrived(id, now);
      return;
    }
    this.stays.set(id, { spot: next, turns: stay.turns + 1, last: this.spots[stay.spot].kind });
    this.nextMove = now + STAGGER;
  }

  private choose(id: string, stay: Stay, headcount: number): number | undefined {
    const here = this.spots[stay.spot].kind;
    const favourite = KINDS[Math.floor(draw(id, 0, 7) * KINDS.length)];
    const someoneWaits = [...this.stays.entries()].some(([other, otherStay]) => other !== id && otherStay.aloneSince !== undefined);
    const options = KINDS.map((kind) => {
      let weight = this.freeSpots(kind).length ? WEIGHT[kind] : 0;
      if (kind === here) weight = 0;
      if (kind === favourite) weight *= 2;
      if (kind === 'table') weight = headcount < 2 ? 0 : someoneWaits ? weight * 5 : weight;
      return { kind, weight };
    }).filter((option) => option.weight > 0);
    const total = options.reduce((sum, option) => sum + option.weight, 0);
    if (!total) return undefined;
    let roll = draw(id, stay.turns + 1, 3) * total;
    const kind = (options.find((option) => (roll -= option.weight) < 0) ?? options[options.length - 1]).kind;
    const free = this.freeSpots(kind);
    // Company first: the table someone is waiting at, the sofa someone is already on.
    const withCompany = free.filter((spot) => this.occupantsOf(this.spots[spot].station) > 0);
    const pool = (kind === 'table' || kind === 'sofa') && withCompany.length ? withCompany : free;
    return pool[Math.floor(draw(id, stay.turns + 1, 5) * pool.length)];
  }

  private isFree(spot: number): boolean {
    for (const stay of this.stays.values()) if (stay.spot === spot) return false;
    return spot >= 0 && spot < this.spots.length;
  }

  private freeSpots(kind: StationKind): number[] {
    const taken = new Set([...this.stays.values()].map((stay) => stay.spot));
    return this.spots.flatMap((spot, index) => (spot.kind === kind && !taken.has(index) ? [index] : []));
  }

  private anyFreeSpot(): number | undefined {
    const taken = new Set([...this.stays.values()].map((stay) => stay.spot));
    const free = this.spots.flatMap((spot, index) => (!taken.has(index) && spot.kind !== 'table' ? [index] : []));
    return free[0];
  }

  private occupantsOf(station: number): number {
    let count = 0;
    for (const stay of this.stays.values()) if (this.spots[stay.spot].station === station) count += 1;
    return count;
  }

  private partnerAt(spot: number, self: string): boolean {
    const station = this.spots[spot].station;
    for (const [id, stay] of this.stays) if (id !== self && this.spots[stay.spot].station === station && stay.until !== undefined) return true;
    return false;
  }
}
