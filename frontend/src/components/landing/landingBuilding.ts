import type { AgentZone } from '@/components/observatory/officePlan';

/*
 * The building the landing page's galaxy condenses into: the observatory's five zones as a
 * cloud of points, plus the spots and walking routes of the scripted agents.
 *
 * Pure data, no three.js. Everything is authored in office metres (x to the right, z towards
 * the viewer, y up) — the same axes and roughly the same plan as the real floor in
 * `officePlan.ts` — and converted to the galaxy's own frame, where the disk lies in XY and the
 * walls rise along +Z.
 *
 * It is an illustration of the floor, not a copy of it: the work studio and the Patron room
 * are drawn larger than life so the route between them reads at a glance.
 */

export type Vec3 = [number, number, number];

const SCALE = 0.32;
const WALL = 1.5;
const DOOR = 1.7;

/** Office metres → the galaxy's frame. */
export function local(x: number, z: number, y = 0): Vec3 {
  return [x * SCALE, -z * SCALE, y * SCALE];
}

interface Room {
  id: AgentZone;
  cx: number;
  cz: number;
  w: number;
  d: number;
  /** Door gaps: which wall, and where along it (x on the n/s walls, z on the e/w walls). */
  doors: { side: 'n' | 's' | 'e' | 'w'; at: number }[];
}

const ROOMS: Room[] = [
  { id: 'setup', cx: -8.5, cz: -8, w: 7.45, d: 7.45, doors: [{ side: 'e', at: -8 }] },
  { id: 'lounge', cx: -8.5, cz: 0, w: 7.45, d: 7.45, doors: [{ side: 'e', at: 0 }] },
  { id: 'clinic', cx: -8.5, cz: 8, w: 7.45, d: 7.45, doors: [{ side: 'e', at: 8 }] },
  { id: 'work', cx: 2.6, cz: -6.2, w: 10.6, d: 9.2, doors: [{ side: 'w', at: -6.2 }, { side: 's', at: 5.4 }] },
  { id: 'patron', cx: 7.3, cz: 6, w: 8.6, d: 8, doors: [{ side: 'n', at: 5.4 }] },
];

const SPINE_X = -4.05;
const LINK_X = 5.4;

/** Colour slots of the cloud. The scene owns the actual colours. */
export const TINTS = ['structure', 'spine', 'setup', 'lounge', 'clinic', 'work', 'patron'] as const;
export type Tint = (typeof TINTS)[number];

/** Where each zone's label hangs: above the middle of its far wall. */
// The Patron room's caption sits over its far corner: its doorway is where the hero's tag is.
export const ZONE_LABELS: { zone: AgentZone; at: Vec3 }[] = ROOMS.map((room) => ({
  zone: room.id,
  at: local(room.id === 'patron' ? room.cx + room.w / 2 - 1.2 : room.cx, room.cz - room.d / 2, WALL + 1.1),
}));

const DESKS: [number, number][] = [
  [-0.6, -8.5],
  [2.6, -8.5],
  [5.8, -8.5],
  [-0.6, -4.7],
  [2.6, -4.7],
  [5.8, -4.7],
];
const seat = (desk: number, y = 0.55): Vec3 => local(DESKS[desk][0], DESKS[desk][1] + 0.95, y);
const BODY = 0.55;

/** The scripted agent's desk, and the top of it, where its task lands. */
export const HERO_SEAT = seat(5);
export const HERO_DESK_TOP = local(DESKS[5][0], DESKS[5][1], 1.05);
/** Out in the spiral arms: where a task comes from before anyone has claimed it. */
export const TASK_ORIGIN = local(17, -15, 6.5);

/** Desk → studio door → Patron room door → in front of the Patron's desk. */
export const HERO_ROUTE: Vec3[] = [
  HERO_SEAT,
  local(LINK_X, -2.9, BODY),
  local(LINK_X, 3.1, BODY),
  local(7.9, 5.5, BODY),
];

/** A second agent that drifts between the lounge and a free desk, so the floor feels lived in. */
export const RUNNER_ROUTE: Vec3[] = [
  local(-7.4, 0.6, BODY),
  local(-5.7, 0, BODY),
  local(SPINE_X, 0, BODY),
  local(SPINE_X, -6.2, BODY),
  local(1.4, -6.2, BODY),
  local(1.4, -3.75, BODY),
  seat(4),
];

/** Agents that hold still: three at desks, one arriving at reception, one resting, one idle. */
export const STILL_AGENTS: { at: Vec3; zone: AgentZone }[] = [
  { at: seat(0), zone: 'work' },
  { at: seat(1), zone: 'work' },
  { at: seat(3), zone: 'work' },
  { at: local(-8.5, -7.5, BODY), zone: 'setup' },
  { at: local(-9.95, 7.2, 0.8), zone: 'clinic' },
  { at: local(-9.5, 0.6, BODY), zone: 'lounge' },
];

