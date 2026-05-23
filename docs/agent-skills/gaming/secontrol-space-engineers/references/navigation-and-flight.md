# Navigation & Flight Control — secontrol API Reference

**⚠️ IMPORTANT — Choose the right flight method:**

| Situation | Use this |
|---|---|
| **Normal space flight (between asteroids, around bases, long distance)** | `SpaceNavigatorController` — 3-phase coarse/medium/fine obstacle scanning |
| **Precise final parking, connector alignment, sub-meter maneuvers** | Low-level `RemoteControl.goto()` or `fly_to_point()` with `cancel_check` |
| **Planetary surface flight with altitude control** | `SurfaceFlightController` |
| **No RemoteControl — cockpit + gyro + thruster manual** | Manual gyro/thruster pattern (see "Manual flight" section) |

## Если перемещение не происходит — диагностика готовности

Если корабль не двигается или команда `navigate_to()` не работает, сначала проверь готовность:

```bash
python examples/organized/diagnostics/check_flight_ready.py <grid_name>
```

**Что проверяет `check_flight_ready.py`:**
- Заряд батарей (< 20% = не готов)
- Водородные двигатели + уровень топлива
- Ion thrusters как fallback

**Возможные причины отказа:**
| Проблема | Сообщение |
|----------|-----------|
| Низкий заряд батарей | `Low battery charge: X%` |
| Нет водорода, нет ионных | `CRITICAL: No hydrogen fuel and no ion backup!` |
| Низкий водород | `WARNING: Low hydrogen, ion thrusters available` |

**Если не готов** — сначала зарядить батареи / заправить водород, затем повторить попытку.

---

## SpaceNavigatorController — RECOMMENDED for all space movement

**For normal ship movement in space, ALWAYS use `SpaceNavigatorController`.**
Do NOT use ad-hoc `RemoteControl.goto()` calls — the ship will crash into asteroids.

```python
from secontrol.controllers.space_navigator_controller import SpaceNavigatorController

controller = SpaceNavigatorController(
    grid_name="MyShip",          # grid name or ID
    ship_radius=None,             # auto-estimated from block AABBs, or set manually in meters
    arrival_distance=50.0,        # stop when within N meters of target
)

# Navigate to target — handles obstacle scanning automatically
result = controller.navigate_to((x, y, z))
print(result.status, result.final_position)

# Or fly to nearest asteroid
controller.target_is_obstacle = True
result = controller.navigate_to(asteroid_center)

controller.close()
```

**CLI wrapper** (run directly):
```bash
python examples/space_flight/space_navigator_v4.py --grid <name> --target "x,y,z"
python examples/space_flight/space_navigator_v4.py --grid <name> --nearest-asteroid
```

**Key features:**
- 3-phase scanning: coarse (long range) → medium → fine (close range)
- Continuous voxel map with path re-planning when obstacles appear
- Speed zones: fast cruise when clear, slow when near obstacles
- Arrival threshold: `arrival_distance` parameter

**⚠️ Only use low-level `rc.goto()` or `fly_to_point()` for:**
- Final parking at a connector (sub-meter precision)
- Docking approach sequences
- Any maneuver where you need exact GPS waypoints with no obstacle scanning

---

## RemoteControlDevice — full API

```python
from secontrol.devices.remote_control_device import RemoteControlDevice
rc = grid.get_first_device(RemoteControlDevice)
```

### Autopilot

```python
rc.goto(gps_string, speed=10.0, gps_name="Target", dock=False)
# gps_string format: "GPS:Name:X:Y:Z:" (trailing colon REQUIRED)
# speed: m/s, dock: enables docking approach mode

rc.set_mode("oneway")      # "oneway" | "patrol" | "circle"
rc.set_collision_avoidance(True/False)  # SE built-in collision avoidance
rc.enable()                 # engage autopilot
rc.disable()                # disengage autopilot (BRAKE)
```

**Critical pitfalls:**
- `set_collision_avoidance(False)` — recommended when doing custom obstacle scanning (SE built-in is unreliable)
- GPS format MUST have trailing colon: `GPS:Name:123.45:678.90:0.00:`
- After `goto()`, poll `telemetry['autopilotEnabled']` to confirm engagement (takes 0.5-3s)
- `disable()` stops autopilot but doesn't enable dampeners — call `dampeners_on()` separately for full stop

