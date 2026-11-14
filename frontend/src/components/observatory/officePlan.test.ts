import { describe, expect, it } from 'vitest';
import { deskSpot, layoutOffice, reportSpot, walkTo, wayOut, zoneOf, type ObservedAgent, type ObservedTask, type OfficePlan, type Point, type Spot } from './officePlan';

const agent = (id: string, status: string, placed = true): ObservedAgent => ({ id, name: id, status, placed });
const team = (count: number, status = 'online') => Array.from({ length: count }, (_, index) => agent(`a${String(index).padStart(2, '0')}`, status));

describe('zoneOf', () => {
  it('does not hold an agent anywhere for a task that is waiting on the patron', () => {
    const waiting: ObservedTask[] = [{ id: 't', status: 'in_review', assigneeId: 'a' }];
    expect(zoneOf(agent('a', 'online'), waiting)).toBe('lounge');
    expect(zoneOf(agent('a', 'offline'), waiting)).toBe('clinic');
    // With something else still to do, it is back at its desk.
    expect(zoneOf(agent('a', 'online'), [...waiting, { id: 'u', status: 'in_progress', assigneeId: 'a' }])).toBe('work');
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
    expect(one.placements.get('a')?.assignment).toEqual({ kind: 'desk', pod: 0, desk: 1 });
  });

  it('keeps an agent at its own desk whoever else is working', () => {
    const idle = layoutOffice([agent('a', 'online'), agent('b', 'working'), agent('c', 'online')], []);
    const busy = layoutOffice([agent('a', 'working'), agent('b', 'working'), agent('c', 'working')], []);
    expect(idle.placements.get('b')?.assignment).toEqual({ kind: 'desk', pod: 0, desk: 2 });
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
    expect(plan.clinicBeds).toBe(2);
    expect(plan.clinicWaiting).toBe(3);
    expect(placements.get('a02')?.assignment).toEqual({ kind: 'clinicQueue', position: 1 });
    expect(placements.get('a00')?.pose).toBe('lying');
  });

  it('counts the reports on the patron’s desk by task, not by agent', () => {
    const tasks: ObservedTask[] = [
      { id: 't1', status: 'in_review', assigneeId: 'a00' },
      { id: 't2', status: 'in_review', assigneeId: 'a00' },
      { id: 't3', status: 'review', assigneeId: 'a01' },
      { id: 't4', status: 'in_review', assigneeId: 'someone-else' },
    ];
    expect(layoutOffice(team(3), tasks).plan.reviewCount).toBe(3);
  });

  it('sits nobody inside their seat: hips above the floor, by what they sit on', () => {
    const { plan, placements } = layoutOffice([agent('a', 'working')], []);
    expect(placements.get('a')!.y).toBeGreaterThan(0.1);
    for (const spot of plan.loungeSpots) if (spot.pose === 'sitting') expect(spot.y).toBeGreaterThan(0.15);
  });
});

