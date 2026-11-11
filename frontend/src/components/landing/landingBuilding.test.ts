import { describe, expect, it } from 'vitest';
import { HERO_ROUTE, TINTS, along, buildCloud, type Vec3 } from './landingBuilding';

function seeded(seed: number) {
  return () => {
    seed = (seed * 1664525 + 1013904223) >>> 0;
    return seed / 4294967296;
  };
}

describe('landing building', () => {
  it('fills exactly the requested number of points, all inside the floor', () => {
    const cloud = buildCloud(5000, seeded(7));
    expect(cloud.positions.length).toBe(15000);
    let filled = 0;
    for (let i = 0; i < 5000; i++) {
      const x = cloud.positions[i * 3];
      const y = cloud.positions[i * 3 + 1];
      const z = cloud.positions[i * 3 + 2];
      if (x !== 0 || y !== 0) filled++;
      expect(Math.abs(x)).toBeLessThan(4.3);
      expect(Math.abs(y)).toBeLessThan(4.3);
      expect(z).toBeGreaterThan(-0.05);
      expect(cloud.tints[i]).toBeLessThan(TINTS.length);
    }
    expect(filled).toBeGreaterThan(4990);
  });

  it('is the same building for the same seed', () => {
    expect(buildCloud(800, seeded(3)).positions).toEqual(buildCloud(800, seeded(3)).positions);
  });

  it('walks a route from its first point to its last', () => {
    const out: Vec3 = [0, 0, 0];
    expect(along(HERO_ROUTE, 0, out)).toEqual(HERO_ROUTE[0]);
    expect(along(HERO_ROUTE, 1, out)).toEqual(HERO_ROUTE[HERO_ROUTE.length - 1]);
    const middle = along(HERO_ROUTE, 0.5, [0, 0, 0]);
    expect(middle[1]).toBeLessThan(HERO_ROUTE[0][1]);
    expect(middle[1]).toBeGreaterThan(HERO_ROUTE[HERO_ROUTE.length - 1][1]);
  });
});