### Dampeners & Thrusters

```python
rc.dampeners_on()           # enable dampeners (auto-brake)
rc.dampeners_off()          # disable dampeners (drift mode)
rc.thrusters_on()           # enable all thrusters
rc.thrusters_off()          # disable all thrusters
```

### Gyro & Handbrake

```python
rc.gyro_control_on()        # enable gyro control
rc.gyro_control_off()       # disable gyro control
rc.handbrake_on()           # enable handbrake (rovers)
rc.handbrake_off()          # disable handbrake
```

### Planetary Autopilot

```python
rc.planetary_autopilot_on()  # enable planetary autopilot mode
rc.planetary_autopilot_off() # disable
```

### Telemetry keys

```python
tel = rc.telemetry or {}
pos = tel.get("worldPosition") or tel.get("position")  # {"x","y","z"}
vel = tel.get("linearVelocity") or tel.get("velocity")  # {"x","y","z"} m/s
orient = tel.get("orientation")  # {"forward":{"x","y","z"}, "up":..., "right"/"left":...}
grav = tel.get("gravitationalVector")  # {"x","y","z"} m/s²
enabled = tel.get("autopilotEnabled")  # bool
```

### Orientation helpers

```python
fwd, up, right = rc.get_orientation_vectors_world()
# Returns (forward, up, right) tuples in world coordinates
# Falls back through orientation.forward → telemetry.forward → default (0,0,1)
```

## GyroDevice

```python
from secontrol.devices.gyro_device import GyroDevice
gyros = grid.find_devices_by_type(GyroDevice)
```

### Override control

```python
gyro.set_override(pitch=0.5, yaw=-0.3, roll=0.0)  # values clamped to [-1, 1]
gyro.clear_override()                               # reset to auto
gyro.enable() / gyro.disable()
```

### Align to world vector

```python
gyro.align_vector({"x": 0, "y": 1, "z": 0})  # aim ship's forward at world Up
# OR
gyro.aim_vector([0, 1, 0])                     # synonym, different cmd string
```

Both send the vector to the SE plugin which handles the actual rotation. Takes dict with x/y/z, list/tuple of 3, or string "x,y,z".

## ThrusterDevice

```python
from secontrol.devices.thruster_device import ThrusterDevice
thrusters = grid.find_devices_by_type(ThrusterDevice)
```

```python
thruster.set_thrust(override=0.5)     # thrust override 0.0-1.0
thruster.set_thrust(enabled=True)     # enable/disable
```

## navigation_tools.py — utility functions

```python
from secontrol.tools.navigation_tools import (
    get_world_position,   # device → (x,y,z) or None
    get_orientation,      # device → Basis(forward, up, right)
    get_gravity_up,       # device → normalized up vector or None
    fly_to_point,         # blocking flight with cancel_check support
    goto,                 # simple blocking flight (grid, gps_or_tuple, speed)
    align_to_gravity,     # gyro-based gravity alignment
    align_to_up_vector,   # gyro-based arbitrary up alignment
    align_heading_with_gravity,  # combine gravity up + heading direction
    Basis,                # orientation container with .forward, .up, .right
)
```

### fly_to_point() — blocking flight with cancel support

```python
pos = fly_to_point(
    rc, target_tuple,
    waypoint_name="Waypoint",
    speed_far=15.0,       # speed when far
    speed_near=5.0,       # speed when close (< 15m)
    arrival_distance=0.2, # consider arrived
    stop_tolerance=0.7,   # autopilot stopped, close enough
    max_flight_time=240.0,
    check_interval=0.2,
    cancel_check=lambda: some_flag,  # return True to abort
    ship_connector=conn,              # optional: for docking
    connector_target=conn_pos,        # optional: connector target pos
)
```

Returns final position or None if autopilot didn't start.

**⚠️ `arrival_distance` matters for precision approaches.** Default `arrival_distance=50.0` means the ship "arrives" when within 50m of the target. For precision stops (e.g. 200m from asteroid surface), use `arrival_distance=5.0` or `10.0`. If the ship is already within `arrival_distance` of a previously-computed target, `fly_to_point` immediately returns without flying — recompute the approach point from the current position.

