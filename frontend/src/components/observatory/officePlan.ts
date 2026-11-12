/*
 * The observatory's floor plan and seating, as pure data (DESIGN §5–§6).
 *
 * One function decides where every agent is: which zone, which resource (desk, bed, queue
 * spot) and in what pose. The 3D scene places figures from it, and the tooltip and the detail
 * modal word the same assignment from it, so the three can never disagree (DESIGN §6.2).
 * Nothing here is random: the same agents and tasks always produce the same office.
 */

export type AgentZone = 'setup' | 'lounge' | 'clinic' | 'work' | 'patron';

/** Display order of the zones, as numbered on the scene's zone navigation (01–05). */
export const ZONES: AgentZone[] = ['setup', 'lounge', 'clinic', 'work', 'patron'];

export interface ObservedAgent {
  id: string;
  name: string;
  status: string;
  /** False when the agent has not been given a runtime yet, so it cannot be called at all. */
  placed?: boolean;
}

export interface ObservedTask {
  id: string;
  status: string;
  assigneeId?: string;
}

export type Pose = 'standing' | 'sitting' | 'lying';

/** Which physical resource an agent holds. Worded on screen by the page, from these codes. */
export type Assignment =
  | { kind: 'desk'; pod: number; desk: number }
  | { kind: 'bed'; bed: number }
  | { kind: 'clinicQueue'; position: number }
  | { kind: 'presenting' }
  | { kind: 'ceoQueue'; position: number }
  | { kind: 'loungeSeat'; seat: number }
  | { kind: 'loungeFloor' }
  | { kind: 'checkIn'; position: number };

export interface Placement {
  zone: AgentZone;
  assignment: Assignment;
  x: number;
  y: number;
  z: number;
  rotation: number;
  pose: Pose;
}

export interface OfficePlan {
  large: boolean;
  workCount: number;
  workPods: number;
  workCapacity: number;
  clinicCount: number;
  clinicBeds: number;
  clinicWaiting: number;
  reviewCount: number;
  floorWidth: number;
  floorDepth: number;
  centerX: number;
  workCenters: number[];
  workRows: number[];
  setupX: number;
  loungeX: number;
  clinicX: number;
  clinicZ: number;
  patronX: number;
  patronZ: number;
}

export interface OfficeLayout {
  plan: OfficePlan;
  zones: Map<string, AgentZone>;
  placements: Map<string, Placement>;
}

const SETUP_QUEUE = [[-1.3, -0.7, Math.PI], [-1.3, 0.55, Math.PI], [-1.3, 1.8, Math.PI], [0.05, 1.8, Math.PI]] as const;
const WORK_SEATS = [[-2.15, -2.45, Math.PI], [1.05, -2.45, Math.PI], [-2.15, 0, Math.PI], [1.05, 0, Math.PI], [-2.15, 2.45, Math.PI], [1.05, 2.45, Math.PI]] as const;
export const SEATS_PER_POD = WORK_SEATS.length;

const CLOSED = new Set(['done', 'cancelled']);

/** The board's spellings of a status, folded to the backend's eight. */
export function normalizeTaskStatus(status: string): string {
  const s = status.replace(/-/g, '_');
  if (s === 'review') return 'in_review';
  if (s === 'pending') return 'todo';
  return s;
}

/** The tasks an agent is holding: assigned to it and not finished. */
export function openTasksOf<T extends ObservedTask>(agentId: string, tasks: readonly T[]): T[] {
  return tasks.filter((task) => task.assigneeId === agentId && !CLOSED.has(normalizeTaskStatus(task.status)));
}

/**
 * Where an agent belongs. Priority: review → offline → draft → work → not placed → lounge.
 * Changing this order means changing the scene, the modal and the zone bar together — they
 * all read it from here.
 *
 * Reception is for an agent that is not ready to take work: it holds a draft, or it has no
 * runtime yet. The design's rule was "carries no skill" (DESIGN §6.1), but linking a skill is
 * optional here — every agent comes with what it needs to work — so that rule parked a whole
 * working team at the front desk for good.
 */
export function zoneOf(agent: ObservedAgent, tasks: readonly ObservedTask[]): AgentZone {
  const open = openTasksOf(agent.id, tasks).map((task) => normalizeTaskStatus(task.status));
  if (open.includes('in_review')) return 'patron';
  if (agent.status === 'offline') return 'clinic';
  if (open.includes('draft')) return 'setup';
  if (agent.status === 'working' || agent.status === 'hung' || open.includes('in_progress') || open.includes('blocked')) return 'work';
  if (agent.placed === false) return 'setup';
  return 'lounge';
}

/** Stable order inside a zone, so a refetch that reorders the list never reshuffles seats. */
function byName(a: ObservedAgent, b: ObservedAgent): number {
  return a.name.localeCompare(b.name) || a.id.localeCompare(b.id);
}

