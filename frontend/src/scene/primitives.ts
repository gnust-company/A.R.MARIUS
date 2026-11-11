import * as THREE from 'three';
import { RoundedBoxGeometry } from 'three/addons/geometries/RoundedBoxGeometry.js';

/*
 * Building blocks for the observatory diorama. Colours passed here are scene materials (wood,
 * fabric, walls), not UI chrome: they live inside the WebGL scene and are lit by its lights,
 * so they cannot follow the CSS theme tokens. The theme reaches the scene through lighting.
 */

/*
 * Shared by every scene built from this module, so they are counted: a scene takes a hold with
 * `retainCaches()` when it starts and gives it back with `releaseCaches()` when it goes, and
 * the caches are emptied only when the last one has gone. Today one scene lives at a time; two
 * side by side must not have the first to leave empty what the other is still drawing with.
 */
const geometryCache = new Map<string, THREE.BufferGeometry>();
const materialCache = new Map<string, THREE.MeshStandardMaterial>();
let cacheHolds = 0;

export function material(color: string, roughness = 0.8): THREE.MeshStandardMaterial {
  const key = `${color}:${roughness}`;
  let cached = materialCache.get(key);
  if (!cached) {
    cached = new THREE.MeshStandardMaterial({ color, roughness });
    materialCache.set(key, cached);
  }
  return cached;
}

function cachedGeometry(key: string, make: () => THREE.BufferGeometry): THREE.BufferGeometry {
  let geometry = geometryCache.get(key);
  if (!geometry) {
    geometry = make();
    geometryCache.set(key, geometry);
  }
  return geometry;
}

function resolve(color: string | THREE.Material): THREE.Material {
  return typeof color === 'string' ? material(color) : color;
}

export function box(
  parent: THREE.Object3D,
  size: [number, number, number],
  position: [number, number, number],
  color: string | THREE.Material,
  radius = 0.025,
): THREE.Mesh {
  const safeRadius = Math.min(radius, Math.min(...size) / 2.1);
  const geometry = cachedGeometry(`box:${size.join(',')}:${safeRadius}`, () =>
    safeRadius > 0.005 ? new RoundedBoxGeometry(...size, 2, safeRadius) : new THREE.BoxGeometry(...size),
  );
  const mesh = new THREE.Mesh(geometry, resolve(color));
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

export function cylinder(
  parent: THREE.Object3D,
  top: number,
  bottom: number,
  height: number,
  position: [number, number, number],
  color: string | THREE.Material,
  segments = 16,
): THREE.Mesh {
  const geometry = cachedGeometry(`cyl:${top},${bottom},${height},${segments}`, () =>
    new THREE.CylinderGeometry(top, bottom, height, segments),
  );
  const mesh = new THREE.Mesh(geometry, resolve(color));
  mesh.position.set(...position);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

export function sphere(
  parent: THREE.Object3D,
  position: [number, number, number],
  scale: [number, number, number],
  color: string | THREE.Material,
  detail = 12,
): THREE.Mesh {
  const geometry = cachedGeometry(`sphere:${detail}`, () =>
    new THREE.SphereGeometry(1, detail, Math.max(6, detail / 2)),
  );
  const mesh = new THREE.Mesh(geometry, resolve(color));
  mesh.position.set(...position);
  mesh.scale.set(...scale);
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  parent.add(mesh);
  return mesh;
}

/** A thin cylinder from one point to another (legs, rails, stems). */
export function rod(
  parent: THREE.Object3D,
  from: [number, number, number],
  to: [number, number, number],
  radius: number,
  color: string,
  radiusEnd = radius,
): THREE.Mesh {
  const a = new THREE.Vector3(...from);
  const b = new THREE.Vector3(...to);
  const mesh = cylinder(parent, radiusEnd, radius, a.distanceTo(b), [0, 0, 0], color, 8);
  mesh.position.copy(a.clone().add(b).multiplyScalar(0.5));
  mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), b.sub(a).normalize());
  return mesh;
}

export function torus(
  parent: THREE.Object3D,
  radius: number,
  tube: number,
  position: [number, number, number],
  color: string,
  arc = Math.PI * 2,
): THREE.Mesh {
  const geometry = cachedGeometry(`torus:${radius},${tube},${arc}`, () =>
    new THREE.TorusGeometry(radius, tube, 6, 24, arc),
  );
  const mesh = new THREE.Mesh(geometry, material(color));
  mesh.position.set(...position);
  parent.add(mesh);
  return mesh;
}

