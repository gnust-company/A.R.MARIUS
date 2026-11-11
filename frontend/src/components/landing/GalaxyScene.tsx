import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import * as THREE from 'three';
import { useTranslation } from 'react-i18next';
import type { Theme } from '@/hooks/use-theme';
import { DEMO_AGENT, demoTaskCode, type LandingDemo } from './landingDemo';
import {
  HERO_DESK_TOP,
  HERO_ROUTE,
  HERO_SEAT,
  RUNNER_ROUTE,
  STILL_AGENTS,
  TASK_ORIGIN,
  TINTS,
  ZONE_LABELS,
  along,
  buildCloud,
  type Tint,
  type Vec3,
} from './landingBuilding';

/*
 * The landing page's sky, fixed behind the copy and never interactive. One WebGL scene, driven
 * by the scroll position, in three acts:
 *
 *   1. a spiral galaxy of points;
 *   2. the inner stars of that galaxy fly together into the observatory's five zones, with a
 *      handful of agents at work inside it;
 *   3. one of those agents plays the scripted demo (`landingDemo.ts`): it takes a task, works,
 *      walks to the Patron room and waits there for the visitor's decision.
 *
 * The hex colours are star light inside the WebGL scene, not UI chrome. The light theme draws
 * the same hues as ink on a pale sky. Zone names and the agent's tag are DOM, laid over the
 * canvas and moved every frame, so they stay sharp and follow the theme tokens.
 */

const TINT_HEX: Record<Tint, string> = {
  structure: '#b7c8ff',
  spine: '#e5bb72',
  setup: '#b9a7ff',
  lounge: '#74e4da',
  clinic: '#f3a9bd',
  work: '#83a7ff',
  patron: '#ffd27a',
};

/** Stars this close to the core become the building; the outer arms stay a galaxy around it. */
const MORPH_RADIUS = 5;
/** The building is seen three-quarter on, with the Patron room nearest the viewer. */
const YAW = -0.5;

/*
 * Where the galaxy sits at each chapter: hero, company, demo, gate. Eased in between.
 * x and y are fractions of the half viewport (0 = centre, 1 = the edge). The chapters in
 * which the galaxy is the building are placed from the viewport instead: docked to the
 * right of the copy on wide screens, in a band above the copy on narrow and portrait ones,
 * where the distance is whatever makes the building fit the width.
 */
const WIDE = { x: [0.24, 0, 0, 0.04], y: [0, -0.02, 0.02, 0], tilt: [-0.86, -0.98, -1.02, -1.22], distance: [20, 17, 14.5, 21] };
const NARROW = { x: [0.2, 0, 0, 0], y: [0.3, 0, 0, 0.04], tilt: [-0.86, -0.96, -0.96, -1.22], distance: [20, 0, 0, 21] };
const BUILT = [false, true, true, false];
/** Half the camera's vertical field of view, as a tangent. */
const HALF_FOV = Math.tan(THREE.MathUtils.degToRad(24));
/** Half the width the building needs on screen, in scene units, with a margin. */
const BUILDING_REACH = 5.9;
/** Half its height on screen, in scene units, at the tilt of the building chapters. */
const BUILDING_RISE = 3.5;
/** Where the building's band starts on narrow screens, in pixels: just under the header. */
const BAND_TOP = 96;

const VERTEX = /* glsl */ `
  uniform float uMorph;
  uniform float uSpin;
  uniform float uYaw;
  uniform float uSize;
  uniform float uScale;
  uniform float uLight;
  uniform float uTime;
  attribute vec3 aTarget;
  attribute vec3 aColor;
  attribute vec3 aColorB;
  // x: when this point leaves for the building (0 first) · y: 1 if it leaves at all
  // z: its size once in the building · w: a random phase
  attribute vec4 aAux;
  varying vec3 vColor;
  varying float vAlpha;

  vec2 turn(vec2 p, float angle) {
    float c = cos(angle);
    float s = sin(angle);
    return vec2(p.x * c - p.y * s, p.x * s + p.y * c);
  }

  void main() {
    float t = aAux.y * smoothstep(0.0, 1.0, clamp(uMorph * 1.8 - aAux.x * 0.8, 0.0, 1.0));
    vec3 from = vec3(turn(position.xy, uSpin), position.z);
    vec3 to = vec3(turn(aTarget.xy, uYaw), aTarget.z);
    vec3 p = mix(from, to, t);
    // In flight a point lifts off the disk, so the building settles down into place.
    p.z += sin(t * 3.14159265) * (0.5 + aAux.w * 1.6) * aAux.y;
    vec4 mv = modelViewMatrix * vec4(p, 1.0);
    gl_Position = projectionMatrix * mv;
    float shimmer = 1.0 + 0.14 * sin(uTime * 1.7 + aAux.w * 40.0) * t;
    gl_PointSize = uSize * mix(1.0, aAux.z * 1.5, t) * shimmer * uScale / -mv.z;
    vec3 color = mix(aColor, aColorB * 1.25, t);
    // Light theme: the same hue, deepened to ink; the building a shade deeper than the stars.
    vColor = mix(color, pow(color, vec3(2.0)) * mix(0.62, 0.42, t), uLight);
    // The arms that stay behind dim, so the building stands out against them.
    vAlpha = 1.0 - (1.0 - aAux.y) * uMorph * 0.68;
  }
`;

