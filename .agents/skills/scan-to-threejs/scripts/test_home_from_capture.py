"""Behavior checks for home_from_capture.py on a synthetic two-session, two-level house.
Run: python3 -m unittest discover -s <skill>/scripts -p 'test_*.py'
"""
import json
import math
from pathlib import Path
import tempfile
import unittest

from bundle_to_room import apply, mat, mul
from house_to_rooms import flatten, inverse_rigid
from home_from_capture import convert

HEIGHT = 2.6


def transform(x=0, y=0, z=0, angle=0):
    c, s = math.cos(angle), math.sin(angle)
    return flatten([[c, 0, s, x], [0, 1, 0, y], [-s, 0, c, z], [0, 0, 0, 1]])


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def element(ident, to_session, center, axis, dims, **extra):
    """RoomPlan element whose local +x runs along `axis`, both given in the house frame."""
    m = mat(to_session)
    c = apply(m, center)
    x = apply(m, axis, 0.0)
    z = [-x[2], 0, x[0]]  # x × up
    return {'identifier': ident, 'transform': [*x, 0, 0, 1, 0, 0, *z, 0, *c, 1],
            'dimensions': dims, 'confidence': {'high': {}}, **extra}


def rectangle(prefix, to_session, x0, z0, x1, z1, floor, with_floor=True):
    """Four walls (house frame) + optional floor polygon, written in a session frame."""
    corners = [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]
    walls = []
    for i, ((ax, az), (bx, bz)) in enumerate(zip(corners, corners[1:] + corners[:1])):
        length = math.dist((ax, az), (bx, bz))
        walls.append(element(f'{prefix}-w{i}', to_session, [(ax + bx) / 2, floor + HEIGHT / 2, (az + bz) / 2],
                             [(bx - ax) / length, 0, (bz - az) / length], [length, HEIGHT, 0]))
    room = {'walls': walls, 'doors': [], 'windows': [], 'openings': [], 'objects': []}
    if with_floor:
        m = mat(to_session)
        points = [apply(m, [x, floor, z]) for x, z in corners]
        room['floors'] = [{'transform': transform(0, points[0][1], 0),
                           'polygonCorners': [[p[0], 0, p[2]] for p in points]}]
    return room


class HomeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        root = self.base / 'house'
        zone_to_house = transform(1, 0, 2, math.pi / 2)
        to_zone = {'s1': transform(0, 1.4, 0), 's2': transform(3, 1.4, -1, 0.7), 's3': transform(0, 1.4, 0)}
        def to_session(s):
            return flatten(inverse_rigid(mul(mat(zone_to_house), mat(to_zone[s]))))

        # Living room 4 × 3 m with a door in its east wall and a table.
        living = rectangle('liv', to_session('s1'), 0, 0, 4, 3, 0)
        east = living['walls'][1]['identifier']
        living['doors'].append(element('liv-door', to_session('s1'), [4, 1.0, 1.0], [0, 0, 1], [0.9, 2.0, 0],
                                       category={'door': {'isOpen': True}}, parentIdentifier=east))
        living['windows'].append(element('liv-win', to_session('s1'), [2, 1.5, 0], [1, 0, 0], [1.2, 1.0, 0],
                                         category={'window': {}}, parentIdentifier=living['walls'][0]['identifier']))
        living['objects'].append(element('liv-table', to_session('s1'), [2, 0.4, 1.5], [1, 0, 0], [1.2, 0.8, 0.8],
                                         category={'table': {}}))
        # Kitchen 3 × 3 m beyond a 12 cm partition, captured in another session without a floor outline.
        kitchen = rectangle('kit', to_session('s2'), 4.12, 0, 7.12, 3, 0, with_floor=False)
        kitchen['windows'].append(element('kit-win', to_session('s2'), [4.12, 1.6, 1.0], [0, 0, -1], [0.6, 0.8, 0],
                                          category={'window': {}}, parentIdentifier=kitchen['walls'][3]['identifier']))
        # Bedroom one storey up.
        bedroom = rectangle('bed', to_session('s3'), 0, 0, 3.5, 3, 2.9)
        for session, room in [('s1', living), ('s2', kitchen), ('s3', bedroom)]:
            write(root / f'sessions/{session}/rooms/room-0.json', room)
        write(root / 'house.json', {'format': 'house-project/1', 'id': 'home', 'name': 'Home',
            'zones': [{'id': 'z', 'name': 'Area', 'aligned': True, 'toHouse': zone_to_house}],
            'sessions': [{'id': s, 'zone': 'z', 'alignment': {'method': 'manual', 'toZone': to_zone[s]}}
                         for s in to_zone] + [{'id': 's4', 'zone': 'z', 'alignment': {'method': 'unaligned', 'toZone': transform()}}],
            'rooms': [{'id': rid, 'name': name, 'zone': 'z', 'active': {'session': s, 'index': 0}}
                      for rid, name, s in [('r-liv', 'Living', 's1'), ('r-kit', 'Kitchen', 's2'),
                                           ('r-bed', 'Bedroom', 's3'), ('r-hall', 'Hall', 's4')]]})
        self.home, self.pairs = convert(root, self.base / 'home.json')
        self.spaces = {s['id']: s for s in self.home['spaces']}
        self.walls = {w['id']: w for w in self.home['walls']}

    def tearDown(self):
        self.temp.cleanup()

    def test_spaces_levels_and_unplaced(self):
        self.assertEqual(set(self.spaces), {'r-liv', 'r-kit', 'r-bed'})
        self.assertEqual([u['roomId'] for u in self.home['unplaced']], ['r-hall'])
        self.assertEqual([l['id'] for l in self.home['levels']], ['level:0', 'level:1'])
        self.assertEqual(self.spaces['r-bed']['levelId'], 'level:1')
        self.assertAlmostEqual(self.spaces['r-bed']['floorY'], 2.9, places=3)
        self.assertEqual(self.spaces['r-kit']['levelId'], 'level:0')

    def test_polygons_in_house_frame(self):
        def area(p):
            return abs(sum(p[i][0] * p[(i + 1) % len(p)][1] - p[(i + 1) % len(p)][0] * p[i][1] for i in range(len(p)))) / 2
        self.assertAlmostEqual(area(self.spaces['r-liv']['polygon']), 12, places=2)
        self.assertAlmostEqual(area(self.spaces['r-kit']['polygon']), 9, places=2)  # chained from walls
        xs = sorted(p[0] for p in self.spaces['r-kit']['polygon'])
        self.assertAlmostEqual(xs[0], 4.12, places=3)
        self.assertAlmostEqual(xs[-1], 7.12, places=3)

    def test_walls_face_inward(self):
        for w in self.home['walls']:
            s = self.spaces[w['spaceId']]
            xs = [p[0] for p in s['polygon']]; zs = [p[1] for p in s['polygon']]
            mid = [(w['start'][0] + w['end'][0]) / 2 + w['normal'][0] * 0.1, (w['start'][1] + w['end'][1]) / 2 + w['normal'][1] * 0.1]
            self.assertTrue(min(xs) < mid[0] < max(xs) and min(zs) < mid[1] < max(zs), w['id'])

    def test_partition_paired_with_thickness(self):
        self.assertEqual(self.pairs, 1)
        east = self.walls['wall:r-liv/liv-w1']
        self.assertEqual(east['adjacent']['spaceId'], 'r-kit')
        self.assertAlmostEqual(east['thickness'], 0.12, places=3)
        self.assertEqual(self.walls[east['adjacent']['wallId']]['adjacent']['wallId'], east['id'])
        self.assertIsNone(self.walls['wall:r-liv/liv-w0']['thickness'])

    def test_openings_and_elements(self):
        door = self.walls['wall:r-liv/liv-w1']['openings'][0]
        self.assertEqual((door['id'], door['kind'], door['isOpen']), ('door:r-liv/liv-door', 'door', True))
        self.assertAlmostEqual(door['u1'] - door['u0'], 0.9, places=3)
        self.assertAlmostEqual((door['u0'] + door['u1']) / 2, 1.0, places=3)  # u runs +z from (4, 0)
        # Seen from the kitchen, its west face runs from z=3 to z=0, so the window sits at u=2.
        window = self.walls['wall:r-kit/kit-w3']['openings'][0]
        self.assertAlmostEqual((window['u0'] + window['u1']) / 2, 2.0, places=3)
        self.assertAlmostEqual(self.walls['wall:r-kit/kit-w3']['start'][1], 3, places=3)
        self.assertEqual(door['v0'], 0)
        window = self.walls['wall:r-liv/liv-w0']['openings'][0]
        self.assertAlmostEqual(window['v0'], 1.0, places=3)
        table = self.home['elements'][0]
        self.assertEqual((table['id'], table['category'], table['spaceId']), ('element:r-liv/liv-table', 'table', 'r-liv'))
        for actual, expected in zip(table['position'], [2, 0.4, 1.5]):
            self.assertAlmostEqual(actual, expected, places=3)

    def test_unique_ids_and_no_overwrite(self):
        ids = [x['id'] for k in ('levels', 'spaces', 'walls', 'elements') for x in self.home[k]]
        ids += [o['id'] for w in self.home['walls'] for o in w['openings']]
        self.assertEqual(len(ids), len(set(ids)))
        with self.assertRaises(ValueError):
            convert(self.base / 'house', self.base / 'home.json')


if __name__ == '__main__':
    unittest.main()
