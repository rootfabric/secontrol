[← Parent skill: secontrol-space-engineers](../SKILL.md)

# Asteroid & Ore Scanning via Ore Detector

## Overview

The Ore Detector device supports multiple scan modes via the SE plugin:
- **Asteroid index** — nearby asteroid positions (via `asteroids` command or auto-populated telemetry)
- **Ore deposits** — ore vein positions within scanned voxels (via `oreCells` in radar telemetry)
- **Solid voxels** — full geometry scan (via `solidPoints` / `solid` in radar telemetry)
- **Contacts** — detected grids and players

As of v0.3.1+, `oreCells` and `radar` telemetry ARE populated by the plugin. Previously these were always empty.

---

## Asteroid Index

### Auto-populated in telemetry

The `asteroidIndex` field appears **automatically** in ore detector telemetry — no explicit command needed:

```python
tel = radar.telemetry or {}
ai = tel.get('asteroidIndex', {})
# ai['ready'] — bool, data is available
# ai['count'] — number of asteroids found (e.g. 320)
# ai['items'] — list of asteroid dicts with full metadata
```

Each asteroid item:
```python
{
    "name": "Asteroid_3_5_-7_0_569081442",
    "center": [71607.258, 110281.835, -117350.274],
    "distance": 437.947,           # meters from grid center
    "surfaceDistance": 0,          # 0 = grid is ON this asteroid
    "approxRadius": 1024,          # meters
    "seed": 569081442,
    "loadedNow": true,
    "aabb": {"min": [...], "max": [...]},
}
```

**Key fields**: `center` (world coords), `distance`, `surfaceDistance` (0 = on asteroid), `approxRadius`.

### Explicit asteroids command

```python
sent = radar.send_command({
    "cmd": "asteroids",
    "targetId": int(radar.device_id),
    "state": {
        "radius": 50000.0,      # search radius in meters
        "limit": 320,            # max results
        "includePlanets": False,
    },
})
```

Poll for response in `telemetry['asteroidIndex']` with `ready=True` and new `revision`.

### Helper function

```python
import time
from typing import Any, Dict, Optional

def request_asteroids(radar, *, radius=50000.0, limit=320, include_planets=False, timeout=10.0):
    telemetry = radar.telemetry or {}
    previous = telemetry.get("asteroidIndex")
    previous_revision = previous.get("revision") if isinstance(previous, dict) else None

    radar.send_command({
        "cmd": "asteroids",
        "targetId": int(radar.device_id),
        "state": {"radius": float(radius), "limit": int(limit), "includePlanets": bool(include_planets)},
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        telemetry = radar.telemetry or {}
        ai = telemetry.get("asteroidIndex")
        if isinstance(ai, dict) and ai.get("ready") and ai.get("revision") != previous_revision:
            return ai
    return None
```

---

## Ore Deposit Scanning (v0.3.1+)

### How it works

The SE plugin now transmits `oreCells` in radar telemetry — ore deposit positions with types (Iron, Ice, Gold, etc.). This was previously client-side HUD only.

### ⚠️ oreCells truncation buffer (256 cells max)

The SE plugin transmits a **maximum of 256 ore cells per telemetry update**. When the scan area contains more ore cells, the excess are truncated:

```python
radar.update()
tel = radar.telemetry or {}
rd = tel.get('radar', {})
print(f"oreCellCount={rd.get('oreCellCount')}")        # total in scan area (e.g. 3162)
print(f"transmitted={len(rd.get('oreCells', []))}")    # actually received (max 256)
print(f"truncated={rd.get('oreCellsTruncated')}")       # lost (e.g. 2906)
```

**Without `ore_only=True`**: Stone voxels dominate the buffer. Typical result: 255 Stone + 1 Gold transmitted, 2906 valuable ores truncated. **With `ore_only=True`**: Stone filtered at plugin level, all 256 cells contain valuable ores. Verified: same scan area — `ore_only=False` → 1 Gold; `ore_only=True` → 35 deposits (19 Platinum + 16 Gold), 0 truncation.

### Tested scan parameter configs

| Config | radius | cell_size | bboxY | policyMaxRadius | gridSize | Notes |
|--------|--------|-----------|-------|-----------------|----------|-------|
| Default ore scan | 1000 | 10 | 1000 | 1000 | 200³ | Works, ~40s for 12656 tiles |
| Close range | 200 | 10 | default | 200 | 40³ | Fast, ~1.5s |
| Medium range | 500 | 10 | default | 500 | 100³ | ~3.5s |
| Wide bbox (broken) | 1000 | 10 | 3000 | **100** | 20³ | Server caps radius! Scan resets at 64% |

**Rule**: don't set `boundingBoxX/Z` larger than ~1000. Large values cause the server to cap `policyMaxRadius` far below the requested radius, resulting in tiny scan areas or scan resets.

### Ore-only scan mode

The fastest and most reliable way to find ore deposits — skips stone/empty voxels, avoids truncation:

```python
from secontrol.controllers.radar_controller import RadarController

ore_ctrl = RadarController(radar, ore_only=True, radius=1000, cell_size=2)
solid, meta, contacts, ore_cells = ore_ctrl.scan_voxels()

# ore_cells = [{"ore": "Iron", "position": [x,y,z], "material": "IronOre"}, ...]
for cell in ore_cells:
    name = cell.get("ore") or cell.get("material") or "?"
    pos = cell.get("position")
    print(f"  {name} at {pos}")
```