const FRAGMENT = /* glsl */ `
  uniform sampler2D uMap;
  uniform float uOpacity;
  varying vec3 vColor;
  varying float vAlpha;

  void main() {
    float alpha = texture2D(uMap, gl_PointCoord).a * uOpacity * vAlpha;
    if (alpha < 0.004) discard;
    gl_FragColor = vec4(vColor, alpha);
    #include <colorspace_fragment>
  }
`;

function randomGenerator(seed: number) {
  return () => {
    seed |= 0;
    seed = (seed + 0x6d2b79f5) | 0;
    let value = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    value = (value + Math.imul(value ^ (value >>> 7), 61 | value)) ^ value;
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function glowTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 64;
  const context = canvas.getContext('2d');
  if (context) {
    const gradient = context.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, 'rgba(255,255,255,1)');
    gradient.addColorStop(0.16, 'rgba(255,255,255,.95)');
    gradient.addColorStop(0.46, 'rgba(255,255,255,.3)');
    gradient.addColorStop(1, 'rgba(255,255,255,0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, 64, 64);
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return !!(canvas.getContext('webgl2') || canvas.getContext('webgl'));
  } catch {
    return false;
  }
}

const ease = (value: number) => value * value * (3 - 2 * value);

/** A keyframed value at chapter position `chapter` (0 … keys.length - 1), eased between keys. */
function keyed(keys: readonly number[], chapter: number): number {
  const index = Math.min(Math.floor(chapter), keys.length - 2);
  return THREE.MathUtils.lerp(keys[index], keys[index + 1], ease(Math.min(chapter - index, 1)));
}

interface Props {
  theme: Theme;
  /** Section ids of the page's chapters, in order. Their offsets pace the journey. */
  chapterIds: readonly string[];
  demo: LandingDemo;
  /** Called once if WebGL cannot start, so the page can drop the room it left for the scene. */
  onUnavailable?: () => void;
}

export default function GalaxyScene({ theme, chapterIds, demo, onUnavailable }: Props) {
  const { t } = useTranslation();
  const host = useRef<HTMLDivElement>(null);
  const labels = useRef<(HTMLSpanElement | null)[]>([]);
  const tag = useRef<HTMLSpanElement>(null);
  const currentTheme = useRef(theme);
  const unavailable = useRef(onUnavailable);
  const [supported] = useState(webglAvailable);
  const snapshot = useSyncExternalStore(demo.subscribe, demo.getSnapshot, demo.getSnapshot);

  useLayoutEffect(() => {
    currentTheme.current = theme;
    unavailable.current = onUnavailable;
  }, [theme, onUnavailable]);

  useEffect(() => {
    const container = host.current;
    if (!container) return;
    if (!supported) {
      // Deferred so the page updates on the next commit rather than inside this effect.
      queueMicrotask(() => unavailable.current?.());
      return;
    }
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let reduced = motionQuery.matches;
    const onMotion = (event: MediaQueryListEvent) => {
      reduced = event.matches;
    };
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' });
    } catch {
      // The gradient fallback underneath stays visible; the demo panel works without the scene.
      // Deferred so the page updates on the next commit rather than inside this effect.
      queueMicrotask(() => unavailable.current?.());
      return;
    }
    const random = randomGenerator(1707);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(48, 1, 0.1, 180);
    camera.position.set(0, 0, 20);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.65));
    renderer.setClearColor(0x000000, 0);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    const canvas = renderer.domElement;
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.position = 'absolute';
    canvas.style.inset = '0';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    container.prepend(canvas);

    // galaxy: tilts and travels with the scroll · disk: spins · building: holds its own heading.
    const galaxy = new THREE.Group();
    const disk = new THREE.Group();
    const building = new THREE.Group();
    galaxy.add(disk, building);
    scene.add(galaxy);
    const texture = glowTexture();
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];

    // Four spiral arms, warm at the core and cooling outward, plus the core itself.
    const armCount = window.innerWidth < 700 ? 8500 : 15500;
    const coreCount = 2100;
    const count = armCount + coreCount;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const leaves = new Uint8Array(count);
    const inner = new THREE.Color('#ffe0a3');
    const middle = new THREE.Color('#83a7ff');
    const outer = new THREE.Color('#74e4da');
    const coreColor = new THREE.Color('#ffdc96');
    const mixed = new THREE.Color();
    for (let index = 0; index < armCount; index++) {
      const radius = Math.pow(random(), 0.58) * 8.8 + 0.08;
      const arm = index % 4;
      const spread = (0.17 + radius * 0.022) * (random() - 0.5) * 2;
      const angle = (arm / 4) * Math.PI * 2 + radius * 0.69 + spread;
      const scatter = Math.pow(random(), 2.2) * (0.18 + radius * 0.07);
      positions[index * 3] = Math.cos(angle) * radius + (random() - 0.5) * scatter;
      positions[index * 3 + 1] = Math.sin(angle) * radius + (random() - 0.5) * scatter;
      positions[index * 3 + 2] = (random() - 0.5) * (0.24 + radius * 0.055);
      if (radius < 2.5) mixed.copy(inner).lerp(middle, radius / 2.5);
      else mixed.copy(middle).lerp(outer, Math.min((radius - 2.5) / 6.3, 1));
      const brightness = 0.58 + random() * 0.55;
      colors[index * 3] = mixed.r * brightness;
      colors[index * 3 + 1] = mixed.g * brightness;
      colors[index * 3 + 2] = mixed.b * brightness;
      leaves[index] = radius < MORPH_RADIUS ? 1 : 0;
    }
    for (let index = armCount; index < count; index++) {
      const radius = Math.pow(random(), 2.7) * 2.1;
      const theta = random() * Math.PI * 2;
      const phi = Math.acos(2 * random() - 1);
      positions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[index * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      positions[index * 3 + 2] = radius * Math.cos(phi) * 0.48;
      const brightness = 0.7 + random() * 0.3;
      colors[index * 3] = coreColor.r * brightness;
      colors[index * 3 + 1] = coreColor.g * brightness;
      colors[index * 3 + 2] = coreColor.b * brightness;
      leaves[index] = 1;
    }

    // Every star that leaves gets a place in the building.
    const leaving = leaves.reduce((sum, flag) => sum + flag, 0);
    const cloud = buildCloud(leaving, random);
    const palette = TINTS.map((tint) => new THREE.Color(TINT_HEX[tint]));
    const targets = new Float32Array(count * 3);
    const targetColors = new Float32Array(count * 3);
    const aux = new Float32Array(count * 4);
    for (let index = 0, slot = 0; index < count; index++) {
      aux[index * 4 + 3] = random();
      if (!leaves[index]) continue;
      targets.set(cloud.positions.subarray(slot * 3, slot * 3 + 3), index * 3);
      const tint = palette[cloud.tints[slot]];
      targetColors[index * 3] = tint.r * cloud.shades[slot];
      targetColors[index * 3 + 1] = tint.g * cloud.shades[slot];
      targetColors[index * 3 + 2] = tint.b * cloud.shades[slot];
      aux[index * 4] = cloud.order[slot] * 0.62 + random() * 0.38;
      aux[index * 4 + 1] = 1;
      aux[index * 4 + 2] = cloud.sizes[slot];
      slot++;
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('aColor', new THREE.BufferAttribute(colors, 3));
    geometry.setAttribute('aTarget', new THREE.BufferAttribute(targets, 3));
    geometry.setAttribute('aColorB', new THREE.BufferAttribute(targetColors, 3));
    geometry.setAttribute('aAux', new THREE.BufferAttribute(aux, 4));
    const uniforms = {
      uMorph: { value: 0 },
      uSpin: { value: 0 },
      uYaw: { value: YAW },
      uSize: { value: 0.105 },
      uScale: { value: 1 },
      uLight: { value: 0 },
      uTime: { value: 0 },
      uOpacity: { value: 0.94 },
      uMap: { value: texture },
    };
    const material = new THREE.ShaderMaterial({
      uniforms,
      vertexShader: VERTEX,
      fragmentShader: FRAGMENT,
      transparent: true,
      depthWrite: false,
      blending: THREE.AdditiveBlending,
    });
    const stars = new THREE.Points(geometry, material);
    // The vertex shader moves the points; the geometry's own bounds mean nothing.
    stars.frustumCulled = false;
    galaxy.add(stars);
    geometries.push(geometry);
    materials.push(material);

    const farGeometry = new THREE.BufferGeometry();
    const farPositions = new Float32Array(1500 * 3);
    for (let index = 0; index < 1500; index++) {
      farPositions[index * 3] = (random() - 0.5) * 70;
      farPositions[index * 3 + 1] = (random() - 0.5) * 48;
      farPositions[index * 3 + 2] = -8 - random() * 45;
    }
    farGeometry.setAttribute('position', new THREE.BufferAttribute(farPositions, 3));
    const farMaterial = new THREE.PointsMaterial({ color: '#b9cfff', size: 0.085, map: texture, transparent: true, opacity: 0.68, depthWrite: false, blending: THREE.AdditiveBlending });
    scene.add(new THREE.Points(farGeometry, farMaterial));
    geometries.push(farGeometry);
    materials.push(farMaterial);

    const rings = new THREE.Group();
    const ringMaterials: THREE.LineBasicMaterial[] = [];
    [2.8, 5.7, 9.2].forEach((radius, index) => {
      const curve = new THREE.EllipseCurve(0, 0, radius, radius, 0, Math.PI * 2, false, index * 0.65);
      const ringGeometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(180));
      const ringMaterial = new THREE.LineBasicMaterial({ color: index === 1 ? '#e5bb72' : '#879fe5', transparent: true, opacity: 0.12 });
      const ring = new THREE.LineLoop(ringGeometry, ringMaterial);
      ring.rotation.x = index * 0.14;
      rings.add(ring);
      geometries.push(ringGeometry);
      materials.push(ringMaterial);
      ringMaterials.push(ringMaterial);
    });
    disk.add(rings);

    // The agents: glowing figures inside the building. They only exist once it has formed.
    const orb = (scale: number) => {
      const orbMaterial = new THREE.SpriteMaterial({ map: texture, transparent: true, opacity: 0, depthWrite: false, depthTest: false });
      const sprite = new THREE.Sprite(orbMaterial);
      sprite.scale.setScalar(scale);
      building.add(sprite);
      materials.push(orbMaterial);
      return sprite;
    };
    const stills = STILL_AGENTS.map((agent) => {
      const sprite = orb(0.34);
      sprite.position.set(...agent.at);
      return { sprite, tint: agent.zone, dim: agent.zone === 'clinic' ? 0.55 : 1 };
    });
    const runner = orb(0.34);
    const hero = orb(0.5);
    const task = orb(0.4);
    const beacon = orb(1);
    beacon.center.set(0.5, 0.08);
    const ringGeometry = new THREE.RingGeometry(0.2, 0.235, 48);
    geometries.push(ringGeometry);
    const floorRing = () => {
      const ringMaterial = new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, side: THREE.DoubleSide, depthWrite: false, depthTest: false });
      const mesh = new THREE.Mesh(ringGeometry, ringMaterial);
      building.add(mesh);
      materials.push(ringMaterial);
      return mesh;
    };
    const heroRing = floorRing();
    const callRing = floorRing();

    let frame = 0;
    let previous = 0;
    let elapsed = 0;
    let targetChapter = 0;
    let chapter = 0;
    let width = 1;
    let height = 1;
    const last = chapterIds.length - 1;
    const readScroll = () => {
      const available = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
      const y = THREE.MathUtils.clamp(window.scrollY, 0, available);
      // Each chapter is "at rest" when its section reaches the top of the viewport.
      let from = 0;
      for (let index = 1; index <= last; index++) {
        const section = document.getElementById(chapterIds[index]);
        const top = section ? section.getBoundingClientRect().top + window.scrollY : (available * index) / last;
        const to = Math.max(Math.min(top, available), from + 1);
        if (y <= to || index === last) {
          targetChapter = index - 1 + THREE.MathUtils.clamp((y - from) / (to - from), 0, 1);
          return;
        }
        from = to;
      }
    };
    const resize = () => {
      width = container.clientWidth;
      height = container.clientHeight;
      renderer.setSize(width, height, false);
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
      uniforms.uScale.value = renderer.getDrawingBufferSize(new THREE.Vector2()).y * 0.5;
      readScroll();
    };
    resize();
    window.addEventListener('scroll', readScroll, { passive: true });
    window.addEventListener('resize', resize);
    motionQuery.addEventListener('change', onMotion);

    const { lerp, smoothstep } = THREE.MathUtils;
    const projected = new THREE.Vector3();
    const distances: number[] = [];
    const offsetsX: number[] = [];
    const offsetsY: number[] = [];
    const heroAt: Vec3 = [...HERO_SEAT];
    const runnerAt: Vec3 = [...RUNNER_ROUTE[0]];
    const taskAt: Vec3 = [...HERO_DESK_TOP];
    const patronSpot = HERO_ROUTE[HERO_ROUTE.length - 1];

    /** A zone's colour for the current theme: light on a dark sky, ink on a pale one. */
    const paint = (target: THREE.Color, tint: Tint, dark: boolean) => {
      target.set(TINT_HEX[tint]);
      if (!dark) target.offsetHSL(0, 0.1, -0.3);
    };

    /** Pin a DOM element above a point of the building. */
    const pin = (element: HTMLElement | null, at: Vec3, lift: number, opacity: number) => {
      if (!element) return;
      if (opacity < 0.02) {
        element.style.opacity = '0';
        return;
      }
      projected.set(at[0], at[1], at[2] + lift).applyMatrix4(building.matrixWorld).project(camera);
      const x = (projected.x * 0.5 + 0.5) * width;
      const y = (-projected.y * 0.5 + 0.5) * height;
      element.style.opacity = opacity.toFixed(2);
      element.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0) translate(-50%, -100%)`;
    };

    const animate = (time: number) => {
      frame = requestAnimationFrame(animate);
      const delta = Math.min((time - (previous || time)) / 1000, 0.05);
      previous = time;
      // Reduced motion: nothing drifts on its own; the scene only follows the scroll position
      // and the demo's phases, and agents change place without walking.
      if (!reduced) elapsed += delta;
      chapter = reduced ? targetChapter : lerp(chapter, targetChapter, 0.06);
      const aspect = width / Math.max(height, 1);
      // Must match the CSS that clears the band above the copy: below md, or portrait.
      const narrow = width < 768 || aspect < 1;
      const dark = currentTheme.current === 'dark';
      const keys = narrow ? NARROW : WIDE;
      const morph = smoothstep(chapter, 0.12, 0.85) * (1 - smoothstep(chapter, 2.5, 2.95));
      const formed = smoothstep(morph, 0.82, 1);

      // Narrow: as close as the building still fits the width, and never taller than about a
      // third of the screen. Wide: pulled back on squarer screens so the copy keeps its column.
      const fit = Math.max(22.5, BUILDING_REACH / (HALF_FOV * aspect));
      const stretch = THREE.MathUtils.clamp((1.6 / aspect) ** 1.5, 1, 1.6);
      for (let index = 0; index <= last; index++) {
        const built = BUILT[index] ?? false;
        const away = narrow ? keys.distance[index] || fit : keys.distance[index] * stretch;
        const half = away * HALF_FOV;
        distances[index] = away;
        offsetsX[index] = built && !narrow ? half * aspect - BUILDING_REACH : keys.x[index] * half * aspect;
        offsetsY[index] = built && narrow ? half * (1 - (2 * BAND_TOP) / Math.max(height, 1)) - BUILDING_RISE : keys.y[index] * half;
      }
      const distance = keyed(distances, chapter);
      // On narrow screens the building's band is only clear while a chapter is just arriving;
      // once the copy scrolls over it, it steps back and its captions go.
      const lean = chapter - Math.floor(chapter);
      const clear = narrow ? 1 - smoothstep(Math.min(lean, 1 - lean), 0.05, 0.16) : 1;
      // The figures and the task follow the building: present once it has formed, dimmed with it.
      const lit = formed * (0.35 + clear * 0.65);
      galaxy.position.x = keyed(offsetsX, chapter);
      galaxy.position.y = keyed(offsetsY, chapter);
      galaxy.rotation.x = keyed(keys.tilt, chapter);
      galaxy.rotation.y = -0.1 + Math.sin((chapter / last) * Math.PI) * 0.22 * (1 - morph);
      camera.position.z = distance;
      camera.position.y = Math.sin((chapter / last) * Math.PI * 2) * 0.8 * (1 - morph);
      camera.lookAt(0, 0, 0);

      const spin = elapsed * 0.032 + chapter * Math.PI * 0.48;
      const yaw = YAW + Math.sin(elapsed * 0.1) * 0.04;
      disk.rotation.z = spin;
      rings.rotation.z = -elapsed * 0.012;
      building.rotation.z = yaw;
      uniforms.uMorph.value = morph;
      uniforms.uSpin.value = spin;
      uniforms.uYaw.value = yaw;
      uniforms.uTime.value = elapsed;
      uniforms.uLight.value = dark ? 0 : 1;
      uniforms.uSize.value = dark ? 0.105 : 0.13;
      uniforms.uOpacity.value = (dark ? 0.94 : 0.9) * lerp(1, 0.45 + clear * 0.55, formed);
      const blending = dark ? THREE.AdditiveBlending : THREE.NormalBlending;
      material.blending = blending;
      farMaterial.opacity = dark ? 0.68 : 0.25;
      farMaterial.color.set(dark ? '#b9cfff' : '#536d9d');
      farMaterial.blending = blending;
      ringMaterials.forEach((ringMaterial) => {
        ringMaterial.opacity = 0.12 * (1 - morph * 0.7);
      });

      // Agents at rest breathe a little; one drifts between the lounge and a desk.
      stills.forEach(({ sprite, tint, dim }, index) => {
        paint(sprite.material.color, tint, dark);
        sprite.material.opacity = lit * dim * (dark ? 0.95 : 0.85);
        sprite.material.blending = blending;
        sprite.scale.setScalar(0.34 * (1 + Math.sin(elapsed * 1.3 + index * 1.7) * 0.06));
      });
      const lap = elapsed % 24;
      const runnerProgress = lap < 5 ? 0 : lap < 10 ? ease((lap - 5) / 5) : lap < 19 ? 1 : 1 - ease((lap - 19) / 5);
      along(RUNNER_ROUTE, runnerProgress, runnerAt);
      runner.position.set(...runnerAt);
      paint(runner.material.color, runnerProgress > 0.5 ? 'work' : 'lounge', dark);
      runner.material.opacity = lit * (dark ? 0.95 : 0.85);
      runner.material.blending = blending;

      // The scripted agent: where the demo's current phase puts it.
      const { phase } = demo.getSnapshot();
      const played = reduced ? 1 : demo.progress();
      if (phase === 'walk') along(HERO_ROUTE, ease(played), heroAt);
      else if (phase === 'waiting') along(HERO_ROUTE, 1, heroAt);
      else if (phase === 'approved' || phase === 'returned') along(HERO_ROUTE, 1 - ease(played), heroAt);
      else along(HERO_ROUTE, 0, heroAt);
      hero.position.set(...heroAt);
      paint(hero.material.color, 'patron', dark);
      hero.material.opacity = lit;
      hero.material.blending = blending;

      const beat = reduced ? 0.35 : (elapsed * (phase === 'work' ? 1.15 : 0.6)) % 1;
      heroRing.position.set(heroAt[0], heroAt[1], 0.02);
      heroRing.scale.setScalar(1 + beat * 2.2);
      paint(heroRing.material.color, 'patron', dark);
      heroRing.material.opacity = lit * (1 - beat) * 0.8;

      // The call for a decision: a column of light and a wide ring over the Patron room.
      const calling = phase === 'waiting' ? lit : 0;
      const call = reduced ? 0.4 : (elapsed * 0.5) % 1;
      beacon.position.set(patronSpot[0], patronSpot[1], 0);
      beacon.scale.set(0.62, 2.7 + Math.sin(elapsed * 2.4) * 0.18, 1);
      paint(beacon.material.color, 'patron', dark);
      beacon.material.opacity = calling * (dark ? 0.55 : 0.4);
      beacon.material.blending = blending;
      callRing.position.set(patronSpot[0], patronSpot[1], 0.02);
      callRing.scale.setScalar(1.5 + call * 5.5);
      paint(callRing.material.color, 'patron', dark);
      callRing.material.opacity = calling * (1 - call) * 0.75;

      // The task: a star that falls from the arms onto the desk, travels with the agent, and
      // rises again once the visitor approves it.
      let taskOpacity = lit;
      let taskScale = 0.36;
      if (phase === 'idle') taskOpacity = 0;
      else if (phase === 'claim') {
        const fall = ease(played);
        for (let axis = 0; axis < 3; axis++) taskAt[axis] = lerp(TASK_ORIGIN[axis], HERO_DESK_TOP[axis], fall);
        taskScale = lerp(1, 0.36, fall);
      } else if (phase === 'work') {
        taskAt[0] = HERO_DESK_TOP[0];
        taskAt[1] = HERO_DESK_TOP[1];
        taskAt[2] = HERO_DESK_TOP[2];
        taskScale = 0.36 + Math.sin(elapsed * 7) * 0.05;
      } else if (phase === 'approved') {
        const rise = Math.min(played * 1.7, 1);
        taskAt[0] = patronSpot[0];
        taskAt[1] = patronSpot[1];
        taskAt[2] = patronSpot[2] + 0.45 + ease(rise) * 3.4;
        taskScale = lerp(0.5, 1.1, rise);
        taskOpacity = lit * (1 - rise);
      } else {
        taskAt[0] = heroAt[0];
        taskAt[1] = heroAt[1];
        taskAt[2] = heroAt[2] + (phase === 'waiting' ? 0.45 + Math.sin(elapsed * 2.4) * 0.05 : 0.36);
      }
      task.position.set(...taskAt);
      task.scale.setScalar(taskScale);
      task.material.color.set(dark ? '#fff4d6' : '#8a5a12');
      task.material.opacity = taskOpacity;
      task.material.blending = blending;

      // DOM pinned to the building. Matrices are refreshed here because render() comes after.
      galaxy.updateMatrixWorld(true);
      camera.updateMatrixWorld();
      labels.current.forEach((element, index) => pin(element, ZONE_LABELS[index].at, 0, formed * clear));
      pin(tag.current, heroAt, 0.62, phase === 'idle' ? 0 : formed * clear);

      renderer.render(scene, camera);
    };
    frame = requestAnimationFrame(animate);

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('scroll', readScroll);
      window.removeEventListener('resize', resize);
      motionQuery.removeEventListener('change', onMotion);
      geometries.forEach((item) => item.dispose());
      materials.forEach((item) => item.dispose());
      texture.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.remove();
    };
  }, [supported, chapterIds, demo]);

  return (
    <div ref={host} aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {/* Static sky: what a browser without WebGL sees, and what shows before the first frame. */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_68%_42%,oklch(var(--sapphire)/0.2),transparent_40%),radial-gradient(ellipse_at_30%_75%,oklch(var(--success)/0.12),transparent_38%)]" />
      {/* Pinned to the building by the frame loop; invisible until the scene places them. */}
      {ZONE_LABELS.map(({ zone }, index) => (
        <span
          key={zone}
          ref={(element) => {
            labels.current[index] = element;
          }}
          className="absolute left-0 top-0 flex flex-col items-center gap-1 whitespace-nowrap font-mono text-[8px] uppercase tracking-[0.12em] text-ink-light opacity-0 will-change-transform sm:text-[10px]"
        >
          {t(`observatory.zone.${zone}`)}
          <i className="h-2.5 w-px bg-line-strong sm:h-4" />
        </span>
      ))}
      <span
        ref={tag}
        className="absolute left-0 top-0 flex items-center gap-1.5 whitespace-nowrap rounded-full border border-gold/50 bg-surface/90 px-2.5 py-1 text-[10px] text-ink-light opacity-0 shadow-soft will-change-transform sm:text-[11px]"
      >
        <strong className="font-semibold text-ink-strong">{DEMO_AGENT}</strong>
        {t(`landing.demo.tag.${snapshot.phase}`, { code: demoTaskCode(snapshot.task) })}
      </span>
    </div>
  );
}
