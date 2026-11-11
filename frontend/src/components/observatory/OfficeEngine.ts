import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { createCharacter, type Appearance, type CharacterRig } from '@/scene/character';
import { chair, coffeeTable, makeFurniture, plant } from '@/scene/furniture';
import { box, cylinder, group, releaseCaches, retainCaches, rod, sphere, woodTexture } from '@/scene/primitives';
import { clinicBed, podLetter, workSeat, type AgentZone, type OfficeLayout, type OfficePlan, type Placement } from './officePlan';

/*
 * The one-floor office diorama of the observatory (DESIGN §5, §7, §10).
 *
 * A plain class rather than React: it owns a WebGL renderer, a render loop and a pile of GPU
 * resources whose lifetime has to be exactly "while this canvas is on screen". The React
 * wrapper builds one per workspace and floor-plan shape and calls `dispose()` when it leaves.
 *
 * Colours written as hex below are scene materials (wood, fabric, glass, lamp light), lit and
 * tone-mapped by the scene. UI text drawn into the scene (name tags) reads the CSS theme tokens.
 */

export interface SceneAgent {
  id: string;
  name: string;
  status: string;
  runtimeLabel: string;
}

export interface SceneState {
  agents: SceneAgent[];
  layout: OfficeLayout;
  theme: 'light' | 'dark';
  selectedId: string | null;
}

/** Words painted onto signs and floor markings. Built once per scene, in the page's language. */
export interface SceneLabels {
  canvas: string;
  mainCirculation: string;
  entry: string;
  reception: [string, string];
  lounge: [string, string];
  pod: (letter: string) => [string, string];
  podFloor: (letter: string) => string;
  clinic: (beds: number, waiting: number) => [string, string];
  patron: (queue: number) => [string, string];
  approvalQueue: string;
}

export type HoverState = { id: string; x: number; y: number } | null;

interface EngineCallbacks {
  onSelect: (id: string) => void;
  onOpenPatron: () => void;
  onHover: (hover: HoverState) => void;
}

// ─── Appearance ──────────────────────────────────────────────────────────────

const SKINS = ['#f1c9a5', '#e0ac85', '#c98e66', '#a8714f', '#7c5139', '#f3d5bd'];
const HAIRS = ['#2f2a28', '#5a3d2b', '#8a5a3a', '#c79a5b', '#3e3f52', '#6b4b6d'];
const SHIRTS = ['#7fb59e', '#d5a84f', '#9c8ac7', '#d18b72', '#789fc7', '#b79265'];
const HAIRSTYLES: Appearance['hairstyle'][] = ['bob', 'crop', 'curls'];

function hash(text: string): number {
  let h = 2166136261;
  for (let index = 0; index < text.length; index++) h = Math.imul(h ^ text.charCodeAt(index), 16777619);
  return h >>> 0;
}

/** Same agent, same figure, on every visit and every device. */
function appearanceOf(id: string): Appearance {
  const h = hash(id);
  return {
    skin: SKINS[h % SKINS.length],
    hair: HAIRS[(h >>> 5) % HAIRS.length],
    shirt: SHIRTS[(h >>> 10) % SHIRTS.length],
    hairstyle: HAIRSTYLES[(h >>> 15) % HAIRSTYLES.length],
  };
}

function accentOf(id: string): string {
  return SHIRTS[(hash(id) >>> 10) % SHIRTS.length];
}

// ─── Name tags ───────────────────────────────────────────────────────────────

/** A theme token as a CSS colour the 2D canvas understands (`oklch(L C H / a)`). */
function token(name: string, alpha = 1): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
  return value ? `oklch(${value} / ${alpha})` : 'gray';
}

const STATUS_TOKEN: Record<string, string> = { working: 'gold', online: 'success', idle: 'success', hung: 'danger', offline: 'faint' };

function canvas2d(width: number, height: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('2D canvas unavailable');
  return [canvas, context];
}

const SCENE_FONT = '"Be Vietnam Pro", Arial, sans-serif';

function paintLabel(sprite: THREE.Sprite, agent: SceneAgent, theme: string) {
  const mat = sprite.material as THREE.SpriteMaterial;
  const canvas = mat.map!.image as HTMLCanvasElement;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = token('surface', 0.94);
  ctx.beginPath();
  ctx.roundRect(6, 8, 500, 106, 28);
  ctx.fill();
  ctx.strokeStyle = token('line', 0.8);
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = token(STATUS_TOKEN[agent.status] ?? 'faint');
  ctx.beginPath();
  ctx.arc(45, 61, 12, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = token('ink-strong');
  ctx.font = `600 42px ${SCENE_FONT}`;
  ctx.textBaseline = 'middle';
  ctx.fillText(agent.name, 74, 51, 420);
  ctx.fillStyle = token('muted');
  ctx.font = '24px ui-monospace, monospace';
  ctx.fillText(agent.runtimeLabel.toUpperCase(), 75, 88, 420);
  mat.map!.needsUpdate = true;
  sprite.userData.paintKey = `${theme}:${agent.status}:${agent.name}:${agent.runtimeLabel}`;
}

function labelSprite(agent: SceneAgent, theme: string): THREE.Sprite {
  const [canvas] = canvas2d(512, 128);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false }));
  sprite.scale.set(1.65, 0.41, 1);
  sprite.position.set(0, 1.93, 0);
  sprite.renderOrder = 4;
  sprite.userData.agentId = agent.id;
  paintLabel(sprite, agent, theme);
  return sprite;
}

// ─── Architecture ────────────────────────────────────────────────────────────

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
  sprite.scale.set(3.5, 0.73, 1);
  parent.add(sprite);
}

