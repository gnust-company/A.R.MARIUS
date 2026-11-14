/*
 * The observatory's floor plan and seating, as pure data.
 *
 * The floor is a small company seen from above, and it is as big as the team: one desk per
 * agent, a lounge that grows with the headcount, a sick bay, a front desk, and the patron's
 * office on a raised gallery at the back, looking down over all of it. The rooms are the
 * agents' *states* — working, idle, offline, not set up yet, waiting for the patron — because
 * an agent belongs to the workspace, not to one project, and may sit on several at once.
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
  | { kind: 'desk'; desk: number }
  | { kind: 'bed'; bed: number }
  | { kind: 'clinicQueue'; position: number }
  | { kind: 'presenting' }
  | { kind: 'ceoQueue'; position: number }
  | { kind: 'lounge' }
  | { kind: 'checkIn'; position: number };

/** Somewhere a figure can be, and the way there from the main aisle (outermost point first). */
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

export interface OfficePlan {
  /** A floor too crowded to name every agent at once. */
  large: boolean;
  headcount: number;
  workCount: number;
  clinicCount: number;
  clinicBeds: number;
  clinicWaiting: number;
  reviewCount: number;
  floorWidth: number;
  floorDepth: number;
  centerX: number;
  /** The line the main aisle is walked along, from the gallery stairs to the lounge. */
  aisleX: number;
  reception: Room;
  clinic: Room;
  work: Room;
  lounge: Room;
  /** The patron's gallery: a raised floor along the back wall. */
  patron: Room;
  galleryHeight: number;
  /** The gallery's landing over the aisle, and the stairs down from it. */
  landing: Room;
  stairs: { x: number; top: number; foot: number; width: number };
  patronDesk: { x: number; z: number };
  noticeBoard: { x: number; z: number };
  receptionDoorZ: number;
  clinicDoorZ: number;
  /** One per agent, in name order. */
  desks: { x: number; z: number }[];
  beds: { x: number; z: number }[];
  stations: Station[];
  loungeSpots: LoungeSpot[];
  loungeLanes: number[];
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

const COLUMN = 6; // the west column: sick bay over front desk
const AISLE = 1.8;
const GALLERY_DEPTH = 3.8;
export const GALLERY_HEIGHT = 0.9;
const DESK_PITCH_X = 2.7;
const DESK_PITCH_Z = 2.6;
/** From a desk's centre to the chair in front of it, and to the walkway behind the chair. */
export const DESK_SEAT = 0.72;
const DESK_WALK = 1.5;
const BED_PITCH = 2.7;
const STATION_DEPTH = 2.6;
/** The walking strip in front of a row of lounge stations. */
const LANE = 1.1;
/** Floor height of a standing figure, and of one sitting on a chair or a sofa. */
const STAND = 0.02;
const SIT = 0.045;
const LIE = 0.69;
const MAX_BEDS = 8;

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

// ─── Lounge ──────────────────────────────────────────────────────────────────

interface LocalSpot {
  x: number;
  z: number;
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
  if (kind === 'table') return 4.6;
  if (kind === 'nook') return 2.5;
  return 1.3 + places * 0.95;
}

function stationSpots(kind: StationKind, places: number): LocalSpot[] {
  if (kind === 'sofa') {
    return [
      { x: -1.04, z: -0.49, rotation: 0, pose: 'sitting', activity: 'relax', via: [-1.55, 0.5] },
      { x: -0.06, z: -0.49, rotation: 0, pose: 'sitting', activity: 'relax', via: [0.5, 0.5] },
      { x: 1.5, z: 0.1, rotation: -Math.PI / 2, pose: 'sitting', activity: 'relax' },
    ];
  }
  if (kind === 'table') {
    return [
      { x: -1.78, z: -0.1, rotation: Math.PI / 2, pose: 'standing', activity: 'play' },
      { x: 1.78, z: -0.1, rotation: -Math.PI / 2, pose: 'standing', activity: 'play' },
    ];
  }
  if (kind === 'nook') return [{ x: 0.35, z: -0.15, rotation: 0, pose: 'sitting', activity: 'read' }];
  const width = stationWidth('bar', places);
  return Array.from({ length: places }, (_, index) => ({
    x: -width / 2 + 1.25 + 0.475 + index * 0.95,
    z: -0.3,
    rotation: Math.PI,
    pose: 'standing' as const,
    activity: 'snack' as const,
  }));
}

/** Where along a bar's counter its places stand, in the bar's own frame. */
export function barStools(places: number): number[] {
  return stationSpots('bar', places).map((spot) => spot.x);
}

/**
 * What the lounge is furnished with for a team of this size. Every idle agent must have
 * somewhere to be, with choice left over: an all-idle team is the most common sight there is.
 */
function loungeFurniture(headcount: number): { kind: StationKind; places: number }[] {
  const sofas = Math.ceil(headcount / 4);
  const nooks = Math.ceil(headcount / 4);
  const tables = headcount >= 2 ? Math.ceil(headcount / 8) : 0;
  const bars = headcount > 15 ? 2 : 1;
  const queue: { kind: StationKind; places: number }[] = [];
  const left = { bar: bars, sofa: sofas, table: tables, nook: nooks };
  // Dealt in turn so that a row never becomes four sofas followed by four tables.
  while (left.bar + left.sofa + left.table + left.nook > 0) {
    for (const kind of ['bar', 'sofa', 'table', 'nook'] as const) {
      if (left[kind] <= 0) continue;
      left[kind] -= 1;
      queue.push({ kind, places: kind === 'bar' ? barPlaces(headcount) : kind === 'sofa' ? 3 : kind === 'table' ? 2 : 1 });
    }
  }
  return queue;
}

interface Segment {
  from: number;
  to: number;
  z: number;
  rotation: number;
  /** A row against the partition takes the tall pieces; the front row stays low. */
  back: boolean;
  items: { kind: StationKind; places: number; width: number }[];
  used: number;
}

/**
 * Lay the lounge out across the front of the building: a row of stations against the
 * partition with a lane in front of it, then — only when the team has outgrown that — a row
 * facing it across the lane, then further pairs. A small team gets one row and a shallow
 * building, which is what fills a wide screen. The line of the main aisle is kept clear
 * through every row, so each lane is reached straight from it.
 */
function furnishLounge(headcount: number, left: number, right: number, aisleX: number, top: number) {
  const furniture = loungeFurniture(headcount);
  const segments: Segment[] = [];
  const lanes: number[] = [];
  let rows = 0;
  const addRow = () => {
    const pair = Math.floor(rows / 2);
    const backRow = top + 0.25 + pair * (2 * STATION_DEPTH + LANE) + STATION_DEPTH / 2;
    const lane = backRow + STATION_DEPTH / 2 + LANE / 2;
    const back = rows % 2 === 0;
    const z = back ? backRow : lane + LANE / 2 + STATION_DEPTH / 2;
    if (back) lanes.push(lane);
    segments.push({ from: left + 0.5, to: aisleX - 0.9, z, rotation: back ? 0 : Math.PI, back, items: [], used: 0 });
    segments.push({ from: aisleX + 0.9, to: right - 0.5, z, rotation: back ? 0 : Math.PI, back, items: [], used: 0 });
    rows += 1;
  };
  addRow();
  for (const item of furniture) {
    const width = stationWidth(item.kind, item.places);
    const tall = item.kind === 'bar' || item.kind === 'nook';
    const room = (segment: Segment) => segment.to - segment.from - segment.used - width;
    const pick = () => {
      const fits = segments.filter((segment) => room(segment) >= 0);
      // Tall pieces stand against the partition where they can: in a front row they would
      // hide whoever is at them. Then the emptiest segment, so the room fills evenly.
      const preferred = tall ? fits.filter((segment) => segment.back) : fits;
      return (preferred.length ? preferred : fits).sort((a, b) => room(b) - room(a))[0];
    };
    let segment = pick();
    for (let attempt = 0; !segment && attempt < 2; attempt++) {
      addRow();
      segment = pick();
    }
    if (!segment) continue;
    segment.items.push({ ...item, width });
    segment.used += width;
  }
  const stations: Station[] = [];
  const spots: LoungeSpot[] = [];
  for (const segment of segments) {
    const gap = (segment.to - segment.from - segment.used) / (segment.items.length + 1);
    let cursor = segment.from;
    const lane = lanes.find((z) => Math.abs(z - segment.z) < STATION_DEPTH)!;
    for (const item of segment.items) {
      cursor += gap;
      const x = cursor + item.width / 2;
      cursor += item.width;
      const sign = segment.rotation === 0 ? 1 : -1;
      const index = stations.length;
      stations.push({ kind: item.kind, x, z: segment.z, rotation: segment.rotation, width: item.width, places: item.places });
      for (const local of stationSpots(item.kind, item.places)) {
        const approach: Point[] = [[aisleX, STAND, lane]];
        if (local.via) {
          approach.push([x + sign * local.via[0], STAND, lane]);
          approach.push([x + sign * local.via[0], STAND, segment.z + sign * local.via[1]]);
        } else {
          approach.push([x + sign * local.x, STAND, lane]);
        }
        spots.push({
          station: index,
          kind: item.kind,
          x: x + sign * local.x,
          y: local.pose === 'sitting' ? SIT : STAND,
          z: segment.z + sign * local.z,
          rotation: local.rotation + segment.rotation,
          pose: local.pose,
          activity: local.activity,
          approach,
        });
      }
    }
  }
  // A lone back row still needs its lane, and a little floor in front of it.
  const pairs = Math.floor(rows / 2);
  const depth = pairs * (2 * STATION_DEPTH + LANE) + (rows % 2 ? STATION_DEPTH + LANE : 0) + 0.5;
  return { stations, spots, lanes, depth };
}

/** How deep the lounge of a team this size is, before anything else about the floor is known. */
function loungeDepthFor(headcount: number, width: number): number {
  // The west column and the aisle are the same for every team; only the east part grows.
  return furnishLounge(headcount, -width / 2, width / 2, -width / 2 + COLUMN + AISLE / 2, 0).depth;
}

// ─── The floor ───────────────────────────────────────────────────────────────

/** The building for a team of `headcount`. Per-zone counts only fill in the signs. */
export function createOfficePlan(zoneCounts: Record<AgentZone, number>, agentCount: number): OfficePlan {
  const headcount = Math.max(1, agentCount);
  const deskCount = Math.max(2, headcount);
  // Wide rows rather than a square block: the screen this is drawn on is wide, and so is an office.
  const deskRows = deskCount <= 6 ? 1 : deskCount <= 16 ? 2 : deskCount <= 30 ? 3 : 4;
  const deskColumns = Math.ceil(deskCount / deskRows);
  const workWidth = Math.max(7.6, deskColumns * DESK_PITCH_X + 1);
  const workDepth = deskRows * DESK_PITCH_Z + 1.1;
  const clinicBeds = Math.max(2, Math.min(MAX_BEDS, Math.ceil(headcount / 2)));
  const clinicDepth = Math.ceil(clinicBeds / 2) * BED_PITCH + 1.7;
  const northDepth = Math.max(GALLERY_DEPTH + workDepth, clinicDepth + 3.7);
  const floorWidth = COLUMN + AISLE + workWidth;
  const loungeDepth = loungeDepthFor(headcount, floorWidth);
  const floorDepth = northDepth + loungeDepth;

  const left = -floorWidth / 2;
  const right = floorWidth / 2;
  const back = -floorDepth / 2;
  const columnEdge = left + COLUMN;
  const aisleX = columnEdge + AISLE / 2;
  const galleryLeft = columnEdge + AISLE;
  const loungeTop = back + northDepth;

  const lounge = furnishLounge(headcount, left, right, aisleX, loungeTop);
  const firstDeskX = galleryLeft + (workWidth - deskColumns * DESK_PITCH_X) / 2 + DESK_PITCH_X / 2;
  const desks = Array.from({ length: deskCount }, (_, index) => ({
    x: firstDeskX + (index % deskColumns) * DESK_PITCH_X,
    z: back + GALLERY_DEPTH + 1.5 + Math.floor(index / deskColumns) * DESK_PITCH_Z,
  }));
  const clinicX = left + COLUMN / 2;
  const beds = Array.from({ length: clinicBeds }, (_, index) => ({
    x: clinicX - BED_PITCH / 2 + (index % 2) * BED_PITCH,
    z: back + 1.5 + Math.floor(index / 2) * BED_PITCH,
  }));
  const receptionDepth = northDepth - clinicDepth;
  const reception: Room = { x: clinicX, z: back + clinicDepth + receptionDepth / 2, width: COLUMN, depth: receptionDepth };
  const patron: Room = { x: galleryLeft + workWidth / 2, z: back + GALLERY_DEPTH / 2, width: workWidth, depth: GALLERY_DEPTH };

  return {
    large: headcount > 12,
    headcount,
    workCount: zoneCounts.work,
    clinicCount: zoneCounts.clinic,
    clinicBeds,
    clinicWaiting: Math.max(0, zoneCounts.clinic - clinicBeds),
    reviewCount: zoneCounts.patron,
    floorWidth,
    floorDepth,
    centerX: 0,
    aisleX,
    reception,
    clinic: { x: clinicX, z: back + clinicDepth / 2, width: COLUMN, depth: clinicDepth },
    work: { x: galleryLeft + workWidth / 2, z: back + GALLERY_DEPTH + workDepth / 2, width: workWidth, depth: northDepth - GALLERY_DEPTH },
    lounge: { x: 0, z: loungeTop + loungeDepth / 2, width: floorWidth, depth: loungeDepth },
    patron,
    galleryHeight: GALLERY_HEIGHT,
    landing: { x: aisleX, z: back + 0.8, width: AISLE, depth: 1.6 },
    stairs: { x: aisleX, top: back + 1.6, foot: back + 2.8, width: AISLE - 0.3 },
    patronDesk: { x: galleryLeft + Math.max(3.8, workWidth / 2), z: back + 1.75 },
    noticeBoard: { x: right - 1.75, z: back + 0.45 },
    receptionDoorZ: reception.z,
    clinicDoorZ: back + clinicDepth - 0.9,
    desks,
    beds,
    stations: lounge.stations,
    loungeSpots: lounge.spots,
    loungeLanes: lounge.lanes,
    shape: [headcount, floorWidth.toFixed(1), floorDepth.toFixed(1)].join('x'),
  };
}

/** The way up to the gallery, to a point of its front walkway. */
function galleryApproach(plan: OfficePlan, x: number): Point[] {
  const back = -plan.floorDepth / 2;
  const height = plan.galleryHeight + STAND;
  const walkway = back + GALLERY_DEPTH - 0.65;
  const turn = plan.patron.x - plan.patron.width / 2 + 0.7;
  return [
    [plan.aisleX, STAND, plan.stairs.foot + 0.2],
    [plan.aisleX, height, plan.stairs.top - 0.1],
    [turn, height, back + 0.95],
    [turn, height, walkway],
    [x, height, walkway],
  ];
}

/** Seat every agent. The single source of truth for scene, tooltip and modal. */
export function layoutOffice(agents: readonly ObservedAgent[], tasks: readonly ObservedTask[]): OfficeLayout {
  const zones = new Map<string, AgentZone>();
  const groups: Record<AgentZone, ObservedAgent[]> = { setup: [], lounge: [], clinic: [], work: [], patron: [] };
  const sorted = [...agents].sort(byName);
  for (const agent of sorted) {
    const zone = zoneOf(agent, tasks);
    zones.set(agent.id, zone);
    groups[zone].push(agent);
  }
  const plan = createOfficePlan(
    { setup: groups.setup.length, lounge: groups.lounge.length, clinic: groups.clinic.length, work: groups.work.length, patron: groups.patron.length },
    agents.length,
  );
  const back = -plan.floorDepth / 2;
  const columnEdge = plan.reception.x + plan.reception.width / 2;
  const placements = new Map<string, Placement>();
  const put = (agent: ObservedAgent, zone: AgentZone, assignment: Assignment, spot: Spot) => placements.set(agent.id, { zone, assignment, ...spot });

  const receptionDoor: Point[] = [[plan.aisleX, STAND, plan.receptionDoorZ], [columnEdge - 0.8, STAND, plan.receptionDoorZ]];
  groups.setup.forEach((agent, index) => {
    put(agent, 'setup', { kind: 'checkIn', position: index + 1 }, {
      x: plan.reception.x - 1.5 + (index % 4) * 1,
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
        approach: [...clinicDoor, [bed.x + 0.85, STAND, bed.z + 0.9]],
      });
      return;
    }
    const waiting = index - plan.clinicBeds;
    const bench = plan.clinic.z + plan.clinic.depth / 2 - 0.55;
    const seated = waiting < 3;
    put(agent, 'clinic', { kind: 'clinicQueue', position: waiting + 1 }, {
      x: seated ? plan.clinic.x - 1.7 + waiting * 0.65 : plan.clinic.x + 0.6 + ((waiting - 3) % 3) * 0.7,
      y: seated ? SIT : STAND,
      z: seated ? bench : bench - 0.2 - Math.floor((waiting - 3) / 3) * 0.8,
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
    const desk = plan.desks[index];
    const walk = desk.z + DESK_WALK;
    put(agent, 'work', { kind: 'desk', desk: index + 1 }, {
      x: desk.x, y: SIT, z: desk.z + DESK_SEAT, rotation: Math.PI, pose: 'sitting',
      activity: agent.status === 'working' ? 'type' : 'think',
      approach: [[plan.aisleX, STAND, walk], [desk.x, STAND, walk]],
    });
  });

  const galleryLeft = plan.patron.x - plan.patron.width / 2;
  const height = plan.galleryHeight + STAND;
  let downstairs = 0;
  groups.patron.forEach((agent, index) => {
    if (index === 0) {
      put(agent, 'patron', { kind: 'presenting' }, {
        x: plan.patronDesk.x, y: height, z: plan.patronDesk.z + 1.3, rotation: Math.PI, pose: 'standing', activity: 'present',
        approach: galleryApproach(plan, plan.patronDesk.x),
      });
      return;
    }
    // The queue runs back along the gallery's walkway, and down the stairs once that is full.
    const x = plan.patronDesk.x - 0.4 - index * 1.05;
    if (x > galleryLeft + 1.4) {
      put(agent, 'patron', { kind: 'ceoQueue', position: index }, {
        x, y: height, z: back + GALLERY_DEPTH - 0.65, rotation: Math.PI / 2, pose: 'standing', activity: 'queue',
        approach: galleryApproach(plan, x).slice(0, -1),
      });
      return;
    }
    put(agent, 'patron', { kind: 'ceoQueue', position: index }, {
      x: plan.aisleX, y: STAND, z: plan.stairs.foot + 0.7 + downstairs * 0.85, rotation: Math.PI, pose: 'standing', activity: 'queue',
      approach: [],
    });
    downstairs += 1;
  });

  return { plan, zones, placements, desks: deskOf };
}

// ─── Getting from one spot to another ────────────────────────────────────────

const samePoint = (a: Point, b: Point) => Math.abs(a[0] - b[0]) < 0.01 && Math.abs(a[1] - b[1]) < 0.01 && Math.abs(a[2] - b[2]) < 0.01;

/** One step of a walk: the point, and the way out to the aisle from it (itself included). */
export interface Step {
  point: Point;
  trail: Point[];
}

/**
 * The walk from one place to another. Each is given as its way in from the main aisle with
 * the place itself last; the walk goes back out along the first as far as the two ways in
 * part company, then in along the second. So two agents on one sofa walk around the coffee
 * table, not out to the aisle and back, and nobody ever crosses a wall.
 */
export function walkBetween(from: Point[], to: Point[]): Step[] {
  // Already there: a change of what it is doing at the same spot is not a walk.
  if (from.length && to.length && samePoint(from[from.length - 1], to[to.length - 1])) return [];
  let shared = 0;
  while (shared < Math.min(from.length, to.length) - 1 && samePoint(from[shared], to[shared])) shared += 1;
  const steps: Step[] = [];
  for (let index = from.length - 2; index >= shared; index--) steps.push({ point: from[index], trail: from.slice(0, index + 1) });
  if (shared > 0) steps.push({ point: from[shared - 1], trail: from.slice(0, shared) });
  for (let index = shared; index < to.length; index++) steps.push({ point: to[index], trail: to.slice(0, index + 1) });
  return steps;
}

/** A spot's way in from the aisle, with the spot itself as the last point. */
export function wayInto(spot: Spot): Point[] {
  return [...spot.approach, [spot.x, spot.y, spot.z]];
}
