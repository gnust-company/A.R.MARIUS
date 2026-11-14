import * as THREE from 'three';
import { chair, coffeeTable, makeFurniture, plant } from '@/scene/furniture';
import { box, cylinder, group, rod, sphere, woodTexture } from '@/scene/primitives';
import { barStools, type OfficePlan, type Room, type Station } from './officePlan';

/*
 * The building of the observatory: walls, rooms and furniture, built once per floor-plan
 * shape from `OfficePlan`. Everything here is static and gets merged into a few draw calls by
 * the engine, except what it hands back under `live` — the parts the engine animates or
 * repaints while the scene runs (desk screens, name plates, the notice board, the balls).
 *
 * Colours written as hex are scene materials (wood, fabric, glass, lamp light), lit and
 * tone-mapped by the scene; they are not UI colours and do not follow the theme tokens.
 */

/** Words painted onto signs and floor markings. Built once per scene, in the page's language. */
export interface SceneLabels {
  canvas: string;
  entry: string;
  reception: [string, string];
  clinic: (beds: number, waiting: number) => [string, string];
  patron: (queue: number) => [string, string];
  snackBar: string;
  /** The notice board in the patron's office: its heading, and the line under the count. */
  noticeBoard: (count: number) => [string, string];
}

export const SCENE_FONT = '"Be Vietnam Pro", Arial, sans-serif';

export function canvas2d(width: number, height: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('2D canvas unavailable');
  return [canvas, context];
}

/** A physical sign on a wall: always dark enamel with light lettering, in both themes. */
function zoneSign(parent: THREE.Object3D, [title, subtitle]: [string, string], position: [number, number, number], accent: string) {
  const [canvas, ctx] = canvas2d(768, 160);
  ctx.fillStyle = 'rgba(20,29,42,.88)';
  ctx.beginPath();
  ctx.roundRect(4, 4, 760, 152, 18);
  ctx.fill();
  ctx.fillStyle = accent;
  ctx.fillRect(4, 4, 9, 152);
  ctx.fillStyle = '#f3efe5';
  ctx.font = `600 42px ${SCENE_FONT}`;
  ctx.fillText(title.toUpperCase(), 40, 67, 700);
  ctx.fillStyle = '#acb8ca';
  ctx.font = '24px ui-monospace, monospace';
  ctx.fillText(subtitle.toUpperCase(), 40, 116, 700);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: true }));
  sprite.position.set(...position);
  sprite.scale.set(3.1, 0.65, 1);
  parent.add(sprite);
}