export function createOfficePlan(zoneCounts: Record<AgentZone, number>, agentCount: number): OfficePlan {
  const workCount = zoneCounts.work;
  const clinicCount = zoneCounts.clinic;
  const reviewCount = zoneCounts.patron;
  const workPods = Math.max(1, Math.ceil(workCount / SEATS_PER_POD));
  const clinicBeds = Math.max(2, Math.min(4, Math.ceil(clinicCount / 2) * 2));
  // More than one studio never fits the compact plan: its single pod column would stack them.
  const large = agentCount > 12 || workPods > 1;
  const workColumns = large ? 2 : 1;
  const workCenters = Array.from({ length: workPods }, (_, index) => (large ? -3.55 : 1.1) + (index % workColumns) * 8.1);
  const workRows = Array.from({ length: workPods }, (_, index) => (large ? -6 + Math.floor(index / workColumns) * 10 : -5.8));
  const workRowCount = large ? Math.ceil(workPods / workColumns) : 1;
  const floorDepth = large ? Math.max(26, workRowCount * 20 - 22) : 26;
  const clinicZ = floorDepth / 2 - 5;
  return {
    large,
    workCount,
    workPods,
    workCapacity: workPods * SEATS_PER_POD,
    clinicCount,
    clinicBeds,
    clinicWaiting: Math.max(0, clinicCount - clinicBeds),
    reviewCount,
    floorWidth: large ? 34 : 26,
    floorDepth,
    centerX: 0,
    workCenters,
    workRows,
    setupX: large ? -12 : -8.5,
    loungeX: large ? -12 : -8.5,
    clinicX: large ? -12 : -8.5,
    clinicZ,
    patronX: large ? 12 : 8,
    patronZ: clinicZ - 3,
  };
}

export function workSeat(index: number, plan: OfficePlan) {
  const pod = Math.floor(index / SEATS_PER_POD);
  const [localX, z, rotation] = WORK_SEATS[index % SEATS_PER_POD];
  return { x: plan.workCenters[pod] + localX, z: plan.workRows[pod] + z, rotation, pod };
}

export function clinicBed(index: number, plan: OfficePlan) {
  return { x: plan.clinicX - 1.45 + (index % 2) * 2.9, z: plan.clinicZ - 1.65 + Math.floor(index / 2) * 2.75 };
}

/** Seat every agent. The single source of truth for scene, tooltip and modal. */
export function layoutOffice(agents: readonly ObservedAgent[], tasks: readonly ObservedTask[]): OfficeLayout {
  const zones = new Map<string, AgentZone>();
  const groups: Record<AgentZone, ObservedAgent[]> = { setup: [], lounge: [], clinic: [], work: [], patron: [] };
  for (const agent of [...agents].sort(byName)) {
    const zone = zoneOf(agent, tasks);
    zones.set(agent.id, zone);
    groups[zone].push(agent);
  }
  const plan = createOfficePlan(
    { setup: groups.setup.length, lounge: groups.lounge.length, clinic: groups.clinic.length, work: groups.work.length, patron: groups.patron.length },
    agents.length,
  );
  const placements = new Map<string, Placement>();
  const put = (agent: ObservedAgent, zone: AgentZone, assignment: Assignment, x: number, z: number, rotation: number, pose: Pose, y?: number) =>
    placements.set(agent.id, { zone, assignment, x, z, rotation, pose, y: y ?? (pose === 'sitting' ? 0.045 : 0.02) });

  groups.setup.forEach((agent, index) => {
    const assignment: Assignment = { kind: 'checkIn', position: index + 1 };
    if (index < SETUP_QUEUE.length) {
      const [x, z, rotation] = SETUP_QUEUE[index];
      put(agent, 'setup', assignment, plan.setupX + x, -8 + z, rotation, 'standing');
    } else {
      put(agent, 'setup', assignment, plan.setupX + 0.6 + (index % 2) * 1.1, -5.9 + Math.floor(index / 2) * 0.75, Math.PI, 'standing');
    }
  });

  groups.lounge.forEach((agent, index) => {
    if (index === 0) put(agent, 'lounge', { kind: 'loungeSeat', seat: 1 }, plan.loungeX - 0.89, 1.19, Math.PI, 'sitting');
    else if (index === 1) put(agent, 'lounge', { kind: 'loungeSeat', seat: 2 }, plan.loungeX + 0.09, 1.19, Math.PI, 'sitting');
    else if (index === 2) put(agent, 'lounge', { kind: 'loungeSeat', seat: 3 }, plan.loungeX + 2.05, -0.25, -Math.PI / 2, 'sitting');
    else put(agent, 'lounge', { kind: 'loungeFloor' }, plan.loungeX - 2.2 + ((index - 3) % 3) * 1.15, -2.25 + Math.floor((index - 3) / 3) * 1.05, 0, 'standing');
  });

  groups.clinic.forEach((agent, index) => {
    if (index < plan.clinicBeds) {
      const bed = clinicBed(index, plan);
      put(agent, 'clinic', { kind: 'bed', bed: index + 1 }, bed.x, bed.z + 0.12, 0, 'lying', 0.69);
      return;
    }
    const waiting = index - plan.clinicBeds;
    const assignment: Assignment = { kind: 'clinicQueue', position: waiting + 1 };
    if (waiting < 3) put(agent, 'clinic', assignment, plan.clinicX - 1.1 + waiting * 0.65, plan.clinicZ - 3.05, 0, 'sitting');
    else put(agent, 'clinic', assignment, plan.clinicX + 2.35, plan.clinicZ - 2.7 - (waiting - 3) * 0.9, -Math.PI / 2, 'standing');
  });

  groups.work.forEach((agent, index) => {
    const seat = workSeat(index, plan);
    put(agent, 'work', { kind: 'desk', pod: seat.pod, desk: index + 1 }, seat.x, seat.z + 0.72, seat.rotation, 'sitting');
  });

  groups.patron.forEach((agent, index) => {
    if (index === 0) put(agent, 'patron', { kind: 'presenting' }, plan.patronX, plan.patronZ - 0.3, 0, 'standing');
    else put(agent, 'patron', { kind: 'ceoQueue', position: index }, plan.patronX - 2.25 + (index - 1) * 1.1, plan.patronZ + 4.25, Math.PI, 'standing');
  });

  return { plan, zones, placements };
}

/** Letter of a work pod: 0 → A. */
export function podLetter(index: number): string {
  return String.fromCharCode(65 + index);
}
