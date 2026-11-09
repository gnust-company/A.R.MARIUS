import * as THREE from 'three';
import { box, cylinder, group, rod, rugTexture, seeded, sphere, torus } from './primitives';

/** Furniture the observatory floor plan actually places. */
export type FurnitureKind = 'sofa' | 'armchair' | 'rug' | 'bookshelf' | 'stereo' | 'bed' | 'bench';

export function plant(parent: THREE.Object3D, size = 1, potColor = '#bd876d', bush = false): THREE.Group {
  const root = group(parent);
  cylinder(root, 0.23, 0.17, 0.35, [0, 0.18, 0], potColor);
  cylinder(root, 0.245, 0.23, 0.07, [0, 0.34, 0], potColor);
  cylinder(root, 0.215, 0.215, 0.01, [0, 0.38, 0], '#63533e');
  const count = bush ? 11 : 7;
  for (let i = 0; i < count; i++) {
    const angle = i * 2.4;
    const height = 0.7 + (i % 3) * 0.17;
    const radius = bush ? 0.23 : 0.27;
    const x = Math.cos(angle) * radius;
    const z = Math.sin(angle) * radius;
    rod(root, [0, 0.34, 0], [x, height, z], 0.014, '#4b4d71');
    const leaf = sphere(root, [x, height, z], [0.11, bush ? 0.21 : 0.26, 0.055], ['#555784', '#585b99', '#626490'][i % 3]);
    leaf.rotation.set(Math.sin(angle) * 0.6, -angle, -Math.cos(angle) * 0.6);
  }
  root.scale.setScalar(size);
  return root;
}

function flowerVase(parent: THREE.Object3D, position: [number, number, number], color = '#e4ddc9'): void {
  const root = group(parent, position);
  sphere(root, [0, 0.13, 0], [0.115, 0.145, 0.115], color);
  cylinder(root, 0.055, 0.08, 0.1, [0, 0.24, 0], color);
  for (let i = 0; i < 5; i++) {
    const x = Math.sin(i * 2.4) * 0.1;
    const z = Math.cos(i * 2.4) * 0.1;
    const y = 0.45 + (i % 2) * 0.07;
    rod(root, [0, 0.24, 0], [x, y, z], 0.008, '#595b88');
    sphere(root, [x, y, z], [0.055, 0.045, 0.055], i % 2 ? '#eed9a1' : '#ede7cc');
  }
}

function legs(root: THREE.Object3D, width: number, depth: number, height: number, color = '#9c7b56'): void {
  for (const x of [-width / 2, width / 2])
    for (const z of [-depth / 2, depth / 2]) rod(root, [x * 1.05, 0.04, z * 1.05], [x, height, z], 0.045, color, 0.035);
}

export function chair(parent: THREE.Object3D, position: [number, number, number], rotation = 0, color = '#ac9c7c'): THREE.Group {
  const root = group(parent, position, rotation);
  legs(root, 0.35, 0.36, 0.46);
  box(root, [0.49, 0.11, 0.49], [0, 0.47, 0], color, 0.06);
  rod(root, [-0.2, 0.45, -0.19], [-0.2, 0.99, -0.23], 0.023, '#ae9471');
  rod(root, [0.2, 0.45, -0.19], [0.2, 0.99, -0.23], 0.023, '#ae9471');
  box(root, [0.45, 0.24, 0.07], [0, 0.83, -0.22], color, 0.07);
  return root;
}

export function coffeeTable(parent: THREE.Object3D, position: [number, number, number]): THREE.Group {
  const root = group(parent, position);
  legs(root, 0.91, 0.41, 0.4);
  box(root, [1.32, 0.095, 0.75], [0, 0.43, 0], '#bc9971', 0.13);
  const book = box(root, [0.31, 0.055, 0.24], [-0.2, 0.51, 0.02], '#e5dfcd', 0.01);
  book.rotation.y = 0.16;
  box(book, [0.315, 0.007, 0.245], [0, 0.031, 0], '#7d7e94', 0.004);
  cylinder(root, 0.09, 0.075, 0.14, [0.3, 0.56, 0.07], '#f3ead7');
  cylinder(root, 0.072, 0.072, 0.007, [0.3, 0.634, 0.07], '#796044');
  torus(root, 0.05, 0.013, [0.395, 0.57, 0.07], '#f3ead7');
  return root;
}