function floorWayfinding(parent: THREE.Object3D, title: string, position: [number, number], color: string) {
  const [canvas, ctx] = canvas2d(512, 128);
  ctx.fillStyle = color;
  ctx.font = `600 43px ${SCENE_FONT}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(title.toUpperCase(), 256, 64, 490);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const mat = new THREE.MeshBasicMaterial({ map: texture, transparent: true, depthWrite: false, opacity: 0.72 });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(3.8, 0.95), mat);
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(position[0], 0.075, position[1]);
  parent.add(mesh);
}

function workstation(parent: THREE.Object3D, index: number, screenMaterial: THREE.Material) {
  const wood = index % 2 ? '#876e52' : '#967a58';
  box(parent, [1.75, 0.12, 0.86], [0, 0.83, 0], wood, 0.045);
  for (const x of [-0.72, 0.72]) for (const z of [-0.3, 0.3]) rod(parent, [x, 0.05, z], [x, 0.78, z], 0.035, '#3e4148');
  box(parent, [0.7, 0.43, 0.055], [0, 1.19, -0.18], '#242c35', 0.035);
  box(parent, [0.62, 0.35, 0.012], [0, 1.19, -0.145], screenMaterial, 0.015);
  for (let line = 0; line < 4; line++) box(parent, [0.36 - line * 0.035, 0.012, 0.008], [-0.06, 1.28 - line * 0.06, -0.134], line === 0 ? '#e0bd68' : '#b8c8ee', 0);
  rod(parent, [0, 0.85, -0.18], [0, 0.98, -0.18], 0.028, '#3e4148');
  box(parent, [0.62, 0.025, 0.21], [0, 0.91, 0.18], '#b9b7ae', 0.015);
  chair(parent, [0, 0, 0.72], Math.PI, index % 2 ? '#4f5e72' : '#695c68');
}

function zoneFloor(parent: THREE.Object3D, center: [number, number], size: [number, number], color: string) {
  return box(parent, [size[0], 0.035, size[1]], [center[0], 0.035, center[1]], color, 0.06);
}

/** Back wall, a solid side, a glazed side (optionally with a door) and a glazed front with a door. */
function roomShell(parent: THREE.Object3D, center: [number, number], size: [number, number], wallColor: string, glass: THREE.Material, sideDoor = false) {
  const [cx, cz] = center;
  const [width, depth] = size;
  const back = cz - depth / 2;
  const front = cz + depth / 2;
  const left = cx - width / 2;
  const right = cx + width / 2;
  box(parent, [width, 2.35, 0.13], [cx, 1.18, back], wallColor, 0.025);
  box(parent, [0.13, 1.55, depth], [left, 0.78, cz], wallColor, 0.025);
  if (sideDoor) {
    const sideSegment = (depth - 1.8) / 2;
    for (const side of [-1, 1]) {
      const z = cz + side * (0.9 + sideSegment / 2);
      box(parent, [0.13, 0.68, sideSegment], [right, 0.34, z], wallColor, 0.025);
      box(parent, [0.055, 0.82, Math.max(0.1, sideSegment - 0.12)], [right, 1.08, z], glass, 0.01);
      box(parent, [0.16, 1.92, 0.09], [right, 0.96, cz + side * 0.95], '#6d777c', 0.015);
    }
    box(parent, [0.16, 0.09, 1.99], [right, 1.89, cz], '#6d777c', 0.015);
  } else {
    box(parent, [0.13, 0.68, depth], [right, 0.34, cz], wallColor, 0.025);
    box(parent, [0.055, 0.82, depth - 0.3], [right, 1.08, cz], glass, 0.01);
  }
  const segment = (width - 1.85) / 2;
  for (const side of [-1, 1]) {
    const x = cx + side * (1.85 / 2 + segment / 2);
    box(parent, [segment, 0.42, 0.13], [x, 0.21, front], wallColor, 0.02);
    box(parent, [segment - 0.12, 0.66, 0.045], [x, 0.78, front], glass, 0.008);
    box(parent, [0.09, 1.92, 0.16], [cx + side * 0.97, 0.96, front], '#6d777c', 0.015);
  }
  box(parent, [2.03, 0.09, 0.16], [cx, 1.89, front], '#6d777c', 0.015);
  box(parent, [width, 0.09, 0.18], [cx, 0.08, back + 0.08], '#766858', 0.01);
}

/** A six-person team studio: low partitions, an open front and a storage wall. */
function podShell(parent: THREE.Object3D, center: [number, number], accent: string) {
  const [cx, cz] = center;
  const width = 7.45;
  const depth = 7.45;
  box(parent, [width, 1.5, 0.11], [cx, 0.75, cz - depth / 2], '#929c9c', 0.02);
  box(parent, [0.11, 0.85, depth], [cx - width / 2, 0.43, cz], '#8e9999', 0.02);
  box(parent, [0.11, 0.48, depth], [cx + width / 2, 0.24, cz], '#8e9999', 0.02);
  for (const x of [cx - width / 2, cx + width / 2]) box(parent, [0.12, 1.85, 0.12], [x, 0.93, cz + depth / 2], '#69777b', 0.015);
  box(parent, [width, 0.08, 0.14], [cx, 0.09, cz + depth / 2], accent, 0.01);
  for (let index = 0; index < 3; index++) {
    box(parent, [1.55, 0.62, 0.48], [cx - 2.2 + index * 2.2, 0.31, cz - 3.35], '#6f7c80', 0.035);
    box(parent, [1.48, 0.055, 0.52], [cx - 2.2 + index * 2.2, 0.65, cz - 3.35], '#c1b18f', 0.02);
  }
}

function buildCompany(scene: THREE.Scene, plan: OfficePlan, labels: SceneLabels) {
  const root = group();
  scene.add(root);
  const floorMaterial = new THREE.MeshStandardMaterial({ map: woodTexture(), color: '#b7a889', roughness: 0.86 });
  const windowMaterial = new THREE.MeshStandardMaterial({ color: '#c6d2de', emissive: '#bcd9f0', emissiveIntensity: 0.65, roughness: 0.25 });
  const glassMaterial = new THREE.MeshStandardMaterial({ color: '#a9c0c9', transparent: true, opacity: 0.24, roughness: 0.18, depthWrite: false });
  const screenMaterial = new THREE.MeshStandardMaterial({ color: '#8ea7ce', emissive: '#5079cb', emissiveIntensity: 0.45, roughness: 0.35 });
  const left = -plan.floorWidth / 2;
  const back = -plan.floorDepth / 2;
  const front = plan.floorDepth / 2;
  const right = plan.floorWidth / 2;

  // Shell: floor slab, back wall with windows, side walls and an entrance gap on the left.
  box(root, [plan.floorWidth, 0.28, plan.floorDepth], [0, -0.14, 0], floorMaterial, 0.08);
  box(root, [plan.floorWidth, 3.55, 0.16], [0, 1.77, back + 0.08], '#b9c5cd', 0.03);
  box(root, [0.16, 2.75, -9.1 - back], [left + 0.08, 1.37, (back - 9.1) / 2], '#aebdc6', 0.03);
  box(root, [0.16, 2.75, front + 6.9], [left + 0.08, 1.37, (front - 6.9) / 2], '#aebdc6', 0.03);
  box(root, [0.16, 1.05, plan.floorDepth], [right - 0.08, 0.52, 0], '#aebdc6', 0.03);
  box(root, [plan.floorWidth, 0.24, 0.12], [0, -0.05, front - 0.08], '#766858', 0.015);
  box(root, [plan.floorWidth, 0.12, 0.12], [0, 0.1, back + 0.18], '#73644f', 0.015);
  const windowCount = Math.ceil(plan.floorWidth / 6.4);
  for (let index = 0; index < windowCount; index++) {
    const x = left + 3.2 + index * ((plan.floorWidth - 6.4) / Math.max(1, windowCount - 1));
    box(root, [4.7, 1.62, 0.025], [x, 2.15, back + 0.18], windowMaterial, 0.012);
    box(root, [4.86, 0.07, 0.07], [x, 3.0, back + 0.22], '#766a56', 0.01);
    box(root, [4.86, 0.07, 0.07], [x, 1.3, back + 0.22], '#766a56', 0.01);
    box(root, [0.06, 1.75, 0.07], [x, 2.15, back + 0.22], '#766a56', 0.01);
  }

  // Stars in the windows: visible only at night.
  const starCount = Math.round(plan.floorWidth * 11);
  const starsGeometry = new THREE.BufferGeometry();
  const starPositions = new Float32Array(starCount * 3);
  for (let index = 0; index < starCount; index++) {
    starPositions[index * 3] = left + 1 + ((index * 2.37) % (plan.floorWidth - 2));
    starPositions[index * 3 + 1] = 1.42 + ((index * 1.61) % 1.45);
    starPositions[index * 3 + 2] = back + 0.21;
  }
  starsGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
  const starsMaterial = new THREE.PointsMaterial({ color: '#ffe6a6', size: 0.035, transparent: true, opacity: 0 });
  root.add(new THREE.Points(starsGeometry, starsMaterial));

  // A continuous circulation spine and cross-corridor make the plan readable before furniture.
  const spineX = plan.large ? -7.72 : -4.35;
  zoneFloor(root, [0, -0.85], [plan.floorWidth - 0.7, 1.55], '#77878a');
  zoneFloor(root, [spineX, 0], [1.28, plan.floorDepth - 0.8], '#77878a');
  box(root, [plan.floorWidth - 1.2, 0.018, 0.035], [0, 0.075, -0.85], '#d4b972', 0);
  box(root, [0.035, 0.018, plan.floorDepth - 1.2], [spineX, 0.075, 0], '#d4b972', 0);
  for (const z of [-10.5, -4.8, 3.0, 10.4]) {
    box(root, [0.34, 0.018, 0.055], [spineX, 0.078, z], '#d9c78e', 0).rotation.y = Math.PI / 4;
    box(root, [0.34, 0.018, 0.055], [spineX, 0.078, z], '#d9c78e', 0).rotation.y = -Math.PI / 4;
  }
  floorWayfinding(root, labels.mainCirculation, [spineX + (plan.large ? 2.2 : 2.5), -0.82], '#e5dcc4');

  // Reception: a room with an exterior entrance, a check-in desk and an interior queue.
  zoneFloor(root, [plan.setupX, -8], [7.45, 7.45], '#9eabb0');
  roomShell(root, [plan.setupX, -8], [7.45, 7.45], '#a5b2b6', glassMaterial, true);
  const reception = group(root, [plan.setupX, 0, -9.55]);
  box(reception, [4.1, 1.05, 1.05], [0, 0.54, 0], '#687e88', 0.08);
  box(reception, [4.35, 0.12, 1.25], [0, 1.09, 0], '#d2c2a2', 0.045);
  box(reception, [1.25, 0.06, 0.65], [0.9, 1.2, 0], '#263744', 0.025).rotation.x = -0.18;
  box(reception, [1.1, 0.025, 0.5], [0.9, 1.235, -0.015], '#88b9d5', 0.015).rotation.x = -0.18;
  zoneSign(root, labels.reception, [plan.setupX, 2.75, -11.52], '#8fc4e8');
  for (const z of [-8.7, -7.45, -6.2]) {
    cylinder(root, 0.055, 0.075, 0.85, [plan.setupX - 2.25, 0.44, z], '#596a74', 12);
    cylinder(root, 0.055, 0.075, 0.85, [plan.setupX - 0.35, 0.44, z], '#596a74', 12);
    if (z < -6.3) rod(root, [plan.setupX - 2.25, 0.77, z], [plan.setupX - 2.25, 0.77, z + 1.25], 0.018, '#d2b568');
  }
  const setupStation = group(root, [plan.setupX + 2.2, 0, -7.0]);
  setupStation.scale.setScalar(0.82);
  workstation(setupStation, 0, screenMaterial);
  const hologram = group(root, [plan.setupX + 2.0, 1.05, -5.7]);
  const holoMaterial = new THREE.MeshBasicMaterial({ color: '#9fb7ff', transparent: true, opacity: 0.52, depthWrite: false });
  for (let index = 0; index < 3; index++) {
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.48 + index * 0.16, 0.012, 6, 48), holoMaterial);
    ring.rotation.set(Math.PI / 2.6 + index * 0.33, index * 0.7, 0);
    hologram.add(ring);
  }
  sphere(hologram, [0, 0, 0], [0.14, 0.14, 0.14], new THREE.MeshBasicMaterial({ color: '#ffe6a0' }), 20);
  cylinder(root, 0.8, 0.95, 0.12, [plan.setupX + 2.0, 0.16, -5.7], '#63747f', 32);
  const entryX = left + 0.18;
  box(root, [0.12, 2.45, 0.12], [entryX, 1.22, -9.1], '#57676f', 0.015);
  box(root, [0.12, 2.45, 0.12], [entryX, 1.22, -6.9], '#57676f', 0.015);
  box(root, [0.12, 0.12, 2.32], [entryX, 2.4, -8.0], '#57676f', 0.015);
  box(root, [0.035, 2.15, 1.85], [entryX + 0.03, 1.18, -8.0], glassMaterial, 0.005);
  floorWayfinding(root, labels.entry, [plan.setupX - 2.2, -10.75], '#e5eef2');

  // Lounge: architectural separation, not a rug dropped on the workfloor.
  zoneFloor(root, [plan.loungeX, 0], [7.45, 7.45], '#82928d');
  roomShell(root, [plan.loungeX, 0], [7.45, 7.45], '#8f9e99', glassMaterial, true);
  const lounge = group(root, [plan.loungeX, 0, 0]);
  const rug = makeFurniture('rug', '#58656e');
  rug.scale.set(1.9, 1, 1.75);
  lounge.add(rug);
  const sofa = makeFurniture('sofa', '#7b7180');
  sofa.position.set(-0.4, 0, 1.25);
  sofa.rotation.y = Math.PI;
  sofa.scale.setScalar(0.88);
  lounge.add(sofa);
  const armchair = makeFurniture('armchair', '#6c7d78');
  armchair.position.set(2.05, 0, -0.25);
  armchair.rotation.y = -Math.PI / 2;
  lounge.add(armchair);
  coffeeTable(lounge, [-0.25, 0, -0.15]);
  plant(lounge, 0.9, '#9c7658', true).position.set(-2.7, 0, -1.45);
  const sideboard = makeFurniture('stereo', '#657a72');
  sideboard.position.set(-1.7, 0, -2.95);
  lounge.add(sideboard);
  zoneSign(root, labels.lounge, [plan.loungeX, 2.75, -3.52], '#a8d5bd');

  // Each studio is a defined six-person team room with a clear entry and storage wall.
  plan.workCenters.forEach((center, pod) => {
    const row = plan.workRows[pod];
    zoneFloor(root, [center, row], [7.45, 7.45], pod % 2 ? '#a6977f' : '#aa9b7d');
    podShell(root, [center, row], pod % 2 ? '#c5a767' : '#d0b779');
    for (let local = 0; local < 6; local++) {
      const seat = workSeat(pod * 6 + local, plan);
      workstation(group(root, [seat.x, 0, seat.z]), pod * 6 + local, screenMaterial);
    }
    zoneSign(root, labels.pod(podLetter(pod)), [center, 2.1, row - 3.5], '#e7c27f');
    floorWayfinding(root, labels.podFloor(podLetter(pod)), [center, row + 3.05], '#f0e4c8');
    plant(root, 0.85, '#8d7156').position.set(center - 3.05, 0, row + 2.85);
  });

  // Clinic: a private room with beds, medical storage and a bench by its own door.
  zoneFloor(root, [plan.clinicX, plan.clinicZ], [7.45, 7.45], '#b8c9ca');
  roomShell(root, [plan.clinicX, plan.clinicZ], [7.45, 7.45], '#a3b6b9', glassMaterial, true);
  for (let index = 0; index < plan.clinicBeds; index++) {
    const position = clinicBed(index, plan);
    const bed = makeFurniture('bed', index % 2 ? '#8aa6b0' : '#91a99c');
    bed.scale.setScalar(0.72);
    bed.position.set(position.x, 0, position.z);
    root.add(bed);
    box(root, [0.42, 0.62, 0.42], [position.x + 1.05, 0.32, position.z - 0.68], '#d4dbd7', 0.04);
    box(root, [0.34, 0.45, 0.04], [position.x + 1.05, 1.0, position.z - 0.7], '#5f7580', 0.025);
    box(root, [0.25, 0.06, 0.015], [position.x + 1.05, 1.03, position.z - 0.675], '#9fe0ca', 0.005);
  }
  const waitingBench = makeFurniture('bench', '#7d9395');
  waitingBench.scale.setScalar(0.78);
  waitingBench.position.set(plan.clinicX - 0.6, 0, plan.clinicZ - 3.05);
  root.add(waitingBench);
  zoneSign(root, labels.clinic(plan.clinicBeds, plan.clinicWaiting), [plan.clinicX, 2.75, plan.clinicZ - 3.52], '#a8d5bd');
  const cross = group(root, [plan.clinicX + 2.9, 1.75, plan.clinicZ - 3.38]);
  box(cross, [0.12, 0.85, 0.28], [0, 0, 0], '#d9eee6', 0.02);
  box(cross, [0.12, 0.28, 0.85], [0, 0, 0], '#d9eee6', 0.02);

  // CEO office: three readable walls, glazed front, private desk and an exterior approval queue.
  zoneFloor(root, [plan.patronX, plan.patronZ], [7.45, 7.45], '#8e7c70');
  roomShell(root, [plan.patronX, plan.patronZ], [7.45, 7.45], '#8d817b', glassMaterial);
  const ceo = group(root, [plan.patronX, 0, plan.patronZ]);
  const ceoRug = makeFurniture('rug', '#6d5d59');
  ceoRug.scale.set(2.15, 1, 2.25);
  ceo.add(ceoRug);
  const ceoDesk = group(ceo, [0, 0, 1.3]);
  box(ceoDesk, [3.25, 0.16, 1.3], [0, 0.91, 0], '#6e5545', 0.05);
  for (const x of [-1.35, 1.35]) box(ceoDesk, [0.18, 0.86, 1.08], [x, 0.45, 0], '#564238', 0.035);
  box(ceoDesk, [0.72, 0.04, 0.48], [0, 1.02, 0.05], '#d6c6a5', 0.015);
  box(ceoDesk, [0.46, 0.055, 0.32], [0.12, 1.07, 0.02], '#f0e5ca', 0.01).rotation.y = -0.1;
  chair(ceo, [0, 0, 2.45], Math.PI, '#625563');
  const shelf = makeFurniture('bookshelf', '#675443');
  shelf.position.set(2.5, 0, -2.65);
  shelf.scale.setScalar(1.25);
  ceo.add(shelf);
  plant(ceo, 1.05, '#987556', true).position.set(-2.55, 0, 2.65);
  const approvalLamp = new THREE.MeshStandardMaterial({ color: '#e0bd68', emissive: '#e0bd68', emissiveIntensity: 0.8 });
  cylinder(ceo, 0.28, 0.28, 0.035, [0, 0.06, -0.3], approvalLamp, 32);
  const queueLength = Math.max(0, plan.reviewCount - 1);
  zoneSign(root, labels.patron(queueLength), [plan.patronX, 2.75, plan.patronZ - 3.52], '#e7c27f');
  for (let index = 0; index < Math.max(1, queueLength); index++) {
    const x = plan.patronX - 2.25 + index * 1.1;
    cylinder(root, 0.05, 0.065, 0.72, [x, 0.37, plan.patronZ + 4.45], '#756552', 12);
    if (index < plan.reviewCount - 2) rod(root, [x, 0.68, plan.patronZ + 4.45], [x + 1.1, 0.68, plan.patronZ + 4.45], 0.016, '#d2b568');
  }
  floorWayfinding(root, labels.approvalQueue, [plan.patronX, plan.patronZ + 5.35], '#eadbbe');
  const patronTarget = box(root, [7.45, 3.35, 7.45], [plan.patronX, 1.67, plan.patronZ], new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }), 0);
  patronTarget.castShadow = false;
  patronTarget.receiveShadow = false;

  // One pendant lamp per room; lit only at night (DESIGN §4).
  const lampMaterial = new THREE.MeshStandardMaterial({ color: '#c7a962', emissive: '#ffd77e', emissiveIntensity: 0, roughness: 0.45 });
  const lights: THREE.PointLight[] = [];
  const lightPositions: [number, number][] = [
    [plan.setupX, -8],
    [plan.loungeX, 0],
    [plan.clinicX, plan.clinicZ],
    [plan.patronX, plan.patronZ],
    ...plan.workCenters.map((x, index): [number, number] => [x, plan.workRows[index]]),
  ];
  for (const [x, z] of lightPositions) {
    rod(root, [x, 3.65, z], [x, 3.05, z], 0.012, '#4b4842');
    cylinder(root, 0.14, 0.32, 0.25, [x, 2.95, z], lampMaterial, 20);
    const light = new THREE.PointLight('#ffd58a', 0, 9.2, 1.6);
    light.position.set(x, 2.7, z);
    root.add(light);
    lights.push(light);
  }
  return { root, windowMaterial, starsMaterial, lights, lampMaterial, hologram, patronTarget };
}

/** Batch static furniture by shared material; articulated agents and interactive targets stay separate. */
function optimizeOffice(root: THREE.Group, keep: THREE.Object3D[]) {
  root.updateMatrixWorld(true);
  const inverse = root.matrixWorld.clone().invert();
  const batches = new Map<string, { material: THREE.Material; geometries: THREE.BufferGeometry[]; cast: boolean; receive: boolean }>();
  const originals: THREE.Mesh[] = [];
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || Array.isArray(object.material)) return;
    for (let ancestor: THREE.Object3D | null = object; ancestor; ancestor = ancestor.parent) if (keep.includes(ancestor)) return;
    const key = `${object.material.uuid}:${object.castShadow}:${object.receiveShadow}`;
    let batch = batches.get(key);
    if (!batch) {
      batch = { material: object.material, geometries: [], cast: object.castShadow, receive: object.receiveShadow };
      batches.set(key, batch);
    }
    const geometry = object.geometry.index ? object.geometry.toNonIndexed() : object.geometry.clone();
    geometry.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse, object.matrixWorld));
    batch.geometries.push(geometry);
    originals.push(object);
  });
  originals.forEach((object) => object.removeFromParent());
  batches.forEach((batch) => {
    const geometry = mergeGeometries(batch.geometries, false);
    batch.geometries.forEach((item) => item.dispose());
    if (!geometry) return;
    const mesh = new THREE.Mesh(geometry, batch.material);
    mesh.castShadow = batch.cast;
    mesh.receiveShadow = batch.receive;
    root.add(mesh);
  });
}

/** Software renderers (SwiftShader, llvmpipe) get Lambert instead of PBR; nothing is removed. */
function toLightweightMaterials(root: THREE.Object3D, preserved: Set<THREE.Material>) {
  const converted = new Map<THREE.Material, THREE.MeshLambertMaterial>();
  root.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || Array.isArray(object.material) || !(object.material instanceof THREE.MeshStandardMaterial) || preserved.has(object.material)) return;
    const source = object.material;
    let target = converted.get(source);
    if (!target) {
      target = new THREE.MeshLambertMaterial({
        color: source.color,
        emissive: source.emissive,
        emissiveIntensity: source.emissiveIntensity,
        map: source.map,
        transparent: source.transparent,
        opacity: source.opacity,
        side: source.side,
        vertexColors: source.vertexColors,
        depthWrite: source.depthWrite,
        alphaTest: source.alphaTest,
      });
      converted.set(source, target);
    }
    object.material = target;
  });
  return converted;
}

// ─── Engine ──────────────────────────────────────────────────────────────────

const DAY = { background: '#edf4f6', ground: '#f4f6f5', groundEmissive: '#dce8ec', groundGlow: 0.85, sun: '#fff0d2', sunPower: 3.15, sky: '#f5f8ff', skyGround: '#d9cbb4', hemi: 2.05, window: '#e8f6ff', windowGlow: '#dcf2ff', windowPower: 0.65, stars: 0, lamp: 0, light: 0, exposure: 1.04 };
const NIGHT = { background: '#101a24', ground: '#111b26', groundEmissive: '#000000', groundGlow: 0, sun: '#8fa9df', sunPower: 0.24, sky: '#8fa9c9', skyGround: '#273647', hemi: 0.52, window: '#102642', windowGlow: '#102642', windowPower: 0.8, stars: 0.9, lamp: 2.2, light: 12, exposure: 0.9 };

type Motion = { moving: boolean; typing: boolean; pose: Placement['pose'] };

export class OfficeEngine {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-8, 8, 8, -8, 0.1, 160);
  private controls: OrbitControls;
  private observer: ResizeObserver;
  private office: ReturnType<typeof buildCompany>;
  private ground: THREE.Mesh;
  private rigs = new Map<string, CharacterRig>();
  private labels = new Map<string, THREE.Sprite>();
  private raycaster = new THREE.Raycaster();
  private pointer = new THREE.Vector2();
  private pointerStart: [number, number] = [0, 0];
  private frame = 0;
  private elapsed = 0;
  private previous = 0;
  private disposed = false;
  private sun: THREE.DirectionalLight;
  private hemi: THREE.HemisphereLight;
  private motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
  private reduced = this.motionQuery.matches;
  private plan: OfficePlan;
  private overview: THREE.Vector3;
  private host: HTMLElement;
  private state: () => SceneState;
  private callbacks: EngineCallbacks;
  private hoveredId: string | null = null;
  private signature = '';
  private lastState: SceneState | null = null;
  private software = false;
  private scratch = { color: new THREE.Color(), desired: new THREE.Vector3(), away: new THREE.Vector3() };

  constructor(host: HTMLElement, state: () => SceneState, labels: SceneLabels, callbacks: EngineCallbacks) {
    this.host = host;
    this.state = state;
    this.callbacks = callbacks;
    const initial = state();
    this.plan = initial.layout.plan;
    this.overview = new THREE.Vector3(this.plan.centerX + 19, 39 + this.plan.workPods * 0.5, 29 + this.plan.workPods * 0.7);
    this.renderer = new THREE.WebGLRenderer({ antialias: false, powerPreference: 'high-performance' });
    // From here on the scene draws with the shared caches; `dispose()` gives the hold back.
    retainCaches();
    const gl = this.renderer.getContext();
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    this.software = !!debug && /swiftshader|llvmpipe|software/i.test(String(gl.getParameter(debug.UNMASKED_RENDERER_WEBGL)));
    this.renderer.setPixelRatio(this.software ? (this.plan.large ? 0.55 : 0.7) : Math.min(window.devicePixelRatio, 1.5));
    this.renderer.shadowMap.enabled = !this.software;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    const canvas = this.renderer.domElement;
    canvas.setAttribute('aria-label', labels.canvas);
    canvas.setAttribute('role', 'img');
    canvas.style.display = 'block';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.touchAction = 'none';
    host.prepend(canvas);

    const look = initial.theme === 'dark' ? NIGHT : DAY;
    this.scene.background = new THREE.Color(look.background);
    this.scene.fog = new THREE.Fog(look.background, 55, 110);
    this.camera.position.copy(this.overview);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.set(this.plan.centerX, 0.5, 0);
    this.controls.enableDamping = !this.reduced && !this.software;
    this.controls.dampingFactor = 0.075;
    this.controls.minPolarAngle = 0.32;
    this.controls.maxPolarAngle = 1.28;
    this.controls.minZoom = 0.6;
    this.controls.maxZoom = 2.8;
    this.controls.enablePan = false;
    this.controls.update();
    this.hemi = new THREE.HemisphereLight(look.sky, look.skyGround, look.hemi);
    this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight(look.sun, look.sunPower);
    this.sun.position.set(-15, 24, 17);
    this.sun.castShadow = !this.software;
    this.sun.shadow.mapSize.set(2048, 2048);
    Object.assign(this.sun.shadow.camera, { left: -this.plan.floorWidth * 0.65, right: this.plan.floorWidth * 0.65, top: 24, bottom: -22, near: 0.5, far: 120 });
    this.sun.shadow.normalBias = 0.025;
    this.scene.add(this.sun);
    this.ground = box(this.scene, [200, 0.08, 200], [0, -0.42, 0], new THREE.MeshStandardMaterial({ color: look.ground, emissive: look.groundEmissive, emissiveIntensity: look.groundGlow }), 0);
    this.ground.receiveShadow = true;
    this.office = buildCompany(this.scene, this.plan, labels);
    optimizeOffice(this.office.root, [this.office.hologram, this.office.patronTarget]);
    this.applyLook(1);
    this.syncAgents(true);
    if (this.software) {
      const converted = toLightweightMaterials(this.scene, new Set([this.office.windowMaterial, this.office.lampMaterial]));
      const groundMaterial = converted.get(this.ground.material as THREE.Material);
      if (groundMaterial) this.ground.material = groundMaterial;
    }
    this.observer = new ResizeObserver(this.resize);
    this.observer.observe(host);
    this.resize();
    canvas.addEventListener('pointerdown', this.onPointerDown);
    canvas.addEventListener('pointerup', this.onPointerUp);
    canvas.addEventListener('pointermove', this.onPointerMove);
    canvas.addEventListener('pointerleave', this.onPointerLeave);
    canvas.addEventListener('contextmenu', this.preventContextMenu);
    this.motionQuery.addEventListener('change', this.onMotionChange);
    this.renderer.render(this.scene, this.camera);
    this.frame = requestAnimationFrame(this.animate);
  }

  // ─── Camera controls (every button on the page drives one of these) ───

  zoom(direction: number) {
    this.camera.zoom = THREE.MathUtils.clamp(this.camera.zoom + direction * 0.14, 0.6, 2.8);
    this.camera.updateProjectionMatrix();
  }

  rotate() {
    const offset = this.camera.position.clone().sub(this.controls.target).applyAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4);
    this.camera.position.copy(this.controls.target).add(offset);
    this.controls.update();
  }

  focusZone(zone: AgentZone) {
    const plan = this.plan;
    let x = 0;
    let z = 0;
    let zoom = 2.05;
    if (zone === 'setup') [x, z] = [plan.setupX, -8];
    if (zone === 'lounge') [x, z] = [plan.loungeX, 0];
    if (zone === 'clinic') [x, z] = [plan.clinicX, plan.clinicZ];
    if (zone === 'patron') [x, z] = [plan.patronX, plan.patronZ];
    if (zone === 'work') {
      x = (Math.min(...plan.workCenters) + Math.max(...plan.workCenters)) / 2;
      z = (Math.min(...plan.workRows) + Math.max(...plan.workRows)) / 2;
      zoom = plan.large ? 1.05 : 1.7;
    }
    this.lookAt(x, z, zoom, [10, 21, 14]);
  }

  focusWorkPod(index: number) {
    const safe = THREE.MathUtils.clamp(index, 0, this.plan.workCenters.length - 1);
    this.lookAt(this.plan.workCenters[safe], this.plan.workRows[safe], 2.15, [9, 19, 13]);
  }

  focusAgent(id: string) {
    const placement = this.state().layout.placements.get(id);
    if (placement) this.lookAt(placement.x, placement.z, 2.4, [9, 19, 13]);
  }

  reset() {
    this.camera.position.copy(this.overview);
    this.camera.zoom = 1;
    this.camera.updateProjectionMatrix();
    this.controls.target.set(this.plan.centerX, 0.5, 0);
    this.controls.update();
  }

  private lookAt(x: number, z: number, zoom: number, offset: [number, number, number]) {
    this.camera.position.set(x + offset[0], offset[1], z + offset[2]);
    this.camera.zoom = zoom;
    this.camera.updateProjectionMatrix();
    this.controls.target.set(x, 0.4, z);
    this.controls.update();
  }

  // ─── Agents ───

  private syncAgents(force = false) {
    const state = this.state();
    // The page hands over a new state object only when something in it changed.
    if (!force && state === this.lastState) return;
    this.lastState = state;
    const { agents, layout, selectedId, theme } = state;
    const signature = JSON.stringify([agents.map((agent) => [agent.id, agent.name, agent.status, agent.runtimeLabel, layout.placements.get(agent.id)]), selectedId, theme]);
    if (!force && signature === this.signature) return;
    this.signature = signature;
    const present = new Set(agents.map((agent) => agent.id));
    for (const [id, rig] of this.rigs) {
      if (present.has(id)) continue;
      this.disposeRig(rig, this.labels.get(id));
      rig.root.removeFromParent();
      this.rigs.delete(id);
      this.labels.delete(id);
    }
    for (const agent of agents) {
      const placement = layout.placements.get(agent.id);
      if (!placement) continue;
      let rig = this.rigs.get(agent.id);
      if (!rig) {
        rig = createCharacter(appearanceOf(agent.id));
        rig.root.position.set(placement.x, placement.y, placement.z);
        rig.root.rotation.y = placement.rotation;
        rig.root.userData.agentId = agent.id;
        const label = labelSprite(agent, theme);
        rig.root.add(label);
        this.labels.set(agent.id, label);
        (rig.ring.material as THREE.MeshStandardMaterial).color.set(accentOf(agent.id));
        if (this.software) toLightweightMaterials(rig.root, new Set());
        this.scene.add(rig.root);
        this.rigs.set(agent.id, rig);
      }
      const label = this.labels.get(agent.id);
      if (label && label.userData.paintKey !== `${theme}:${agent.status}:${agent.name}:${agent.runtimeLabel}`) paintLabel(label, agent, theme);
      rig.ring.visible = selectedId === agent.id;
      rig.routineDial.visible = placement.pose !== 'lying' && (this.plan.large ? selectedId === agent.id : placement.zone === 'work' || selectedId === agent.id);
    }
  }

  private seed(id: string) {
    return hash(id) % 97;
  }

  /** Where a figure wants to be this frame, inside its assigned resource (DESIGN §6.3). */
  private desired(placement: Placement, id: string, target: THREE.Vector3, presenterId: string | undefined): Motion {
    target.set(placement.x, placement.y, placement.z);
    const still: Motion = { moving: false, typing: false, pose: placement.pose };
    if (this.reduced) return { ...still, typing: placement.zone === 'work' && placement.pose === 'sitting' };
    const seed = this.seed(id);
    if (placement.zone === 'lounge' && placement.pose === 'standing') {
      const angle = this.elapsed * 0.18 + seed;
      target.x += Math.cos(angle) * 0.28;
      target.z += Math.sin(angle) * 0.24;
      return { moving: true, typing: false, pose: 'standing' };
    }
    if (placement.zone === 'work') {
      // 24-second routine: type, stand, push back, walk to the break spot, pause, return, sit.
      const cycle = (this.elapsed + seed * 0.31) % 24;
      const away = this.scratch.away.set(placement.x + 0.85, 0.02, placement.z + 1.35);
      if (cycle < 12) return { moving: false, typing: true, pose: 'sitting' };
      if (cycle < 13) return { moving: false, typing: false, pose: 'standing' };
      if (cycle < 16) {
        target.lerp(away, THREE.MathUtils.smoothstep(cycle, 13, 16));
        target.y = 0.02;
        return { moving: true, typing: false, pose: 'standing' };
      }
      if (cycle < 18) {
        target.copy(away);
        return { moving: false, typing: false, pose: 'standing' };
      }
      if (cycle < 21) {
        const progress = THREE.MathUtils.smoothstep(cycle, 18, 21);
        target.set(away.x + (placement.x - away.x) * progress, 0.02, away.z + (placement.z - away.z) * progress);
        return { moving: true, typing: false, pose: 'standing' };
      }
      return { moving: false, typing: false, pose: cycle > 22.5 ? 'sitting' : 'standing' };
    }
    if (placement.zone === 'patron' && id === presenterId) {
      const cycle = (this.elapsed + seed * 0.2) % 16;
      target.z += THREE.MathUtils.smoothstep(cycle, 3, 6) * 0.38 - THREE.MathUtils.smoothstep(cycle, 11, 14) * 0.38;
      return { moving: (cycle > 3 && cycle < 6) || (cycle > 11 && cycle < 14), typing: false, pose: 'standing' };
    }
    return still;
  }

  // ─── Theme ───

  /** Ease lights and materials toward the current theme's look; `blend` 1 snaps. */
  private applyLook(blend: number) {
    const look = this.state().theme === 'dark' ? NIGHT : DAY;
    const color = this.scratch.color;
    const lerp = THREE.MathUtils.lerp;
    (this.scene.background as THREE.Color).lerp(color.set(look.background), blend);
    (this.scene.fog as THREE.Fog).color.lerp(color, blend);
    const groundMaterial = this.ground.material as THREE.MeshStandardMaterial;
    groundMaterial.color.lerp(color.set(look.ground), blend);
    groundMaterial.emissive.lerp(color.set(look.groundEmissive), blend);
    groundMaterial.emissiveIntensity = lerp(groundMaterial.emissiveIntensity, look.groundGlow, blend);
    this.sun.intensity = lerp(this.sun.intensity, look.sunPower, blend);
    this.sun.color.lerp(color.set(look.sun), blend);
    this.hemi.intensity = lerp(this.hemi.intensity, look.hemi, blend);
    this.hemi.color.lerp(color.set(look.sky), blend);
    this.hemi.groundColor.lerp(color.set(look.skyGround), blend);
    const office = this.office;
    office.windowMaterial.color.lerp(color.set(look.window), blend);
    office.windowMaterial.emissive.lerp(color.set(look.windowGlow), blend);
    office.windowMaterial.emissiveIntensity = lerp(office.windowMaterial.emissiveIntensity, look.windowPower, blend);
    office.starsMaterial.opacity = lerp(office.starsMaterial.opacity, look.stars, blend);
    office.lampMaterial.emissiveIntensity = lerp(office.lampMaterial.emissiveIntensity, look.lamp, blend);
    office.lights.forEach((light) => {
      light.intensity = lerp(light.intensity, look.light, blend);
      light.visible = light.intensity > 0.01;
    });
    this.renderer.toneMappingExposure = lerp(this.renderer.toneMappingExposure, look.exposure, blend);
  }

  // ─── Loop ───

  private animate = (time: number) => {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(this.animate);
    const delta = Math.min((time - (this.previous || time)) / 1000, 0.05);
    this.previous = time;
    this.elapsed += delta;
    this.syncAgents();
    const { layout, selectedId } = this.state();
    const presenterId = [...layout.placements.entries()].find(([, placement]) => placement.assignment.kind === 'presenting')?.[0];
    const blend = this.reduced ? 1 : Math.min(delta * 4.2, 1);
    const lerp = THREE.MathUtils.lerp;
    const desired = this.scratch.desired;
    this.rigs.forEach((rig, id) => {
      const placement = layout.placements.get(id);
      if (!placement) return;
      const motion = this.desired(placement, id, desired, presenterId);
      const dx = desired.x - rig.root.position.x;
      const dz = desired.z - rig.root.position.z;
      rig.root.position.lerp(desired, blend);
      const facing = motion.moving && Math.hypot(dx, dz) > 0.015 ? Math.atan2(dx, dz) : placement.rotation;
      rig.root.rotation.y = lerp(rig.root.rotation.y, facing, blend);
      const phase = this.elapsed * 8 + this.seed(id);
      const swing = !this.reduced && motion.moving ? Math.sin(phase) * 0.48 : 0;
      const sitting = motion.pose === 'sitting';
      const lying = motion.pose === 'lying';
      rig.leftLeg.rotation.x = lerp(rig.leftLeg.rotation.x, lying ? 0 : sitting ? -1.22 : swing, blend);
      rig.rightLeg.rotation.x = lerp(rig.rightLeg.rotation.x, lying ? 0 : sitting ? -1.22 : -swing, blend);
      const typingLeft = this.reduced ? -0.7 : -0.68 + Math.cos(this.elapsed * 6.4) * 0.1;
      const typingRight = this.reduced ? -0.72 : -0.72 + Math.sin(this.elapsed * 7) * 0.12;
      rig.leftArm.rotation.x = lerp(rig.leftArm.rotation.x, motion.typing ? typingLeft : lying ? 0.18 : -swing * 0.65, blend);
      rig.rightArm.rotation.x = lerp(rig.rightArm.rotation.x, motion.typing ? typingRight : lying ? -0.18 : swing * 0.65, blend);
      rig.body.position.y = this.reduced || lying || sitting ? 0 : Math.sin(phase) * (motion.moving ? 0.025 : 0.008);
      rig.body.rotation.x = lerp(rig.body.rotation.x, lying ? -Math.PI / 2 : 0, blend);
      const label = this.labels.get(id);
      if (label) {
        label.position.y = lying ? 0.62 : 1.93;
        // A crowded floor only names the agent in focus (DESIGN §7).
        label.visible = !this.plan.large || selectedId === id || this.hoveredId === id;
      }
      if (!this.reduced) {
        rig.routineDial.rotation.y += delta * 0.65;
        rig.routineDial.position.y = 1.73 + Math.sin(this.elapsed * 2) * 0.04;
      }
    });
    this.applyLook(this.reduced ? 1 : Math.min(delta * 3.5, 1));
    if (!this.reduced) {
      this.office.hologram.rotation.y += delta * 0.24;
      this.office.hologram.position.y = 1.05 + Math.sin(this.elapsed * 1.2) * 0.04;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

  private onMotionChange = (event: MediaQueryListEvent) => {
    this.reduced = event.matches;
    this.controls.enableDamping = !this.reduced && !this.software;
  };

  private resize = () => {
    const width = this.host.clientWidth;
    const height = this.host.clientHeight;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    const aspect = width / height;
    const viewHeight = Math.max(25, (this.plan.floorWidth + 7) / aspect, this.plan.floorWidth * 0.36 + this.plan.floorDepth * 0.58 + 7);
    this.camera.left = (-viewHeight * aspect) / 2;
    this.camera.right = (viewHeight * aspect) / 2;
    this.camera.top = viewHeight / 2;
    this.camera.bottom = -viewHeight / 2;
    this.camera.updateProjectionMatrix();
  };

  // ─── Pointer ───

  private preventContextMenu = (event: Event) => event.preventDefault();
  private onPointerDown = (event: PointerEvent) => {
    this.pointerStart = [event.clientX, event.clientY];
  };
  private onPointerMove = (event: PointerEvent) => {
    const hit = this.pick(event);
    this.renderer.domElement.style.cursor = hit ? 'pointer' : 'grab';
    if (hit?.type !== 'agent') {
      if (this.hoveredId) {
        this.hoveredId = null;
        this.callbacks.onHover(null);
      }
      return;
    }
    const rect = this.host.getBoundingClientRect();
    this.hoveredId = hit.id;
    this.callbacks.onHover({
      id: hit.id,
      x: THREE.MathUtils.clamp(event.clientX - rect.left, 125, Math.max(125, rect.width - 125)),
      y: THREE.MathUtils.clamp(event.clientY - rect.top - 14, 150, Math.max(150, rect.height - 20)),
    });
  };
  private onPointerLeave = () => {
    this.hoveredId = null;
    this.callbacks.onHover(null);
  };
  private onPointerUp = (event: PointerEvent) => {
    // A drag is the orbit control's; only a still press counts as a click.
    if (Math.hypot(event.clientX - this.pointerStart[0], event.clientY - this.pointerStart[1]) > 7) return;
    const hit = this.pick(event);
    if (hit?.type === 'agent') {
      this.hoveredId = null;
      this.callbacks.onHover(null);
      this.callbacks.onSelect(hit.id);
    }
    if (hit?.type === 'patron') this.callbacks.onOpenPatron();
  };
  private pick(event: PointerEvent): { type: 'agent'; id: string } | { type: 'patron' } | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects([...this.rigs.values()].map((rig) => rig.root), true);
    for (const hit of hits) {
      for (let object: THREE.Object3D | null = hit.object; object; object = object.parent) {
        if (object.userData.agentId) return { type: 'agent', id: object.userData.agentId as string };
      }
    }
    return this.raycaster.intersectObject(this.office.patronTarget, false).length ? { type: 'patron' } : null;
  }

  // ─── Teardown ───

  /** Free what one departing figure owns; shared primitives stay for the figures still here. */
  private disposeRig(rig: CharacterRig, label: THREE.Sprite | undefined) {
    if (label) {
      label.material.map?.dispose();
      label.material.dispose();
    }
    (rig.ring.material as THREE.Material).dispose();
    rig.head.children.forEach((child) => {
      if (child instanceof THREE.Mesh) child.geometry.dispose();
    });
  }

  private disposeObject(root: THREE.Object3D) {
    root.traverse((object) => {
      if (object instanceof THREE.Mesh || object instanceof THREE.Points || object instanceof THREE.Sprite) {
        object.geometry?.dispose();
        const materials: THREE.Material[] = Array.isArray(object.material) ? object.material : [object.material];
        materials.forEach((item) => {
          (item as THREE.Material & { map?: THREE.Texture | null }).map?.dispose();
          item.dispose();
        });
      }
    });
  }

  dispose() {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    this.controls.dispose();
    const canvas = this.renderer.domElement;
    canvas.removeEventListener('pointerdown', this.onPointerDown);
    canvas.removeEventListener('pointerup', this.onPointerUp);
    canvas.removeEventListener('pointermove', this.onPointerMove);
    canvas.removeEventListener('pointerleave', this.onPointerLeave);
    canvas.removeEventListener('contextmenu', this.preventContextMenu);
    this.motionQuery.removeEventListener('change', this.onMotionChange);
    this.disposeObject(this.scene);
    releaseCaches();
    this.rigs.clear();
    this.labels.clear();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    canvas.remove();
  }
}
