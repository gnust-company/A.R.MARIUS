import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { createCharacter, type Appearance, type CharacterRig } from '@/scene/character';
import { box, cylinder, releaseCaches, retainCaches } from '@/scene/primitives';
import { LoungeLife, type IdleAgent } from './loungeLife';
import { SCENE_FONT, buildCompany, canvas2d, type SceneLabels } from './officeBuilding';
import { reportSpot, walkTo, wayOut, type Activity, type AgentZone, type OfficeLayout, type OfficePlan, type Placement, type Point, type Spot, type Step } from './officePlan';

export type { SceneLabels } from './officeBuilding';

/*
 * The one-floor office diorama of the observatory (DESIGN §5, §7, §10). The building itself
 * is built in `officeBuilding.ts`; this file runs it: camera, figures, motion, pointer.
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
  /** What this agent is on the team (leader, workspace assistant…), shown beside its name. */
  role?: string;
  /** The codes of the tasks it is holding, for the plate on its desk. */
  holding?: string;
  /** Ids of its tasks that are waiting for the patron: a new one sends it up with the report. */
  reviewing?: string[];
}

export interface SceneState {
  agents: SceneAgent[];
  layout: OfficeLayout;
  theme: 'light' | 'dark';
  selectedId: string | null;
  /** What floats above each zone at a distance: its name and how full it is. */
  captions: Record<AgentZone, string>;
  /** How many letters are waiting for the patron: the number on the notice board. */
  inboxPending: number;
}

/** Pixels of the canvas the page covers with its own controls; the floor is framed inside. */
export interface SceneInsets {
  top: number;
  bottom: number;
}

export type HoverState = { id: string; x: number; y: number } | null;

interface EngineCallbacks {
  onSelect: (id: string) => void;
  onOpenPatron: () => void;
  onHover: (hover: HoverState) => void;
  /** The person moved the view themselves: whatever the page had focused is no longer in frame. */
  onRoam: () => void;
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

/*
 * Tags and captions are drawn at a fixed size on screen, whatever the zoom: a name that
 * shrinks with the floor is a name nobody can read from the overview, which is the one view
 * where it matters. Their canvases keep one size (a texture cannot change its size once it is
 * on the GPU); the plate is drawn centred and `span` remembers how much of the width it takes.
 */
const TAG = { width: 512, height: 72, screen: 26 };
const CAPTION = { width: 640, height: 72, screen: 28 };

function tagKey(agent: SceneAgent, theme: string): string {
  return `${theme}:${agent.status}:${agent.name}:${agent.role ?? ''}`;
}

function paintLabel(sprite: THREE.Sprite, agent: SceneAgent, theme: string) {
  const mat = sprite.material as THREE.SpriteMaterial;
  const canvas = mat.map!.image as HTMLCanvasElement;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const nameFont = `700 37px ${SCENE_FONT}`;
  const roleFont = `500 27px ${SCENE_FONT}`;
  const room = TAG.width - 96;
  // The role rides beside the name, quieter: who this is on the team matters as much as where it sits.
  ctx.font = roleFont;
  const role = agent.role ?? '';
  const roleWidth = role ? Math.min(ctx.measureText(role).width, room * 0.5) : 0;
  const gap = role ? 20 : 0;
  ctx.font = nameFont;
  const nameWidth = Math.min(ctx.measureText(agent.name).width, room - roleWidth - gap);
  const plate = nameWidth + gap + roleWidth + 84;
  const left = (TAG.width - plate) / 2;
  ctx.fillStyle = token('surface', 0.95);
  ctx.beginPath();
  ctx.roundRect(left, 6, plate, 60, 30);
  ctx.fill();
  ctx.strokeStyle = token('line', 0.9);
  ctx.lineWidth = 2;
  ctx.stroke();
  ctx.fillStyle = token(STATUS_TOKEN[agent.status] ?? 'faint');
  ctx.beginPath();
  ctx.arc(left + 30, 36, 10, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = token('ink-strong');
  ctx.textBaseline = 'middle';
  ctx.fillText(agent.name, left + 52, 38, nameWidth);
  if (role) {
    ctx.font = roleFont;
    ctx.fillStyle = token('ink-light');
    ctx.fillText(role, left + 52 + nameWidth + gap, 39, roleWidth);
  }
  mat.map!.needsUpdate = true;
  sprite.userData.span = plate / TAG.width;
  sprite.userData.paintKey = tagKey(agent, theme);
}

/** The plate on a desk: whose it is, and the task they have on it. */
function paintPlate(plate: THREE.Mesh, name: string, holding: string) {
  const material = plate.material as THREE.MeshBasicMaterial;
  const canvas = material.map!.image as HTMLCanvasElement;
  const ctx = canvas.getContext('2d')!;
  ctx.fillStyle = name ? '#f3ecd9' : '#cfc8b6';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.textBaseline = 'middle';
  ctx.fillStyle = '#2a323c';
  ctx.font = `700 40px ${SCENE_FONT}`;
  ctx.fillText(name, 16, holding ? 30 : 50, canvas.width - 32);
  if (holding) {
    ctx.fillStyle = '#8a5a12';
    ctx.font = '600 30px ui-monospace, monospace';
    ctx.fillText(holding, 16, 72, canvas.width - 32);
  }
  material.map!.needsUpdate = true;
  plate.userData.paintKey = `${name}:${holding}`;
}

/** The notice board: how many letters wait for the patron, as a number and as envelopes. */
function paintBoard(board: THREE.Mesh, count: number, [heading, line]: [string, string]) {
  const material = board.material as THREE.MeshBasicMaterial;
  const canvas = material.map!.image as HTMLCanvasElement;
  const ctx = canvas.getContext('2d')!;
  const waiting = count > 0;
  ctx.fillStyle = '#16212c';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.textBaseline = 'alphabetic';
  ctx.fillStyle = '#9fb0c4';
  ctx.font = `600 34px ${SCENE_FONT}`;
  ctx.fillText(heading.toUpperCase(), 36, 64, 568);
  ctx.fillStyle = waiting ? '#f0c869' : '#5d6c7d';
  ctx.font = `700 170px ${SCENE_FONT}`;
  ctx.fillText(String(count), 36, 238, 260);
  ctx.fillStyle = waiting ? '#f3efe5' : '#8494a6';
  ctx.font = `500 34px ${SCENE_FONT}`;
  ctx.fillText(line, 36, 312, 568);
  // Up to six envelopes; the rest is the number's job.
  const shown = Math.max(1, Math.min(6, count));
  for (let index = 0; index < shown; index++) {
    const x = 330 + (index % 3) * 96;
    const y = 104 + Math.floor(index / 3) * 78;
    ctx.fillStyle = waiting ? '#f0c869' : '#33424f';
    ctx.beginPath();
    ctx.roundRect(x, y, 80, 58, 8);
    ctx.fill();
    ctx.strokeStyle = '#16212c';
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(x + 5, y + 7);
    ctx.lineTo(x + 40, y + 34);
    ctx.lineTo(x + 75, y + 7);
    ctx.stroke();
  }
  material.map!.needsUpdate = true;
  board.userData.paintKey = `${count}:${heading}:${line}`;
}

function labelSprite(agent: SceneAgent, theme: string): THREE.Sprite {
  const [canvas] = canvas2d(TAG.width, TAG.height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  // UI text: the theme's exact colours, untouched by the scene's tone mapping and fog.
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false, toneMapped: false, fog: false }));
  sprite.renderOrder = 4;
  sprite.userData.agentId = agent.id;
  paintLabel(sprite, agent, theme);
  return sprite;
}

