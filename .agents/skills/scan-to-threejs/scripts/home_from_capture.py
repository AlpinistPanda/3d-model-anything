#!/usr/bin/env python3
"""Build a home-model/1 home.json from a whole-house capture.

usage: home_from_capture.py <house folder | house-rebuild index dir> -o home.json

Input is either an unpacked house-project/1 export (converted with house_to_rooms.py first) or
an existing house_to_rooms.py output directory. Every placed room becomes a Space with its
walls, openings and RoomPlan objects in the shared house frame. Spaces are grouped into levels
by floor elevation, and opposite wall faces of neighbouring spaces are paired to estimate
partition thickness. Rooms without a validated placement are listed in `unplaced`, never guessed.

The schema is packages/home-model/types.ts. Uses only the Python standard library; never
overwrites the output or edits the capture.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sys
import tempfile

from bundle_to_room import apply, mat
from house_to_rooms import export_house, rigid

LEVEL_GAP = 1.0  # m: floors closer than this share a level (steps, sunken rooms)
PAIR_GAP = (0.02, 0.6)  # m: plausible partition thickness between paired faces
PAIR_OVERLAP = 0.3  # m: paired faces must run alongside each other at least this far
CHAIN_GAP = 0.3  # m: wall ends this close are joined when deriving a missing floor outline


def r(v, n=4):
    return round(v, n)


def chain_polygon(walls):
    """Floor outline from wall ends, for scans without floor corners; None if they don't close."""
    if len(walls) < 3:
        return None
    left = [(w['a'], w['b']) for w in walls[1:]]
    loop = [walls[0]['a'], walls[0]['b']]
    while left:
        end = loop[-1]
        a, b = min(left, key=lambda s: min(math.dist(s[0], end), math.dist(s[1], end)))
        if min(math.dist(a, end), math.dist(b, end)) > CHAIN_GAP:
            return None
        left.remove((a, b))
        loop.append(b if math.dist(a, end) <= math.dist(b, end) else a)
    if math.dist(loop[-1], loop[0]) > CHAIN_GAP:
        return None
    return loop[:-1]