describe('the work floor', () => {
  it('is never fewer than three pods of four desks', () => {
    for (const count of [1, 4, 12]) {
      const { plan } = layoutOffice(team(count), []);
      expect(plan.pods).toHaveLength(3);
      expect(plan.desks).toHaveLength(12);
    }
    expect(layoutOffice(team(13), []).plan.pods).toHaveLength(4);
    expect(layoutOffice(team(30), []).plan.desks).toHaveLength(32);
  });

  it('seats a pod two facing two, each owner on the outside of the pod', () => {
    const { plan } = layoutOffice(team(4), []);
    const pod = plan.pods[0];
    const seats = [0, 1, 2, 3].map((index) => deskSpot(plan, index, 'type'));
    // Two sit behind the desks facing the front of the building, two in front facing the back.
    expect(seats.filter((seat) => seat.z < pod.z && seat.rotation === 0)).toHaveLength(2);
    expect(seats.filter((seat) => seat.z > pod.z && seat.rotation === Math.PI)).toHaveLength(2);
    for (const seat of seats) expect(Math.abs(seat.z - pod.z)).toBeGreaterThan(1);
  });

  it('is an L: a row of pods across the building, and a leg up to the back wall beside the patron', () => {
    const { plan } = layoutOffice(team(4), []);
    const back = -plan.floorDepth / 2;
    const right = plan.floorWidth / 2;
    const platformWest = plan.patron.x - plan.patron.width / 2;
    const platformFront = plan.patron.z + plan.patron.depth / 2;
    // The patron's platform is the back corner by the east wall, and no wider than it needs.
    expect(plan.patron.x + plan.patron.width / 2).toBeCloseTo(right);
    expect(plan.patron.z - plan.patron.depth / 2).toBeCloseTo(back);
    expect(plan.patron.width).toBeLessThan(plan.work.width / 2);
    // The leg: pods behind the front of the platform, west of it and of its steps.
    const leg = plan.pods.filter((pod) => pod.z < platformFront);
    const row = plan.pods.filter((pod) => pod.z > platformFront);
    expect(leg.length).toBeGreaterThanOrEqual(1);
    expect(row.length).toBeGreaterThanOrEqual(2);
    for (const pod of leg) expect(pod.x + 1.85).toBeLessThan(plan.stairs.foot);
    // The row runs on under the platform, so the two arms meet at the leg's end.
    expect(Math.max(...row.map((pod) => pod.x))).toBeGreaterThan(platformWest);
    // The west column is still the sick bay over the front desk, across the aisle.
    expect(plan.clinic.z).toBeLessThan(plan.reception.z);
    expect(plan.clinic.x + plan.clinic.width / 2).toBeLessThan(plan.aisleX);
  });

  it('has the patron facing west down the steps, and a report handed in from that side', () => {
    const { plan } = layoutOffice(team(4), []);
    const first = reportSpot(plan, 0);
    // In front of the desk is west of it, facing east; the patron's chair is against the east wall.
    expect(first.x).toBeLessThan(plan.patronDesk.x - 1);
    expect(first.rotation).toBeCloseTo(Math.PI / 2);
    expect(first.activity).toBe('present');
    expect(first.y).toBeGreaterThan(plan.platformHeight);
    expect(plan.stairs.top).toBeLessThan(first.x);
    expect(plan.stairs.z).toBeCloseTo(plan.patronDesk.z);
    // The queue stands behind — one more on the platform, the rest at the foot of the steps — never two on one spot.
    const queue = [1, 2, 3, 4].map((position) => reportSpot(plan, position));
    expect(new Set(queue.map((spot) => `${spot.x.toFixed(2)}:${spot.z.toFixed(2)}`)).size).toBe(4);
    for (const spot of queue) expect(spot.activity).toBe('queue');
    expect(queue[0].y).toBeGreaterThan(plan.platformHeight);
    expect(queue[2].y).toBeLessThan(0.1);
  });
});

