# Home Digital Twin — Development Roadmap

Goal: turn this scan-to-Three.js pipeline into a digital twin of my home that supports
renovation planning, BIM export, decoration/refurbishment planning and inventory/stock management.

## 1. What exists today

| Layer | Where | What it does |
|---|---|---|
| iPhone capture app (Swift, iOS 17+, LiDAR) | `apps/house-capture/` | One ARSession per room: RoomPlan walls/doors/windows/openings + furniture boxes (16 categories), LiDAR mesh (`.ply`, per-face class), posed photos with intrinsics, depth frames, ARWorldMap. Multi-day house projects with relocalization, room history, export as `.zip` (`house-project/1`, `house-capture/5`). |
| Conversion scripts (Python) | `.agents/skills/scan-to-threejs/scripts/` | `house_to_rooms.py` (house → rooms + placement matrices), `bundle_to_room.py` (RoomPlan → walls/openings/objects/photo poses in room-local meters), `bundle_plan.py` (2D plan PNG), `reconstruct_bundle.py` (TSDF mesh from depth), photo prep/compare tools. |
| Room runtime (TS/Three.js) | `packages/room-runtime/` | `WallDef` walls with openings, moldings, materials, lighting, render pipeline, batching. `RoomLayout` = measured 2D plan. |
| Physics | `packages/room-physics/` | Rapier colliders, tagging via `userData.physics`, walk/interact. |
| Viewer | `apps/room-viewer/` | Dollhouse/orbit, walk, overhead layout, wireframe, scan overlay, **knolling** (auto-extracted inventory of objects). |
| Agent skill | `.agents/skills/scan-to-threejs/` | Guides an AI agent to hand-model each room as TypeScript, comparing against photos. |

### Key architectural observation

**The room model is code, not data.** Each room (e.g. `demos/office-v2/items/desk.ts`) is
hand-written TypeScript that builds Three.js meshes directly. Semantic info is thin: object
names, `userData.physics`, and the RoomPlan category on the converted JSON. There is:

- no persistent, editable building model (walls/slabs/openings as entities with IDs),
- no object/asset registry (what an item is, its brand, price, location, state),
- no editing in the viewer (everything is read-only),
- no combined-house viewer (rooms are viewed one at a time; placement matrices exist but are unused),
- no backend/database.

Every feature you want (renovation, BIM, decoration, stock) needs the same foundation:
**a semantic home model stored as data**, with the Three.js scene *generated from* it.

## 2. Target architecture

```
iPhone app ──export──▶ Ingest (Python) ──▶ Home Model (JSON/DB, source of truth)
                                              │   ├─ Building: levels, spaces, walls, slabs, openings, MEP points
                                              │   ├─ Elements: furniture, fixtures, appliances (typed, with IDs)
                                              │   ├─ Inventory: items, quantities, locations, consumables
                                              │   └─ Scenarios: "as-is" + proposals (diffs over as-is)
                                              ▼
              ┌───────────────┬───────────────┼───────────────┬───────────────┐
         Three.js viewer   Plan editor     IFC export      Cost/BOQ      Inventory UI
         (as-is / proposal) (2D + 3D)     (BIM tools)     estimator     (+ search in 3D)
```