### Alignment functions

```python
align_to_gravity(grid, gain=2.0, max_rate=1.0, tolerance=0.01)
# Aligns ship Up with gravity using gyro overrides

align_to_up_vector(grid, (0,1,0), gain=2.0)
# Aligns ship Up with arbitrary vector

align_heading_with_gravity(grid, target_forward, gain=2.0)
# Aligns Up to gravity + rotates heading toward target_forward (horizontal projection)
```

All accept `cancel_check=lambda: bool` for early exit.

## SurfaceFlightController — surface flight with voxel map

```python
from secontrol.controllers.surface_flight_controller import SurfaceFlightController

sfc = SurfaceFlightController("skynet-baza0", scan_radius=100.0, boundingBoxY=100.0)
# Auto-connects to grid, finds Radar + RC, loads initial voxel map from Redis
```

Key methods:
```python
sfc.scan_voxels(persist_to_shared_map=True)  # radar scan → occupancy grid + Redis
sfc.ensure_map_coverage_for_point(pos)       # expand map if point is near edge
sfc._sample_surface_along_path(start, dir, dist, step)  # sample heights along path
sfc._find_surface_point_along_gravity(pos, down, max_dist, step)  # trace down to surface
```

This controller is for planetary/surface flight — not needed for space navigation.

## Forward-scan obstacle avoidance pattern

Reusable pattern for space flight with continuous obstacle detection.

### ⚠️ Scan parameter tuning (critical)

Large bounding boxes cause scans to **reset at 0-1.5% progress** before completing.
The scan tiles can't finish within the 5s timeout → always returns 0 solid points.

| Config | Tiles | Result |
|--------|-------|--------|
| `bbox 100x100x5000, cell=10` | 1,024,000 | ❌ Resets at 0-1.5%, never completes |
| `bbox 30x30x80, cell=5` | ~2,300 | ⚠️ May work but unreliable during flight |
| **`bbox 20x20x100, cell=10`** | **4,000** | **✅ Completes in ~5s, detects voxels (narrow beam)** |
| **`bbox 100x100x100, cell=100`** | **~1,000** | **✅ Completes in ~0.3s, long-range detection (5km radius)** |

**Two scanner configs serve different purposes:**

1. **Narrow beam** (`bbox 20x20x100, cell=10`) — close-range obstacle detection, ~200×200×1000m beam, 5s per scan. Good for planetary approach where you need to detect terrain at close range.

2. **Long-range** (`bbox 100x100x100, cell=100, radius=5000`) — distant asteroid detection, ~10km × 10km × 10km coverage, 0.3s per scan. Detects asteroids at 3-5km distance. Use this for space flight approach.

**Working real-time configs** (tested 2026-05-17 on skynet-baza0/baza1):

```python
# Narrow beam — close-range obstacle detection (~5s per scan)
RadarController(
    radar,
    radius=1000.0,
    cell_size=10.0,
    boundingBoxX=20,    # 200m wide beam
    boundingBoxY=20,    # 200m tall beam
    boundingBoxZ=100,   # 1000m deep forward beam
    ore_only=False,
)

# Long-range — asteroid detection (~0.3s per scan)
RadarController(
    radar,
    radius=5000.0,
    cell_size=100.0,    # 100m voxels — coarse but fast
    boundingBoxX=100,   # 10km wide
    boundingBoxY=100,   # 10km tall
    boundingBoxZ=100,   # 10km deep
    ore_only=False,
)
```

### ForwardScanner class