describe('the building', () => {
  it('grows with the team instead of standing at one size', () => {
    const small = layoutOffice(team(4), []).plan;
    const big = layoutOffice(team(30), []).plan;
    expect(small.floorWidth * small.floorDepth).toBeLessThan(400);
    expect(big.floorWidth * big.floorDepth).toBeGreaterThan(small.floorWidth * small.floorDepth * 1.5);
    expect(small.shape).not.toBe(big.shape);
    // Wide and shallow, for a wide screen.
    expect(small.floorWidth).toBeGreaterThan(small.floorDepth * 1.3);
  });

  it('always has two table-tennis tables, at the two ends of the lounge east of the aisle', () => {
    for (const count of [1, 4, 9, 12]) {
      const { plan } = layoutOffice(team(count), []);
      const tables = plan.stations.filter((station) => station.kind === 'table');
      expect(tables).toHaveLength(2);
      expect(tables[0].z).toBeCloseTo(tables[1].z);
      const stretch = plan.stations.filter((station) => Math.abs(station.z - tables[0].z) < 0.1 && station.x > plan.aisleX).sort((a, b) => a.x - b.x);
      expect(stretch[0].kind).toBe('table');
      expect(stretch[stretch.length - 1].kind).toBe('table');
      expect(stretch.length).toBeGreaterThan(2);
      // Mirror images of each other about the middle of that stretch.
      const middle = (plan.aisleX + 0.9 + plan.floorWidth / 2 - 0.5) / 2;
      expect(tables[0].x + tables[1].x).toBeCloseTo(2 * middle, 1);
    }
  });

  it('never stands a bar or a bookshelf in a front row, where it would hide people', () => {
    for (const count of [4, 9, 12, 24, 40]) {
      const { plan } = layoutOffice(team(count), []);
      for (const station of plan.stations) {
        const front = station.rotation !== 0;
        if (station.kind === 'bar') expect(front).toBe(false);
        if (station.kind === 'nook') expect(station.low === true).toBe(front);
      }
    }
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

  it.each([1, 4, 12, 40])('keeps everything inside the walls for a team of %i', (count) => {
    const { plan } = layoutOffice(team(count), []);
    const halfWidth = plan.floorWidth / 2;
    const halfDepth = plan.floorDepth / 2;
    for (const station of plan.stations) {
      expect(Math.abs(station.x) + station.width / 2).toBeLessThanOrEqual(halfWidth);
      expect(Math.abs(station.z) + 1.3).toBeLessThanOrEqual(halfDepth);
      // The main aisle stays clear through every row of the lounge.
      expect(Math.abs(station.x - plan.aisleX) - station.width / 2).toBeGreaterThanOrEqual(0.85);
      expect(station.z).toBeGreaterThan(plan.partitionZ);
    }
    const platformWest = plan.patron.x - plan.patron.width / 2;
    const platformFront = plan.patron.z + plan.patron.depth / 2;
    for (const desk of plan.desks) {
      expect(desk.x).toBeLessThan(halfWidth - 0.8);
      expect(desk.x - plan.aisleX).toBeGreaterThan(1.5);
      expect(desk.z).toBeLessThan(plan.partitionZ - 1.5);
      expect(desk.z).toBeGreaterThan(-halfDepth + 1.2);
      // No desk under the patron's platform or its steps.
      if (desk.z < platformFront + 0.5) expect(desk.x + 0.9).toBeLessThan(plan.stairs.foot);
      expect(desk.x < platformWest || desk.z > platformFront).toBe(true);
    }
    for (const bed of plan.beds) {
      expect(bed.x - 0.8).toBeGreaterThan(plan.clinic.x - plan.clinic.width / 2);
      expect(bed.x + 1.3).toBeLessThan(plan.clinic.x + plan.clinic.width / 2);
      expect(bed.z + 1).toBeLessThan(plan.clinic.z + plan.clinic.depth / 2);
    }
    // No two lounge stations stand on top of each other.
    plan.stations.forEach((one, index) =>
      plan.stations.slice(index + 1).forEach((other) => {
        if (Math.abs(one.z - other.z) < 1) expect(Math.abs(one.x - other.x)).toBeGreaterThanOrEqual((one.width + other.width) / 2 - 0.01);
      }),
    );
  });

  it('is not left deeper than the team needs: no empty floor between the pods and the lounge', () => {
    for (const count of [4, 9, 12, 20]) {
      const { plan } = layoutOffice(team(count), []);
      const lastPod = Math.max(...plan.pods.map((pod) => pod.z));
      expect(plan.partitionZ - lastPod).toBeLessThan(5.2);
    }
  });
});

describe('walkTo', () => {
  const at = (spot: Spot): Point => [spot.x, spot.y, spot.z];
  const walk = (plan: OfficePlan, from: Spot, to: Spot) => walkTo(plan, at(from), wayOut(from), to);
  /** Every stretch of a walk runs along x or along z: nothing is ever crossed diagonally. */
  const square = (from: Point, points: Point[]) => points.every((point, index) => {
    const before = index ? points[index - 1] : from;
    return Math.abs(point[0] - before[0]) < 0.01 || Math.abs(point[2] - before[2]) < 0.01;
  });

  it('is no walk at all when the spot is the same', () => {
    const { plan } = layoutOffice(team(4), []);
    const seat = deskSpot(plan, 0, 'type');
    expect(walk(plan, seat, deskSpot(plan, 0, 'think'))).toEqual([]);
  });

  it('ends at the spot, and gets there in straight stretches', () => {
    const { plan } = layoutOffice(team(9), []);
    const seat = deskSpot(plan, 6, 'type');
    for (const spot of [...plan.loungeSpots, reportSpot(plan, 0), deskSpot(plan, 3, 'type')]) {
      const steps = walk(plan, seat, spot);
      expect(steps[steps.length - 1].point).toEqual(at(spot));
      expect(square(at(seat), steps.slice(0, -1).map((step) => step.point))).toBe(true);
    }
  });

  it('takes a report from a desk up the steps to the patron, without going round by the main aisle', () => {
    const { plan } = layoutOffice(team(8), []);
    // A seat in the east pod of the row, on the lounge side.
    const seat = deskSpot(plan, 7, 'type');
    const steps = walk(plan, seat, reportSpot(plan, 0));
    for (const step of steps) expect(step.point[0]).toBeGreaterThan(plan.aisleX + 2);
    // Up by the steps: the foot on the floor, the top on the platform, in that order.
    const foot = steps.findIndex((step) => Math.abs(step.point[0] - plan.stairs.foot) < 0.01 && step.point[1] < 0.1);
    const top = steps.findIndex((step) => Math.abs(step.point[0] - plan.stairs.top) < 0.01 && step.point[1] > plan.platformHeight);
    expect(foot).toBeGreaterThanOrEqual(0);
    expect(top).toBe(foot + 1);
    // And back down the same way to its own desk.
    const home = walk(plan, reportSpot(plan, 0), seat);
    expect(home.map((step) => step.point[0]).slice(0, 2)).toEqual([plan.stairs.top, plan.stairs.foot]);
    expect(home[home.length - 1].point).toEqual(at(seat));
  });

  it('goes straight down the aisle between the two doors on it', () => {
    const agents = [agent('a', 'online', false), agent('b', 'offline')];
    const { plan, placements } = layoutOffice(agents, []);
    const steps = walk(plan, placements.get('a')!, placements.get('b')!);
    const onAisle = steps.filter((step) => Math.abs(step.point[0] - plan.aisleX) < 0.01).map((step) => step.point[2]);
    expect(onAisle).toEqual([plan.receptionDoorZ, plan.clinicDoorZ]);
  });

  it('reaches the lounge only by the main aisle: the partition has one way through', () => {
    const { plan } = layoutOffice(team(9), []);
    const east = plan.loungeSpots.find((spot) => spot.x > plan.aisleX + 3)!;
    const steps = walk(plan, deskSpot(plan, 5, 'type'), east);
    const crossing = steps.findIndex((step) => step.point[2] > plan.partitionZ);
    expect(steps[crossing].point[0]).toBeCloseTo(plan.aisleX);
  });

  it('remembers, at each step, the way from it out onto the walkways', () => {
    const { plan } = layoutOffice(team(4), []);
    const sofa = plan.loungeSpots.find((spot) => spot.approach.length > 1)!;
    const steps = walk(plan, deskSpot(plan, 0, 'type'), sofa);
    const last = steps[steps.length - 1];
    expect(last.out[0]).toEqual(at(sofa));
    expect(last.out[last.out.length - 1]).toEqual(sofa.approach[0]);
    // Picking the walk up again from the middle of it still arrives.
    const again = walkTo(plan, steps[0].point, steps[1].out, reportSpot(plan, 0));
    expect(again[again.length - 1].point).toEqual(at(reportSpot(plan, 0)));
  });

  it('never leaves the floor, from anywhere to anywhere, and only climbs at the steps', () => {
    const { plan } = layoutOffice(team(9), []);
    const spots = [...plan.loungeSpots, ...plan.desks.map((_, index) => deskSpot(plan, index, 'type'))];
    for (const from of [reportSpot(plan, 0), spots[0], spots[spots.length - 1]]) {
      for (const spot of spots) {
        const steps = walk(plan, from, spot);
        if (from !== spot) expect(steps[steps.length - 1].point).toEqual(at(spot));
        for (const step of steps) {
          expect(Math.abs(step.point[0])).toBeLessThanOrEqual(plan.floorWidth / 2);
          expect(Math.abs(step.point[2])).toBeLessThanOrEqual(plan.floorDepth / 2);
          // Anything up at platform height is on the platform.
          if (step.point[1] > plan.platformHeight) expect(step.point[0]).toBeGreaterThanOrEqual(plan.stairs.top - 0.01);
        }
      }
    }
  });
});
