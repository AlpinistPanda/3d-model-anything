/**
 * home-model/1: the semantic home, stored as data. Written by home_from_capture.py, read by
 * viewers, exporters (IFC), estimators and inventory. Everything else is generated from it.
 *
 * Frame: the house frame of the capture (house.json zone/session placements). Meters, +Y up,
 * right-handed. Plan coordinates are [x, z]. Elevations are absolute house-frame y values.
 */
export const HOME_FORMAT = 'home-model/1';

export type Vec2 = [number, number];
export type Vec3 = [number, number, number];

/** Free-form annotations (finish, loadBearing, notes, …) that survive re-import by ID. */
export type Properties = Record<string, string | number | boolean>;

export interface Home {
  format: typeof HOME_FORMAT;
  /** house.json id */
  id: string;
  name: string;
  units: 'm';
  generatedFrom: { tool: string; house: string; generatedAt: string };
  levels: Level[];
  spaces: Space[];
  walls: Wall[];
  elements: Element[];
  /** captured rooms that could not be placed in the house frame */
  unplaced: Unplaced[];
}

/** Where an entity came from in the capture, for re-import and photo lookup. */
export interface Source {
  session: string;
  /** room index inside the session bundle */
  room: number;
  /** RoomPlan identifier, when the export has one */
  identifier?: string;
  confidence?: string;
}

export interface Level {
  /** `level:<n>`, numbered from the lowest floor */
  id: string;
  name: string;
  /** floor elevation (house-frame y) */
  elevation: number;
}

export interface Space {
  /** the house room's stable ID */
  id: string;
  name: string;
  levelId: string;
  /** floor y of this space (spaces on one level can differ by a step) */
  floorY: number;
  /** tallest captured wall; RoomPlan assumes flat ceilings */
  height: number;
  /** floor outline, counter-clockwise seen from above; null when the scan has none */
  polygon: Vec2[] | null;
  wallIds: string[];
  source: Source;
  properties?: Properties;
}

export type OpeningKind = 'door' | 'window' | 'opening';

/** Rectangle in wall coordinates: u along the wall from `start`, v up from the wall base. */
export interface Opening {
  id: string;
  kind: OpeningKind;
  u0: number;
  u1: number;
  v0: number;
  v1: number;
  isOpen?: boolean;
  source: Source;
  properties?: Properties;
}

/**
 * One captured wall face. RoomPlan reports each room's face separately, so a partition between
 * two spaces is two Walls linked through `adjacent`.
 */
export interface Wall {
  id: string;
  spaceId: string;
  levelId: string;
  /** interior face, left end, seen from inside the space */
  start: Vec2;
  end: Vec2;
  /** unit plan direction into the space */
  normal: Vec2;
  /** y of the wall bottom */
  base: number;
  height: number;
  /** measured from a paired face; null when unknown (exterior or unmatched) */
  thickness: number | null;
  /** the opposite face of the same partition, in another space */
  adjacent?: { wallId: string; spaceId: string };
  openings: Opening[];
  source: Source;
  properties?: Properties;
}

/** Furniture, fixtures and appliances: RoomPlan's object boxes, refined later. */
export interface Element {
  id: string;
  /** RoomPlan category (sofa, table, storage, refrigerator, …) */
  category: string;
  name?: string;
  spaceId: string;
  levelId: string;
  /** box center */
  position: Vec3;
  /** rotation about +Y that turns local +Z to the element's front */
  rotY: number;
  /** [width, height, depth] */
  size: Vec3;
  source: Source;
  properties?: Properties;
}

export interface Unplaced {
  roomId: string;
  name: string;
  reason: string;
}