```python
import threading, time
from secontrol.controllers.radar_controller import RadarController

class ForwardScanner:
    """Background thread: forward beam scan for obstacles with distance-based filtering.

    ⚠️ CRITICAL: The scanner detects ALL voxels in the beam, including the target
    asteroid itself. Voxels far away are the TARGET — keep flying. Voxels close
    are an OBSTACLE — stop immediately. The OBSTACLE_RANGE threshold distinguishes.

    Scanner MUST directly call rc.disable() — don't rely solely on cancel_check
    (cancel_check is polled by fly_to_point each iteration, which may be too slow).
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

    def start(self, interval=0.3):
        self._running = True
        threading.Thread(target=self._loop, args=(interval,), daemon=True).start()

    def stop(self): self._running = False

    def _loop(self, interval):
        ctrl = RadarController(
            self.radar,
            radius=5000.0,
            cell_size=100.0,
            boundingBoxX=100, boundingBoxY=100, boundingBoxZ=100,
            ore_only=False,
        )
        while self._running:
            try:
                solid, meta, contacts, ore_cells = ctrl.scan_voxels()
                if solid and len(solid) > 0:
                    # ⚠️ solid points are WORLD coordinates — must subtract ship position
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
                        with self._lock:
                            self._obstacle = True
                        try:
                            self.rc.disable()
                            self.rc.dampeners_on()
                        except: pass
                        return
                    # else: voxels are far away = target asteroid, keep flying
            except: pass
            time.sleep(interval)
```

### Integration with fly_to_point()

```python
scanner = ForwardScanner(radar, rc)
scanner.start()

def should_cancel():
    """Update target distance as ship moves, then check obstacle."""
    rc.update()
    pos = get_world_position(rc)
    if pos:
        scanner.target_distance = _dist(pos, target)
    return scanner.obstacle_detected

final_pos = fly_to_point(
    rc, target,
    speed_far=15.0, speed_near=5.0,
    arrival_distance=50.0,
    max_flight_time=600.0,
    cancel_check=should_cancel,  # updates target_distance + checks obstacle
)

scanner.stop()

if scanner.obstacle_detected:
    print("STOPPED BY SCANNER — voxels detected ahead")
    rc.disable()
    rc.dampeners_on()
```

**Key design decisions:**
- `bbox 100x100x100, cell_size=100, radius=5000` — long-range scan (~0.3s), detects asteroids at 3-5km. Use this for space approach.
- `bbox 20x20x100, cell_size=10` — narrow beam (~5s), close-range obstacle detection. Use for planetary/low-altitude.
- **OBSTACLE_RANGE threshold** (default 1000m) — voxels farther than this are the TARGET ASTEROID (keep flying). Voxels closer are an OBSTACLE (stop). This is the critical distinction.
- Scanner computes `nearest = min(sqrt(x²+y²+z²))` for all solid points and compares to `obstacle_range`
- Scanner directly calls `rc.disable()` + `rc.dampeners_on()` on detection — don't rely solely on cancel_check (too slow)
- `cancel_check=lambda: scanner.obstacle_detected` — `fly_to_point()` checks this each iteration, returns `True` to abort
- Daemon thread — dies when main process exits
- Lock protects only the boolean flag for minimal contention
- `scan_voxels()` takes ~0.3s per call with long-range config; `interval=0.3` means next scan starts immediately after previous finishes

## Gyro orientation — point forward at a target (P-controller)

For space flight, you often need to orient the ship's forward vector toward a target point.
Use the **same P-controller pattern** as `align_to_up_vector` (proven stable), adapted for forward:

```python
from secontrol.tools.navigation_tools import get_orientation, _dot, _normalize
import math

basis = get_orientation(device)  # works with CockpitDevice or RemoteControlDevice
desired_fwd = _normalize((target[0]-pos[0], target[1]-pos[1], target[2]-pos[2]))

# Project desired direction into ship's local frame
local_y = _dot(desired_fwd, basis.up)      # positive = target is "above"
local_x = _dot(desired_fwd, basis.right)   # positive = target is "right"

# P-controller (sign convention from align_to_up_vector)
pitch_cmd = max(-1.0, min(1.0, -local_y * gain))   # gain=1.5 typical
yaw_cmd   = max(-1.0, min(1.0, -local_x * gain))

for gyro in gyros:
    gyro.set_override(pitch=pitch_cmd, yaw=yaw_cmd, roll=0.0)

# Angle error for thrust gating
angle_err = math.acos(max(-1.0, min(1.0, _dot(basis.forward, desired_fwd))))
```