function floorWayfinding(parent: THREE.Object3D, title: string, position: [number, number], color: string, turn = 0) {
  const [canvas, ctx] = canvas2d(512, 128);
  ctx.fillStyle = color;
  ctx.font = `600 43px ${SCENE_FONT}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(title.toUpperCase(), 256, 64, 490);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, opacity: 0.72 });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(3, 0.75), mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.rotation.z = turn;
  mesh.position.set(position[0], 0.075, position[1]);
  parent.add(mesh);
}

/** A desk with its monitor and chair. Returns the monitor's face, which the engine lights. */
function workstation(parent: THREE.Object3D, index: number, screenMaterial: THREE.Material): THREE.Mesh {
  const wood = index % 2 ? '#876e52' : '#967a58';
  box(parent, [1.75, 0.12, 0.86], [0, 0.83, 0], wood, 0.045);
  for (const x of [-0.72, 0.72]) for (const z of [-0.3, 0.3]) rod(parent, [x, 0.05, z], [x, 0.78, z], 0.035, '#3e4148');
  box(parent, [0.7, 0.43, 0.055], [0, 1.19, -0.18], '#242c35', 0.035);
  const screen = box(parent, [0.62, 0.35, 0.012], [0, 1.19, -0.145], screenMaterial, 0);
  rod(parent, [0, 0.85, -0.18], [0, 0.98, -0.18], 0.028, '#3e4148');
  box(parent, [0.62, 0.025, 0.21], [0, 0.91, 0.18], '#b9b7ae', 0.015);
  chair(parent, [0, 0, 0.72], Math.PI, index % 2 ? '#4f5e72' : '#695c68');
  return screen;
}

/** A coloured floor laid over the slab: the carpet that tells one zone from the next. */
function zoneFloor(parent: THREE.Object3D, room: Room, color: string) {
  return box(parent, [room.width - 0.06, 0.035, room.depth - 0.06], [room.x, 0.035, room.z], color, 0.01);
}

/** A glazed wall along z with one doorway in it, for a room that opens onto the aisle. */
function glazedWallWithDoor(parent: THREE.Object3D, x: number, from: number, to: number, doorZ: number, wallColor: string, glass: THREE.Material) {
  const half = 0.85;
  for (const [start, end] of [[from, doorZ - half], [doorZ + half, to]] as const) {
    const length = end - start;
    if (length < 0.15) continue;
    const z = (start + end) / 2;
    box(parent, [0.13, 0.68, length], [x, 0.34, z], wallColor, 0.025);
    box(parent, [0.055, 0.82, Math.max(0.1, length - 0.12)], [x, 1.08, z], glass, 0.01);
  }
  for (const side of [-1, 1]) box(parent, [0.16, 1.92, 0.09], [x, 0.96, doorZ + side * (half + 0.05)], '#6d777c', 0.015);
  box(parent, [0.16, 0.09, half * 2 + 0.19], [x, 1.89, doorZ], '#6d777c', 0.015);
}

/** A railing: glass under a handrail, on posts. Runs along x when `alongX`, else along z. */
function railing(parent: THREE.Object3D, from: [number, number], to: [number, number], floor: number, glass: THREE.Material) {
  const alongX = Math.abs(to[0] - from[0]) > Math.abs(to[1] - from[1]);
  const length = alongX ? Math.abs(to[0] - from[0]) : Math.abs(to[1] - from[1]);
  if (length < 0.2) return;
  const x = (from[0] + to[0]) / 2;
  const z = (from[1] + to[1]) / 2;
  box(parent, alongX ? [length, 0.5, 0.035] : [0.035, 0.5, length], [x, floor + 0.32, z], glass, 0.008);
  box(parent, alongX ? [length, 0.05, 0.08] : [0.08, 0.05, length], [x, floor + 0.62, z], '#6d777c', 0.015);
  const posts = Math.max(2, Math.round(length / 1.7) + 1);
  for (let index = 0; index < posts; index++) {
    const along = -length / 2 + (index * length) / (posts - 1);
    box(parent, [0.06, 0.64, 0.06], [alongX ? x + along : x, floor + 0.32, alongX ? z : z + along], '#6d777c', 0.01);
  }
}

// ─── Lounge furniture ────────────────────────────────────────────────────────

const SOFA_COLORS = ['#7b7180', '#6f7f8c', '#8a7667'];
const CHAIR_COLORS = ['#6c7d78', '#84706b', '#6a7890'];

function sofaGroup(root: THREE.Group, index: number) {
  const rug = makeFurniture('rug', index % 2 ? '#5f6d63' : '#58656e');
  rug.scale.set(1.75, 1, 1.25);
  rug.position.set(-0.15, 0.03, 0.1);
  root.add(rug);
  const sofa = makeFurniture('sofa', SOFA_COLORS[index % SOFA_COLORS.length]);
  sofa.position.set(-0.55, 0, -0.55);
  sofa.scale.setScalar(0.88);
  root.add(sofa);
  const armchair = makeFurniture('armchair', CHAIR_COLORS[index % CHAIR_COLORS.length]);
  armchair.position.set(1.5, 0, 0.1);
  armchair.rotation.y = -Math.PI / 2;
  root.add(armchair);
  coffeeTable(root, [-0.55, 0, 0.55]);
  plant(root, 0.8, '#9c7658', true).position.set(1.85, 0, -1);
}

/** The snack bar: a fridge, a counter with a coffee machine on it, and a shelf of snacks. */
function snackBar(root: THREE.Group, station: Station, label: string) {
  const width = station.width;
  const from = -width / 2 + 1.2;
  const to = width / 2 - 0.15;
  const length = to - from;
  const middle = (from + to) / 2;
  // Back panel: the bar brings its own wall, so it reads the same against glass or a partition.
  box(root, [width - 0.2, 2.05, 0.07], [0, 1.03, -1.24], '#7d6c5d', 0.02);
  // Fridge, with a glass door showing bottles.
  box(root, [0.82, 1.9, 0.7], [-width / 2 + 0.56, 0.95, -0.86], '#cfd6d8', 0.05);
  box(root, [0.66, 1.2, 0.02], [-width / 2 + 0.56, 1.2, -0.5], '#2f4654', 0.01);
  for (let row = 0; row < 3; row++)
    for (let col = 0; col < 4; col++) cylinder(root, 0.045, 0.045, 0.2, [-width / 2 + 0.33 + col * 0.155, 0.78 + row * 0.36, -0.52], ['#d98b5f', '#8fc4a8', '#e3c46a', '#9fb7ff'][(row + col) % 4], 8);
  box(root, [0.03, 0.5, 0.04], [-width / 2 + 0.92, 1.15, -0.47], '#8d979b', 0.01);
  // Counter.
  box(root, [length, 0.92, 0.62], [middle, 0.46, -0.92], '#6f5a48', 0.04);
  box(root, [length + 0.08, 0.06, 0.72], [middle, 0.95, -0.9], '#d8c7a6', 0.02);
  // Coffee machine and a stack of cups.
  box(root, [0.36, 0.44, 0.32], [from + 0.3, 1.2, -1], '#2e3338', 0.04);
  box(root, [0.2, 0.05, 0.16], [from + 0.3, 1.03, -0.84], '#8d979b', 0.01);
  cylinder(root, 0.05, 0.04, 0.09, [from + 0.3, 1.1, -0.84], '#f3ead7', 10);
  for (let cup = 0; cup < 3; cup++) cylinder(root, 0.05, 0.04, 0.05, [from + 0.68, 1.01 + cup * 0.045, -0.98], '#f3ead7', 10);
  // Snack jars, then a fruit bowl, along the rest of the counter.
  const jarColors = ['#d98b5f', '#e3c46a', '#8fc4a8', '#c98fb0'];
  const jars = Math.max(2, Math.min(4, Math.floor((length - 1.6) / 0.34)));
  for (let jar = 0; jar < jars; jar++) {
    const x = from + 1.05 + jar * 0.34;
    cylinder(root, 0.11, 0.11, 0.26, [x, 1.11, -1], jarColors[jar % jarColors.length], 12);
    cylinder(root, 0.115, 0.115, 0.03, [x, 1.255, -1], '#5b4a3c', 12);
  }
  sphere(root, [to - 0.4, 1.02, -0.9], [0.2, 0.07, 0.2], '#b9a07a', 14);
  for (const [dx, dz, color] of [[-0.07, 0, '#d9694f'], [0.06, 0.04, '#e3c46a'], [0, -0.07, '#8fbf6a']] as const) sphere(root, [to - 0.4 + dx, 1.09, -0.9 + dz], [0.065, 0.065, 0.065], color, 10);
  // A shelf of snack boxes above the counter.
  box(root, [length, 0.05, 0.28], [middle, 1.62, -1.08], '#5b4a3c', 0.01);
  const packs = Math.floor(length / 0.26);
  for (let pack = 0; pack < packs; pack++) box(root, [0.18, 0.24 - (pack % 3) * 0.04, 0.16], [from + 0.16 + pack * 0.26, 1.76 - (pack % 3) * 0.02, -1.08], jarColors[(pack * 3 + 1) % jarColors.length], 0.015);
  // Its name, on the panel.
  const [canvas, ctx] = canvas2d(512, 96);
  ctx.fillStyle = '#f3e9d2';
  ctx.font = `700 54px ${SCENE_FONT}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(label.toUpperCase(), 256, 50, 490);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const name = new THREE.Mesh(new THREE.PlaneGeometry(1.5, 0.28), new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false }));
  name.position.set(middle, 1.98, -1.19);
  root.add(name);
  // A foot rail in front, where people stand.
  for (const x of barStools(station.places)) cylinder(root, 0.2, 0.2, 0.012, [x, 0.06, -0.3], '#5b6a70', 20);
}

