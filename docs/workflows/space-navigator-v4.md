# Space Navigator v4

## Overview

`SpaceNavigatorController` is the reusable base controller for moving ships in
space with radar-backed obstacle avoidance. The CLI wrapper is
`scripts/space_navigator_v4.py`.

The controller now uses one scan at a time:

1. Scan voxels and grid contacts.
2. Build a `RawRadarMap`.
3. Inflate obstacles by ship radius plus scan-profile clearance.
4. Resolve the requested target to the nearest safe reachable cell if needed.
5. Run A*.
6. Fly only to a bounded waypoint that remains inside the scanned volume.
7. Rescan after the profile distance is covered.

There is no default background scanner and no blind direct-flight fallback.

## Quick Start

```bash
# Fly to a point.
python scripts/space_navigator_v4.py --grid skynet-baza0 --target "100000,5000,-200000"

# GPS target.
python scripts/space_navigator_v4.py --grid skynet-baza0 --target "GPS:Base:100000:5000:-200000:"

# Plan one bounded segment without moving.
python scripts/space_navigator_v4.py --grid skynet-baza0 --target "100000,5000,-200000" --dry-run

# Fly toward the nearest asteroid center; final point is resolved to safe space.
python scripts/space_navigator_v4.py --grid skynet-baza0 --nearest-asteroid

# Test the navigator by targeting a point 10 km straight ahead.
python scripts/test_flight_10km.py --grid skynet-baza0

# Test the navigator by targeting the nearest asteroid center.
python scripts/test_flight_nearest_asteroid.py --grid skynet-baza0
```

## Scan Profiles

| Profile | Radius | Cell | Rescan | Clearance |
|---|---:|---:|---:|---:|
| `COARSE` | 5000 m | 50 m | 2000 m | 12 cells |
| `MEDIUM` | 1000 m | 10 m | 500 m | 20 cells |
| `FINE` | 300 m | 10 m | 200 m | 20 cells |

The default route uses all three profiles. Coarse is for open-space cruise,
medium is entered before nearby asteroid work, and fine is for the final
parking boundary.

The radar bbox is sent to the game server in meters. It is computed as
`ceil(2 * radius / cell_size) * cell_size`, so the default coarse scan sends a
10000 m bbox, medium sends 2000 m, and fine sends 600 m. Those correspond to
200x200x200, 200x200x200, and 60x60x60 cells.

Profile switching is conservative:

- `MEDIUM` starts when the target is within 1000 m, or when a coarse scan sees
  any voxel within the medium activation range before movement.
- `FINE` starts only when the requested target is inside the fine scan radius.
  Nearby voxels by themselves keep the controller in `MEDIUM`, because medium
  already uses the 10 m grid and keeps a larger safe map around the ship.
- Medium movement is speed-capped by `--medium-speed`; fine movement uses
  `--close-speed`.

## Safety Model

The controller estimates ship radius from `grid.blocks` world bounding boxes.
Pass `--ship-radius` to override it. If no block bounds are available, the
fallback is 50 m.

Obstacle inflation is:

```text
ship_radius + clearance_voxels * cell_size
```

With the defaults this means:

- Coarse: ship radius plus 600 m.
- Medium: ship radius plus 200 m.
- Fine: ship radius plus 200 m.

If the requested target is inside an asteroid or too close to voxels, the
controller treats the nearest safe reachable point as the destination. The
returned `NavigationResult` includes both `requested_target` and
`resolved_target`.

During fine parking, safe-target resolution prefers the side of the target that
faces the current ship position. If the ship is already on a safe inflated
boundary near the requested target, navigation stops there instead of chasing a
new safe cell around the far side of the asteroid.

When navigating to an asteroid center, the controller never treats an empty
medium or fine scan as permission to fly into the center. If no voxels are
returned while the asteroid center is inside the medium or fine scan volume,
navigation stops with `scan_failed` instead of moving on a blind map. Coarse can
still resolve a conservative long-range standoff point, but medium/fine require
voxel evidence before approach or parking.

## Python API

```python
from secontrol.controllers.space_navigator_controller import SpaceNavigatorController

controller = SpaceNavigatorController(
    grid_name="skynet-baza0",
    ship_radius=None,  # auto-estimate from block AABBs
    dry_run=False,
)

try:
    result = controller.navigate_to((100000.0, 5000.0, -200000.0))
    print(result.status, result.final_position, result.resolved_target)
finally:
    controller.close()
```

`NavigationResult` fields:

- `status`: `arrived`, `safe_target_reached`, `dry_run`, `blocked`,
  `scan_failed`, `flight_failed`, `telemetry_lost`, `cancelled`, or `max_steps`.
- `final_position`: last known ship position.
- `requested_target`: original target.
- `resolved_target`: safe target used for the last plan.
- `profile`: last scan profile.
- `scan_count`, `replans`, `nearest_voxel_distance`.

## CLI Options

Common options:

```bash
--grid skynet-baza0
--target "x,y,z"
--nearest-asteroid
--dry-run
--ship-radius 50
--arrival 50
--max-steps 200
```

Scan tuning:

```bash
--coarse-radius 5000 --coarse-cell 50 --coarse-rescan 2000 --coarse-clearance 12
--medium-radius 1000 --medium-cell 10 --medium-rescan 500 --medium-clearance 20
--fine-radius 300 --fine-cell 10 --fine-rescan 200 --fine-clearance 20
```

Speed tuning:

```bash
--max-speed 50 --far-speed 30 --medium-speed 15 --close-speed 3
```

Fine-profile movement always uses `close-speed`; medium movement is capped by
`medium-speed`; coarse movement uses the speed zone selected from the nearest
voxel distance in the latest scan.

## Forward-Vector Test

`scripts/test_flight_10km.py` is a focused real-flight example for testing
asteroid avoidance. It reads the current RemoteControl position and forward
vector, builds a target 10 km ahead, then calls `SpaceNavigatorController`.

The target remains straight ahead even if an asteroid cluster is on that line.
The script does not run a separate line-clear check and does not fall back to
direct SE autopilot; any deviation around voxels must come from the scanned-map
route.

```bash
python scripts/test_flight_10km.py --grid skynet-baza0
python scripts/test_flight_10km.py --grid skynet-baza0 --dry-run
python scripts/test_flight_10km.py --grid skynet-baza0 --distance 10000 --ship-radius 60
```

## Nearest-Asteroid Test

`scripts/test_flight_nearest_asteroid.py` finds the nearest asteroid through the
radar asteroid index, targets the asteroid center, and relies on the navigator
to resolve the final point to safe space near the voxels.

```bash
python scripts/test_flight_nearest_asteroid.py --grid skynet-baza0
python scripts/test_flight_nearest_asteroid.py --grid skynet-baza0 --dry-run
python scripts/test_flight_nearest_asteroid.py --grid skynet-baza0 --ship-radius 60
```

## Failure Behavior

On scan or path failure the controller disables autopilot, enables dampeners,
and retries up to `max_replans`. If no safe path is found, it returns a failed
`NavigationResult` instead of flying directly.

The current map boundary is always enforced during movement. If the ship nears
the edge of the scanned volume, the active `fly_to_point` call is cancelled and
the next loop performs a fresh scan.