export function makeFurniture(kind: FurnitureKind, color: string): THREE.Group {
  const root = group();
  switch (kind) {
    case 'sofa': {
      legs(root, 2.17, 0.67, 0.25);
      box(root, [2.6, 0.29, 1.02], [0, 0.35, 0], color, 0.11);
      box(root, [2.45, 0.62, 0.26], [0, 0.72, -0.4], color, 0.09);
      for (const x of [-1.19, 1.19]) box(root, [0.25, 0.46, 0.99], [x, 0.64, 0], color, 0.09);
      for (const x of [-0.56, 0.56]) {
        box(root, [1.07, 0.2, 0.78], [x, 0.53, 0.06], color, 0.07);
        box(root, [1.09, 0.46, 0.17], [x, 0.8, -0.21], color, 0.09).rotation.x = 0.12;
      }
      box(root, [0.43, 0.42, 0.15], [-0.84, 0.76, 0.08], '#e6d9ba', 0.09).rotation.set(-0.16, 0.2, -0.22);
      box(root, [0.44, 0.4, 0.16], [0.78, 0.78, 0.01], '#c68f70', 0.09).rotation.set(-0.2, -0.16, 0.19);
      box(root, [0.42, 0.026, 0.7], [0.38, 0.655, 0.16], '#e1d3b7', 0.015).rotation.y = -0.1;
      box(root, [0.42, 0.32, 0.03], [0.42, 0.48, 0.51], '#e1d3b7', 0.01);
      break;
    }
    case 'armchair': {
      legs(root, 0.65, 0.64, 0.27);
      box(root, [0.93, 0.28, 0.87], [0, 0.4, 0], color, 0.11);
      box(root, [0.9, 0.66, 0.2], [0, 0.76, -0.36], color, 0.13);
      for (const x of [-0.42, 0.42]) box(root, [0.16, 0.4, 0.85], [x, 0.62, 0], color, 0.075);
      box(root, [0.7, 0.18, 0.68], [0, 0.55, 0.08], color, 0.065);
      box(root, [0.39, 0.36, 0.13], [0, 0.78, -0.15], '#e7dcc4', 0.08).rotation.x = -0.12;
      break;
    }
    case 'rug': {
      const mat = new THREE.MeshStandardMaterial({ map: rugTexture(color), roughness: 1 });
      box(root, [2.4, 0.025, 1.8], [0, 0.018, 0], mat, 0.018);
      for (let x = -1.1; x <= 1.1; x += 0.09)
        for (const z of [-0.92, 0.92]) box(root, [0.03, 0.012, 0.1], [x, 0.016, z], '#e7dac2', 0.002);
      break;
    }
    case 'bookshelf': {
      box(root, [1.6, 1.85, 0.08], [0, 0.97, -0.2], color);
      for (const x of [-0.75, 0.75]) box(root, [0.09, 1.9, 0.47], [x, 0.98, 0], color);
      for (const y of [0.09, 0.56, 1.02, 1.48, 1.91]) box(root, [1.6, 0.075, 0.5], [0, y, 0], color);
      const random = seeded(24);
      const covers = ['#9e9fb6', '#d2b28b', '#7e7f95', '#d5cbb6', '#bd8876', '#d8c695', '#6a6b7c'];
      for (let row = 0; row < 4; row++)
        for (let col = 0; col < 8; col++) {
          if ((row === 2 && col > 4) || (row === 0 && col < 3)) continue;
          const height = 0.23 + random() * 0.1;
          const book = box(
            root,
            [0.095 + random() * 0.045, height, 0.25],
            [-0.59 + col * 0.155, 0.14 + row * 0.46 + height / 2, 0.01],
            covers[(row * 3 + col) % covers.length],
            0.005,
          );
          if (col === 7) book.rotation.z = 0.14;
        }
      flowerVase(root, [-0.38, 0.14, 0.04], '#dbcaae');
      sphere(root, [0.46, 1.2, 0.02], [0.13, 0.14, 0.13], '#e6d5b5');
      break;
    }
    case 'stereo': {
      legs(root, 0.59, 0.35, 0.38);
      box(root, [0.8, 0.34, 0.47], [0, 0.55, 0], color, 0.05);
      box(root, [0.7, 0.22, 0.018], [0, 0.57, 0.247], '#665e4b', 0.018);
      for (const x of [-0.23, 0.23]) {
        cylinder(root, 0.075, 0.075, 0.02, [x, 0.57, 0.262], '#a49a7d').rotation.x = Math.PI / 2;
        cylinder(root, 0.045, 0.045, 0.02, [x, 0.57, 0.275], '#5b5849').rotation.x = Math.PI / 2;
      }
      box(root, [0.14, 0.08, 0.01], [0, 0.58, 0.26], '#b3b4d8', 0.005);
      const vinyl = cylinder(root, 0.16, 0.16, 0.017, [0, 0.735, 0], '#42463d', 32);
      cylinder(vinyl, 0.045, 0.045, 0.022, [0, 0.002, 0], '#c19170');
      break;
    }
    case 'bed': {
      legs(root, 1.75, 2.12, 0.24);
      box(root, [2.15, 0.3, 2.65], [0, 0.28, 0], '#b49a76', 0.055);
      box(root, [2.17, 1.0, 0.13], [0, 0.68, -1.29], '#b9a07a', 0.04);
      box(root, [2.01, 0.28, 2.48], [0, 0.52, 0], '#f3eddc', 0.1);
      box(root, [2.05, 0.24, 1.76], [0, 0.66, 0.39], color, 0.1);
      for (const x of [-0.51, 0.51]) box(root, [0.8, 0.18, 0.52], [x, 0.74, -0.89], '#f2ebda', 0.12).rotation.y = x * 0.04;
      box(root, [2.09, 0.035, 0.43], [0, 0.797, 0.95], '#d5bb9e', 0.02);
      for (let x = -0.94; x < 1; x += 0.12) box(root, [0.022, 0.009, 0.43], [x, 0.82, 0.95], '#eee2cc', 0.003);
      box(root, [0.06, 0.37, 0.43], [1.04, 0.61, 0.95], '#d5bb9e', 0.02);
      box(root, [0.06, 0.37, 0.43], [-1.04, 0.61, 0.95], '#d5bb9e', 0.02);
      break;
    }
    case 'bench': {
      for (const x of [-0.66, 0.66]) {
        box(root, [0.07, 0.44, 0.5], [x, 0.25, 0], '#54556d');
        rod(root, [x, 0.25, -0.21], [x, 0.92, -0.3], 0.03, '#54556d');
      }
      for (let i = 0; i < 4; i++) box(root, [1.8, 0.06, 0.11], [0, 0.49, -0.18 + i * 0.12], color);
      for (let i = 0; i < 3; i++) box(root, [1.8, 0.1, 0.055], [0, 0.65 + i * 0.12, -0.25 - i * 0.017], color);
      break;
    }
  }
  return root;
}