/** A point `progress` (0–1) of the way along a route, by distance. Writes into `out`. */
export function along(route: readonly Vec3[], progress: number, out: Vec3): Vec3 {
  if (progress >= 1) {
    const last = route[route.length - 1];
    out[0] = last[0];
    out[1] = last[1];
    out[2] = last[2];
    return out;
  }
  let total = 0;
  for (let i = 1; i < route.length; i++) total += distance(route[i - 1], route[i]);
  let remaining = Math.min(Math.max(progress, 0), 1) * total;
  for (let i = 1; i < route.length; i++) {
    const length = distance(route[i - 1], route[i]);
    if (remaining <= length || i === route.length - 1) {
      const f = length > 0 ? Math.min(remaining / length, 1) : 1;
      for (let axis = 0; axis < 3; axis++) out[axis] = route[i - 1][axis] + (route[i][axis] - route[i - 1][axis]) * f;
      return out;
    }
    remaining -= length;
  }
  return out;
}

function distance(a: Vec3, b: Vec3): number {
  return Math.hypot(b[0] - a[0], b[1] - a[1], b[2] - a[2]);
}

export interface BuildingCloud {
  /** xyz per point, in the galaxy's frame. */
  positions: Float32Array;
  /** Index into `TINTS`. */
  tints: Uint8Array;
  /** Brightness of the tint, about 0.4–1.1. */
  shades: Float32Array;
  /** Point size relative to a spiral star. */
  sizes: Float32Array;
  /** 0–1: floor first, then walls, then furniture. The scene assembles the building in this order. */
  order: Float32Array;
}

interface Feature {
  weight: number;
  tint: Tint;
  shade: number;
  size: number;
  order: number;
  sample: (random: () => number) => [number, number, number];
}

type Segment = [number, number, number, number];

/** The four walls of a room as segments, with the doorways cut out. */
function wallSegments(room: Room): Segment[] {
  const x0 = room.cx - room.w / 2;
  const x1 = room.cx + room.w / 2;
  const z0 = room.cz - room.d / 2;
  const z1 = room.cz + room.d / 2;
  const sides: { side: 'n' | 's' | 'e' | 'w'; from: number; to: number; fixed: number; alongX: boolean }[] = [
    { side: 'n', from: x0, to: x1, fixed: z0, alongX: true },
    { side: 's', from: x0, to: x1, fixed: z1, alongX: true },
    { side: 'w', from: z0, to: z1, fixed: x0, alongX: false },
    { side: 'e', from: z0, to: z1, fixed: x1, alongX: false },
  ];
  const segments: Segment[] = [];
  for (const wall of sides) {
    const gaps = room.doors.filter((door) => door.side === wall.side).map((door) => door.at).sort((a, b) => a - b);
    let cursor = wall.from;
    for (const stop of [...gaps.map((at) => [at - DOOR / 2, at + DOOR / 2]), [wall.to, wall.to]]) {
      if (stop[0] > cursor) {
        segments.push(wall.alongX ? [cursor, wall.fixed, stop[0], wall.fixed] : [wall.fixed, cursor, wall.fixed, stop[0]]);
      }
      cursor = stop[1];
    }
  }
  return segments;
}

const span = ([x0, z0, x1, z1]: Segment) => Math.hypot(x1 - x0, z1 - z0);