function paintCaption(sprite: THREE.Sprite, text: string, theme: string) {
  const mat = sprite.material as THREE.SpriteMaterial;
  const canvas = mat.map!.image as HTMLCanvasElement;
  const ctx = canvas.getContext('2d')!;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.font = `700 35px ${SCENE_FONT}`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  // No plate: a halo in the page's own ground colour keeps the words readable over any floor.
  ctx.lineJoin = 'round';
  ctx.lineWidth = 7;
  ctx.strokeStyle = token('canvas-deep', 0.92);
  ctx.strokeText(text, CAPTION.width / 2, 38, CAPTION.width - 24);
  ctx.fillStyle = token('ink-strong');
  ctx.fillText(text, CAPTION.width / 2, 38, CAPTION.width - 24);
  mat.map!.needsUpdate = true;
  sprite.userData.span = Math.min(ctx.measureText(text).width + 14, CAPTION.width) / CAPTION.width;
  sprite.userData.paintKey = `${theme}:${text}`;
}

function captionSprite(): THREE.Sprite {
  const [canvas] = canvas2d(CAPTION.width, CAPTION.height);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthTest: false, toneMapped: false, fog: false }));
  sprite.renderOrder = 3;
  return sprite;
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

/** A figure's walk across the floor, and what it carries. */
interface Walker {
  /** The spot it is at or heading for; a new key is a new walk. */
  key: string;
  steps: Step[];
  /** The way from where it is out onto the walkways: back out of its spot, or the rest of its current step. */
  out: Point[];
  settled: boolean;
  zone: AgentZone;
  /** It reached the lounge from another zone, or from the patron's desk, while the scene was open. */
  cameOffWork: boolean;
  /** Seconds it has stood at the patron's desk with a report. */
  handover: number;
  cup: THREE.Mesh;
  paper: THREE.Mesh;
  paddle: THREE.Mesh;
}

/*
 * Where the overview looks from: nearly straight on from the front and well above, like the
 * open side of a model. The floor is wide and shallow, the gallery is at the back, and seen
 * this way the three bands — patron above, desks in the middle, lounge in front — read at a
 * glance and fill a wide screen; the old corner-on view drew a diamond with four empty corners.
 */
const OVERVIEW_TURN = 0.21;
const OVERVIEW_TILT = 0.7;
const OVERVIEW = new THREE.Vector3(Math.sin(OVERVIEW_TURN) * Math.cos(OVERVIEW_TILT), Math.sin(OVERVIEW_TILT), Math.cos(OVERVIEW_TURN) * Math.cos(OVERVIEW_TILT)).multiplyScalar(52);

/** Floor units a figure covers in a second: at a walk, and hurrying up to the patron with a report. */
const WALK_SPEED = 2;
const RUN_SPEED = 3.8;
/** How long handing a report over takes, and when in it the paper changes hands. */
const HANDOVER_SECONDS = 2.6;
const HANDOVER_GIVEN = 1.4;

/** Turn an angle toward another by the short way round. */
function turnToward(from: number, to: number, blend: number): number {
  return from + Math.atan2(Math.sin(to - from), Math.cos(to - from)) * blend;
}

const MIN_ZOOM = 0.8;
const MAX_ZOOM = 3.2;
/** One press of a zoom button, or of + and -. */
const ZOOM_STEP = 1.35;
const FLIGHT_SECONDS = 0.55;
/** How far a press may wander, in pixels, and still be a click rather than a drag. */
const CLICK_SLOP = 6;
/** Below this canvas width the zone bar alone names the zones: captions would run off the edge. */
const CAPTION_MIN_WIDTH = 720;

export class OfficeEngine {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.OrthographicCamera(-8, 8, 8, -8, 0.1, 160);
  private controls: OrbitControls;
  private observer: ResizeObserver;
  private office: ReturnType<typeof buildCompany>;
  private ground: THREE.Mesh;
  private rigs = new Map<string, CharacterRig>();
  private walkers = new Map<string, Walker>();
  private life: LoungeLife;
  /** Which desks have someone typing at them this frame. */
  private lit: boolean[] = [];
  /** Seconds left of the notice board calling for attention after a new letter. */
  private boardPulse = 0;
  private boardCount = -1;
  /** Agents on their way to the patron with a report, or waiting their turn, in order. */
  private errands: string[] = [];
  /** The tasks each agent is known to have handed in, so a new one can be told from an old one. */
  private handed = new Map<string, Set<string>>();
  private labelsOnSigns: SceneLabels;
  private labels = new Map<string, THREE.Sprite>();
  private captions = new Map<AgentZone, THREE.Sprite>();
  /** The floor's own level, where a drag takes hold of it. */
  private floor = new THREE.Plane(new THREE.Vector3(0, 1, 0), -0.5);
  private pointers = new Set<number>();
  /** A drag across the floor: the point of the floor the pointer took hold of. */
  private pan: { pointer: number; grab: THREE.Vector3; moved: boolean } | null = null;
  /** A camera move in progress, eased rather than jumped so the eye can follow where it went. */
  private flight: { fromPosition: THREE.Vector3; toPosition: THREE.Vector3; fromTarget: THREE.Vector3; toTarget: THREE.Vector3; fromZoom: number; toZoom: number; progress: number } | null = null;
  private insets: SceneInsets;
  private roomForCaptions = true;
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
  private scratch = { color: new THREE.Color(), desired: new THREE.Vector3(), away: new THREE.Vector3(), ground: new THREE.Vector3(), shift: new THREE.Vector3() };