export function group(
  parent?: THREE.Object3D,
  position: [number, number, number] = [0, 0, 0],
  rotation = 0,
): THREE.Group {
  const result = new THREE.Group();
  result.position.set(...position);
  result.rotation.y = rotation;
  parent?.add(result);
  return result;
}

/** Deterministic pseudo-random sequence: the same seed draws the same office every time. */
export function seeded(seed: number): () => number {
  let state = seed;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function canvas2d(width: number, height: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) throw new Error('2D canvas unavailable');
  return [canvas, context];
}

export function woodTexture(): THREE.CanvasTexture {
  const [canvas, ctx] = canvas2d(512, 512);
  const random = seeded(23);
  for (let y = 0; y < 512; y += 48) {
    for (let x = -128 * ((y / 48) % 2); x < 512; x += 256) {
      const value = 207 + Math.floor(random() * 30);
      ctx.fillStyle = `rgb(${value + 15},${value + 8},${value})`;
      ctx.fillRect(x, y, 255, 47);
      ctx.fillStyle = '#8d755b25';
      ctx.fillRect(x, y + 46, 256, 2);
      ctx.fillRect(x + 253, y, 2, 47);
      for (let i = 0; i < 9; i++) {
        ctx.strokeStyle = `rgba(125,102,75,${0.035 + random() * 0.07})`;
        ctx.lineWidth = 0.6 + random();
        ctx.beginPath();
        const grainY = y + random() * 46;
        ctx.moveTo(x, grainY);
        ctx.bezierCurveTo(x + 75, grainY - 3, x + 120, grainY + 4, x + 256, grainY);
        ctx.stroke();
      }
    }
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = texture.wrapT = THREE.RepeatWrapping;
  texture.repeat.set(2.6, 2.6);
  texture.anisotropy = 8;
  return texture;
}

export function rugTexture(color: string): THREE.CanvasTexture {
  const [canvas, ctx] = canvas2d(256, 256);
  ctx.fillStyle = color;
  ctx.fillRect(0, 0, 256, 256);
  ctx.strokeStyle = '#faf1df';
  ctx.lineWidth = 3;
  ctx.strokeRect(15, 15, 226, 226);
  ctx.strokeRect(22, 22, 212, 212);
  const random = seeded(41);
  for (let i = 0; i < 2200; i++) {
    ctx.fillStyle = random() > 0.5 ? '#fff5' : '#88775b25';
    ctx.fillRect(random() * 256, random() * 256, 0.8, 3);
  }
  ctx.strokeStyle = '#f5e9d880';
  ctx.lineWidth = 2;
  for (let x = 40; x < 230; x += 30) {
    ctx.beginPath();
    ctx.moveTo(x, 32);
    ctx.lineTo(x, 224);
    ctx.stroke();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = 8;
  return texture;
}

let contactTexture: THREE.CanvasTexture | undefined;

/** A soft dark ellipse under a figure so it reads as standing on the floor. */
export function contactShadow(
  parent: THREE.Object3D,
  x: number,
  z: number,
  sx: number,
  sz: number,
  y = 0.015,
  opacity = 0.18,
): void {
  if (!contactTexture) {
    const [canvas, ctx] = canvas2d(64, 64);
    const gradient = ctx.createRadialGradient(32, 32, 3, 32, 32, 32);
    gradient.addColorStop(0, '#3b3b45bb');
    gradient.addColorStop(0.45, '#3b3b4560');
    gradient.addColorStop(1, '#3b3b4500');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, 64, 64);
    contactTexture = new THREE.CanvasTexture(canvas);
  }
  const mesh = new THREE.Mesh(
    new THREE.PlaneGeometry(sx, sz),
    new THREE.MeshBasicMaterial({ map: contactTexture, transparent: true, opacity, depthWrite: false }),
  );
  mesh.rotation.x = -Math.PI / 2;
  mesh.position.set(x, y, z);
  parent.add(mesh);
}

/** A scene that draws with the shared geometries and materials takes a hold on them. */
export function retainCaches(): void {
  cacheHolds += 1;
}

/** Give a hold back. The caches are emptied when no scene holds them any more. */
export function releaseCaches(): void {
  if (cacheHolds === 0) return;
  cacheHolds -= 1;
  if (cacheHolds === 0) disposeCaches();
}

/** Release every shared geometry, material and texture. */
function disposeCaches(): void {
  geometryCache.forEach((geometry) => geometry.dispose());
  geometryCache.clear();
  materialCache.forEach((item) => item.dispose());
  materialCache.clear();
  contactTexture?.dispose();
  contactTexture = undefined;
}
