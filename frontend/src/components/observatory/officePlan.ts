/*
 * The observatory's floor plan and seating, as pure data.
 *
 * The floor is a small company seen from above, and it is as big as the team. Down the west
 * wall, the sick bay over the front desk; beside them the main aisle; then the work floor,
 * which is an L of pods of four desks — a row of them across the building and, at its west
 * end, a leg that runs up to the back wall. The corner the L leaves at the back is the
 * patron's office, on a raised platform: the patron sits with their back to the east wall,
 * facing down the steps to meet whoever comes up the leg with a report. The lounge runs
 * across the front of the building.
 *
 * The rooms are the agents' *states* — working, idle, offline, not set up yet — because an
 * agent belongs to the workspace, not to one project, and may sit on several at once. Handing
 * work in for review is not a state: an agent goes up to the patron with it and comes back
 * (the scene plays that trip; this file only says where the patron's desk is).
 *
 * One function decides where every agent is: which zone, which resource (desk, bed, queue
 * spot) and in what pose. The 3D scene places figures from it, and the tooltip and the detail
 * modal word the same assignment from it, so the three can never disagree. Nothing here is
 * random: the same agents and tasks always produce the same office. What an idle agent does
 * minute by minute in the lounge is the scene's business (`loungeLife.ts`), and it only ever
 * picks among the spots this file lays out.
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

/** What a figure is doing where it stands; the scene animates each one differently. */
export type Activity = 'type' | 'think' | 'relax' | 'snack' | 'play' | 'read' | 'queue' | 'present' | 'rest' | 'wait';

/** A point of the floor: x across, y up, z toward the front of the building. */
export type Point = readonly [x: number, y: number, z: number];

/** Which physical resource an agent holds. Worded on screen by the page, from these codes. */
export type Assignment =
  | { kind: 'desk'; pod: number; desk: number }
  | { kind: 'bed'; bed: number }
  | { kind: 'clinicQueue'; position: number }
  | { kind: 'lounge' }
  | { kind: 'checkIn'; position: number };

/**
 * Somewhere a figure can be, and the way in to it: the first point of `approach` lies on a
 * walkway of the floor, and any further ones lead from there round the furniture to the spot.
 */
export interface Spot {
  x: number;
  y: number;
  z: number;
  rotation: number;
  pose: Pose;
  activity: Activity;
  approach: Point[];
}

export interface Placement extends Spot {
  zone: AgentZone;
  assignment: Assignment;
  /** For an idle agent: which lounge spot it starts out at (an index into `loungeSpots`). */
  start?: number;
}

export type StationKind = 'sofa' | 'bar' | 'table' | 'nook';

/** One piece of the lounge: a sofa group, the snack bar, a ping-pong table, a reading corner. */
export interface Station {
  kind: StationKind;
  x: number;
  z: number;
  /** 0 when it faces the front of the building, π when it faces the back. */
  rotation: number;
  width: number;
  /** How many agents it takes at once. */
  places: number;
  /** A reading corner in a front row has no bookshelf: it would hide whoever sits behind it. */
  low?: boolean;
}

export interface LoungeSpot extends Spot {
  station: number;
  kind: StationKind;
}

/** A rectangle of the floor, by its centre. */
export interface Room {
  x: number;
  z: number;
  width: number;
  depth: number;
}

/** A straight strip of clear floor between two points, along x or along z. */
export interface Walkway {
  from: Point;
  to: Point;
}

/** A desk in a pod. `rotation` is 0 for the row whose owner faces the back wall, π for the row facing it. */
export interface Desk {
  x: number;
  z: number;
  rotation: number;
  pod: number;
}

export interface OfficePlan {
  /** A floor too crowded to name every agent at once. */
  large: boolean;
  headcount: number;
  workCount: number;
  clinicCount: number;
  clinicBeds: number;
  clinicWaiting: number;
  /** Reports handed in and not yet answered: the stack on the patron's desk. */
  reviewCount: number;
  floorWidth: number;
  floorDepth: number;
  centerX: number;
  /** The line the main aisle is walked along, between the west rooms and the work floor. */
  aisleX: number;
  reception: Room;
  clinic: Room;
  /** The long arm of the L: the pods across the building. */
  work: Room;
  /** The short arm of the L: the pods that run up to the back wall, beside the patron. */
  workLeg: Room;
  lounge: Room;
  /** The patron's office: a raised platform in the back corner the L leaves. */
  patron: Room;
  platformHeight: number;
  /** The steps up to the platform from the leg of the L, climbing east. */
  stairs: { foot: number; top: number; z: number; width: number };
  patronDesk: { x: number; z: number };
  noticeBoard: { x: number; z: number };
  receptionDoorZ: number;
  clinicDoorZ: number;
  /** Where the lounge begins: the line the partition stands on. */
  partitionZ: number;
  pods: { x: number; z: number }[];
  /** Four per pod, in pod order; the first `headcount` are owned, in name order. */
  desks: Desk[];
  beds: { x: number; z: number }[];
  stations: Station[];
  loungeSpots: LoungeSpot[];
  loungeLanes: number[];
  /** Where figures walk: straight strips of clear floor, each along x or along z. */
  walkways: Walkway[];
  /** Everything that changes the building's shape, so the scene knows when to rebuild. */
  shape: string;
}

