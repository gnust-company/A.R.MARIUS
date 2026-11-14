import { describe, expect, it } from 'vitest';
import { layoutOffice, walkBetween, wayInto, zoneOf, type ObservedAgent, type ObservedTask, type Point } from './officePlan';

const agent = (id: string, status: string, placed = true): ObservedAgent => ({ id, name: id, status, placed });
const team = (count: number, status = 'online') => Array.from({ length: count }, (_, index) => agent(`a${String(index).padStart(2, '0')}`, status));

describe('zoneOf', () => {
  it('sends a task in review to the CEO even when the agent is offline', () => {
    const tasks: ObservedTask[] = [{ id: 't', status: 'in_review', assigneeId: 'a' }];
    expect(zoneOf(agent('a', 'offline'), tasks)).toBe('patron');
  });

  it('puts offline before setup, a draft before work, work before lounge', () => {
    expect(zoneOf(agent('a', 'offline', false), [])).toBe('clinic');
    expect(zoneOf(agent('a', 'online', false), [])).toBe('setup');
    expect(zoneOf(agent('a', 'online'), [{ id: 't', status: 'draft', assigneeId: 'a' }])).toBe('setup');
    expect(zoneOf(agent('a', 'online'), [{ id: 't', status: 'blocked', assigneeId: 'a' }])).toBe('work');
    expect(zoneOf(agent('a', 'working'), [])).toBe('work');
    expect(zoneOf(agent('a', 'online'), [{ id: 't', status: 'done', assigneeId: 'a' }])).toBe('lounge');
  });
});

describe('zoneOf, for a team that links no skills', () => {
  it('lets an idle agent with a runtime rest in the lounge, not queue at reception', () => {
    expect(zoneOf({ id: 'a', name: 'a', status: 'online', placed: true }, [])).toBe('lounge');
    expect(zoneOf({ id: 'a', name: 'a', status: 'online' }, [])).toBe('lounge');
  });

  it('seats an agent that is working even when nothing says where it runs', () => {
    expect(zoneOf(agent('a', 'working', false), [])).toBe('work');
  });
});

describe('layoutOffice', () => {
  it('seats the same agents identically whatever order they arrive in', () => {
    const agents = ['d', 'b', 'a', 'c'].map((id) => agent(id, 'working'));
    const one = layoutOffice(agents, []);
    const two = layoutOffice([...agents].reverse(), []);
    for (const { id } of agents) expect(one.placements.get(id)).toEqual(two.placements.get(id));
    expect(one.placements.get('a')?.assignment).toEqual({ kind: 'desk', desk: 1 });
  });

  it('keeps an agent at its own desk whoever else is working', () => {
    const idle = layoutOffice([agent('a', 'online'), agent('b', 'working'), agent('c', 'online')], []);
    const busy = layoutOffice([agent('a', 'working'), agent('b', 'working'), agent('c', 'working')], []);
    expect(idle.placements.get('b')?.assignment).toEqual({ kind: 'desk', desk: 2 });
    expect(idle.placements.get('b')).toEqual(busy.placements.get('b'));
    expect(idle.desks.get('a')).toBe(0);
  });

  it('tells a run that is going from a task that is only held', () => {
    const tasks: ObservedTask[] = [{ id: 't', status: 'in_progress', assigneeId: 'b' }];
    const { placements } = layoutOffice([agent('a', 'working'), agent('b', 'online')], tasks);
    expect(placements.get('a')?.activity).toBe('type');
    expect(placements.get('b')?.activity).toBe('think');
  });

  it('queues offline agents once the sick bay beds are taken', () => {
    const { plan, placements } = layoutOffice(team(5, 'offline'), []);
    expect(plan.clinicBeds).toBe(3);
    expect(plan.clinicWaiting).toBe(2);
    expect(placements.get('a03')?.assignment).toEqual({ kind: 'clinicQueue', position: 1 });
    expect(placements.get('a00')?.pose).toBe('lying');
  });

  it('sends the review queue down the stairs once the gallery is full', () => {
    const agents = team(8);
    const tasks = agents.map((one, index) => ({ id: `t${index}`, status: 'in_review', assigneeId: one.id }));
    const { plan, placements } = layoutOffice(agents, tasks);
    const heights = agents.map((one) => placements.get(one.id)!.y);
    expect(placements.get('a00')?.assignment).toEqual({ kind: 'presenting' });
    expect(heights[0]).toBeGreaterThan(plan.galleryHeight);
    expect(heights[heights.length - 1]).toBeLessThan(0.1);
  });
});