/** A table-tennis table. Returns where its ball rests, in the station's own frame. */
function tennisTable(root: THREE.Group) {
  const z = -0.1;
  box(root, [2.6, 0.07, 1.4], [0, 0.76, z], '#2f6f5e', 0.01);
  box(root, [2.6, 0.012, 0.03], [0, 0.8, z], '#f1f1ee', 0);
  for (const side of [-1, 1]) {
    box(root, [2.6, 0.012, 0.03], [0, 0.8, z + side * 0.685], '#f1f1ee', 0);
    box(root, [0.03, 0.012, 1.4], [side * 1.285, 0.8, z], '#f1f1ee', 0);
  }
  box(root, [0.025, 0.15, 1.52], [0, 0.875, z], '#e9ebe6', 0);
  for (const x of [-0.95, 0.95]) for (const side of [-1, 1]) rod(root, [x, 0.04, z + side * 0.5], [x, 0.73, z + side * 0.5], 0.04, '#3e4148');
  box(root, [1.9, 0.05, 0.05], [0, 0.4, z], '#3e4148', 0.01);
}

function readingNook(root: THREE.Group, index: number) {
  const shelf = makeFurniture('bookshelf', '#675443');
  shelf.position.set(-0.45, 0, -1);
  shelf.scale.setScalar(0.92);
  root.add(shelf);
  const armchair = makeFurniture('armchair', CHAIR_COLORS[(index + 1) % CHAIR_COLORS.length]);
  armchair.position.set(0.35, 0, -0.15);
  root.add(armchair);
  // Floor lamp.
  cylinder(root, 0.16, 0.18, 0.04, [1.05, 0.04, -0.85], '#4b4842', 16);
  rod(root, [1.05, 0.05, -0.85], [1.05, 1.5, -0.85], 0.02, '#4b4842');
  cylinder(root, 0.12, 0.22, 0.26, [1.05, 1.58, -0.85], '#e9d7ae', 16);
  // Side table with a mug.
  cylinder(root, 0.2, 0.2, 0.04, [1, 0.5, 0], '#bc9971', 16);
  rod(root, [1, 0.04, 0], [1, 0.48, 0], 0.03, '#9c7b56');
  cylinder(root, 0.05, 0.045, 0.09, [1, 0.565, 0], '#f3ead7', 10);
}

