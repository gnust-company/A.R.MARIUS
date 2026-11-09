import * as THREE from 'three';
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js';
import { box, contactShadow, cylinder, group, material, sphere, torus } from './primitives';

/** How a figure looks. Picked deterministically from the agent's id, so it never changes. */
export interface Appearance {
  skin: string;
  hair: string;
  shirt: string;
  hairstyle: 'bob' | 'crop' | 'curls';
}

/** The articulated parts the observatory animates; everything else is merged. */
export interface CharacterRig {
  root: THREE.Group;
  body: THREE.Group;
  head: THREE.Group;
  leftArm: THREE.Group;
  rightArm: THREE.Group;
  leftLeg: THREE.Group;
  rightLeg: THREE.Group;
  routineDial: THREE.Group;
  ring: THREE.Mesh;
}

/** Merge facial details and hair per material: the head moves as one part. */
function optimizeHead(head: THREE.Group): void {
  head.updateMatrixWorld(true);
  const inverse = head.matrixWorld.clone().invert();
  const batches = new Map<THREE.Material, THREE.BufferGeometry[]>();
  const originals: THREE.Mesh[] = [];
  head.traverse((object) => {
    if (!(object instanceof THREE.Mesh) || Array.isArray(object.material)) return;
    const geometry = object.geometry.index ? object.geometry.toNonIndexed() : object.geometry.clone();
    geometry.applyMatrix4(new THREE.Matrix4().multiplyMatrices(inverse, object.matrixWorld));
    const list = batches.get(object.material) ?? [];
    list.push(geometry);
    batches.set(object.material, list);
    originals.push(object);
  });
  originals.forEach((object) => object.removeFromParent());
  for (const [mat, geometries] of batches) {
    const geometry = mergeGeometries(geometries, false);
    geometries.forEach((item) => item.dispose());
    if (!geometry) continue;
    const mesh = new THREE.Mesh(geometry, mat);
    mesh.castShadow = mesh.receiveShadow = true;
    head.add(mesh);
  }
}

