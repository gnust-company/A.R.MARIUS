import { describe, expect, it } from 'vitest';
import { layoutOffice, zoneOf, type ObservedAgent, type ObservedTask } from './officePlan';

const agent = (id: string, status: string, skills: string[] = ['api']): ObservedAgent => ({ id, name: id, status, skills });

describe('zoneOf', () => {
  it('sends a task in review to the CEO even when the agent is offline', () => {
    const tasks: ObservedTask[] = [{ id: 't', status: 'in_review', assigneeId: 'a' }];
    expect(zoneOf(agent('a', 'offline'), tasks)).toBe('patron');
  });

  it('puts offline before setup, setup before work, work before lounge', () => {
    expect(zoneOf(agent('a', 'offline', []), [])).toBe('clinic');
    expect(zoneOf(agent('a', 'online', []), [])).toBe('setup');
    expect(zoneOf(agent('a', 'online'), [{ id: 't', status: 'draft', assigneeId: 'a' }])).toBe('setup');
    expect(zoneOf(agent('a', 'online'), [{ id: 't', status: 'blocked', assigneeId: 'a' }])).toBe('work');
    expect(zoneOf(agent('a', 'working'), [])).toBe('work');
    expect(zoneOf(agent('a', 'online'), [{ id: 't', status: 'done', assigneeId: 'a' }])).toBe('lounge');
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

  it('queues offline agents once the clinic beds are taken', () => {
    const agents = ['a', 'b', 'c', 'd', 'e'].map((id) => agent(id, 'offline'));
    const { plan, placements } = layoutOffice(agents, []);
    expect(plan.clinicBeds).toBe(4);
    expect(plan.clinicWaiting).toBe(1);
    expect(placements.get('e')?.assignment).toEqual({ kind: 'clinicQueue', position: 1 });
    expect(placements.get('a')?.pose).toBe('lying');
  });

  it('opens a second studio beside the first instead of on top of it', () => {
    const agents = Array.from({ length: 8 }, (_, index) => agent(`w${index}`, 'working'));
    const { plan } = layoutOffice(agents, []);
    expect(plan.workPods).toBe(2);
    expect(new Set(plan.workCenters).size).toBe(2);
  });
});