// ─── The building ────────────────────────────────────────────────────────────

export interface LiveParts {
  /** The monitor of each desk, in desk order; lit while its owner is running. */
  screens: THREE.Mesh[];
  /** The name plate of each desk, in desk order. */
  plates: THREE.Mesh[];
  board: THREE.Mesh;
  boardFrame: THREE.Mesh;
  /** The ball of each table-tennis table, keyed by station index, with where it rests. */
  balls: Map<number, { mesh: THREE.Mesh; x: number; z: number }>;
}

export function buildCompany(scene: THREE.Scene, plan: OfficePlan, labels: SceneLabels) {
  const root = group();
  scene.add(root);
  // Everything the engine moves or repaints lives under here and is left out of the merge.
  const live = group(root);
  const floorMaterial = new THREE.MeshStandardMaterial({ map: woodTexture(), color: '#b7a889', roughness: 0.86 });
  const windowMaterial = new THREE.MeshStandardMaterial({ color: '#c6d2de', emissive: '#bcd9f0', emissiveIntensity: 0.65, roughness: 0.25 });
  const glassMaterial = new THREE.MeshStandardMaterial({ color: '#a9c0c9', transparent: true, opacity: 0.24, roughness: 0.18, depthWrite: false });
  const screenMaterial = new THREE.MeshStandardMaterial({ color: '#8ea7ce', emissive: '#5079cb', emissiveIntensity: 0.45, roughness: 0.35 });
  const width = plan.floorWidth;
  const depth = plan.floorDepth;
  const left = -width / 2;
  const right = width / 2;
  const back = -depth / 2;
  const front = depth / 2;
  const columnEdge = plan.reception.x + plan.reception.width / 2;
  const galleryLeft = plan.patron.x - plan.patron.width / 2;
  const galleryFront = plan.patron.z + plan.patron.depth / 2;
  const height = plan.galleryHeight;
  const loungeTop = plan.lounge.z - plan.lounge.depth / 2;
  const entryZ = plan.receptionDoorZ;

  // Shell: floor slab, back wall with windows, a tall west wall with the way in, low east and front.
  box(root, [width, 0.28, depth], [0, -0.14, 0], floorMaterial, 0.08);
  box(root, [width, 3.55, 0.16], [0, 1.77, back + 0.08], '#b9c5cd', 0.03);
  box(root, [0.16, 2.75, entryZ - 1.1 - back], [left + 0.08, 1.37, (back + entryZ - 1.1) / 2], '#aebdc6', 0.03);
  box(root, [0.16, 2.75, front - entryZ - 1.1], [left + 0.08, 1.37, (front + entryZ + 1.1) / 2], '#aebdc6', 0.03);
  box(root, [0.16, 1.05, depth], [right - 0.08, 0.52, 0], '#aebdc6', 0.03);
  box(root, [width, 0.24, 0.12], [0, -0.05, front - 0.08], '#766858', 0.015);
  box(root, [width, 0.12, 0.12], [0, 0.1, back + 0.18], '#73644f', 0.015);
  const windowCount = Math.max(2, Math.ceil(width / 6.4));
  for (let index = 0; index < windowCount; index++) {
    const x = left + 3.2 + index * ((width - 6.4) / Math.max(1, windowCount - 1));
    box(root, [4.7, 1.62, 0.025], [x, 2.35, back + 0.18], windowMaterial, 0.012);
    box(root, [4.86, 0.07, 0.07], [x, 3.2, back + 0.22], '#766a56', 0.01);
    box(root, [4.86, 0.07, 0.07], [x, 1.5, back + 0.22], '#766a56', 0.01);
    box(root, [0.06, 1.75, 0.07], [x, 2.35, back + 0.22], '#766a56', 0.01);
  }

  // Stars in the windows: visible only at night.
  const starCount = Math.round(width * 11);
  const starsGeometry = new THREE.BufferGeometry();
  const starPositions = new Float32Array(starCount * 3);
  for (let index = 0; index < starCount; index++) {
    starPositions[index * 3] = left + 1 + ((index * 2.37) % (width - 2));
    starPositions[index * 3 + 1] = 1.62 + ((index * 1.61) % 1.45);
    starPositions[index * 3 + 2] = back + 0.21;
  }
  starsGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
  const starsMaterial = new THREE.PointsMaterial({ color: '#ffe6a6', size: 0.035, transparent: true, opacity: 0 });
  root.add(new THREE.Points(starsGeometry, starsMaterial));

  // The main aisle: one line from the foot of the gallery stairs down into the lounge.
  const aisleFrom = plan.stairs.foot + 0.1;
  const aisleTo = plan.loungeLanes[plan.loungeLanes.length - 1] + 0.6;
  box(root, [1.5, 0.035, aisleTo - aisleFrom], [plan.aisleX, 0.036, (aisleFrom + aisleTo) / 2], '#77878a', 0.01);
  box(root, [0.035, 0.018, aisleTo - aisleFrom - 0.4], [plan.aisleX, 0.075, (aisleFrom + aisleTo) / 2], '#d4b972', 0);

  // ── Sick bay: beds, bedside monitors, a bench for whoever is waiting for one.
  zoneFloor(root, plan.clinic, '#b8c9ca');
  const clinicSouth = plan.clinic.z + plan.clinic.depth / 2;
  glazedWallWithDoor(root, columnEdge, back + 0.1, clinicSouth, plan.clinicDoorZ, '#a3b6b9', glassMaterial);
  // The wall it shares with the front desk is low and glazed, so the beds are not hidden behind it.
  box(root, [plan.clinic.width, 0.9, 0.13], [plan.clinic.x, 0.45, clinicSouth], '#a3b6b9', 0.025);
  box(root, [plan.clinic.width - 0.3, 0.7, 0.055], [plan.clinic.x, 1.25, clinicSouth], glassMaterial, 0.01);
  plan.beds.forEach((position, index) => {
    const bed = makeFurniture('bed', index % 2 ? '#8aa6b0' : '#91a99c');
    bed.scale.setScalar(0.72);
    bed.position.set(position.x, 0, position.z);
    root.add(bed);
    box(root, [0.42, 0.62, 0.42], [position.x + 1.05, 0.32, position.z - 0.68], '#d4dbd7', 0.04);
    box(root, [0.34, 0.45, 0.04], [position.x + 1.05, 1, position.z - 0.7], '#5f7580', 0.025);
    box(root, [0.25, 0.06, 0.015], [position.x + 1.05, 1.03, position.z - 0.675], '#9fe0ca', 0.005);
  });
  const bench = makeFurniture('bench', '#7d9395');
  bench.scale.setScalar(0.78);
  bench.rotation.y = Math.PI;
  bench.position.set(plan.clinic.x - 1.05, 0, clinicSouth - 0.5);
  root.add(bench);
  zoneSign(root, labels.clinic(plan.clinicBeds, plan.clinicWaiting), [plan.clinic.x, 3.25, back + 0.3], '#a8d5bd');
  const cross = group(root, [columnEdge - 0.1, 1.72, plan.clinicDoorZ - 1.5]);
  box(cross, [0.1, 0.62, 0.2], [0, 0, 0], '#d9eee6', 0.02);
  box(cross, [0.1, 0.2, 0.62], [0, 0, 0], '#d9eee6', 0.02);

  // ── Front desk: the way in from outside, a counter, and room to queue in front of it.
  zoneFloor(root, plan.reception, '#9eabb0');
  glazedWallWithDoor(root, columnEdge, clinicSouth, loungeTop, plan.receptionDoorZ, '#a5b2b6', glassMaterial);
  box(root, [plan.reception.width, 0.68, 0.13], [plan.reception.x, 0.34, loungeTop], '#a5b2b6', 0.025);
  box(root, [plan.reception.width - 0.3, 0.82, 0.055], [plan.reception.x, 1.08, loungeTop], glassMaterial, 0.01);
  const counterZ = clinicSouth + 0.85;
  const counter = group(root, [plan.reception.x - 0.5, 0, counterZ]);
  box(counter, [3.5, 1.05, 0.9], [0, 0.54, 0], '#687e88', 0.08);
  box(counter, [3.7, 0.12, 1.08], [0, 1.09, 0], '#d2c2a2', 0.045);
  box(counter, [1.1, 0.06, 0.6], [0.9, 1.2, 0], '#263744', 0.025).rotation.x = -0.18;
  box(counter, [0.96, 0.025, 0.46], [0.9, 1.235, -0.015], screenMaterial, 0.015).rotation.x = -0.18;
  zoneSign(root, labels.reception, [left + 0.3, 2.35, plan.reception.z + plan.reception.depth / 2 - 1], '#8fc4e8');
  const hologram = group(root, [columnEdge - 0.95, 1.05, counterZ + 0.15]);
  const holoMaterial = new THREE.MeshBasicMaterial({ color: '#9fb7ff', transparent: true, opacity: 0.52, depthWrite: false });
  for (let index = 0; index < 3; index++) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.3 + index * 0.1, 0.01, 6, 40), holoMaterial);
    ring.rotation.set(Math.PI / 2.6 + index * 0.33, index * 0.7, 0);
    hologram.add(ring);
  }
  sphere(hologram, [0, 0, 0], [0.1, 0.1, 0.1], new THREE.MeshBasicMaterial({ color: '#ffe6a0' }), 20);
  cylinder(root, 0.5, 0.6, 0.1, [columnEdge - 0.95, 0.12, counterZ + 0.15], '#63747f', 32);
  const entryX = left + 0.18;
  for (const side of [-1, 1]) box(root, [0.12, 2.45, 0.12], [entryX, 1.22, entryZ + side * 1.1], '#57676f', 0.015);
  box(root, [0.12, 0.12, 2.32], [entryX, 2.4, entryZ], '#57676f', 0.015);
  box(root, [0.035, 2.15, 1.85], [entryX + 0.03, 1.18, entryZ], glassMaterial, 0.005);
  floorWayfinding(root, labels.entry, [left + 0.75, entryZ], '#e5eef2', Math.PI / 2);

  // ── The patron's gallery: a raised floor along the back wall, looking down over the desks.
  const gallery = group(root, [0, height, 0]);
  box(root, [plan.patron.width, height, plan.patron.depth], [plan.patron.x, height / 2, plan.patron.z], '#7d6a5c', 0.02);
  box(root, [plan.landing.width, height, plan.landing.depth], [plan.landing.x, height / 2, plan.landing.z], '#7d6a5c', 0.02);
  box(root, [plan.patron.width, 0.05, 0.05], [plan.patron.x, height - 0.04, galleryFront + 0.02], '#d2b568', 0);
  const treads = 4;
  const run = (plan.stairs.foot - plan.stairs.top) / treads;
  for (let tread = 0; tread < treads; tread++) {
    const top = (height * (treads - tread)) / (treads + 1);
    box(root, [plan.stairs.width, top, run], [plan.stairs.x, top / 2, plan.stairs.top + run / 2 + tread * run], tread % 2 ? '#85715f' : '#7d6a5c', 0.01);
  }
  railing(root, [galleryLeft + 0.05, galleryFront - 0.06], [right - 0.2, galleryFront - 0.06], height, glassMaterial);
  railing(root, [galleryLeft + 0.05, plan.stairs.top + 0.05], [galleryLeft + 0.05, galleryFront - 0.06], height, glassMaterial);
  const galleryRug = makeFurniture('rug', '#6d5d59');
  galleryRug.scale.set(2.1, 1, 1.5);
  galleryRug.position.set(plan.patronDesk.x, 0.02, plan.patronDesk.z + 0.35);
  gallery.add(galleryRug);
  const desk = group(gallery, [plan.patronDesk.x, 0, plan.patronDesk.z]);
  box(desk, [3.05, 0.16, 1.2], [0, 0.91, 0], '#6e5545', 0.05);
  for (const x of [-1.28, 1.28]) box(desk, [0.18, 0.86, 1], [x, 0.45, 0], '#564238', 0.035);
  box(desk, [0.72, 0.04, 0.48], [-0.5, 1.02, 0.05], '#d6c6a5', 0.015);
  box(desk, [0.46, 0.055, 0.32], [-0.38, 1.07, 0.02], '#f0e5ca', 0.01).rotation.y = -0.1;
  box(desk, [0.6, 0.38, 0.05], [0.55, 1.2, -0.2], '#242c35', 0.03).rotation.y = Math.PI;
  chair(gallery, [plan.patronDesk.x, 0, plan.patronDesk.z - 0.98], 0, '#625563');
  plant(gallery, 0.95, '#987556', true).position.set(right - 0.65, 0, galleryFront - 0.7);
  plant(gallery, 0.8, '#987556').position.set(galleryLeft + 1.9, 0, plan.patron.z - plan.patron.depth / 2 + 0.6);
  const presenterMark = new THREE.MeshStandardMaterial({ color: '#e0bd68', emissive: '#e0bd68', emissiveIntensity: 0.8 });
  cylinder(gallery, 0.28, 0.28, 0.03, [plan.patronDesk.x, 0.03, plan.patronDesk.z + 1.3], presenterMark, 32);
  zoneSign(root, labels.patron(Math.max(0, plan.reviewCount - 1)), [plan.patronDesk.x - 2.2, 3.3 + height * 0.2, back + 0.3], '#e7c27f');

  // The notice board: what is waiting for the patron, on a stand beside the desk.
  const boardBase = height;
  for (const side of [-1, 1]) rod(root, [plan.noticeBoard.x + side * 1.05, boardBase, plan.noticeBoard.z], [plan.noticeBoard.x + side * 1.05, boardBase + 0.75, plan.noticeBoard.z], 0.035, '#3e4148');
  box(root, [2.7, 1.55, 0.07], [plan.noticeBoard.x, boardBase + 1.45, plan.noticeBoard.z], '#1d2a36', 0.03);
  const boardFrame = new THREE.Mesh(new THREE.BoxGeometry(2.78, 1.63, 0.04), new THREE.MeshBasicMaterial({ color: '#d2b568' }));
  boardFrame.position.set(plan.noticeBoard.x, boardBase + 1.45, plan.noticeBoard.z - 0.01);
  live.add(boardFrame);
  const [boardCanvas] = canvas2d(640, 360);
  const boardTexture = new THREE.CanvasTexture(boardCanvas);
  boardTexture.colorSpace = THREE.SRGBColorSpace;
  const board = new THREE.Mesh(new THREE.PlaneGeometry(2.56, 1.44), new THREE.MeshBasicMaterial({ map: boardTexture, toneMapped: false }));
  board.position.set(plan.noticeBoard.x, boardBase + 1.45, plan.noticeBoard.z + 0.04);
  live.add(board);

  // A click anywhere on the gallery opens the patron's inbox.
  const patronTarget = box(root, [plan.patron.width, 2.7, plan.patron.depth], [plan.patron.x, height + 1.35, plan.patron.z], new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }), 0);
  patronTarget.castShadow = false;
  patronTarget.receiveShadow = false;

  // ── The work floor: one desk per agent, each with its owner's name on it.
  zoneFloor(root, plan.work, '#aa9b7d');
  const screens: THREE.Mesh[] = [];
  const plates: THREE.Mesh[] = [];
  plan.desks.forEach((position, index) => {
    const station = group(root, [position.x, 0, position.z]);
    const screen = workstation(station, index, new THREE.MeshBasicMaterial({ color: '#27303a' }));
    live.attach(screen);
    screen.castShadow = false;
    screens.push(screen);
    const [canvas] = canvas2d(320, 96);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const plate = new THREE.Mesh(new THREE.PlaneGeometry(0.8, 0.24), new THREE.MeshBasicMaterial({ map: texture, toneMapped: false }));
    plate.position.set(position.x - 0.42, 1.03, position.z + 0.3);
    plate.rotation.x = -0.5;
    live.add(plate);
    plates.push(plate);
    box(root, [0.84, 0.03, 0.12], [position.x - 0.42, 0.905, position.z + 0.33], '#3e4148', 0.01);
  });
  plant(root, 0.85, '#8d7156').position.set(right - 0.6, 0, galleryFront + 0.7);

  // ── The lounge, across the front of the building, behind a low partition.
  zoneFloor(root, plan.lounge, '#82928d');
  const partitionFrom = plan.aisleX + 0.9;
  box(root, [right - 0.2 - partitionFrom, 0.9, 0.12], [(partitionFrom + right - 0.2) / 2, 0.45, loungeTop], '#8e9999', 0.02);
  box(root, [right - 0.2 - partitionFrom, 0.05, 0.18], [(partitionFrom + right - 0.2) / 2, 0.92, loungeTop], '#c5a767', 0.01);
  const balls = new Map<number, { mesh: THREE.Mesh; x: number; z: number }>();
  const counts = { sofa: 0, bar: 0, table: 0, nook: 0 };
  plan.stations.forEach((station, index) => {
    const spot = group(root, [station.x, 0, station.z], station.rotation);
    const nth = counts[station.kind]++;
    if (station.kind === 'sofa') sofaGroup(spot, nth);
    if (station.kind === 'bar') snackBar(spot, station, labels.snackBar);
    if (station.kind === 'nook') readingNook(spot, nth);
    if (station.kind === 'table') {
      tennisTable(spot);
      const sign = station.rotation === 0 ? 1 : -1;
      const ball = new THREE.Mesh(new THREE.SphereGeometry(0.035, 10, 8), new THREE.MeshBasicMaterial({ color: '#fff4d6' }));
      const rest = { x: station.x, z: station.z - sign * 0.1 };
      ball.position.set(rest.x, 0.85, rest.z);
      ball.visible = false;
      live.add(ball);
      balls.set(index, { mesh: ball, ...rest });
    }
  });

  // Pendant lamps, lit only at night. Few of them: each one is a real light.
  const lampMaterial = new THREE.MeshStandardMaterial({ color: '#c7a962', emissive: '#ffd77e', emissiveIntensity: 0, roughness: 0.45 });
  const lights: THREE.PointLight[] = [];
  const lamps: [x: number, z: number, lift: number][] = [
    [plan.reception.x, plan.reception.z, 0],
    [plan.clinic.x, plan.clinic.z, 0],
    [plan.patronDesk.x, plan.patronDesk.z + 0.4, height * 0.6],
    [plan.work.x - plan.work.width / 4, plan.work.z + 0.5, 0],
    [plan.work.x + plan.work.width / 4, plan.work.z + 0.5, 0],
    ...plan.loungeLanes.slice(0, 2).flatMap((lane): [number, number, number][] => [[-width / 4, lane, 0], [width / 4, lane, 0]]),
  ];
  for (const [x, z, lift] of lamps.slice(0, 9)) {
    rod(root, [x, 3.65 + lift, z], [x, 3.05 + lift, z], 0.012, '#4b4842');
    cylinder(root, 0.14, 0.32, 0.25, [x, 2.95 + lift, z], lampMaterial, 20);
    const light = new THREE.PointLight('#ffd58a', 0, 9.2, 1.6);
    light.position.set(x, 2.7 + lift, z);
    root.add(light);
    lights.push(light);
  }
  const parts: LiveParts = { screens, plates, board, boardFrame, balls };
  return { root, live, windowMaterial, starsMaterial, lights, lampMaterial, hologram, patronTarget, parts };
}