export interface OfficeLayout {
  plan: OfficePlan;
  zones: Map<string, AgentZone>;
  placements: Map<string, Placement>;
  /** Which desk is whose (an index into `plan.desks`), wherever its owner is right now. */
  desks: Map<string, number>;
}

// ─── Dimensions ──────────────────────────────────────────────────────────────

/** The west column: sick bay over front desk. */
const COLUMN = 7.2;
const AISLE = 1.8;
/** The patron's platform: just room for a desk, a visitor and the notice board. */
const PLATFORM_WIDTH = 5.6;
const PLATFORM_DEPTH = 3.4;
export const PLATFORM_HEIGHT = 0.9;
const STAIRS = 1.2;
const SEATS_PER_POD = 4;
const POD_WIDTH = 3.7;
const POD_PITCH = 4.6;
/** From a pod's centre to the strip of floor its chairs are reached from, in front or behind. */
const POD_WALK = 1.97;
/** How far the first row of pods — the leg of the L — stands from the back wall. */
const LEG_POD = 2;
/** From a desk's centre to the chair in front of it. */
export const DESK_SEAT = 0.72;
const BED_PITCH = 2.7;
const STATION_DEPTH = 2.6;
/** The walking strip in front of a row of lounge stations. */
const LANE = 1.1;
/** Floor height of a standing figure. */
const STAND = 0.02;
/** How high a seated figure's hips are, by what it sits on: its legs rest on the seat, not in it. */
const SEAT = { chair: 0.16, sofa: 0.19, armchair: 0.27, bench: 0.045 };
const LIE = 0.69;
const MAX_BEDS = 6;

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
 * Where an agent belongs. Priority: offline → draft → work → not placed → lounge.
 * Changing this order means changing the scene, the modal and the zone bar together — they
 * all read it from here.
 *
 * A task waiting for the patron's signature does not hold its agent anywhere: the report is
 * on the patron's desk, and the agent is back at its own if it has more to do, or in the
 * lounge if it has not. It used to stand in the patron's office for as long as the review
 * took, which could be days, and looked like the busiest agent on the floor while idle.
 *
 * Reception is for an agent that is not ready to take work: it holds a draft, or it has no
 * runtime yet. The design's rule was "carries no skill" (DESIGN §6.1), but linking a skill is
 * optional here — every agent comes with what it needs to work — so that rule parked a whole
 * working team at the front desk for good.
 */
