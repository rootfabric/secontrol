# Asteroid Flight Pattern — proven working code

Fly a grid to the nearest asteroid using `fly_to_point()` + asteroid discovery.

## Working script (tested on skynet-baza1, 2026-05-17)

```python
from __future__ import annotations
import time, math
from typing import Any, Dict, Optional
from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.tools.navigation_tools import fly_to_point, get_world_position, _dist

GRID_NAME = "skynet-baza1"
SEARCH_RADIUS = 50_000.0
TIMEOUT_SECONDS = 15.0

def request_asteroids(radar: OreDetectorDevice, radius=SEARCH_RADIUS, timeout=TIMEOUT_SECONDS):
    """Force-refresh asteroid index, wait for NEW revision (not stale data)."""
    telemetry = radar.telemetry or {}
    previous = telemetry.get("asteroidIndex")
    previous_revision = previous.get("revision") if isinstance(previous, dict) else None

    radar.send_command({
        "cmd": "asteroids",
        "targetId": int(radar.device_id),
        "state": {"radius": float(radius), "limit": 320, "includePlanets": False},
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        telemetry = radar.telemetry or {}
        asteroid_index = telemetry.get("asteroidIndex")
        if not isinstance(asteroid_index, dict):
            continue
        revision = asteroid_index.get("revision")
        if asteroid_index.get("ready") and revision != previous_revision:
            return asteroid_index
    return None

def find_nearest_asteroid(asteroid_index: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    items = asteroid_index.get("items", [])
    asteroids = [i for i in items if i.get("kind") == "asteroid"]
    if not asteroids:
        asteroids = items
    return min(asteroids, key=lambda i: i.get("distance", float("inf")))

def compute_approach_point(ship_pos, asteroid, stop_distance=500.0):
    """Compute FINAL stop position at (radius + stop_distance) from asteroid center.

    ⚠️ CRITICAL FIX (2026-05-17): The original formula computed an intermediate
    point relative to the SHIP position, which gave wrong results when the ship
    was already close (e.g. 997m away, the approach point was only 490m from ship
    instead of the expected 1256m from center). The correct formula places the
    point at a fixed distance from the ASTEROID CENTER along the center→ship line,
    so the ship stops at exactly (radius + stop_distance) from the center regardless
    of starting position.

    OLD (WRONG): approach_dist = dist - radius - stop_distance
       → returns point at dist-756m from ship → wrong when dist < 1256m
    NEW (CORRECT): stop_radius = radius + stop_distance
       → returns point at (radius+stop_distance) from center on ship side
    """
    center = asteroid.get("center", [0, 0, 0])
    cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
    radius = float(asteroid.get("approxRadius", 50.0))
    # Direction from asteroid center to ship (we stop on the ship side)
    dx, dy, dz = ship_pos[0]-cx, ship_pos[1]-cy, ship_pos[2]-cz
    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
    if dist < 1e-3:
        return (cx, cy, cz)
    d = (dx/dist, dy/dist, dz/dist)
    # Final stop position: radius + stop_distance from center, toward ship
    stop_radius = radius + stop_distance
    return (cx + d[0]*stop_radius, cy + d[1]*stop_radius, cz + d[2]*stop_radius)

# Main flow:
grid = prepare_grid(GRID_NAME)
radar = grid.get_first_device(OreDetectorDevice)
rc = grid.get_first_device(RemoteControlDevice)

rc.enable()
rc.gyro_control_on()
rc.thrusters_on()
rc.dampeners_on()
time.sleep(1)

# 1. Scan for asteroids
asteroid_index = request_asteroids(radar)
nearest = find_nearest_asteroid(asteroid_index)

# 2. Compute approach point (500m before surface — radius + 500m from center)
rc.update()
ship_pos = get_world_position(rc)
target = compute_approach_point(ship_pos, nearest, 500.0)

# 3. Fly
final_pos = fly_to_point(
    rc, target,
    waypoint_name=nearest.get("name", "Asteroid"),
    speed_far=30.0, speed_near=5.0,
    arrival_distance=50.0, max_flight_time=600.0,
)

# 4. Stop
rc.disable()
rc.dampeners_on()
rc.handbrake_on()
close(grid)
```

## Key details

