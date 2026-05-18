# Voxel Distance Diagnostics — measuring distances to radar voxels

Diagnostic patterns for understanding what the radar scanner sees and how far away it is.

## Key fact: solidPoints are WORLD coordinates

The `solid` list from `RadarController.scan_voxels()` contains points in **SE world space** `[x, y, z]`.
To get distance from the ship, subtract ship position:

```python
import math
from secontrol.tools.navigation_tools import get_world_position

ship_pos = get_world_position(rc)  # (x, y, z) world coords
solid, meta, contacts, ore_cells = ctrl.scan_voxels()

for pt in solid:
    dx = pt[0] - ship_pos[0]
    dy = pt[1] - ship_pos[1]
    dz = pt[2] - ship_pos[2]
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    print(f"  Voxel at ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f}) — {dist:.1f}m from ship")
```

**Wrong approach** (treats points as origin-relative vectors):
```python
# ❌ WRONG — gives distance from world origin, not from ship
dist = math.sqrt(pt[0]**2 + pt[1]**2 + pt[2]**2)
```

## Diagnostic scan script pattern

Quick one-shot scan with sorted distance output:

```python
import os, math, time
from dotenv import load_dotenv
load_dotenv('/workspace/.env')

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position

grid = prepare_grid('skynet-baza0')
radar = grid.get_first_device(OreDetectorDevice)
rc = grid.find_devices_by_type('remote_control')[0]

rc.update()
pos = get_world_position(rc)
print(f'Ship: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})')

# Scan with desired parameters
ctrl = RadarController(radar, radius=1000, cell_size=10, boundingBoxX=50, boundingBoxY=50)
t0 = time.time()
solid, meta, contacts, ore_cells = ctrl.scan_voxels()
print(f'Scan: {time.time()-t0:.2f}s, {len(solid)} points')

if solid:
    dists = []
    for pt in solid:
        dx = pt[0] - pos[0]
        dy = pt[1] - pos[1]
        dz = pt[2] - pos[2]
        d = math.sqrt(dx*dx + dy*dy + dz*dz)
        dists.append((d, pt))
    dists.sort()
    print(f'Range: {dists[0][0]:.1f}m — {dists[-1][0]:.1f}m')
    for i in range(min(10, len(dists))):
        d, pt = dists[i]
        print(f'  {i+1}. {d:.1f}m  ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})')
close(grid)
```

## Scan config vs results comparison

| Config | Solid points | Nearest | Use case |
|--------|-------------|---------|----------|
| cell=100, radius=5000, bbox=100x100 | 1 (coarse) | ~764m | Long-range asteroid detection |
| cell=10, radius=1000, bbox=50x50 | 1250 (fine) | ~639m | Detailed voxel mapping |
| cell=10, radius=500, bbox=100x100 | 0 (too close) | N/A | Ship inside scan dead zone |

Larger `cell_size` aggregates voxels — fewer points, less detail, faster scan.
Smaller `cell_size` gives more points — more detail, slower scan.

## Ore cells distance

Ore cells have position in `centerX/centerY/centerZ` or `center.{x,y,z}`:

```python
if ore_cells:
    for cell in ore_cells:
        cx = cell.get("centerX") or cell.get("center", {}).get("x", 0)
        cy = cell.get("centerY") or cell.get("center", {}).get("y", 0)
        cz = cell.get("centerZ") or cell.get("center", {}).get("z", 0)
        d = math.sqrt((cx-pos[0])**2 + (cy-pos[1])**2 + (cz-pos[2])**2)
        ore_type = cell.get("ore", cell.get("type", "?"))
        print(f"  {ore_type}: {d:.1f}m")
```

## Common pitfalls

- **`RadarVisualizer` line 58**: `rel = (arr - origin.reshape(1, 3)) / cell_size` — this converts FROM world coords TO grid indices for occupancy grid. Confirms `solid` arrives as world coords.
- **Truncated results**: `scan_voxels()` may return `truncated=N` meaning N points were dropped. Check `meta` for truncation info.
- **Scan resets at 0-1%**: Large bounding boxes with small cell_size cause too many tiles → scan never completes. Reduce bbox or increase cell_size.
- **`reset_active_scan=True`**: Use on OreDetector to force-restart a stuck scan.
- **Voxel distance ≠ geometric surface distance.** The nearest voxel from a scan (e.g. 339m with cell=10) differs from the geometric distance to the asteroid surface (e.g. `dist_to_center - radius = 204m`). Voxels are discrete grid cells — the nearest cell doesn't perfectly match the ideal sphere surface. Cell size matters: `cell_size=10` gives 339m (closer to geometric 204m), `cell_size=100` gives 764m (much coarser). For geometric approach planning, use `distance_to_center - radius`. For **voxel-based stopping** (the preferred approach), use the scanner's nearest distance directly — the ship stops when `nearest < stop_distance`, which accounts for real terrain geometry.