Principles:
- Keep the hand-modeled detail path (it's the visual quality), but attach it to model elements by ID.
- Use stable GUIDs (RoomPlan `identifier` where available) so every view, cost line and inventory
  item points at the same element.
- Proposals are non-destructive layers over the as-is model.

## 3. Phased plan

### Phase 0 — Capture my home (1–2 weeks, mostly fieldwork)
- Build the iOS app with my signing team; scan every room; set room names consistently.
- Use "Continue scanning from this room" to keep rooms in aligned zones; verify alignment.
- Export whole house → `data/captures-in/home/` (gitignored). Run `house_to_rooms.py`, `bundle_plan.py`.
- Record what's weak (alignment gaps, low photo coverage, ceilings).
- **Exit:** every room converts; placement matrices exist for all rooms.

### Phase 1 — Semantic home model + whole-house viewer (foundation)
Status: schema (`packages/home-model/`) and converter (`home_from_capture.py`, synthetic tests)
done; untested on a real capture. Next: generator `home.json` → Three.js, whole-house viewer.
- Define `packages/home-model/` schema (TypeScript types + JSON Schema):
  `Home → Level → Space(polygon, height, name, usage) → Wall(baseline, thickness, height, openings[])`,
  `Opening(door/window, size, sill, swing)`, `Slab/Ceiling`, `Element(category, bbox, transform, meshRef?, props)`.
- Write `home_from_capture.py`: house export → `home.json` (merge shared walls between adjacent rooms,
  derive wall thickness from parallel faces, levels from floor heights, RoomPlan `story`).
- Generator: `home.json` → Three.js (reuse `WallDef`/`walls.ts`), so a home renders with no hand code.
- Whole-house viewer using `roomToHouse` matrices; per-level toggle; click-to-select elements → property panel.
- Measurements: area per space, wall area minus openings, perimeter, ceiling height, distance tool.
- **Exit:** my whole home visible, every wall/door/window/item selectable with an ID and dimensions.

### Phase 2 — BIM export / interop
- IFC4 export via **IfcOpenShell** (Python): `IfcSite/IfcBuilding/IfcBuildingStorey/IfcSpace`,
  `IfcWall` (with `IfcOpeningElement` + `IfcDoor`/`IfcWindow`), `IfcSlab`, `IfcFurnishingElement`,
  property sets (area, finish, condition). Stable GlobalIds from model GUIDs.
- Validate in BlenderBIM/Bonsai, Revit or ArchiCAD viewer; round-trip check of dimensions.
- Optional: IFC import (to bring architect changes back), DXF/SVG floor-plan export, glTF export.
- Optional in-browser IFC viewing via `web-ifc` / ThatOpen Components.
- **Exit:** `home.ifc` opens cleanly in a BIM tool with correct storeys, spaces and openings.

### Phase 3 — Renovation planning
- Scenario system: `scenarios/<name>.json` = list of ops (add/remove/move wall, change opening,
  change finish, add/remove element) applied over as-is. Compare as-is vs. proposal (toggle/split/slider).
- Editing tools in viewer: 2D plan editor (drag wall endpoints, snap, insert door/window),
  3D gizmo for elements. Edits write ops, never mutate as-is.
- Quantity take-off (BOQ): floor m² by finish, wall paint m², tiles, skirting m, demolition volume.
- Cost estimation: unit-rate table (`costs.json`, per region/currency), labor + material, contingency.
- Phasing/task list: export ops as tasks (could sync to ClickUp/Notion), Gantt-ish ordering.
- Constraint checks (warnings, not engineering): door clearances, min room sizes, flags on
  possibly load-bearing walls (needs manual tagging — the scan can't know).
- **Exit:** can draft "open kitchen to living room" and get a visual, a BOQ and a rough cost.

### Phase 4 — Decoration & refurbishment
- Finish library: paints (with real color codes), flooring, tiles, wallpaper → PBR materials;
  apply per wall/floor/surface; save as part of a scenario.
- Furniture catalog: import glTF/GLB (IKEA/manufacturer models, Sketchfab, generated), place,
  collision/clearance check against walls and existing items.
- Lighting studies: time-of-day sun from address/orientation, artificial light presets.
- Photo-matched renders: render a proposal from the exact pose of a captured photo
  (camera poses already exist) to see "my real room, repainted".
- Optional AI: style suggestions, image-to-3D for items, auto material from photo crops.
- Moodboards and shopping lists per scenario (links, prices, quantities from take-off).
- **Exit:** can try three color/furniture options for a room and compare them side by side.

### Phase 5 — Inventory / stock management
- Item registry: `Item{id, name, category, location(spaceId, elementId?, shelf/bin), qty, unit,
  min_qty, purchase date/price, warranty, serial, photos, tags}` in SQLite (local-first).
- Seed from the scan: RoomPlan objects + knolling extraction become "furniture/appliance" items.
- Containers & locations: cabinets/shelves/drawers as location nodes in the 3D model ("where is X?" →
  highlight in 3D).
- Consumables: pantry, cleaning, spare parts, renovation leftovers (paint tins, tiles) with
  low-stock alerts and shopping list generation.
- Capture on the phone: barcode/QR scan, photo, "place item here" using relocalization in the app.
- Maintenance: appliance service schedules, filter changes, warranty expiry reminders.
- **Exit:** search an item, see it highlighted in the 3D home, get low-stock list.

### Phase 6 — Platform (as needed)
- Backend (e.g. SQLite → Postgres/Supabase) + auth if sharing with family/contractors.
- Sync between iPhone app and web.
- Sensor/IoT hookup (Home Assistant) for a live twin: temperatures, energy per room.
- Document vault per element (invoices, manuals, permits).

## 4. Suggested order and first concrete steps

Phase 1 unlocks everything; Phase 5 (inventory) can run in parallel once element IDs exist.
Recommended path: **0 → 1 → 2 (minimal IFC) → 5 basic → 3 → 4**.

First sprint:
1. Scan 2–3 adjacent rooms; run the existing pipeline end-to-end to learn its limits.
2. Draft `packages/home-model` schema and a sample `home.json` by hand from one room.
3. Write `home_from_capture.py` for walls/openings/spaces of one room; render via generator.
4. Add selection + property panel to the viewer.
5. Spike IfcOpenShell export of that one room; open in Bonsai.

## 5. Risks / open questions
- Scan accuracy: RoomPlan is ~±2–5 cm, flat ceilings, single wall height; good for planning,
  not for construction drawings — always field-verify before ordering.
- Wall thickness and structure aren't captured; exterior walls, load-bearing and MEP must be
  tagged manually or from existing drawings.
- Multi-room alignment depends on relocalization quality; may need ICP/manual alignment tool.
- Licensing: code is MIT; office assets have separate terms. Keep personal captures out of Git
  (`data/captures-in/` is ignored) — the home model will contain private data.
- Decide: local-first single-user tool vs. multi-user web app (affects Phase 5–6 heavily).