  constructor(host: HTMLElement, state: () => SceneState, labels: SceneLabels, callbacks: EngineCallbacks, insets: SceneInsets = { top: 0, bottom: 0 }) {
    this.host = host;
    this.insets = insets;
    this.state = state;
    this.callbacks = callbacks;
    const initial = state();
    this.plan = initial.layout.plan;
    this.overview = new THREE.Vector3(this.plan.centerX + OVERVIEW.x, OVERVIEW.y, OVERVIEW.z);
    this.life = new LoungeLife(this.plan.loungeSpots);
    this.labelsOnSigns = labels;
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
    canvas.style.cursor = 'grab';
    // Reachable by keyboard: the arrows move across the floor (see onKeyDown).
    canvas.tabIndex = 0;
    canvas.className = 'outline-none focus-visible:outline focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-gold';
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
    this.controls.minZoom = MIN_ZOOM;
    this.controls.maxZoom = MAX_ZOOM;
    /*
     * This is a floor plan, so it moves like a map: a plain drag slides the floor, the wheel
     * zooms toward the pointer, and turning the view is the deliberate gesture (right button,
     * or a drag with Shift/Ctrl held; two fingers on a touch screen).
     *
     * The slide itself is ours (onPointerMove), not the orbit control's: its pan moves the
     * target by screen distance, so on a tilted floor the point under the pointer drifts away
     * from it. With its pan switched off, the PAN binding below still gives the orbit control
     * the modified drag as a rotate and leaves the plain one alone.
     */
    this.controls.enablePan = false;
    this.controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.ROTATE };
    this.controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_ROTATE };
    this.controls.zoomToCursor = true;
    this.controls.addEventListener('start', this.onRoam);
    this.controls.update();
    this.hemi = new THREE.HemisphereLight(look.sky, look.skyGround, look.hemi);
    this.scene.add(this.hemi);
    this.sun = new THREE.DirectionalLight(look.sun, look.sunPower);
    this.sun.position.set(-15, 24, 17);
    this.sun.castShadow = !this.software;
    this.sun.shadow.mapSize.set(2048, 2048);
    Object.assign(this.sun.shadow.camera, { left: -this.plan.floorWidth * 0.65, right: this.plan.floorWidth * 0.65, top: Math.max(24, this.plan.floorDepth * 0.85), bottom: -Math.max(22, this.plan.floorDepth * 0.8), near: 0.5, far: 140 });
    this.sun.shadow.normalBias = 0.025;
    this.scene.add(this.sun);
    this.ground = box(this.scene, [200, 0.08, 200], [0, -0.42, 0], new THREE.MeshStandardMaterial({ color: look.ground, emissive: look.groundEmissive, emissiveIntensity: look.groundGlow }), 0);
    this.ground.receiveShadow = true;
    this.office = buildCompany(this.scene, this.plan, labels);
    // Each zone is named just outside the wall it shares with the outside of the building,
    // where no agent ever stands: a caption over the room itself lands on its name tags.
    const west = this.plan.centerX - this.plan.floorWidth / 2 - 0.7;
    const east = this.plan.centerX + this.plan.floorWidth / 2 + 0.7;
    const zoneSpots: Record<AgentZone, [x: number, y: number, z: number, outward: number]> = {
      setup: [west, 0.6, this.plan.reception.z, -1],
      lounge: [east, 0.6, this.plan.lounge.z, 1],
      clinic: [west, 0.6, this.plan.clinic.z, -1],
      work: [east, 0.6, this.plan.work.z, 1],
      patron: [east, 0.6, this.plan.patron.z, 1],
    };
    (Object.keys(zoneSpots) as AgentZone[]).forEach((zone) => {
      const [x, y, z, outward] = zoneSpots[zone];
      const caption = captionSprite();
      caption.position.set(x, y, z);
      caption.userData.outward = outward;
      this.scene.add(caption);
      this.captions.set(zone, caption);
    });
    optimizeOffice(this.office.root, [this.office.hologram, this.office.patronTarget, this.office.live]);
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
    canvas.addEventListener('pointercancel', this.onPointerCancel);
    canvas.addEventListener('pointermove', this.onPointerMove);
    canvas.addEventListener('pointerleave', this.onPointerLeave);
    canvas.addEventListener('dblclick', this.onDoubleClick);
    canvas.addEventListener('keydown', this.onKeyDown);
    canvas.addEventListener('wheel', this.onRoam, { passive: true });
    canvas.addEventListener('contextmenu', this.preventContextMenu);
    this.motionQuery.addEventListener('change', this.onMotionChange);
    this.renderer.render(this.scene, this.camera);
    this.frame = requestAnimationFrame(this.animate);
  }

  // ─── Camera controls (every button on the page drives one of these) ───

  zoom(direction: number) {
    const zoom = THREE.MathUtils.clamp(this.camera.zoom * (direction > 0 ? ZOOM_STEP : 1 / ZOOM_STEP), MIN_ZOOM, MAX_ZOOM);
    this.flyTo(this.camera.position, this.controls.target, zoom);
  }

  rotate() {
    const offset = this.camera.position.clone().sub(this.controls.target).applyAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 4);
    this.flyTo(offset.add(this.controls.target), this.controls.target, this.camera.zoom);
  }

  focusZone(zone: AgentZone) {
    const plan = this.plan;
    const room = { setup: plan.reception, lounge: plan.lounge, clinic: plan.clinic, work: plan.work, patron: plan.patron }[zone];
    // Close enough to read the room, never closer than the room is wide.
    const zoom = THREE.MathUtils.clamp(15 / Math.max(room.width, room.depth * 1.4), 1.15, 2.2);
    this.lookAt(room.x, room.z, zoom);
  }

  focusAgent(id: string) {
    const rig = this.rigs.get(id);
    if (rig) this.lookAt(rig.root.position.x, rig.root.position.z, 2.4);
  }

  reset() {
    this.flyTo(this.overview, new THREE.Vector3(this.plan.centerX, 0.5, 0), 1);
  }

  /** Centre a spot of the floor, from the direction the person is already looking from. */
  private lookAt(x: number, z: number, zoom: number) {
    const target = new THREE.Vector3(x, 0.5, z);
    const position = this.camera.position.clone().sub(this.controls.target).add(target);
    this.flyTo(position, target, zoom);
  }

  private flyTo(position: THREE.Vector3, target: THREE.Vector3, zoom: number) {
    if (this.reduced) {
      this.flight = null;
      this.camera.position.copy(position);
      this.controls.target.copy(target);
      this.camera.zoom = zoom;
      this.camera.updateProjectionMatrix();
      this.controls.update();
      return;
    }
    this.flight = {
      fromPosition: this.camera.position.clone(),
      toPosition: position.clone(),
      fromTarget: this.controls.target.clone(),
      toTarget: target.clone(),
      fromZoom: this.camera.zoom,
      toZoom: zoom,
      progress: 0,
    };
  }

  /** Keep the floor in frame: the view's centre never leaves the building. */
  private keepInside() {
    const target = this.controls.target;
    const halfWidth = this.plan.floorWidth / 2 + 1;
    const halfDepth = this.plan.floorDepth / 2 + 1;
    const x = THREE.MathUtils.clamp(target.x, this.plan.centerX - halfWidth, this.plan.centerX + halfWidth);
    const z = THREE.MathUtils.clamp(target.z, -halfDepth, halfDepth);
    if (x === target.x && z === target.z) return;
    this.camera.position.x += x - target.x;
    this.camera.position.z += z - target.z;
    target.x = x;
    target.z = z;
  }

  /** Slide the view across the floor by a vector on it. */
  private slide(shift: THREE.Vector3) {
    this.camera.position.add(shift);
    this.controls.target.add(shift);
    this.keepInside();
  }

  /** The point of the floor under a pointer position, or null when the pointer is over the sky. */
  private floorAt(clientX: number, clientY: number, out: THREE.Vector3): THREE.Vector3 | null {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.set(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.camera.updateMatrixWorld();
    this.raycaster.setFromCamera(this.pointer, this.camera);
    return this.raycaster.ray.intersectPlane(this.floor, out);
  }

  // ─── Agents ───

  private syncAgents(force = false) {
    const state = this.state();
    // The page hands over a new state object only when something in it changed.
    if (!force && state === this.lastState) return;
    this.lastState = state;
    const { agents, layout, selectedId, theme } = state;
    const signature = JSON.stringify([agents.map((agent) => [agent.id, agent.name, agent.status, agent.role, agent.holding, agent.reviewing, layout.placements.get(agent.id)]), selectedId, theme, state.captions, state.inboxPending]);
    if (!force && signature === this.signature) return;
    this.signature = signature;
    this.captions.forEach((caption, zone) => {
      const text = state.captions[zone];
      if (caption.userData.paintKey !== `${theme}:${text}`) paintCaption(caption, text, theme);
    });
    const present = new Set(agents.map((agent) => agent.id));
    for (const [id, rig] of this.rigs) {
      if (present.has(id)) continue;
      this.disposeRig(rig, this.labels.get(id));
      rig.root.removeFromParent();
      this.rigs.delete(id);
      this.labels.delete(id);
      this.walkers.delete(id);
      this.handed.delete(id);
      this.errands = this.errands.filter((other) => other !== id);
    }
    // A task that has just gone up for review sends its agent to the patron with the report.
    // Only a change seen while the scene is open counts: what was already waiting when the
    // page opened was handed in long ago.
    for (const agent of agents) {
      const now = new Set(agent.reviewing ?? []);
      const before = this.handed.get(agent.id);
      if (before && !this.reduced && !this.errands.includes(agent.id) && [...now].some((task) => !before.has(task))) this.errands.push(agent.id);
      this.handed.set(agent.id, now);
    }
    // The notice board: repainted when the count changes, and it calls out when it goes up.
    if (state.inboxPending !== this.boardCount) {
      if (this.boardCount >= 0 && state.inboxPending > this.boardCount) this.boardPulse = 4;
      this.boardCount = state.inboxPending;
      paintBoard(this.office.parts.board, state.inboxPending, this.labelsOnSigns.noticeBoard(state.inboxPending));
    }
    // Desk plates: a desk is its owner's wherever the owner happens to be.
    const owners = new Map<number, SceneAgent>();
    for (const agent of agents) {
      const desk = layout.desks.get(agent.id);
      if (desk !== undefined) owners.set(desk, agent);
    }
    this.office.parts.plates.forEach((plate, index) => {
      const owner = owners.get(index);
      const holding = owner && layout.placements.get(owner.id)?.zone === 'work' ? owner.holding ?? '' : '';
      if (plate.userData.paintKey !== `${owner?.name ?? ''}:${holding}`) paintPlate(plate, owner?.name ?? '', holding);
    });
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
        // What it may be holding: a cup at the snack bar, a page when reading or presenting,
        // a paddle at the table. Each sits in the right hand and is shown only when it applies.
        const cup = cylinder(rig.rightArm, 0.04, 0.032, 0.085, [0, -0.4, 0.07], '#f3ead7', 10);
        const paper = box(rig.rightArm, [0.21, 0.012, 0.27], [0, -0.41, 0.13], '#f4efe2', 0);
        const paddle = cylinder(rig.rightArm, 0.085, 0.085, 0.016, [0, -0.47, 0.07], '#c9483f', 14);
        paddle.rotation.x = Math.PI / 2;
        for (const prop of [cup, paper, paddle]) prop.visible = false;
        if (this.software) toLightweightMaterials(rig.root, new Set());
        this.scene.add(rig.root);
        this.rigs.set(agent.id, rig);
        // A figure found on the floor starts where it belongs; only later changes are walked.
        this.walkers.set(agent.id, { key: '', steps: [], out: wayOut(placement), settled: false, zone: placement.zone, cameOffWork: false, handover: 0, cup, paper, paddle });
      }
      const label = this.labels.get(agent.id);
      if (label && label.userData.paintKey !== tagKey(agent, theme)) paintLabel(label, agent, theme);
      rig.ring.visible = selectedId === agent.id;
    }
  }

  private seed(id: string) {
    return hash(id) % 97;
  }

  /** The spot a figure is at or heading for: its seat, or wherever the lounge has it right now. */
  private goalOf(id: string, placement: Placement): { key: string; spot: Spot } {
    const turn = this.errands.indexOf(id);
    if (turn >= 0) return { key: `report:${turn}`, spot: reportSpot(this.plan, turn) };
    if (placement.zone === 'lounge' && !this.reduced) {
      const index = this.life.spotOf(id);
      if (index !== undefined) return { key: `lounge:${index}`, spot: this.plan.loungeSpots[index] };
    }
    return { key: `${placement.zone}:${placement.x.toFixed(2)}:${placement.y.toFixed(2)}:${placement.z.toFixed(2)}`, spot: placement };
  }

  /**
   * Move one figure for this frame: along its walk if it has one, else settled at its spot and
   * doing what that spot is for. A figure never slides to a new place: when its spot changes it
   * walks there by the aisle and the doors, from wherever it is — even mid-walk.
   */
  private move(id: string, rig: CharacterRig, walker: Walker, placement: Placement, delta: number, blend: number) {
    const { key, spot } = this.goalOf(id, placement);
    const reporting = key.startsWith('report:');
    const position = rig.root.position;
    const target = this.scratch.desired;
    if (walker.key !== key) {
      const first = walker.key === '';
      walker.key = key;
      walker.settled = false;
      if (first || this.reduced) {
        walker.steps = [];
        position.set(spot.x, spot.y, spot.z);
        rig.root.rotation.y = spot.rotation;
      } else {
        // Mid-walk it finishes the stretch it is on, then turns for the new place.
        const here: Point = [position.x, position.y, position.z];
        walker.steps = walkTo(this.plan, here, walker.steps[0]?.out ?? walker.out, spot);
      }
    }

    let moving = false;
    let facing = spot.rotation;
    if (walker.steps.length) {
      const [x, y, z] = walker.steps[0].point;
      target.set(x, y, z);
      const dx = x - position.x;
      const dz = z - position.z;
      const stride = (reporting ? RUN_SPEED : WALK_SPEED) * delta;
      if (position.distanceTo(target) <= stride) {
        position.copy(target);
        walker.out = walker.steps[0].out;
        walker.steps.shift();
      } else {
        position.addScaledVector(target.sub(position).normalize(), stride);
      }
      if (Math.hypot(dx, dz) > 0.01) facing = Math.atan2(dx, dz);
      moving = walker.steps.length > 0;
    }
    if (!moving && !walker.settled) {
      walker.settled = true;
      walker.out = wayOut(spot);
      if (placement.zone === 'lounge') this.life.arrived(id, this.elapsed);
    }

    // What the body does. Angles are radians about the shoulder or hip; negative reaches forward.
    const calm = this.reduced;
    const seed = this.seed(id);
    const t = this.elapsed;
    const phase = t * (reporting ? 13 : 8) + seed;
    const activity: Activity | 'walk' = moving ? 'walk' : spot.activity;
    const pose = moving ? 'standing' : spot.pose;
    let swing = moving ? Math.sin(phase) * 0.48 : 0;
    let leftArm = -swing * 0.65;
    let rightArm = swing * 0.65;
    let headX = 0;
    let headY = 0;
    let held: THREE.Mesh | null = null;
    if (!moving) target.set(spot.x, spot.y, spot.z);
    switch (activity) {
      case 'walk':
        // Someone hurrying up to the patron carries the report they are about to hand in.
        if (reporting) {
          held = walker.paper;
          rightArm = -0.75;
        }
        break;
      case 'type':
        leftArm = calm ? -0.7 : -0.68 + Math.cos(t * 6.4 + seed) * 0.1;
        rightArm = calm ? -0.72 : -0.72 + Math.sin(t * 7 + seed) * 0.12;
        headX = 0.08;
        this.lit[placement.assignment.kind === 'desk' ? placement.assignment.desk - 1 : -1] = true;
        break;
      case 'think': {
        // Holding a task with no run going: reading the screen, now and then a hand to the chin.
        const cycle = (t + seed * 0.7) % 16;
        leftArm = -0.42;
        rightArm = !calm && cycle > 12.5 ? -1.8 : -0.42;
        headX = 0.14;
        headY = calm ? 0 : Math.sin(t * 0.4 + seed) * 0.12;
        break;
      }
      case 'relax':
        leftArm = rightArm = -0.18;
        headY = calm ? 0 : Math.sin(t * 0.3 + seed) * 0.42;
        break;
      case 'snack': {
        const sip = !calm && (t + seed * 0.9) % 6.5 < 1.3;
        held = walker.cup;
        rightArm = sip ? -1.95 : -0.62;
        headX = sip ? -0.16 : 0;
        headY = calm || sip ? 0 : Math.sin(t * 0.5 + seed) * 0.32;
        break;
      }
      case 'play': {
        held = walker.paddle;
        const station = 'station' in spot ? (spot as { station: number }).station : -1;
        if (!calm && this.life.rallyAt(station)) {
          rightArm = -0.95 + Math.sin(t * 7.5 + seed) * 0.6;
          leftArm = -0.25;
          target.z += Math.sin(t * 2.1 + seed) * 0.3;
          swing = Math.sin(phase) * 0.22;
        } else {
          // Nobody across the table yet: paddle down, looking round for a partner.
          rightArm = -0.35;
          headY = calm ? 0 : Math.sin(t * 0.8 + seed) * 0.6;
        }
        break;
      }
      case 'read':
        held = walker.paper;
        leftArm = rightArm = -0.95;
        headX = 0.32;
        break;
      case 'present': {
        // At the patron's desk: hold the report out, let go of it, step back. Then the trip
        // is over and the figure goes wherever it belongs — its desk, or the lounge.
        walker.handover += delta;
        const given = walker.handover > HANDOVER_GIVEN;
        held = given ? null : walker.paper;
        rightArm = given ? -0.2 : -1.3;
        headX = given ? 0.12 : 0;
        if (walker.handover > HANDOVER_SECONDS) {
          walker.handover = 0;
          walker.cameOffWork = true;
          this.errands = this.errands.filter((other) => other !== id);
        }
        break;
      }
      case 'queue':
        // In line behind someone at the patron's desk: still holding the report.
        if (reporting) {
          held = walker.paper;
          rightArm = -0.75;
        }
        headY = calm ? 0 : Math.sin(t * 0.45 + seed) * 0.3;
        break;
      case 'wait':
        headX = 0.2;
        break;
      case 'rest':
        leftArm = 0.18;
        rightArm = -0.18;
        break;
    }
    if (!moving) position.lerp(target, blend);
    rig.root.rotation.y = turnToward(rig.root.rotation.y, facing, blend);
    const lerp = THREE.MathUtils.lerp;
    const sitting = pose === 'sitting';
    const lying = pose === 'lying';
    rig.leftLeg.rotation.x = lerp(rig.leftLeg.rotation.x, lying ? 0 : sitting ? -1.22 : swing, blend);
    rig.rightLeg.rotation.x = lerp(rig.rightLeg.rotation.x, lying ? 0 : sitting ? -1.22 : -swing, blend);
    rig.leftArm.rotation.x = lerp(rig.leftArm.rotation.x, leftArm, blend);
    rig.rightArm.rotation.x = lerp(rig.rightArm.rotation.x, rightArm, blend);
    rig.head.rotation.x = lerp(rig.head.rotation.x, headX, blend);
    rig.head.rotation.y = lerp(rig.head.rotation.y, headY, blend);
    rig.body.position.y = calm || lying || sitting ? 0 : Math.sin(phase) * (moving ? 0.025 : 0.008);
    rig.body.rotation.x = lerp(rig.body.rotation.x, lying ? -Math.PI / 2 : 0, blend);
    walker.cup.visible = held === walker.cup;
    walker.paper.visible = held === walker.paper;
    walker.paddle.visible = held === walker.paddle;
    // The dial over a head means one thing: a run is going right now.
    rig.routineDial.visible = activity === 'type';
    return lying;
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
    const blend = this.reduced ? 1 : Math.min(delta * 4.2, 1);
    const lerp = THREE.MathUtils.lerp;
    if (this.flight) {
      const flight = this.flight;
      flight.progress = Math.min(1, flight.progress + delta / FLIGHT_SECONDS);
      const eased = THREE.MathUtils.smootherstep(flight.progress, 0, 1);
      this.camera.position.lerpVectors(flight.fromPosition, flight.toPosition, eased);
      this.controls.target.lerpVectors(flight.fromTarget, flight.toTarget, eased);
      this.camera.zoom = lerp(flight.fromZoom, flight.toZoom, eased);
      this.camera.updateProjectionMatrix();
      if (flight.progress >= 1) this.flight = null;
    }
    this.keepInside();
    // World units per screen pixel right now: what keeps tags and captions one size on screen.
    const unitsPerPixel = (this.camera.top - this.camera.bottom) / this.camera.zoom / Math.max(this.host.clientHeight, 1);
    const tagHeight = TAG.screen * unitsPerPixel;
    const captionHeight = CAPTION.screen * unitsPerPixel;
    // Up close the signs on the walls are readable and the captions would only sit on top of them.
    const captionOpacity = 1 - THREE.MathUtils.smoothstep(this.camera.zoom, 1.45, 1.95);
    // Which way "out of the building" points on screen, so a caption always reads away from the
    // floor however the view has been turned.
    const elements = this.camera.matrixWorld.elements;
    this.captions.forEach((caption) => {
      const outward = caption.userData.outward as number;
      const span = (caption.userData.span as number | undefined) ?? 1;
      caption.center.set(0.5 - THREE.MathUtils.clamp(outward * elements[0] * 1.5, -1, 1) * (span / 2), 0.5 - THREE.MathUtils.clamp(outward * elements[4] * 1.5, -1, 1) * 0.42);
      caption.scale.set((captionHeight * CAPTION.width) / CAPTION.height, captionHeight, 1);
      caption.material.opacity = captionOpacity;
      caption.visible = this.roomForCaptions && captionOpacity > 0.02;
    });
    // Who is idle, for the lounge to decide what each of them is up to.
    const idle: IdleAgent[] = [];
    layout.placements.forEach((placement, id) => {
      const walker = this.walkers.get(id);
      if (walker && walker.zone !== placement.zone) {
        walker.cameOffWork = placement.zone === 'lounge';
        walker.zone = placement.zone;
      }
      // Someone up at the patron's desk has left the lounge, and their seat with it.
      if (placement.zone === 'lounge' && !this.errands.includes(id)) idle.push({ id, start: placement.start ?? 0, cameOffWork: walker?.cameOffWork ?? false });
    });
    if (!this.reduced) this.life.step(this.elapsed, idle);
    this.lit.fill(false);
    this.rigs.forEach((rig, id) => {
      const placement = layout.placements.get(id);
      const walker = this.walkers.get(id);
      if (!placement || !walker) return;
      const lying = this.move(id, rig, walker, placement, delta, blend);
      const label = this.labels.get(id);
      if (label) {
        const scale = rig.root.scale.y || 1;
        label.scale.set((tagHeight * TAG.width) / TAG.height / scale, tagHeight / scale, 1);
        label.userData.rest = (lying ? 0.7 : 1.78) + (tagHeight * 0.62) / scale;
        // A crowded floor only names the agent in focus (DESIGN §7).
        label.visible = !this.plan.large || selectedId === id || this.hoveredId === id;
      }
      if (!this.reduced && rig.routineDial.visible) {
        rig.routineDial.rotation.y += delta * 2.4;
        rig.routineDial.position.y = 1.73 + Math.sin(this.elapsed * 2) * 0.04;
      }
    });
    // A monitor is lit only while its owner has a run going.
    const parts = this.office.parts;
    parts.screens.forEach((screen, index) => {
      const color = (screen.material as THREE.MeshBasicMaterial).color;
      color.lerp(this.scratch.color.set(this.lit[index] ? (Math.sin(this.elapsed * 5 + index) > 0.6 ? '#b9d2ff' : '#8fb4ff') : '#27303a'), Math.min(1, delta * 6));
    });
    // The stack on the patron's desk: every report waiting for an answer, less those still on their way.
    const waiting = Math.max(0, layout.plan.reviewCount - this.errands.length);
    parts.reports.forEach((report, index) => {
      report.visible = index < waiting;
    });
    // A ball crosses each table that has a player on both sides.
    parts.balls.forEach((ball, station) => {
      const rally = !this.reduced && this.life.rallyAt(station);
      ball.mesh.visible = rally;
      if (!rally) return;
      const swing = this.elapsed * 3.4 + station;
      ball.mesh.position.set(ball.x + Math.sin(swing) * 1.15, 0.84 + Math.abs(Math.sin(swing * 2)) * 0.3, ball.z + Math.sin(swing * 0.37) * 0.3);
    });
    // The notice board glows while letters wait, and flashes for a few seconds when one arrives.
    this.boardPulse = Math.max(0, this.boardPulse - delta);
    const flash = this.boardPulse > 0 && !this.reduced ? Math.abs(Math.sin(this.boardPulse * 5)) : 0;
    const frame = (parts.boardFrame.material as THREE.MeshBasicMaterial).color;
    frame.set(this.boardCount > 0 ? '#d2b568' : '#6d6456').lerp(this.scratch.color.set('#fff1c2'), this.boardCount > 0 ? Math.max(flash, this.reduced ? 0 : 0.25 + Math.sin(this.elapsed * 2) * 0.25) : 0);
    parts.boardFrame.scale.setScalar(1 + flash * 0.035);
    this.spreadTags(unitsPerPixel, blend);
    this.applyLook(this.reduced ? 1 : Math.min(delta * 3.5, 1));
    if (!this.reduced) {
      this.office.hologram.rotation.y += delta * 0.24;
      this.office.hologram.position.y = 1.05 + Math.sin(this.elapsed * 1.2) * 0.04;
    }
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

  /**
   * Neighbours on one sofa stand closer than their names are wide. Tags that would land on each
   * other are stacked upward instead, in a fixed order so the stack does not reshuffle, and
   * eased so a tag joining or leaving the stack slides rather than jumps.
   */
  private spreadTags(unitsPerPixel: number, blend: number) {
    const width = this.host.clientWidth;
    const height = this.host.clientHeight;
    const tagWidth = (TAG.screen * TAG.width) / TAG.height;
    const placed: { left: number; right: number; top: number; bottom: number }[] = [];
    const point = this.scratch.ground;
    // The zone captions were here first: a tag never sits on one of them either.
    const captionWidth = (CAPTION.screen * CAPTION.width) / CAPTION.height;
    this.captions.forEach((caption) => {
      if (!caption.visible) return;
      point.copy(caption.position).project(this.camera);
      const span = (caption.userData.span as number | undefined) ?? 1;
      const left = (point.x * 0.5 + 0.5) * width - caption.center.x * captionWidth + (0.5 - span / 2) * captionWidth;
      const top = (-point.y * 0.5 + 0.5) * height - (1 - caption.center.y) * CAPTION.screen;
      placed.push({ left, right: left + span * captionWidth, top, bottom: top + CAPTION.screen });
    });
    // How far one world unit of height moves a tag on screen, in pixels.
    const rise = Math.max(0.2, this.camera.matrixWorld.elements[5]) / unitsPerPixel;
    [...this.labels.keys()].sort().forEach((id) => {
      const label = this.labels.get(id)!;
      const rig = this.rigs.get(id);
      if (!rig || !label.visible) return;
      const rest = (label.userData.rest as number | undefined) ?? label.position.y;
      point.set(0, rest, 0).applyMatrix4(rig.root.matrixWorld).project(this.camera);
      const x = (point.x * 0.5 + 0.5) * width;
      let y = (-point.y * 0.5 + 0.5) * height;
      const half = (tagWidth * ((label.userData.span as number | undefined) ?? 1)) / 2 + 2;
      let lift = 0;
      for (let attempt = 0; attempt < 6; attempt++) {
        const top = y - TAG.screen / 2;
        const bottom = y + TAG.screen / 2;
        const clash = placed.some((box) => x - half < box.right && x + half > box.left && top < box.bottom && bottom > box.top);
        if (!clash) break;
        y -= TAG.screen + 2;
        lift += TAG.screen + 2;
      }
      placed.push({ left: x - half, right: x + half, top: y - TAG.screen / 2, bottom: y + TAG.screen / 2 });
      const scale = rig.root.scale.y || 1;
      const shown = THREE.MathUtils.lerp((label.userData.lift as number | undefined) ?? 0, lift / rise / scale, blend);
      label.userData.lift = shown;
      label.position.y = rest + shown;
    });
  }

  private onMotionChange = (event: MediaQueryListEvent) => {
    this.reduced = event.matches;
    this.controls.enableDamping = !this.reduced && !this.software;
  };

  private resize = () => {
    const width = this.host.clientWidth;
    const height = this.host.clientHeight;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    // The floor is fitted to the part of the canvas the page leaves uncovered, and centred there.
    const clear = Math.max(120, height - this.insets.top - this.insets.bottom);
    const aspect = width / clear;
    // How much of the view the floor takes from the overview, across and up, with the walls'
    // height and a margin; the zone captions stand outside it and need room of their own
    // where the canvas is wide enough to have them.
    this.roomForCaptions = width >= CAPTION_MIN_WIDTH;
    const { floorWidth, floorDepth } = this.plan;
    const across = floorWidth * Math.cos(OVERVIEW_TURN) + floorDepth * Math.sin(OVERVIEW_TURN) + (this.roomForCaptions ? 12 : 2.5);
    const tall = (floorWidth * Math.sin(OVERVIEW_TURN) + floorDepth * Math.cos(OVERVIEW_TURN)) * Math.sin(OVERVIEW_TILT) + 3.6 * Math.cos(OVERVIEW_TILT) + 2.6;
    const viewHeight = Math.max(14, across / aspect, tall);
    const unitsPerPixel = viewHeight / clear;
    this.camera.left = (-viewHeight * aspect) / 2;
    this.camera.right = (viewHeight * aspect) / 2;
    this.camera.top = viewHeight / 2 + this.insets.top * unitsPerPixel;
    this.camera.bottom = -viewHeight / 2 - this.insets.bottom * unitsPerPixel;
    this.camera.updateProjectionMatrix();
  };

  // ─── Pointer ───

  private preventContextMenu = (event: Event) => event.preventDefault();
  private onRoam = () => {
    this.flight = null;
    this.callbacks.onRoam();
  };
  private onPointerDown = (event: PointerEvent) => {
    this.pointerStart = [event.clientX, event.clientY];
    this.pointers.add(event.pointerId);
    this.flight = null;
    // A plain press with one pointer takes hold of the floor. Anything else — a second finger,
    // the right button, a modifier key — is the orbit control's.
    const plain = event.pointerType !== 'mouse' || (event.button === 0 && !event.ctrlKey && !event.metaKey && !event.shiftKey);
    const grab = this.pointers.size === 1 && plain ? this.floorAt(event.clientX, event.clientY, this.scratch.ground) : null;
    this.pan = grab ? { pointer: event.pointerId, grab: grab.clone(), moved: false } : null;
  };
  private onPointerMove = (event: PointerEvent) => {
    const canvas = this.renderer.domElement;
    if (this.pan && event.pointerId === this.pan.pointer) {
      if (!this.pan.moved) {
        if (Math.hypot(event.clientX - this.pointerStart[0], event.clientY - this.pointerStart[1]) <= CLICK_SLOP) return;
        this.pan.moved = true;
        canvas.style.cursor = 'grabbing';
        if (this.hoveredId) {
          this.hoveredId = null;
          this.callbacks.onHover(null);
        }
        this.callbacks.onRoam();
      }
      // Put the point that was grabbed back under the pointer.
      const now = this.floorAt(event.clientX, event.clientY, this.scratch.ground);
      if (now) this.slide(this.scratch.shift.subVectors(this.pan.grab, now));
      return;
    }
    if (this.pointers.size > 0) return;
    const hit = this.pick(event);
    canvas.style.cursor = hit ? 'pointer' : 'grab';
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
  private onPointerCancel = (event: PointerEvent) => {
    this.pointers.delete(event.pointerId);
    this.pan = null;
    this.renderer.domElement.style.cursor = 'grab';
  };
  private onDoubleClick = (event: MouseEvent) => {
    const point = this.floorAt(event.clientX, event.clientY, this.scratch.ground);
    if (!point) return;
    this.callbacks.onRoam();
    this.lookAt(point.x, point.z, Math.min(MAX_ZOOM, this.camera.zoom * 1.7));
  };
  private onKeyDown = (event: KeyboardEvent) => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const step = 2.4 / this.camera.zoom;
    const shift = this.scratch.shift.set(0, 0, 0);
    // Screen directions laid onto the floor: right is the camera's own right, up is away from it.
    const right = this.scratch.ground.setFromMatrixColumn(this.camera.matrixWorld, 0).setY(0).normalize();
    const away = this.scratch.desired.subVectors(this.controls.target, this.camera.position).setY(0).normalize();
    switch (event.key) {
      case 'ArrowLeft': shift.addScaledVector(right, -step); break;
      case 'ArrowRight': shift.addScaledVector(right, step); break;
      case 'ArrowUp': shift.addScaledVector(away, step); break;
      case 'ArrowDown': shift.addScaledVector(away, -step); break;
      case '+': case '=': this.zoom(1); break;
      case '-': case '_': this.zoom(-1); break;
      case 'r': case 'R': this.rotate(); break;
      case '0': this.reset(); break;
      default: return;
    }
    event.preventDefault();
    this.callbacks.onRoam();
    if (shift.lengthSq() > 0) {
      this.flight = null;
      this.slide(shift);
    }
  };
  private onPointerLeave = () => {
    this.hoveredId = null;
    this.callbacks.onHover(null);
  };
  private onPointerUp = (event: PointerEvent) => {
    this.pointers.delete(event.pointerId);
    this.pan = null;
    this.renderer.domElement.style.cursor = 'grab';
    // A drag moved the view; only a still press counts as a click.
    if (Math.hypot(event.clientX - this.pointerStart[0], event.clientY - this.pointerStart[1]) > CLICK_SLOP) return;
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
      // A name tag's canvas is wider than its plate; only the plate itself counts.
      if (hit.object instanceof THREE.Sprite && hit.uv && Math.abs(hit.uv.x - 0.5) > ((hit.object.userData.span as number | undefined) ?? 1) / 2) continue;
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
    canvas.removeEventListener('pointercancel', this.onPointerCancel);
    canvas.removeEventListener('dblclick', this.onDoubleClick);
    canvas.removeEventListener('keydown', this.onKeyDown);
    canvas.removeEventListener('wheel', this.onRoam);
    this.controls.removeEventListener('start', this.onRoam);
    this.captions.forEach((caption) => {
      caption.material.map?.dispose();
      caption.material.dispose();
    });
    this.captions.clear();
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
