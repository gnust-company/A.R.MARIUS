import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import * as THREE from 'three';
import type { Theme } from '@/hooks/use-theme';

/*
 * The landing page's galaxy: a spiral of points that the page scrolls through (four chapters,
 * one continuous journey). Fixed behind the copy, never interactive.
 *
 * The hex colours are star light inside the WebGL scene, not UI chrome. Light theme swaps the
 * additive glow for normal blending and deeper inks so the spiral still reads on a pale sky.
 */

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

export default function GalaxyScene({ theme }: { theme: Theme }) {
  const host = useRef<HTMLDivElement>(null);
  const currentTheme = useRef(theme);
  const [supported] = useState(webglAvailable);

  useLayoutEffect(() => {
    currentTheme.current = theme;
  }, [theme]);

  useEffect(() => {
    const container = host.current;
    if (!container || !supported) return;
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    let reduced = motionQuery.matches;
    const onMotion = (event: MediaQueryListEvent) => {
      reduced = event.matches;
    };
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: 'high-performance' });
    } catch {
      // The gradient fallback underneath stays visible.
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
    container.appendChild(canvas);

    const galaxy = new THREE.Group();
    const disk = new THREE.Group();
    galaxy.add(disk);
    scene.add(galaxy);
    const texture = glowTexture();
    const geometries: THREE.BufferGeometry[] = [];
    const materials: THREE.Material[] = [];

    // Four spiral arms, warm at the core and cooling outward.
    const count = window.innerWidth < 700 ? 8500 : 15500;
    const positions = new Float32Array(count * 3);
    const colors = new Float32Array(count * 3);
    const inner = new THREE.Color('#ffe0a3');
    const middle = new THREE.Color('#83a7ff');
    const outer = new THREE.Color('#74e4da');
    const mixed = new THREE.Color();
    for (let index = 0; index < count; index++) {
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
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    const material = new THREE.PointsMaterial({ size: 0.105, map: texture, transparent: true, opacity: 0.94, vertexColors: true, depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true });
    disk.add(new THREE.Points(geometry, material));
    geometries.push(geometry);
    materials.push(material);

    const coreGeometry = new THREE.BufferGeometry();
    const corePositions = new Float32Array(2100 * 3);
    for (let index = 0; index < 2100; index++) {
      const radius = Math.pow(random(), 2.7) * 2.1;
      const theta = random() * Math.PI * 2;
      const phi = Math.acos(2 * random() - 1);
      corePositions[index * 3] = radius * Math.sin(phi) * Math.cos(theta);
      corePositions[index * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      corePositions[index * 3 + 2] = radius * Math.cos(phi) * 0.48;
    }
    coreGeometry.setAttribute('position', new THREE.BufferAttribute(corePositions, 3));
    const coreMaterial = new THREE.PointsMaterial({ color: '#ffdc96', size: 0.12, map: texture, transparent: true, opacity: 0.82, depthWrite: false, blending: THREE.AdditiveBlending });
    disk.add(new THREE.Points(coreGeometry, coreMaterial));
    geometries.push(coreGeometry);
    materials.push(coreMaterial);

    const starGeometry = new THREE.BufferGeometry();
    const starPositions = new Float32Array(1500 * 3);
    for (let index = 0; index < 1500; index++) {
      starPositions[index * 3] = (random() - 0.5) * 70;
      starPositions[index * 3 + 1] = (random() - 0.5) * 48;
      starPositions[index * 3 + 2] = -8 - random() * 45;
    }
    starGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    const starMaterial = new THREE.PointsMaterial({ color: '#b9cfff', size: 0.085, map: texture, transparent: true, opacity: 0.68, depthWrite: false, blending: THREE.AdditiveBlending });
    scene.add(new THREE.Points(starGeometry, starMaterial));
    geometries.push(starGeometry);
    materials.push(starMaterial);

    const rings = new THREE.Group();
    [2.8, 5.7, 9.2].forEach((radius, index) => {
      const curve = new THREE.EllipseCurve(0, 0, radius, radius, 0, Math.PI * 2, false, index * 0.65);
      const ringGeometry = new THREE.BufferGeometry().setFromPoints(curve.getPoints(180));
      const ringMaterial = new THREE.LineBasicMaterial({ color: index === 1 ? '#e5bb72' : '#879fe5', transparent: true, opacity: 0.12 });
      const ring = new THREE.LineLoop(ringGeometry, ringMaterial);
      ring.rotation.x = index * 0.14;
      rings.add(ring);
      geometries.push(ringGeometry);
      materials.push(ringMaterial);
    });
    disk.add(rings);

    let frame = 0;
    let previous = 0;
    let elapsed = 0;
    let targetProgress = 0;
    let smoothProgress = 0;
    const readScroll = () => {
      const available = Math.max(document.documentElement.scrollHeight - window.innerHeight, 1);
      targetProgress = THREE.MathUtils.clamp(window.scrollY / available, 0, 1);
    };
    const resize = () => {
      const width = container.clientWidth;
      const height = container.clientHeight;
      renderer.setSize(width, height, false);
      camera.aspect = width / Math.max(height, 1);
      camera.updateProjectionMatrix();
    };
    readScroll();
    resize();
    window.addEventListener('scroll', readScroll, { passive: true });
    window.addEventListener('resize', resize);
    motionQuery.addEventListener('change', onMotion);

    const lerp = THREE.MathUtils.lerp;
    const animate = (time: number) => {
      frame = requestAnimationFrame(animate);
      const delta = Math.min((time - (previous || time)) / 1000, 0.05);
      previous = time;
      // Reduced motion: the galaxy holds still; it only follows the scroll position.
      if (!reduced) elapsed += delta;
      smoothProgress = reduced ? targetProgress : lerp(smoothProgress, targetProgress, 0.045);
      const mobile = window.innerWidth < 760;
      const dark = currentTheme.current === 'dark';
      const chapter = smoothProgress * 2;
      galaxy.position.x =
        chapter < 1
          ? lerp(mobile ? 0.8 : 3.4, mobile ? -0.5 : -3.2, chapter)
          : lerp(mobile ? -0.5 : -3.2, mobile ? 0 : 1.4, chapter - 1);
      galaxy.position.y = mobile ? 1.4 - smoothProgress * 1.2 : Math.sin(smoothProgress * Math.PI * 2) * 0.7;
      galaxy.rotation.x = 0.86 + smoothProgress * 0.48;
      galaxy.rotation.y = -0.1 + Math.sin(smoothProgress * Math.PI) * 0.32;
      disk.rotation.z = elapsed * 0.032 + smoothProgress * Math.PI * 1.45;
      rings.rotation.z = -elapsed * 0.012;
      camera.position.z = 20 - Math.sin(smoothProgress * Math.PI) * 6 + smoothProgress * 2;
      camera.position.y = Math.sin(smoothProgress * Math.PI * 2) * 1.1;
      camera.lookAt(0, 0, 0);
      const blending = dark ? THREE.AdditiveBlending : THREE.NormalBlending;
      material.size = dark ? 0.105 : 0.13;
      material.opacity = dark ? 0.94 : 0.88;
      material.blending = blending;
      coreMaterial.opacity = dark ? 0.82 : 0.68;
      coreMaterial.color.set(dark ? '#ffdc96' : '#b96d28');
      coreMaterial.blending = blending;
      starMaterial.opacity = dark ? 0.68 : 0.25;
      starMaterial.color.set(dark ? '#b9cfff' : '#536d9d');
      starMaterial.blending = blending;
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
  }, [supported]);

  return (
    <div ref={host} aria-hidden="true" className="pointer-events-none fixed inset-0 z-0 overflow-hidden">
      {/* Static sky: what a browser without WebGL sees, and what shows before the first frame. */}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_68%_42%,oklch(var(--sapphire)/0.2),transparent_40%),radial-gradient(ellipse_at_30%_75%,oklch(var(--success)/0.12),transparent_38%)]" />
    </div>
  );
}