describe('the building', () => {
  it('grows with the team instead of standing at one size', () => {
    const small = layoutOffice(team(4), []).plan;
    const big = layoutOffice(team(24), []).plan;
    expect(small.floorWidth * small.floorDepth).toBeLessThan(300);
    expect(big.floorWidth * big.floorDepth).toBeGreaterThan(small.floorWidth * small.floorDepth * 1.8);
    expect(big.desks).toHaveLength(24);
    expect(small.shape).not.toBe(big.shape);
  });

  it.each([1, 2, 4, 7, 12, 24, 40])('has room in the lounge for a whole idle team of %i', (count) => {
    const agents = team(count);
    const { plan, placements } = layoutOffice(agents, []);
    expect(plan.loungeSpots.length).toBeGreaterThanOrEqual(count);
    // Nobody shares a spot, and nobody is started alone at a table that takes two.
    const taken = agents.map((one) => placements.get(one.id)!.start);
    expect(new Set(taken).size).toBe(count);
    const alone = plan.stations.flatMap((station, index) => (station.kind === 'table' && taken.filter((spot) => plan.loungeSpots[spot!].station === index).length === 1 ? [index] : []));
    if (count <= plan.loungeSpots.filter((spot) => spot.kind !== 'table').length) expect(alone).toEqual([]);
  });

  it.each([1, 4, 12, 40])('keeps every piece of furniture inside the walls for a team of %i', (count) => {
    const { plan } = layoutOffice(team(count), []);
    const halfWidth = plan.floorWidth / 2;
    const halfDepth = plan.floorDepth / 2;
    for (const station of plan.stations) {
      expect(Math.abs(station.x) + station.width / 2).toBeLessThanOrEqual(halfWidth);
      expect(Math.abs(station.z) + 1.3).toBeLessThanOrEqual(halfDepth);
      // The main aisle stays clear through every row of the lounge.
      expect(Math.abs(station.x - plan.aisleX) - station.width / 2).toBeGreaterThanOrEqual(0.85);
    }
    for (const desk of plan.desks) expect(Math.abs(desk.x)).toBeLessThan(halfWidth - 0.8);
    // No two lounge stations stand on top of each other.
    plan.stations.forEach((one, index) =>
      plan.stations.slice(index + 1).forEach((other) => {
        if (Math.abs(one.z - other.z) < 1) expect(Math.abs(one.x - other.x)).toBeGreaterThanOrEqual((one.width + other.width) / 2 - 0.01);
      }),
    );
  });
});

describe('walkBetween', () => {
  const aisle: Point = [0, 0, 5];
  const door: Point = [-2, 0, 5];
  const bed: Point = [-4, 0.69, 4];
  const walkway: Point = [0, 0, -3];
  const seat: Point = [3, 0.045, -3.8];

  it('goes out by the door, along the aisle, and in again', () => {
    const steps = walkBetween([aisle, door, bed], [walkway, [3, 0, -3], seat]);
    expect(steps.map((step) => step.point)).toEqual([door, aisle, walkway, [3, 0, -3], seat]);
  });

  it('does not walk out to the aisle between two spots that share a way in', () => {
    const steps = walkBetween([aisle, door, bed], [aisle, door, [-4, 0.69, 6]]);
    expect(steps.map((step) => step.point)).toEqual([door, [-4, 0.69, 6]]);
  });

  it('is no walk at all when the spot is the same', () => {
    expect(walkBetween([aisle, door, bed], [aisle, door, bed])).toEqual([]);
  });

  it('remembers, at each step, the way back out from it', () => {
    const steps = walkBetween([aisle, door, bed], [walkway, seat]);
    expect(steps[0].trail).toEqual([aisle, door]);
    expect(steps[steps.length - 1].trail).toEqual([walkway, seat]);
  });

  it('leads from any seat to any other without leaving the floor', () => {
    const agents = team(9);
    const { plan, placements } = layoutOffice(agents, [{ id: 't', status: 'in_review', assigneeId: 'a00' }]);
    const from = wayInto(placements.get('a00')!);
    for (const spot of plan.loungeSpots) {
      for (const step of walkBetween(from, wayInto(spot))) {
        expect(Math.abs(step.point[0])).toBeLessThanOrEqual(plan.floorWidth / 2);
        expect(Math.abs(step.point[2])).toBeLessThanOrEqual(plan.floorDepth / 2);
      }
    }
  });
});