- **`request_asteroids` uses revision checking** — compares `asteroidIndex.revision` before/after to detect NEW data. Without this, you may read stale cached data from a previous scan.
- **`wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)`** — the correct polling pattern. Don't use `update()` + `sleep()` — `wait_for_telemetry` blocks efficiently until new data arrives.
- **`compute_approach_point`** — computes FINAL stop position at `(radius + stop_distance)` from asteroid center along center→ship line. Returns `(cx + d[0]*stop_radius, ...)` where `stop_radius = radius + stop_distance`. This is NOT an intermediate waypoint — it's the exact position where the ship should stop.
- **`fly_to_point()` handles autopilot engage/disengage** — waits up to 3s for `autopilotEnabled`, monitors position, returns final position or None.
- **`surfaceDistance=0`** means the grid is ON the asteroid surface.
- **Asteroid radius varies** — can be 50-500m+. Always use `approxRadius` from the asteroid data, not a hardcoded value.
- **Voxel distance ≠ geometric surface distance.** The nearest voxel from a scan (e.g. 339m) differs from the geometric distance (e.g. `dist_to_center - radius = 204m`). Voxels are discrete grid cells — the nearest cell doesn't perfectly match the ideal sphere surface. Cell size matters: `cell_size=10` gives closer approximation than `cell_size=100`. Don't be alarmed by the difference — the geometric calculation is the accurate one for approach planning.
- **Re-approach requires recomputing approach point.** If the ship already stopped near a previous approach point and you want to fly closer, the old approach point is within `arrival_distance` → `fly_to_point` immediately "arrives". Solution: compute a NEW approach point from the current ship position with smaller `arrival_distance` (5-10m).

## Two-phase asteroid approach (tested 2026-05-17)

For safe approach with distance-based obstacle detection:

```
Ship → [Phase 1: 30 m/s] → SLOW_DISTANCE (1000m) → [Phase 2: 5 m/s] → OBSTACLE_RANGE (756m from surface) → STOP
```

**Constants:**
```python
SLOW_DISTANCE = 1000.0    # switch to slow speed this far from approach point
OBSTACLE_RANGE = 1000.0   # voxels closer than this = OBSTACLE (stop)
STOP_DISTANCE = 500.0     # final stop distance from surface (passed to compute_approach_point)
FLIGHT_SPEED_FAR = 30.0   # Phase 1 speed
FLIGHT_SPEED_NEAR = 5.0   # Phase 2 speed
```

**Why OBSTACLE_RANGE matters**: The forward scanner detects ALL voxels in its beam — including the target asteroid. Voxels at 1500m are the target (keep flying). Voxels at 800m are an obstacle (stop). The threshold distinguishes the two. **But OBSTACLE_RANGE alone is NOT enough** — when the ship is within OBSTACLE_RANGE of the target, the target's own voxels trigger a false positive. The scanner must ALSO check that voxels are closer than the target distance (`nearest < target_distance`). Both conditions must be true for a real obstacle.

**Phase logic:**
1. Compute approach point (final stop at `radius + STOP_DISTANCE` from center)
2. Compute distance from ship to approach point
3. If distance > SLOW_DISTANCE: Phase 1 — fly at `FLIGHT_SPEED_FAR`, intermediate target at `approach_point + direction * (dist - SLOW_DISTANCE)`
4. When distance ≤ SLOW_DISTANCE: Phase 2 — fly at `FLIGHT_SPEED_NEAR` to approach point
5. ForwardScanner watches for voxels closer than OBSTACLE_RANGE — if found, brake immediately

## Skynet grids (tested)

| Grid | ID | Has RC | Has Radar |
|------|----|--------|-----------|
| skynet-baza1 | 110200444398431415 | ✅ | ✅ |
| skynet-baza0 | 121585905264556027 | ✅ | ✅ |

## Integrated flight + scanner pattern (tested 2026-05-17)

Combines asteroid approach with continuous forward voxel scanning.
Scanner stops ship before it hits asteroid surface.