### Two-pass scan pattern (ore + voxels)

For maximum data — ore positions AND solid geometry:

```python
# Pass 1: ore-only (fast, wide radius)
ore_ctrl = RadarController(radar, ore_only=True, radius=1000, cell_size=2)
ore_solid, ore_meta, ore_contacts, ore_cells = ore_ctrl.scan_voxels()

# Pass 2: full voxels (slower, smaller radius)
voxel_ctrl = RadarController(radar, ore_only=False, radius=300, cell_size=2, fullSolidScan=True)
vox_solid, vox_meta, vox_contacts, vox_ore = voxel_ctrl.scan_voxels()
```

### Direct scan via OreDetectorDevice

```python
radar.scan(include_voxels=True, ore_only=True, radius=1000, cell_size=2)
# Then wait for scan completion and read radar telemetry
```

### RadarController scan_voxels() returns

```python
solid, metadata, contacts, ore_cells = controller.scan_voxels()
# solid: list of [x,y,z] points (voxel geometry)
# metadata: dict with size, cellSize, origin, rev, tsMs
# contacts: list of detected grids/players
# ore_cells: list of {"ore": "Iron", "position": [x,y,z], "material": "..."}
```

### Ore cell structure

```python
{
    "ore": "Gold",              # ore type name (Iron, Gold, Platinum, Ice, etc.)
    "material": "",             # SE material name (may be empty string)
    "position": [x, y, z],     # world coordinates
    "content": 255,             # ore richness (0-255, 255 = max)
}
```

**`content` field**: indicates ore vein richness. 255 = full/high content, lower values = depleted or partial veins. Useful for prioritizing which deposits to mine first.

### Filtering stone

`RadarController` has `filter_no_stone=True` by default — Stone ore cells are excluded. To include stone:
```python
ctrl = RadarController(radar, ore_only=True, filter_no_stone=False)
```

---

## Contacts Scanning (grids + players)

Fast scan for nearby grids and players — skips voxel geometry entirely.

### Via RadarController

```python
from secontrol.controllers.radar_controller import RadarController

controller = RadarController(radar, radius=500, cell_size=10, ore_only=False)
contacts = controller.scan_contacts()

grids = [c for c in contacts if c.get("type") == "grid"]
players = [c for c in contacts if c.get("type") == "player"]
```

### Via OreDetectorDevice

```python
radar.scan(include_players=True, include_grids=True, include_voxels=False, radius=500)
contacts = radar.contacts()
```

### Ready-to-run script

```
python examples/organized/radar/basic/scan_contacts.py
python examples/organized/radar/basic/scan_contacts.py --grid skynet-baza1 --radius 1000
```

### Contact structure

```python
{
    "type": "grid",              # or "player"
    "name": "skynet-farpost0",
    "id": 80828718952705651,
    "position": [x, y, z],      # world coordinates
    "distance": 1234.5,          # meters from scanner (if available)
    "velocity": [vx, vy, vz],   # m/s (if available)
}
```

---

## Voxel Scan Progress

When scanning voxels, progress appears in `telemetry['scan']`:
- `inProgress` — bool
- `progressPercent` — 0-100
- `processedTiles`, `totalTiles` — tile counts
- `elapsedSeconds`

---

## Pitfalls

- **`ore_only` requires v0.3.1+ plugin.** Older SE server plugins don't recognize `oreOnly` in scan state. If ore_cells are always empty despite `ore_only=True`, the plugin needs updating.
- **Ore detection range is limited by detector range setting.** Even with `ore_only=True`, deposits must be within the ore detector's physical range (~50-250m). Fly close to asteroid surfaces.
- **`surfaceDistance=0`** in asteroidIndex means the grid's AABB intersects the asteroid — the grid is on or inside it.
- **`send_command` with `set` can toggle `includeVoxels` to False.** Avoid sending `set` property commands to OreDetector — they can flip boolean scan flags irreversibly via API.
- **RadarController requires numpy.** Install with `pip install -q numpy` if not available.
- **Two-pass scan takes time.** Ore-only pass is faster (fewer tiles), but full voxel scan with `fullSolidScan=True` on large radius can take 1-5 minutes depending on `cell_size` and `budget_ms_per_tick`.
- **⚠️ `oreCells` buffer truncation (256 cells max).** The SE plugin transmits max 256 ore cells per telemetry update. `oreCellCount` shows total (e.g. 3162), `oreCellsTruncated` shows lost cells. Without `ore_only=True`, Stone fills the buffer (255 Stone + 1 Gold). With `ore_only=True`, Stone filtered at plugin level → all 256 cells are valuable ores (verified: 35 Platinum/Gold, 0 truncation). Always check `oreCellsTruncated`; if > 0, use `ore_only=True` or reduce radius.
- **`bbox` (boundingBoxX/Y/Z) affects server-side radius capping.** Large bbox values (3000+) cause server to cap `policyMaxRadius` much lower than requested (e.g. request 1000m → cap 100m). Safe defaults: `radius=1000, cell_size=10, boundingBoxY=1000` → `policyMaxRadius=1000, gridSize=[200,200,200]`. If scan resets at low %, check `policyMaxRadius` in output.