**⚠️ Do NOT add a derivative term (D-gain).** The `align_to_up_vector` reference uses pure P-controller.
Adding D-term to gyro orientation causes wild oscillation — the ship spins continuously because
the D-term amplifies noise in the angle error signal. If you need clamping, use `max_rate` limiting
instead of D-damping.

**Thrust gating**: only fire thrusters when `angle_err < 0.5` (~30°). Otherwise the ship accelerates
in the wrong direction while turning.

## Asteroid approach workflow

Pattern for autonomous flight to nearest asteroid with distance-based stop.

```python
from secontrol.devices.ore_detector_device import OreDetectorDevice
import math

# 1. Find nearest asteroid (use request_asteroids() with revision tracking)
radar = grid.get_first_device(OreDetectorDevice)
asteroid_index = request_asteroids(radar, radius=50000, timeout=15)  # see asteroid-scanning.md
items = asteroid_index.get("items", [])
asteroids = [i for i in items if i.get("kind") == "asteroid"]
nearest = min(asteroids or items, key=lambda a: float(a.get("distance", 1e12)))

# 2. Compute approach point — FINAL stop at (radius + stop_distance) from center
center = tuple(float(c) for c in nearest["center"])
radius = float(nearest.get("approxRadius", 50.0))
stop_dist = 500.0  # meters from surface

dx, dy, dz = ship_pos[0]-center[0], ship_pos[1]-center[1], ship_pos[2]-center[2]
dist = math.sqrt(dx*dx + dy*dy + dz*dz)
direction = (dx/dist, dy/dist, dz/dist)
stop_radius = radius + stop_dist  # distance from CENTER
approach_point = (center[0]+direction[0]*stop_radius,
                  center[1]+direction[1]*stop_radius,
                  center[2]+direction[2]*stop_radius)

# 3. Enable RC (REQUIRED sequence)
rc.enable(); rc.gyro_control_on(); rc.thrusters_on(); rc.dampeners_on()
time.sleep(1)

# 4. Two-phase flight with ForwardScanner (OBSTACLE_RANGE=1000m)
SLOW_DISTANCE = 1000.0
OBSTACLE_RANGE = 1000.0

scanner = ForwardScanner(radar, rc, obstacle_range=OBSTACLE_RANGE)
scanner.start()

dist_to_approach = _dist(ship_pos, approach_point)
if dist_to_approach > SLOW_DISTANCE:
    # Phase 1: fast approach to SLOW_DISTANCE boundary
    fly_dist = dist_to_approach - SLOW_DISTANCE
    phase1_target = (ship_pos[0]+direction[0]*fly_dist, ...)
    fly_to_point(rc, phase1_target, speed_far=30.0, ...,
                 cancel_check=lambda: scanner.obstacle_detected)

# Phase 2: slow approach to final point
fly_to_point(rc, approach_point, speed_near=5.0, ...,
             cancel_check=lambda: scanner.obstacle_detected)

# 5. Stop
scanner.stop()
rc.disable(); rc.dampeners_on(); rc.handbrake_close()
```

**Key**: The `compute_approach_point` formula `center + direction * (radius + stop_distance)` gives
the FINAL stop position, not an intermediate waypoint. The ship stops at exactly `stop_distance`
from the asteroid surface regardless of starting position. See `references/asteroid-flight-pattern.md`
for the full tested implementation.

## Manual flight vs autopilot — when to use which

| Approach | Requires | Use case |
|----------|----------|----------|
| `goto(grid, point, speed)` | RemoteControl | Simple one-shot flight, SE handles everything |
| `fly_to_point(rc, point, ...)` | RemoteControl | Flight with cancel_check, speed ramping, docking |
| Gyro + Thruster manual | Cockpit + pilot | No RC available, need full control |
| SurfaceFlightController | RemoteControl + Radar | Planetary surface flight with altitude control |

**`goto()` and `fly_to_point()` require RemoteControlDevice.** They call `rc.goto()` which is
SE's built-in autopilot. If there's no RC on the grid, these fail with "RemoteControlDevice не найден".

**CockpitDevice provides flight telemetry** (position, velocity, orientation, gravity) but NOT
autopilot. For manual flight without RC, use CockpitDevice for telemetry + gyro/thruster overrides.
Requires `hasPilot=True` in cockpit telemetry (someone must be seated).
