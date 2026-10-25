import type { Home, Space, Vec2, Wall } from './types';

/** Shoelace area of a plan polygon (m²), independent of winding. */
export function polygonArea(polygon: Vec2[]) {
  let sum = 0;
  for (let i = 0; i < polygon.length; i++) {
    const [x1, z1] = polygon[i], [x2, z2] = polygon[(i + 1) % polygon.length];
    sum += x1 * z2 - x2 * z1;
  }
  return Math.abs(sum) / 2;
}

export function polygonPerimeter(polygon: Vec2[]) {
  let sum = 0;
  for (let i = 0; i < polygon.length; i++) {
    const [x1, z1] = polygon[i], [x2, z2] = polygon[(i + 1) % polygon.length];
    sum += Math.hypot(x2 - x1, z2 - z1);
  }
  return sum;
}

export const wallLength = (w: Wall) => Math.hypot(w.end[0] - w.start[0], w.end[1] - w.start[1]);

/** Face area minus openings, clipped to the wall (m²): paint, plaster, tiling take-off. */
export function wallNetArea(w: Wall) {
  const length = wallLength(w);
  const cut = w.openings.reduce((sum, o) => {
    const du = Math.min(o.u1, length) - Math.max(o.u0, 0);
    const dv = Math.min(o.v1, w.height) - Math.max(o.v0, 0);
    return sum + Math.max(0, du) * Math.max(0, dv);
  }, 0);
  return length * w.height - cut;
}

export interface SpaceSummary {
  id: string;
  name: string;
  floorArea: number | null;
  perimeter: number | null;
  height: number;
  wallNetArea: number;
  doors: number;
  windows: number;
  elements: number;
}

export function summarizeSpace(home: Home, space: Space): SpaceSummary {
  const walls = home.walls.filter(w => w.spaceId === space.id);
  const openings = walls.flatMap(w => w.openings);
  return {
    id: space.id,
    name: space.name,
    floorArea: space.polygon ? polygonArea(space.polygon) : null,
    perimeter: space.polygon ? polygonPerimeter(space.polygon) : null,
    height: space.height,
    wallNetArea: walls.reduce((sum, w) => sum + wallNetArea(w), 0),
    doors: openings.filter(o => o.kind === 'door').length,
    windows: openings.filter(o => o.kind === 'window').length,
    elements: home.elements.filter(e => e.spaceId === space.id).length,
  };
}