```python
import threading, time, math
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import fly_to_point, get_world_position, _dist

class ForwardScanner:
    """Background scanner — disables RC when voxels are CLOSE and closer than target.

    ⚠️ CRITICAL: The scanner detects ALL voxels in the beam, including the target
    asteroid itself. Two checks are required:
    1. nearest < OBSTACLE_RANGE — voxels must be within obstacle detection range
    2. nearest < target_distance — voxels must be CLOSER than the target approach point

    Both must be true. Without check #2, the scanner triggers on the target asteroid's
    own voxels when the ship is within OBSTACLE_RANGE of the target (e.g. ship at 981m
    from center, target voxels at 998m, OBSTACLE_RANGE=1000m → false positive stop).
    """
    def __init__(self, radar, rc, obstacle_range=1000.0):
        self.radar = radar
        self.rc = rc
        self.obstacle_range = obstacle_range
        self._obstacle = False
        self._target_dist = float('inf')  # set from main thread as ship moves
        self._lock = threading.Lock()

    @property
    def obstacle_detected(self):
        with self._lock: return self._obstacle

    @property
    def target_distance(self):
        with self._lock: return self._target_dist

    @target_distance.setter
    def target_distance(self, value: float):
        with self._lock: self._target_dist = value

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self): self._running = False

    def _loop(self):
        ctrl = RadarController(
            self.radar, radius=5000.0, cell_size=100.0,
            boundingBoxX=100, boundingBoxY=100, boundingBoxZ=100,
            ore_only=False,
        )
        while self._running:
            try:
                solid, *_ = ctrl.scan_voxels()
                if solid and len(solid) > 0:
                    # Get ship position for accurate distance calc
                    ship_pos = get_world_position(self.rc)
                    if not ship_pos: continue
                    nearest = float('inf')
                    for pt in solid:
                        dx = pt[0] - ship_pos[0]
                        dy = pt[1] - ship_pos[1]
                        dz = pt[2] - ship_pos[2]
                        d = math.sqrt(dx*dx + dy*dy + dz*dz)
                        if d < nearest: nearest = d

                    # BOTH checks required: close AND closer than target
                    with self._lock:
                        target_d = self._target_dist
                    if nearest < self.obstacle_range and nearest < target_d:
                        with self._lock: self._obstacle = True
                        try:
                            self.rc.disable()
                            self.rc.dampeners_on()
                        except: pass
                        return
                    # else: voxels are the target itself, keep scanning
            except: pass
            time.sleep(0.3)

# Usage:
scanner = ForwardScanner(radar, rc, obstacle_range=1000.0)
scanner.target_distance = dist_to_approach  # initial distance to approach point
scanner.start()

def should_cancel():
    """Update target distance as ship moves, then check obstacle."""
    rc.update()
    pos = get_world_position(rc)
    if pos:
        scanner.target_distance = _dist(pos, target)
    return scanner.obstacle_detected

final_pos = fly_to_point(
    rc, approach_point,
    speed_far=30.0, speed_near=5.0,
    arrival_distance=50.0, max_flight_time=600.0,
    cancel_check=should_cancel,
)

scanner.stop()
if scanner.obstacle_detected:
    print("STOPPED — voxels detected within obstacle range AND closer than target")
```

**Key**: Uses `cell_size=100.0` with `bbox 100x100x100` for long-range detection (~5000m radius).
Scans complete in ~0.3s. The `nearest` distance check prevents the scanner from triggering on the target asteroid itself.

---

## Voxel-based stopping (PREFERRED — tested 2026-05-17)

The geometric approach (`compute_approach_point`) has a fundamental problem: it uses
`approxRadius` from asteroid data and assumes a perfect sphere. Real asteroids are
irregular, and `approxRadius` can be off. The result: the ship stops at the wrong distance
(e.g. 380m from surface instead of 200m).

**Better approach**: fly toward the asteroid center and stop when the **nearest voxel**
from the scanner is within `stop_distance` meters. No geometric formulas needed.

### Why this is better

| | Geometric | Voxel-based |
|---|---|---|
| Accuracy | Depends on `approxRadius` (often wrong) | Uses actual terrain data |
| Code complexity | `compute_approach_point` + `target_distance` tracking | Simple `nearest < stop_distance` |
| False stops | Needs `target_distance` comparison to avoid stopping on target's own voxels | No — voxels ARE the target, stop when close enough |
| Works on irregular asteroids | Poorly (sphere assumption) | Perfectly (real voxel geometry) |