def inside(poly, x, z):
    hit = False
    for i in range(len(poly)):
        (x1, z1), (x2, z2) = poly[i], poly[(i + 1) % len(poly)]
        if (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            hit = not hit
    return hit


def orient_walls(walls, polygon):
    """Make every wall's normal face into the room (bundle_to_room.py can't without a floor outline).
    A flipped wall starts from its other end, so its openings are mirrored along u."""
    if polygon:
        faces_in = lambda m, n: inside(polygon, m[0] + n[0] * 0.05, m[1] + n[2] * 0.05)
    else:
        mids = [[(w['a'][0] + w['b'][0]) / 2, (w['a'][1] + w['b'][1]) / 2] for w in walls]
        c = [sum(m[0] for m in mids) / len(mids), sum(m[1] for m in mids) / len(mids)] if mids else [0, 0]
        faces_in = lambda m, n: (c[0] - m[0]) * n[0] + (c[1] - m[1]) * n[2] >= 0
    out = []
    for w in walls:
        mid = [(w['a'][0] + w['b'][0]) / 2, (w['a'][1] + w['b'][1]) / 2]
        if faces_in(mid, w['n']):
            out.append(w)
            continue
        L = w['length']
        out.append({**w, 'a': w['b'], 'b': w['a'],
                    'origin': [w['b'][0], w['origin'][1], w['b'][1]],
                    'u': [-v for v in w['u']], 'n': [-v for v in w['n']],
                    'openings': sorted(({**o, 'u0': r(L - o['u1'], 3), 'u1': r(L - o['u0'], 3)} for o in w['openings']),
                                       key=lambda o: o['u0'])})
    return out


def counter_clockwise(poly):
    # Seen from above (+y) with x right and -z up, as in bundle_to_room.py.
    area = sum(poly[i][0] * -poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * -poly[i][1]
               for i in range(len(poly)))
    return poly if area >= 0 else poly[::-1]


def assign_levels(spaces):
    levels = []
    for space in sorted(spaces, key=lambda s: s['floorY']):
        if not levels or space['floorY'] - levels[-1]['elevation'] > LEVEL_GAP:
            n = len(levels)
            levels.append({'id': f'level:{n}', 'name': f'Level {n}', 'elevation': space['floorY']})
        space['levelId'] = levels[-1]['id']
    return levels


def pair_walls(walls):
    """Mutually best opposite faces from different spaces on one level."""
    best = {}
    for a in walls:
        la = math.dist(a['start'], a['end'])
        ua = [(a['end'][0] - a['start'][0]) / la, (a['end'][1] - a['start'][1]) / la]
        for b in walls:
            if b['spaceId'] == a['spaceId'] or b['levelId'] != a['levelId']:
                continue
            if a['normal'][0] * b['normal'][0] + a['normal'][1] * b['normal'][1] > -0.98:
                continue
            # b's face must lie behind a's face, away from a's space
            gap = -((b['start'][0] - a['start'][0]) * a['normal'][0] + (b['start'][1] - a['start'][1]) * a['normal'][1])
            if not PAIR_GAP[0] <= gap <= PAIR_GAP[1]:
                continue
            t = sorted((p[0] - a['start'][0]) * ua[0] + (p[1] - a['start'][1]) * ua[1] for p in (b['start'], b['end']))
            if min(t[1], la) - max(t[0], 0) < PAIR_OVERLAP:
                continue
            if a['id'] not in best or gap < best[a['id']][1]:
                best[a['id']] = (b, gap)
    by_id = {w['id']: w for w in walls}
    pairs = 0
    for wid, (b, gap) in best.items():
        if best.get(b['id'], (None,))[0] is by_id[wid]:
            by_id[wid]['thickness'] = r(gap, 3)
            by_id[wid]['adjacent'] = {'wallId': b['id'], 'spaceId': b['spaceId']}
            pairs += 1
    return pairs // 2


def place_room(entry, room):
    """One converted room (room-local) → space, walls and elements in the house frame."""
    placement = room['housePlacement']
    m = mat(placement['roomToHouse'])
    if abs(m[1][1]) < math.cos(math.radians(1)):
        print(f'warning: {entry["name"]}: house placement tilts the room more than 1°', file=sys.stderr)
    point = lambda p: apply(m, p)
    plan = lambda x, z: [r(v) for v in point([x, 0, z])[::2]]
    direction = lambda x, z: [r(v, 5) for v in apply(m, [x, 0, z], 0.0)[::2]]
    rid = entry['id']
    source = lambda **extra: {'session': placement['session'], 'room': placement['index'],
                              **{k: v for k, v in extra.items() if v is not None}}
    floor_y = r(point([0, 0, 0])[1])

    polygon = room.get('polygon') or chain_polygon(room['walls'])
    room_walls = orient_walls(room['walls'], polygon)
    walls = []
    for w in room_walls:
        key = w.get('id') or str(w['index'])
        openings = []
        for k, o in enumerate(w['openings']):
            opening = {'id': f'{o["kind"]}:{rid}/{o.get("id") or f"{key}.{k}"}', 'kind': o['kind'],
                       'u0': o['u0'], 'u1': o['u1'], 'v0': o['v0'], 'v1': o['v1'],
                       'source': source(identifier=o.get('id'))}
            if o['kind'] == 'door':
                opening['isOpen'] = bool(o.get('isOpen'))
            openings.append(opening)
        start = plan(w['origin'][0], w['origin'][2])
        u = direction(w['u'][0], w['u'][2])
        walls.append({
            'id': f'wall:{rid}/{key}', 'spaceId': rid, 'levelId': None,
            'start': start, 'end': [r(start[0] + u[0] * w['length']), r(start[1] + u[1] * w['length'])],
            'normal': direction(w['n'][0], w['n'][2]), 'base': floor_y, 'height': w['height'],
            'thickness': None, 'openings': openings,
            'source': source(identifier=w.get('id'), confidence=w.get('confidence')),
        })

    if polygon:
        polygon = counter_clockwise([plan(x, z) for x, z in polygon])

    elements = []
    for k, o in enumerate(room['objects']):
        front = direction(*o['front'])
        elements.append({
            'id': f'element:{rid}/{o.get("id") or k}', 'category': o['category'], 'spaceId': rid,
            'levelId': None, 'position': [r(v) for v in point(o['center'])],
            'rotY': r(math.atan2(front[0], front[1])), 'size': o['size'],
            'source': source(identifier=o.get('id'), confidence=o.get('confidence')),
        })

    space = {'id': rid, 'name': entry['name'], 'levelId': None, 'floorY': floor_y,
             'height': max((w['height'] for w in room['walls']), default=0), 'polygon': polygon,
             'wallIds': [w['id'] for w in walls], 'source': source()}
    return space, walls, elements


def build_home(rebuild):
    index = json.loads((rebuild / 'index.json').read_text())
    if index.get('format') != 'house-rebuild/1':
        raise ValueError('expected a house_to_rooms.py output (house-rebuild/1)')
    spaces, walls, elements, unplaced = [], [], [], []
    for entry in index['rooms']:
        if entry['status'] != 'ready':
            unplaced.append({'roomId': entry['id'], 'name': entry['name'], 'reason': entry.get('reason', entry['status'])})
            continue
        room = json.loads((rebuild / entry['file']).read_text())
        rigid(room['housePlacement']['roomToHouse'])
        space, room_walls, room_elements = place_room(entry, room)
        spaces.append(space)
        walls += room_walls
        elements += room_elements
    levels = assign_levels(spaces)
    level_of = {s['id']: s['levelId'] for s in spaces}
    for x in walls + elements:
        x['levelId'] = level_of[x['spaceId']]
    pairs = pair_walls(walls)
    home = {'format': 'home-model/1', 'id': index['house'], 'name': index['name'], 'units': 'm',
            'generatedFrom': {'tool': 'home_from_capture.py', 'house': Path(index['source']).name,
                              'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds')},
            'levels': levels, 'spaces': spaces, 'walls': walls, 'elements': elements, 'unplaced': unplaced}
    return home, pairs


