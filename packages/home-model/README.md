# home-model

`home-model/1` is the semantic home: levels, spaces, walls, openings and elements with stable IDs,
in the capture's house frame (meters, +Y up, plan coordinates `[x, z]`). It is the source of truth
for viewers, IFC export, take-offs and inventory; Three.js scenes are generated from it.

- `types.ts`: the schema.
- `measure.ts`: floor area, perimeter, net wall area (minus openings) and per-space summaries.
- `index.ts`: `parseHome()` checks format, unique IDs and references after loading a file.

## Create one from a capture

```sh
S=.agents/skills/scan-to-threejs/scripts
python3 "$S/home_from_capture.py" data/captures-in/my-house -o data/homes/my-house/home.json
```

The input is an unpacked whole-house export (`house.json`) or an existing `house_to_rooms.py`
output directory. `data/homes/` is ignored by Git: a home model describes a private house.

What the converter does:

- Places every room with a validated `roomToHouse` placement; others are listed in `unplaced`
  (exit code 2) and never guessed.
- Groups spaces into levels by floor elevation (floors within 1 m share a level).
- Uses the RoomPlan floor outline, or chains wall ends when the scan has none; turns every wall
  normal into its space.
- Pairs opposite faces of neighbouring spaces (2–60 cm apart, ≥ 30 cm alongside) and records the
  gap as `thickness` plus an `adjacent` link. Unpaired walls keep `thickness: null`.

IDs are `wall:<roomId>/<RoomPlan identifier>`, `door:…`, `window:…`, `opening:…` and
`element:<roomId>/…`, falling back to indices when an export has no identifiers. They stay the same
when the same scan is converted again. A rescan creates new RoomPlan identifiers, so carrying
annotations (`properties`) over to a new scan needs matching, which is not implemented yet.

## Limits

RoomPlan walls are straight faces with one height each and flat ceilings; accuracy is a few
centimeters. The model records what was captured. Exterior wall thickness, structure and services
are unknown until annotated.