### Implementation

```python
import threading, time, math
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import fly_to_point, get_world_position

class ForwardScanner:
    """Stop when nearest voxel < stop_distance. No geometric formulas."""

    def __init__(self, radar, rc, stop_distance=200.0):
        self.radar = radar
        self.rc = rc
        self._stop_distance = stop_distance
        self._arrived = False
        self._nearest_dist = float('inf')
        self._lock = threading.Lock()

    @property
    def arrived(self):
        with self._lock: return self._arrived

    @property
    def nearest_distance(self):
        with self._lock: return self._nearest_dist

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self): self._running = False

    def _loop(self):
        ctrl = RadarController(
            self.radar, radius=5000.0, cell_size=100.0,
            boundingBoxX=100, boundingBoxY=100,
            ore_only=False,
        )
        while self._running:
            try:
                solid, *_ = ctrl.scan_voxels()
                if solid and len(solid) > 0:
                    ship_pos = get_world_position_safe(self.rc)
                    if not ship_pos: continue
                    nearest = min(
                        math.sqrt((p[0]-ship_pos[0])**2 + (p[1]-ship_pos[1])**2 + (p[2]-ship_pos[2])**2)
                        for p in solid
                    )
                    with self._lock:
                        self._nearest_dist = nearest
                        self._arrived = nearest < self._stop_distance
                    if self._arrived:
                        try:
                            self.rc.disable()
                            self.rc.dampeners_on()
                        except: pass
                        return
            except: pass
            time.sleep(0.3)

# Usage — fly to CENTER, stop by voxel distance:
target = (float(center[0]), float(center[1]), float(center[2]))
scanner = ForwardScanner(radar, rc, stop_distance=200.0)
scanner.start()

def should_cancel():
    return scanner.arrived

fly_to_point(rc, target, speed_far=30, speed_near=5,
             arrival_distance=50, cancel_check=should_cancel)
scanner.stop()
# Result: ship stops when nearest voxel < 200m
```

### Two-phase with voxel stopping

```
Ship → [Phase 1: 30 m/s] → SLOW_DISTANCE (1000m from center) → [Phase 2: 5 m/s] → nearest voxel < stop_distance → STOP
```

Phase 1 target: point at `SLOW_DISTANCE` from asteroid center (on ship side).
Phase 2 target: asteroid center itself — scanner stops the ship when voxels are close enough.

### Voxel distance vs geometric distance

The nearest voxel from a scan (e.g. 339m with cell=10) differs from the geometric
distance (e.g. `dist_to_center - radius = 204m`). This is normal — voxels are discrete
grid cells, the nearest cell doesn't perfectly match the ideal sphere. Cell size matters:
`cell_size=10` gives closer approximation than `cell_size=100`.

For voxel-based stopping, this difference is acceptable — the ship stops when the
SCANNER sees voxels at the target distance, which is what matters for collision avoidance.

### `arrival_distance` pitfall

`fly_to_point()` default `arrival_distance=50.0` means the ship "arrives" when within
50m of the target point. If flying toward the asteroid CENTER (which is inside the rock),
the ship may "arrive" at the center point while still far from the surface. The scanner's
`cancel_check` should trigger before this happens, but set `arrival_distance` to a large
value (e.g. 9999) to ensure the scanner, not the arrival threshold, controls the stop.

### Voxel distance diagnostics

For measuring distances to voxels from the current ship position (without flying):

```python
import math
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import get_world_position

ctrl = RadarController(radar, radius=1000, cell_size=10, boundingBoxX=50, boundingBoxY=50)
solid, meta, contacts, ore_cells = ctrl.scan_voxels()
pos = get_world_position(rc)

if solid:
    # solid points are WORLD coordinates — subtract ship position directly
    dists = sorted([math.sqrt((p[0]-pos[0])**2+(p[1]-pos[1])**2+(p[2]-pos[2])**2) for p in solid])
    print(f"Nearest: {dists[0]:.1f}m, range: {dists[0]:.1f}-{dists[-1]:.1f}m")
```

Diagnostic script: `/workspace/scripts/voxel_distance_meter.py` (supports `--loop`, `--ore-only`, `--cell`, `--radius`).