def convert(source, out):
    if out.exists():
        raise ValueError(f'{out} already exists; choose a new output file')
    source = source.resolve()
    if (source / 'house.json').exists():
        with tempfile.TemporaryDirectory(prefix='home-from-capture-') as temp:
            rebuild = Path(temp) / 'rebuild'
            export_house(source, rebuild)
            home, pairs = build_home(rebuild)
    elif (source / 'index.json').exists():
        home, pairs = build_home(source)
    else:
        raise ValueError('expected a folder with house.json or a house_to_rooms.py index.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(home, indent=1) + '\n')
    return home, pairs


def area(poly):
    return abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
                   for i in range(len(poly)))) / 2


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path, help='house folder (house.json) or house_to_rooms.py output')
    parser.add_argument('-o', '--out', type=Path, required=True, help='new home.json path')
    args = parser.parse_args()
    try:
        home, pairs = convert(args.source, args.out)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    for level in home['levels']:
        print(f'{level["name"]} (y {level["elevation"]:.2f})')
        for s in (s for s in home['spaces'] if s['levelId'] == level['id']):
            a = f'{area(s["polygon"]):.2f} m²' if s['polygon'] else 'no outline'
            n = sum(len(w['openings']) for w in home['walls'] if w['spaceId'] == s['id'])
            print(f'  {s["name"]}: {a}, h {s["height"]:.2f}, {len(s["wallIds"])} walls, {n} openings, '
                  f'{sum(e["spaceId"] == s["id"] for e in home["elements"])} objects')
    for u in home['unplaced']:
        print(f'unplaced: {u["name"]}: {u["reason"]}')
    print(f'{len(home["spaces"])} spaces, {pairs} paired partitions → {args.out}')
    return 2 if home['unplaced'] else 0


if __name__ == '__main__':
    sys.exit(main())
