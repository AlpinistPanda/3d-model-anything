import { HOME_FORMAT, type Home } from './types';

export * from './types';
export * from './measure';

/**
 * Structural check for a loaded home.json: format, unique IDs and references between entities.
 * Throws on the first problem; it does not validate geometry.
 */
export function parseHome(data: unknown): Home {
  const home = data as Home;
  if (!home || home.format !== HOME_FORMAT) throw new Error(`expected ${HOME_FORMAT}`);
  for (const key of ['levels', 'spaces', 'walls', 'elements', 'unplaced'] as const)
    if (!Array.isArray(home[key])) throw new Error(`missing ${key}`);
  const ids = new Set<string>();
  const unique = (id: string) => {
    if (ids.has(id)) throw new Error(`duplicate id ${id}`);
    ids.add(id);
  };
  [...home.levels, ...home.spaces, ...home.walls, ...home.elements, ...home.walls.flatMap(w => w.openings)].forEach(x => unique(x.id));
  const levels = new Set(home.levels.map(l => l.id));
  const spaces = new Set(home.spaces.map(s => s.id));
  const walls = new Set(home.walls.map(w => w.id));
  for (const x of [...home.spaces, ...home.walls, ...home.elements])
    if (!levels.has(x.levelId)) throw new Error(`${x.id}: unknown level ${x.levelId}`);
  for (const x of [...home.walls, ...home.elements])
    if (!spaces.has(x.spaceId)) throw new Error(`${x.id}: unknown space ${x.spaceId}`);
  for (const s of home.spaces) for (const id of s.wallIds)
    if (!walls.has(id)) throw new Error(`${s.id}: unknown wall ${id}`);
  for (const w of home.walls) if (w.adjacent && !walls.has(w.adjacent.wallId))
    throw new Error(`${w.id}: unknown adjacent wall ${w.adjacent.wallId}`);
  return home;
}