function features(): Feature[] {
  const list: Feature[] = [];
  const jitter = (random: () => number, amount = 0.05) => (random() - 0.5) * amount;

  const line = (segment: Segment, y: number, tint: Tint, density: number, order: number, shade = 1, size = 0.72) =>
    list.push({
      weight: span(segment) * density,
      tint,
      shade,
      size,
      order,
      sample: (random) => {
        const f = random();
        return [segment[0] + (segment[2] - segment[0]) * f + jitter(random), y + jitter(random), segment[1] + (segment[3] - segment[1]) * f + jitter(random)];
      },
    });

  const box = (cx: number, cz: number, w: number, d: number, h: number, tint: Tint, order: number) =>
    list.push({
      weight: (w + d) * 2 * 9 + w * d * 10,
      tint,
      shade: 1.05,
      size: 0.66,
      order,
      sample: (random) => {
        const pick = random();
        if (pick < 0.45) {
          // The rim of the top face.
          const onX = random() < w / (w + d);
          const side = random() < 0.5 ? -0.5 : 0.5;
          const f = random() - 0.5;
          return onX ? [cx + f * w, h, cz + side * d] : [cx + side * w, h, cz + f * d];
        }
        if (pick < 0.65) {
          // The four upright edges.
          return [cx + (random() < 0.5 ? -0.5 : 0.5) * w, random() * h, cz + (random() < 0.5 ? -0.5 : 0.5) * d];
        }
        return [cx + (random() - 0.5) * w, h, cz + (random() - 0.5) * d];
      },
    });

  const ring = (cx: number, cz: number, radius: number, y: number, tint: Tint, order: number) =>
    list.push({
      weight: radius * 2 * Math.PI * 9,
      tint,
      shade: 1.05,
      size: 0.66,
      order,
      sample: (random) => {
        const angle = random() * Math.PI * 2;
        return [cx + Math.cos(angle) * radius, y, cz + Math.sin(angle) * radius];
      },
    });

  // The floor slab and the corridors that tie the rooms together.
  const edge = 13;
  for (const segment of [[-edge, -edge, edge, -edge], [-edge, edge, edge, edge], [-edge, -edge, -edge, edge], [edge, -edge, edge, edge]] as Segment[]) {
    line(segment, 0, 'structure', 4.2, 0, 0.7);
  }
  line([SPINE_X, -11.7, SPINE_X, 11.7], 0, 'spine', 4.5, 0.05);
  line([SPINE_X, -6.2, 2.6 - 10.6 / 2, -6.2], 0, 'spine', 4.5, 0.05);
  line([LINK_X - 0.85, -1.6, LINK_X - 0.85, 2], 0, 'spine', 5, 0.05);
  line([LINK_X + 0.85, -1.6, LINK_X + 0.85, 2], 0, 'spine', 5, 0.05);

  for (const room of ROOMS) {
    const walls = wallSegments(room);
    // Floor: a sparse fill, so each zone reads as a tinted patch.
    list.push({
      weight: room.w * room.d * 2.3,
      tint: room.id,
      shade: 0.5,
      size: 0.58,
      order: 0.1,
      sample: (random) => [room.cx + (random() - 0.5) * room.w, 0, room.cz + (random() - 0.5) * room.d],
    });
    for (const segment of walls) {
      line(segment, 0, room.id, 6.5, 0.2, 0.9);
      line(segment, WALL, room.id, 7.5, 0.55, 1.1);
      list.push({
        weight: span(segment) * WALL * 1.7,
        tint: room.id,
        shade: 0.62,
        size: 0.56,
        order: 0.4,
        sample: (random) => {
          const f = random();
          return [segment[0] + (segment[2] - segment[0]) * f, random() * WALL, segment[1] + (segment[3] - segment[1]) * f];
        },
      });
      // Uprights at both ends of every wall piece: room corners and door jambs.
      for (const [x, z] of [[segment[0], segment[1]], [segment[2], segment[3]]]) {
        list.push({ weight: 9, tint: room.id, shade: 1.1, size: 0.7, order: 0.45, sample: (random) => [x, random() * WALL * 1.12, z] });
      }
    }
  }

  // Furniture: enough to tell the rooms apart without labels.
  for (const [x, z] of DESKS) box(x, z, 1.7, 0.8, 0.75, 'work', 0.8);
  box(7.9, 7.4, 2.8, 1.05, 0.8, 'patron', 0.8);
  ring(7.9, 5.5, 1.15, 0.02, 'patron', 0.85);
  box(-9.5, 1.75, 2.6, 0.9, 0.6, 'lounge', 0.8);
  ring(-7.9, -0.9, 0.75, 0.5, 'lounge', 0.8);
  box(-9.95, 7.2, 1.05, 2.3, 0.55, 'clinic', 0.8);
  box(-7.05, 7.2, 1.05, 2.3, 0.55, 'clinic', 0.8);
  box(-8.5, -9.5, 2.9, 0.7, 1.0, 'setup', 0.8);

  return list;
}

/** `count` points laid over the building, deterministically for a given random source. */
export function buildCloud(count: number, random: () => number): BuildingCloud {
  const list = features();
  const total = list.reduce((sum, feature) => sum + feature.weight, 0);
  const cloud: BuildingCloud = {
    positions: new Float32Array(count * 3),
    tints: new Uint8Array(count),
    shades: new Float32Array(count),
    sizes: new Float32Array(count),
    order: new Float32Array(count),
  };
  let index = 0;
  let cumulative = 0;
  for (const feature of list) {
    cumulative += feature.weight;
    // Cumulative rounding: the shares add up to exactly `count`.
    const end = Math.round((cumulative / total) * count);
    for (; index < end; index++) {
      const [x, y, z] = feature.sample(random);
      const at = local(x, z, y);
      cloud.positions[index * 3] = at[0];
      cloud.positions[index * 3 + 1] = at[1];
      cloud.positions[index * 3 + 2] = at[2];
      cloud.tints[index] = TINTS.indexOf(feature.tint);
      cloud.shades[index] = feature.shade * (0.78 + random() * 0.32);
      cloud.sizes[index] = feature.size;
      cloud.order[index] = feature.order;
    }
  }
  return cloud;
}
