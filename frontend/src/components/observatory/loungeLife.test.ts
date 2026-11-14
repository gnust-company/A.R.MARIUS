import { describe, expect, it } from 'vitest';
import { LoungeLife, draw, type IdleAgent } from './loungeLife';
import { layoutOffice, type LoungeSpot, type ObservedAgent } from './officePlan';

const team = (count: number): ObservedAgent[] => Array.from({ length: count }, (_, index) => ({ id: `agent-${index}`, name: `agent-${index}`, status: 'online', placed: true }));

/** The lounge of a team, and its agents as the scene would hand them over. */
function lounge(count: number) {
  const agents = team(count);
  const { plan, placements } = layoutOffice(agents, []);
  const idle: IdleAgent[] = agents.map((agent) => ({ id: agent.id, start: placements.get(agent.id)!.start!, cameOffWork: false }));
  return { spots: plan.loungeSpots, idle, life: new LoungeLife(plan.loungeSpots) };
}

/** Run the room for a while, with everyone arriving the moment they pick a spot. */
function run(life: LoungeLife, idle: IdleAgent[], spots: readonly LoungeSpot[], seconds: number, watch?: (now: number) => void) {
  const seen = new Map<string, number | undefined>();
  for (let now = 0; now <= seconds; now += 0.5) {
    life.step(now, idle);
    for (const agent of idle) {
      const spot = life.spotOf(agent.id);
      if (seen.get(agent.id) !== spot) {
        seen.set(agent.id, spot);
        life.arrived(agent.id, now);
      }
    }
    watch?.(now);
  }
  return spots;
}

describe('draw', () => {
  it('is the same number for the same agent and turn, and stays inside [0, 1)', () => {
    expect(draw('a', 3)).toBe(draw('a', 3));
    expect(draw('a', 3)).not.toBe(draw('a', 4));
    for (let turn = 0; turn < 200; turn++) {
      const value = draw('agent', turn, turn % 5);
      expect(value).toBeGreaterThanOrEqual(0);
      expect(value).toBeLessThan(1);
    }
  });
});

describe('LoungeLife', () => {
  it('starts everyone where the floor plan put them', () => {
    const { life, idle } = lounge(4);
    life.step(0, idle);
    for (const agent of idle) expect(life.spotOf(agent.id)).toBe(agent.start);
  });

  it('never puts two agents on one spot', () => {
    const { life, idle, spots } = lounge(7);
    run(life, idle, spots, 600, () => {
      const taken = idle.map((agent) => life.spotOf(agent.id));
      expect(new Set(taken).size).toBe(idle.length);
    });
  });

  it('sends an agent that has just come off work to the snack bar first', () => {
    const { life, idle, spots } = lounge(4);
    life.step(0, idle.slice(0, 3));
    const late: IdleAgent = { ...idle[3], cameOffWork: true };
    life.step(1, [...idle.slice(0, 3), late]);
    expect(spots[life.spotOf(late.id)!].kind).toBe('bar');
  });

  it('never has an agent do the same thing twice in a row', () => {
    const { life, idle, spots } = lounge(4);
    const last = new Map<string, number>();
    run(life, idle, spots, 900, () => {
      for (const agent of idle) {
        const spot = life.spotOf(agent.id)!;
        const before = last.get(agent.id);
        if (before !== undefined && before !== spot) expect(spots[spot].kind).not.toBe(spots[before].kind);
        last.set(agent.id, spot);
      }
    });
  });

  it('gets agents up one at a time', () => {
    const { life, idle, spots } = lounge(8);
    let previous = idle.map((agent) => agent.start);
    run(life, idle, spots, 600, () => {
      const now = idle.map((agent) => life.spotOf(agent.id)!);
      expect(now.filter((spot, index) => spot !== previous[index]).length).toBeLessThanOrEqual(1);
      previous = now;
    });
  });

  it('moves people around: over ten minutes everyone has been somewhere else', () => {
    const { life, idle, spots } = lounge(4);
    const visited = new Map(idle.map((agent) => [agent.id, new Set<number>()]));
    run(life, idle, spots, 600, () => idle.forEach((agent) => visited.get(agent.id)!.add(life.spotOf(agent.id)!)));
    for (const places of visited.values()) expect(places.size).toBeGreaterThan(1);
  });

  it('lets a lone player give up when nobody comes to the table', () => {
    const { life, spots } = lounge(4);
    const table = spots.findIndex((spot) => spot.kind === 'table');
    const loner: IdleAgent = { id: 'loner', start: table, cameOffWork: false };
    life.step(0, [loner]);
    life.arrived('loner', 0);
    expect(life.rallyAt(spots[table].station)).toBe(false);
    for (let now = 0.5; now <= 30; now += 0.5) life.step(now, [loner]);
    expect(spots[life.spotOf('loner')!].kind).not.toBe('table');
  });

  it('has a rally only when both sides of the table have arrived', () => {
    const { life, spots } = lounge(4);
    const sides = spots.flatMap((spot, index) => (spot.kind === 'table' ? [index] : []));
    const players: IdleAgent[] = sides.slice(0, 2).map((start, index) => ({ id: `p${index}`, start, cameOffWork: false }));
    life.step(0, players);
    life.arrived('p0', 0);
    expect(life.rallyAt(spots[sides[0]].station)).toBe(false);
    life.arrived('p1', 1);
    expect(life.rallyAt(spots[sides[0]].station)).toBe(true);
  });

  it('frees the spot of an agent that has gone back to work', () => {
    const { life, idle } = lounge(4);
    life.step(0, idle);
    life.step(1, idle.slice(1));
    expect(life.spotOf(idle[0].id)).toBeUndefined();
  });
});