export function createCharacter(appearance: Appearance): CharacterRig {
  const root = group();
  contactShadow(root, 0, 0, 0.65, 0.52, 0.014, 0.28);
  const body = group(root);
  const { skin, hair, shirt, hairstyle } = appearance;
  const leftLeg = group(body, [-0.105, 0.45, 0]);
  const rightLeg = group(body, [0.105, 0.45, 0]);
  for (const leg of [leftLeg, rightLeg]) {
    box(leg, [0.155, 0.36, 0.17], [0, -0.17, 0], '#595a67', 0.055);
    box(leg, [0.18, 0.12, 0.28], [0, -0.355, 0.035], '#e8e1ce', 0.04);
    box(leg, [0.18, 0.025, 0.28], [0, -0.4, 0.035], '#c4bfae', 0.015);
  }
  box(body, [0.41, 0.42, 0.24], [0, 0.67, 0], shirt, 0.1);
  box(body, [0.4, 0.065, 0.245], [0, 0.49, 0], shirt, 0.025);
  cylinder(body, 0.08, 0.075, 0.14, [0, 0.9, 0], skin);
  torus(body, 0.084, 0.015, [0, 0.865, 0], '#e4d2b0').rotation.x = Math.PI / 2;
  const leftArm = group(body, [-0.225, 0.82, 0]);
  const rightArm = group(body, [0.225, 0.82, 0]);
  for (const arm of [leftArm, rightArm]) {
    box(arm, [0.135, 0.25, 0.155], [0, -0.085, 0], shirt, 0.057);
    box(arm, [0.105, 0.13, 0.12], [0, -0.26, 0], skin, 0.047);
    sphere(arm, [0, -0.34, 0.005], [0.066, 0.075, 0.066], skin);
  }
  leftArm.rotation.z = -0.07;
  rightArm.rotation.z = 0.07;
  const head = group(body, [0, 1.095, 0]);
  sphere(head, [0, 0, -0.025], [0.257, 0.286, 0.221], hair, 20);
  sphere(head, [0, -0.024, 0.035], [0.218, 0.239, 0.205], skin, 24);
  for (const side of [-1, 1]) {
    sphere(head, [side * 0.211, -0.045, 0.025], [0.045, 0.061, 0.045], skin);
    sphere(head, [side * 0.078, 0.007, 0.22], [0.018, 0.027, 0.012], '#3b3028', 12);
    sphere(head, [side * 0.082 + 0.005, 0.014, 0.23], [0.005, 0.007, 0.003], '#f2eddf', 8);
    box(head, [0.048, 0.009, 0.012], [side * 0.08, 0.063, 0.221], hair, 0.004).rotation.z = -side * 0.11;
    sphere(head, [side * 0.119, -0.06, 0.204], [0.035, 0.02, 0.009], '#d88e7b', 12);
  }
  sphere(head, [0, -0.031, 0.24], [0.032, 0.036, 0.04], skin);
  torus(head, 0.043, 0.007, [0, -0.081, 0.222], '#905b48', Math.PI).rotation.z = Math.PI;
  if (hairstyle === 'bob') {
    for (const side of [-1, 1]) {
      sphere(head, [side * 0.216, -0.031, -0.02], [0.072, 0.247, 0.19], hair, 16).rotation.z = side * 0.05;
      sphere(head, [side * 0.154, 0.16, 0.133], [0.116, 0.098, 0.11], hair, 16);
    }
    sphere(head, [-0.054, 0.204, 0.135], [0.157, 0.07, 0.117], hair, 16).rotation.z = -0.18;
    box(head, [0.05, 0.018, 0.04], [0.215, 0.058, 0.146], '#c2a565', 0.009).rotation.z = -0.15;
  } else if (hairstyle === 'crop') {
    sphere(head, [0.0, 0.174, 0.044], [0.253, 0.16, 0.231], hair, 16);
    sphere(head, [-0.079, 0.173, 0.19], [0.158, 0.08, 0.087], hair, 16).rotation.z = -0.2;
    sphere(head, [0.18, 0.083, 0.035], [0.052, 0.118, 0.13], hair);
  } else {
    for (let i = 0; i < 13; i++) {
      const angle = (i / 13) * Math.PI * 2;
      sphere(head, [Math.cos(angle) * 0.225, 0.1 + Math.sin(angle) * 0.16, -0.038], [0.095, 0.095, 0.16], hair);
    }
    for (let i = 0; i < 5; i++) sphere(head, [-0.18 + i * 0.087, 0.19 + Math.sin(i) * 0.03, 0.145], [0.07, 0.075, 0.073], hair);
  }

  // The routine dial floats above the head of an agent that is mid-routine.
  const routineDial = group(root, [0, 1.73, 0]);
  routineDial.add(
    new THREE.Mesh(
      new THREE.TorusGeometry(0.12, 0.025, 8, 24),
      new THREE.MeshStandardMaterial({ color: '#4c50ad', roughness: 0.22, metalness: 0.06, emissive: '#292b65', emissiveIntensity: 0.08, flatShading: true }),
    ),
  );
  for (let n = 0; n < 3; n++) {
    const tick = new THREE.Mesh(new THREE.BoxGeometry(0.025, 0.045, 0.02), material('#e6ad8c'));
    tick.position.set((n - 1) * 0.065, -0.18, 0);
    routineDial.add(tick);
  }
  box(body, [0.14, 0.16, 0.035], [0.1, 0.67, 0.135], '#ebbaa1', 0.012);
  box(body, [0.12, 0.015, 0.045], [0.1, 0.75, 0.15], '#fff0d8', 0.004);

  // Selection ring on the floor. Its own material, because its colour follows the agent.
  const ring = new THREE.Mesh(new THREE.TorusGeometry(0.38, 0.014, 6, 24), new THREE.MeshStandardMaterial({ color: '#5c5fa6', roughness: 0.8 }));
  ring.position.set(0, 0.018, 0);
  ring.rotation.x = -Math.PI / 2;
  root.add(ring);
  optimizeHead(head);
  return { root, body, head, leftArm, rightArm, leftLeg, rightLeg, routineDial, ring };
}