export function zoneOf(agent: ObservedAgent, tasks: readonly ObservedTask[]): Exclude<AgentZone, 'patron'> {
  const open = openTasksOf(agent.id, tasks).map((task) => normalizeTaskStatus(task.status));
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

// ─── Lounge ──────────────────────────────────────────────────────────────────

interface LocalSpot {
  x: number;
  z: number;
  y: number;
  rotation: number;
  pose: Pose;
  activity: Activity;
  /** A point to pass through on the way in from the lane, where furniture stands in the way. */
  via?: [x: number, z: number];
}

/** How many agents the snack bar serves at once. */
function barPlaces(headcount: number): number {
  return Math.max(2, Math.min(5, Math.ceil(headcount / 3)));
}

/** A station in its own frame: +z faces the lane it is entered from. */
export function stationWidth(kind: StationKind, places: number): number {
  if (kind === 'sofa') return 4.4;
  if (kind === 'table') return 4.2;
  if (kind === 'nook') return 2.5;
  return 1.3 + places * 0.95;
}

function stationSpots(kind: StationKind, places: number): LocalSpot[] {
  if (kind === 'sofa') {
    return [
      { x: -1.04, z: -0.49, y: SEAT.sofa, rotation: 0, pose: 'sitting', activity: 'relax', via: [-1.55, 0.5] },
      { x: -0.06, z: -0.49, y: SEAT.sofa, rotation: 0, pose: 'sitting', activity: 'relax', via: [0.5, 0.5] },
      { x: 1.5, z: 0.1, y: SEAT.armchair, rotation: -Math.PI / 2, pose: 'sitting', activity: 'relax' },
    ];
  }
  if (kind === 'table') {
    return [
      { x: -1.6, z: -0.1, y: STAND, rotation: Math.PI / 2, pose: 'standing', activity: 'play' },
      { x: 1.6, z: -0.1, y: STAND, rotation: -Math.PI / 2, pose: 'standing', activity: 'play' },
    ];
  }
  if (kind === 'nook') return [{ x: 0.35, z: -0.15, y: SEAT.armchair, rotation: 0, pose: 'sitting', activity: 'read' }];
  const width = stationWidth('bar', places);
  return Array.from({ length: places }, (_, index) => ({
    x: -width / 2 + 1.25 + 0.475 + index * 0.95,
    z: -0.3,
    y: STAND,
    rotation: Math.PI,
    pose: 'standing' as const,
    activity: 'snack' as const,
  }));
}

/** Where along a bar's counter its places stand, in the bar's own frame. */
export function barStools(places: number): number[] {
  return stationSpots('bar', places).map((spot) => spot.x);
}

type Furniture = { kind: StationKind; places: number; width: number };

/**
 * What the lounge is furnished with for a team of this size. Every idle agent must have
 * somewhere to be, with choice left over: an all-idle team is the most common sight there is.
 * Table tennis comes in pairs — one table alone looks left behind, two make a games corner.
 */
function loungeFurniture(headcount: number): Furniture[] {
  const count = { bar: headcount > 15 ? 2 : 1, sofa: Math.ceil(headcount / 4), table: Math.max(2, 2 * Math.ceil(headcount / 16)), nook: Math.max(1, Math.floor(headcount / 6)) };
  const places = { bar: barPlaces(headcount), sofa: 3, table: 2, nook: 1 };
  // In the order they are placed: the games claim the ends of the first row, then the tall
  // pieces take what is left against the partition, then the sofas fill in.
  return (['table', 'bar', 'nook', 'sofa'] as const).flatMap((kind) =>
    Array.from({ length: count[kind] }, () => ({ kind, places: places[kind], width: stationWidth(kind, places[kind]) })),
  );
}

const STATION_GAP = 0.3;

/** The floor width that holds a set of stations side by side in one row. */
function rowWidth(items: readonly Furniture[]): number {
  return items.reduce((sum, item) => sum + item.width, 0) + STATION_GAP * (items.length + 1);
}

/** A stretch reads best with the games at its two ends and everything else between them. */
function arrange(items: Furniture[]): Furniture[] {
  const tables = items.filter((item) => item.kind === 'table');
  const order = { sofa: 0, bar: 1, nook: 2, table: 3 };
  const rest = items.filter((item) => item.kind !== 'table').sort((a, b) => order[a.kind] - order[b.kind]);
  return [...tables.slice(0, Math.ceil(tables.length / 2)), ...rest, ...tables.slice(Math.ceil(tables.length / 2))];
}

interface Stretch {
  from: number;
  to: number;
  row: number;
  west: boolean;
  items: Furniture[];
}

/**
 * Lay the lounge out across the front of the building: a row of stations against the
 * partition with a lane in front of it, then — only when the team has outgrown that — a row
 * facing it across the lane, then further pairs. The main aisle comes down through every
 * row, so each row is two stretches: a short one west of the aisle, under the front desk,
 * which is the snack corner; and a long one east of it, where the two table-tennis tables
 * stand at the ends with the sofas between them.
 */
function furnishLounge(furniture: readonly Furniture[], west: [number, number], east: [number, number], top: number) {
  const stretches: Stretch[] = [];
  let rows = 0;
  const addRow = () => {
    stretches.push({ from: west[0], to: west[1], row: rows, west: true, items: [] }, { from: east[0], to: east[1], row: rows, west: false, items: [] });
    rows += 1;
  };
  addRow();
  const fits = (stretch: Stretch, item: Furniture) => rowWidth([...stretch.items, item]) <= stretch.to - stretch.from + 0.001;
  for (const item of furniture) {
    // Tall pieces — the bar, the bookshelves — go against the partition, in a back row, and
    // west of the aisle first; in a front row they would hide whoever is at them. The bar
    // waits for a back row; a reading corner may take a front one and go without its shelf.
    // The games and the sofas go east, into the first row that has room.
    const tall = item.kind === 'bar' || item.kind === 'nook';
    const rank = (stretch: Stretch) => (tall ? (stretch.row % 2) * 100 + (stretch.west ? 0 : 10) + stretch.row : (stretch.west ? 100 : 0) + stretch.row);
    const pick = () => stretches.filter((stretch) => fits(stretch, item) && (item.kind !== 'bar' || stretch.row % 2 === 0)).sort((a, b) => rank(a) - rank(b))[0];
    let stretch = pick();
    for (let attempt = 0; !stretch && attempt < 2; attempt++) {
      addRow();
      stretch = pick();
    }
    stretch?.items.push(item);
  }
  const stations: Station[] = [];
  const spots: LoungeSpot[] = [];
  const lanes: number[] = [];
  for (let row = 0; row < rows; row++) {
    const pair = Math.floor(row / 2);
    const back = row % 2 === 0;
    const backRow = top + 0.25 + pair * (2 * STATION_DEPTH + LANE) + STATION_DEPTH / 2;
    const lane = backRow + STATION_DEPTH / 2 + LANE / 2;
    if (back) lanes.push(lane);
    const z = back ? backRow : lane + LANE / 2 + STATION_DEPTH / 2;
    const rotation = back ? 0 : Math.PI;
    const sign = back ? 1 : -1;
    for (const stretch of stretches.filter((one) => one.row === row)) {
      const items = arrange(stretch.items);
      const gap = (stretch.to - stretch.from - items.reduce((sum, item) => sum + item.width, 0)) / (items.length + 1);
      let cursor = stretch.from;
      for (const item of items) {
        cursor += gap;
        const x = cursor + item.width / 2;
        cursor += item.width;
        const station = stations.length;
        stations.push({ kind: item.kind, x, z, rotation, width: item.width, places: item.places, ...(item.kind === 'nook' && !back ? { low: true } : {}) });
        for (const local of stationSpots(item.kind, item.places)) {
          const approach: Point[] = local.via
            ? [[x + sign * local.via[0], STAND, lane], [x + sign * local.via[0], STAND, z + sign * local.via[1]]]
            : [[x + sign * local.x, STAND, lane]];
          spots.push({ station, kind: item.kind, x: x + sign * local.x, y: local.y, z: z + sign * local.z, rotation: local.rotation + rotation, pose: local.pose, activity: local.activity, approach });
        }
      }
    }
  }
  // A lone back row still needs its lane in front of it.
  const pairs = Math.floor(rows / 2);
  const depth = pairs * (2 * STATION_DEPTH + LANE) + (rows % 2 ? STATION_DEPTH + LANE : 0) + 0.5;
  return { stations, spots, lanes, depth };
}

// ─── The floor ───────────────────────────────────────────────────────────────

/** How many pods fit in the leg of the L, beside the patron's platform and its steps. */
function legPods(workWidth: number): number {
  return Math.max(1, Math.floor((workWidth - PLATFORM_WIDTH - STAIRS - 1.8) / (POD_WIDTH + 0.6)));
}

/** The building for a team of `agentCount`. Per-zone counts only fill in the signs. */
export function createOfficePlan(counts: { work: number; clinic: number; review: number }, agentCount: number): OfficePlan {
  const headcount = Math.max(1, agentCount);
  // Never fewer than three pods: with two there is no L, only a row.
  const podCount = Math.max(3, Math.ceil(headcount / SEATS_PER_POD));
  const furniture = loungeFurniture(headcount);
  // The work floor is at least wide enough for the lounge under it to show the games and a
  // sofa in one row. Then: the fewest rows of pods, and the fewest pods across, that seat the team.
  const tables = furniture.filter((item) => item.kind === 'table').slice(0, 2);
  const firstSofa = furniture.filter((item) => item.kind === 'sofa').slice(0, 1);
  const loungeWidth = rowWidth([...tables, ...firstSofa]) + 0.5;
  // Rows of pods: as many as the team needs — and as many as the west column is deep, so a
  // big sick bay does not leave bare floor between the pods and the lounge.
  const clinicBeds = Math.max(2, Math.min(MAX_BEDS, Math.ceil(headcount / 4)));
  const clinicDepth = Math.ceil(clinicBeds / 2) * BED_PITCH + 1.7;
  const rowsToFill = Math.floor((clinicDepth + 3.5 - LEG_POD - POD_WALK - 0.75) / (2 * POD_WALK));
  const podRows = Math.max(podCount <= 6 ? 1 : podCount <= 12 ? 2 : 3, Math.min(rowsToFill, Math.ceil((podCount - 1) / 2)));
  let podColumns = 2;
  const widthFor = (columns: number) => Math.max(columns * POD_PITCH + 0.8, loungeWidth);
  while (podColumns * podRows + legPods(widthFor(podColumns)) < podCount) podColumns += 1;
  const workWidth = widthFor(podColumns);
  const inLeg = Math.min(legPods(workWidth), Math.max(1, podCount - podColumns * podRows));
  const inRows = podCount - inLeg;

  // Rows of pods share the strip of floor between them, so they stand two walks apart.
  const lastStrip = LEG_POD + POD_WALK + podRows * 2 * POD_WALK;
  const northDepth = Math.max(lastStrip + 0.75, clinicDepth + 3.5);
  const floorWidth = COLUMN + AISLE + workWidth;

  const left = -floorWidth / 2;
  const right = floorWidth / 2;
  const columnEdge = left + COLUMN;
  const aisleX = columnEdge + AISLE / 2;
  const workLeft = columnEdge + AISLE;
  const stretches: [[number, number], [number, number]] = [[left + 0.5, aisleX - 0.9], [aisleX + 0.9, right - 0.5]];
  const loungeDepth = furnishLounge(furniture, ...stretches, 0).depth;
  const floorDepth = northDepth + loungeDepth;
  const back = -floorDepth / 2;
  const partitionZ = back + northDepth;
  const lounge = furnishLounge(furniture, ...stretches, partitionZ);

  // The patron's platform, in the back corner; its steps come down west into the leg of the L.
  const platformWest = right - PLATFORM_WIDTH;
  const stairsFoot = platformWest - STAIRS;
  const sideWalk = stairsFoot - 0.45;
  const patronDesk = { x: right - 1.95, z: back + PLATFORM_DEPTH / 2 + 0.05 };

  // The pods. Rows across the building first, west to east; then the leg, centred in the
  // floor between the aisle and the steps.
  const strip = (index: number) => back + LEG_POD + POD_WALK + index * 2 * POD_WALK;
  const rowPods = Array.from({ length: inRows }, (_, index) => ({
    x: workLeft + (workWidth * ((index % podColumns) + 0.5)) / podColumns,
    z: strip(Math.floor(index / podColumns)) + POD_WALK,
  }));
  const legFrom = workLeft + 0.5;
  const legPitch = (sideWalk - 0.4 - legFrom) / inLeg;
  const leg = Array.from({ length: inLeg }, (_, index) => ({ x: legFrom + legPitch * (index + 0.5), z: back + LEG_POD }));
  const pods = [...rowPods, ...leg];
  // In a pod: back row west, back row east, front row west, front row east.
  const desks: Desk[] = pods.flatMap((pod, index) =>
    [[-0.9, -0.45, Math.PI], [0.9, -0.45, Math.PI], [-0.9, 0.45, 0], [0.9, 0.45, 0]].map(([x, z, rotation]) => ({ x: pod.x + x, z: pod.z + z, rotation, pod: index })),
  );
  const clinicX = left + COLUMN / 2;
  const beds = Array.from({ length: clinicBeds }, (_, index) => ({
    x: clinicX - BED_PITCH / 2 + (index % 2) * BED_PITCH - 0.25,
    z: back + 1.5 + Math.floor(index / 2) * BED_PITCH,
  }));

  // Where figures walk. The main aisle; the strip of floor between each two rows of pods
  // (the first also runs under the front of the platform); the gaps between pods, which join
  // the strips; the walk beside the steps, which is the way up to the patron; and the lane of
  // each lounge row. The partition has one way through it: the aisle.
  const east = right - 0.8;
  const strips = Array.from({ length: podRows + 1 }, (_, index) => strip(index));
  const columnXs = [...new Set(rowPods.map((pod) => pod.x))];
  const rowGaps = columnXs.slice(1).map((x, index) => (x + columnXs[index]) / 2);
  const legGaps = leg.slice(1).map((pod, index) => (pod.x + leg[index].x) / 2);
  const legTop = back + LEG_POD - POD_WALK + 0.8;
  const walkways: Walkway[] = [
    { from: [aisleX, STAND, legTop], to: [aisleX, STAND, lounge.lanes[lounge.lanes.length - 1]] },
    ...strips.map((z): Walkway => ({ from: [aisleX, STAND, z], to: [east, STAND, z] })),
    ...rowGaps.map((x): Walkway => ({ from: [x, STAND, strips[0]], to: [x, STAND, strips[strips.length - 1]] })),
    ...[...legGaps, sideWalk].map((x): Walkway => ({ from: [x, STAND, legTop], to: [x, STAND, strips[0]] })),
    ...lounge.lanes.map((z): Walkway => ({ from: [left + 0.6, STAND, z], to: [right - 0.6, STAND, z] })),
  ];

  return {
    large: headcount > 12,
    headcount,
    workCount: counts.work,
    clinicCount: counts.clinic,
    clinicBeds,
    clinicWaiting: Math.max(0, counts.clinic - clinicBeds),
    reviewCount: counts.review,
    floorWidth,
    floorDepth,
    centerX: 0,
    aisleX,
    reception: { x: clinicX, z: back + clinicDepth + (northDepth - clinicDepth) / 2, width: COLUMN, depth: northDepth - clinicDepth },
    clinic: { x: clinicX, z: back + clinicDepth / 2, width: COLUMN, depth: clinicDepth },
    work: { x: workLeft + workWidth / 2, z: back + PLATFORM_DEPTH + (northDepth - PLATFORM_DEPTH) / 2, width: workWidth, depth: northDepth - PLATFORM_DEPTH },
    workLeg: { x: (workLeft + platformWest) / 2, z: back + PLATFORM_DEPTH / 2, width: platformWest - workLeft, depth: PLATFORM_DEPTH },
    lounge: { x: 0, z: partitionZ + lounge.depth / 2, width: floorWidth, depth: lounge.depth },
    patron: { x: right - PLATFORM_WIDTH / 2, z: back + PLATFORM_DEPTH / 2, width: PLATFORM_WIDTH, depth: PLATFORM_DEPTH },
    platformHeight: PLATFORM_HEIGHT,
    stairs: { foot: stairsFoot, top: platformWest, z: patronDesk.z, width: 1.5 },
    patronDesk,
    noticeBoard: { x: right - 3.6, z: back + 0.4 },
    receptionDoorZ: back + clinicDepth + (northDepth - clinicDepth) / 2,
    clinicDoorZ: back + clinicDepth - 0.9,
    partitionZ,
    pods,
    desks,
    beds,
    stations: lounge.stations,
    loungeSpots: lounge.spots,
    loungeLanes: lounge.lanes,
    walkways,
    shape: [headcount, floorWidth.toFixed(1), floorDepth.toFixed(1)].join('x'),
  };
}

/** The walkway nearest a point across the floor, among those that run past it front to back. */
function sideWalkway(plan: OfficePlan, x: number, z: number, westward: boolean): number {
  const beside = plan.walkways
    .filter(({ from, to }) => Math.abs(from[0] - to[0]) < 0.01 && Math.min(from[2], to[2]) <= z + 0.01 && Math.max(from[2], to[2]) >= z - 0.01)
    .map(({ from }) => from[0])
    .filter((at) => (westward ? at < x : at > x));
  return beside.length ? (westward ? Math.max(...beside) : Math.min(...beside)) : plan.aisleX;
}

/** Where a desk's owner sits, and the way there. */
export function deskSpot(plan: OfficePlan, index: number, activity: Activity): Spot {
  const desk = plan.desks[index];
  const pod = plan.pods[desk.pod];
  const facingBack = desk.rotation === 0;
  const z = desk.z + (facingBack ? DESK_SEAT : -DESK_SEAT);
  const back = -plan.floorDepth / 2;
  // A chair is reached from the strip of floor on its side of the pod. The far side of the
  // leg's pods has no strip — it is the back wall — so those chairs are reached from beside.
  const againstWall = !facingBack && pod.z - POD_WALK < back + 0.5;
  const entry: Point = againstWall ? [sideWalkway(plan, desk.x, z, desk.x < pod.x), STAND, z] : [desk.x, STAND, pod.z + (facingBack ? POD_WALK : -POD_WALK)];
  return { x: desk.x, y: SEAT.chair, z, rotation: facingBack ? Math.PI : 0, pose: 'sitting', activity, approach: [entry] };
}

/**
 * Where someone handing in a report stands: on the platform in front of the patron's desk,
 * facing it. `position` 0 is at the desk and 1 waits behind; the rest queue at the foot of the
 * steps, back down the leg of the L.
 */
export function reportSpot(plan: OfficePlan, position: number): Spot {
  const height = plan.platformHeight + STAND;
  const beside = plan.stairs.foot - 0.45;
  if (position > 1) {
    const z = plan.stairs.z + 0.9 * (position - 2);
    return { x: beside, y: STAND, z, rotation: Math.PI / 2, pose: 'standing', activity: 'queue', approach: [[beside, STAND, z]] };
  }
  return {
    x: plan.patronDesk.x - 1.45 - position * 0.95,
    y: height,
    z: plan.stairs.z,
    rotation: Math.PI / 2,
    pose: 'standing',
    activity: position === 0 ? 'present' : 'queue',
    approach: [[beside, STAND, plan.stairs.z], [plan.stairs.foot, STAND, plan.stairs.z], [plan.stairs.top, height, plan.stairs.z]],
  };
}

/** Seat every agent. The single source of truth for scene, tooltip and modal. */
export function layoutOffice(agents: readonly ObservedAgent[], tasks: readonly ObservedTask[]): OfficeLayout {
  const zones = new Map<string, AgentZone>();
  const groups = { setup: [] as ObservedAgent[], lounge: [] as ObservedAgent[], clinic: [] as ObservedAgent[], work: [] as ObservedAgent[] };
  const sorted = [...agents].sort(byName);
  for (const agent of sorted) {
    const zone = zoneOf(agent, tasks);
    zones.set(agent.id, zone);
    groups[zone].push(agent);
  }
  const ids = new Set(agents.map((agent) => agent.id));
  const review = tasks.filter((task) => task.assigneeId && ids.has(task.assigneeId) && normalizeTaskStatus(task.status) === 'in_review').length;
  const plan = createOfficePlan({ work: groups.work.length, clinic: groups.clinic.length, review }, agents.length);
  const columnEdge = plan.reception.x + plan.reception.width / 2;
  const placements = new Map<string, Placement>();
  const put = (agent: ObservedAgent, zone: AgentZone, assignment: Assignment, spot: Spot) => placements.set(agent.id, { zone, assignment, ...spot });

  const receptionDoor: Point[] = [[plan.aisleX, STAND, plan.receptionDoorZ], [columnEdge - 0.8, STAND, plan.receptionDoorZ]];
  groups.setup.forEach((agent, index) => {
    put(agent, 'setup', { kind: 'checkIn', position: index + 1 }, {
      x: plan.reception.x - 1.9 + (index % 4) * 1,
      y: STAND,
      z: plan.reception.z + 0.35 + Math.floor(index / 4) * 0.9,
      rotation: Math.PI,
      pose: 'standing',
      activity: 'queue',
      approach: receptionDoor,
    });
  });

  // Where an idle agent starts out. One per station in turn, so a team that has just come off
  // work is spread across the room rather than lined up on one sofa; a table needs two, so
  // nobody is started at one alone.
  const startOrder = [...plan.loungeSpots.keys()].sort((a, b) => {
    const spotA = plan.loungeSpots[a];
    const spotB = plan.loungeSpots[b];
    const rank = (index: number, spot: LoungeSpot) => plan.loungeSpots.slice(0, index).filter((other) => other.station === spot.station).length;
    return Number(spotA.kind === 'table') - Number(spotB.kind === 'table') || rank(a, spotA) - rank(b, spotB) || a - b;
  });
  groups.lounge.forEach((agent, index) => {
    const start = startOrder[index % startOrder.length];
    const { x, y, z, rotation, pose, activity, approach } = plan.loungeSpots[start];
    placements.set(agent.id, { zone: 'lounge', assignment: { kind: 'lounge' }, x, y, z, rotation, pose, activity, approach, start });
  });

  const clinicDoor: Point[] = [[plan.aisleX, STAND, plan.clinicDoorZ], [columnEdge - 0.8, STAND, plan.clinicDoorZ]];
  groups.clinic.forEach((agent, index) => {
    if (index < plan.clinicBeds) {
      const bed = plan.beds[index];
      put(agent, 'clinic', { kind: 'bed', bed: index + 1 }, {
        x: bed.x, y: LIE, z: bed.z + 0.12, rotation: 0, pose: 'lying', activity: 'rest',
        approach: [...clinicDoor, [bed.x + 0.95, STAND, plan.clinicDoorZ], [bed.x + 0.95, STAND, bed.z + 0.6]],
      });
      return;
    }
    // Out of beds: the bench by the wall, then standing beside it.
    const waiting = index - plan.clinicBeds;
    const bench = plan.clinic.z + plan.clinic.depth / 2 - 0.55;
    const seated = waiting < 3;
    put(agent, 'clinic', { kind: 'clinicQueue', position: waiting + 1 }, {
      x: seated ? plan.clinic.x - 2.2 + waiting * 0.65 : plan.clinic.x - 0.1 + ((waiting - 3) % 3) * 0.7,
      y: seated ? SEAT.bench : STAND,
      z: seated ? bench : bench - 0.15 - Math.floor((waiting - 3) / 3) * 0.8,
      rotation: Math.PI,
      pose: seated ? 'sitting' : 'standing',
      activity: 'wait',
      approach: clinicDoor,
    });
  });

  // A desk belongs to an agent for good, whatever it is doing right now: the desk of someone
  // who is in the lounge stands empty with their name on it, which is itself worth seeing.
  const deskOf = new Map(sorted.map((agent, index) => [agent.id, index]));
  groups.work.forEach((agent) => {
    const index = deskOf.get(agent.id) ?? 0;
    put(agent, 'work', { kind: 'desk', pod: plan.desks[index].pod, desk: index + 1 }, deskSpot(plan, index, agent.status === 'working' ? 'type' : 'think'));
  });

  return { plan, zones, placements, desks: deskOf };
}

/** Letter of a pod: 0 → A. */
export function podLetter(index: number): string {
  return String.fromCharCode(65 + (index % 26));
}

// ─── Getting from one spot to another ────────────────────────────────────────

const samePoint = (a: Point, b: Point) => Math.abs(a[0] - b[0]) < 0.01 && Math.abs(a[1] - b[1]) < 0.01 && Math.abs(a[2] - b[2]) < 0.01;
const distance = (a: Point, b: Point) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

/** `middle` lies on the straight line through the other two. */
function inLine(a: Point, middle: Point, b: Point): boolean {
  const u = [middle[0] - a[0], middle[1] - a[1], middle[2] - a[2]];
  const v = [b[0] - middle[0], b[1] - middle[1], b[2] - middle[2]];
  const cross = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  return Math.hypot(...cross) < 0.01;
}

/** `point` lies on this walkway, between its ends. */
function onWalkway(point: Point, { from, to }: Walkway): boolean {
  const alongX = Math.abs(to[0] - from[0]) > Math.abs(to[2] - from[2]);
  const [fixed, along] = alongX ? [2, 0] : [0, 2];
  return Math.abs(point[fixed] - from[fixed]) < 0.01 && point[along] >= Math.min(from[along], to[along]) - 0.01 && point[along] <= Math.max(from[along], to[along]) + 0.01;
}

/** Where two walkways cross, if they do. */
function crossing(a: Walkway, b: Walkway): Point | null {
  const aAlongX = Math.abs(a.to[0] - a.from[0]) > Math.abs(a.to[2] - a.from[2]);
  const bAlongX = Math.abs(b.to[0] - b.from[0]) > Math.abs(b.to[2] - b.from[2]);
  if (aAlongX === bAlongX) return null;
  const [across, down] = aAlongX ? [a, b] : [b, a];
  const point: Point = [down.from[0], across.from[1], across.from[2]];
  return onWalkway(point, across) && onWalkway(point, down) ? point : null;
}

/** The shortest way along the walkways from one point on them to another. */
function alongWalkways(walkways: readonly Walkway[], start: Point, goal: Point): Point[] {
  const nodes: Point[] = [start, goal];
  walkways.forEach((one, index) =>
    walkways.slice(index + 1).forEach((other) => {
      const point = crossing(one, other);
      if (point && !nodes.some((node) => samePoint(node, point))) nodes.push(point);
    }),
  );
  // Any two points on one walkway are a straight walk apart.
  const reach = nodes.map((node) => walkways.flatMap((walkway, index) => (onWalkway(node, walkway) ? [index] : [])));
  const linked = (a: number, b: number) => reach[a].some((walkway) => reach[b].includes(walkway));
  const cost = nodes.map(() => Infinity);
  const via = nodes.map(() => -1);
  const done = nodes.map(() => false);
  cost[0] = 0;
  for (;;) {
    let current = -1;
    nodes.forEach((_, index) => {
      if (!done[index] && cost[index] < Infinity && (current < 0 || cost[index] < cost[current])) current = index;
    });
    if (current < 0 || current === 1) break;
    done[current] = true;
    nodes.forEach((node, index) => {
      if (done[index] || !linked(current, index)) return;
      const reached = cost[current] + distance(nodes[current], node);
      if (reached < cost[index]) {
        cost[index] = reached;
        via[index] = current;
      }
    });
  }
  // A goal off the walkways altogether should not happen; walk straight there if it does.
  if (cost[1] === Infinity) return [start, goal];
  const path: Point[] = [];
  for (let index = 1; index >= 0; index = via[index]) path.unshift(nodes[index]);
  return path;
}

/** One step of a walk: the point, and the way from it out onto the walkways (itself first). */
export interface Step {
  point: Point;
  out: Point[];
}

/** The way from a spot out onto the walkways: back along its way in. */
export function wayOut(spot: Spot): Point[] {
  return [...spot.approach].reverse();
}

/**
 * The walk to a spot. `lead` is what the walker does first — the points from where it is
 * out onto a walkway: `wayOut` of the spot it is sitting at, or, in the middle of a walk,
 * the rest of the step it is on. From there it takes the shortest way along the walkways
 * and then the spot's own way in, so it goes round the furniture and through the doors and
 * never across a wall.
 *
 * A point on the straight line between its neighbours is dropped, so a walk is as few
 * straight stretches as it can be.
 */
export function walkTo(plan: OfficePlan, at: Point, lead: readonly Point[], spot: Spot): Step[] {
  const goal: Point = [spot.x, spot.y, spot.z];
  if (samePoint(at, goal)) return [];
  const entry = spot.approach[0];
  const start = lead[lead.length - 1] ?? entry;
  const along = alongWalkways(plan.walkways, start, entry);
  const steps: Step[] = [
    ...lead.map((point, index) => ({ point, out: lead.slice(index) })),
    ...along.slice(1).map((point) => ({ point, out: [point] })),
    ...spot.approach.slice(1).map((point, index) => ({ point, out: spot.approach.slice(0, index + 2).reverse() })),
    { point: goal, out: [goal, ...wayOut(spot)] },
  ];
  let previous = at;
  return steps.filter((step, index) => {
    const next = steps[index + 1];
    const skip = samePoint(previous, step.point) || (next !== undefined && inLine(previous, step.point, next.point));
    if (!skip) previous = step.point;
    return !skip;
  });
}
