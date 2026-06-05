---
name: se-asteroid-approach
description: "Fly a Space Engineers ship to the nearest asteroid and stop at a precise distance from the voxel surface. Uses SpaceNavigatorController with coarse/medium/fine scan profiles for obstacle-avoiding navigation."
triggers:
  - "подлететь к астероиду"
  - "fly to asteroid"
  - "подлёт к астероиду"
  - "approach asteroid"
  - "лететь к астероиду"
  - "asteroid approach"
---

# SE Asteroid Approach

Fly ship to nearest asteroid using `SpaceNavigatorController`.

## Key Principle

**Use `SpaceNavigatorController`** for all space flight. It handles scan profiles
(coarse/medium/fine), obstacle inflation, A* pathfinding, and safe target resolution
automatically. Never use raw `RemoteControl.goto()` or ad-hoc flight scripts.

## Quick Run

```bash
cd /workspace && python3 examples/space_flight/test_flight_nearest_asteroid.py --grid <grid_name>
```

Examples:
```bash
python3 examples/space_flight/test_flight_nearest_asteroid.py --grid skynet-baza0
python3 examples/space_flight/test_flight_nearest_asteroid.py --grid skynet-baza0 --dry-run
python3 examples/space_flight/test_flight_nearest_asteroid.py --grid skynet-baza0 --ship-radius 60
```

## How It Works

1. **Scan asteroids** — `asteroidIndex` from OreDetector via `space_navigator_v4.request_asteroids()`
2. **Target = asteroid center** — navigator resolves to nearest safe reachable point
3. **Three-phase scan** — COARSE (5000m, 50m cell) → MEDIUM (1000m, 10m cell) → FINE (300m, 10m cell)
4. **Obstacle inflation** — ship_radius + clearance_voxels * cell_size
5. **A* pathfinding** — route around voxels within scanned volume
6. **Safe arrival** — stops at resolved safe target, not inside asteroids

## Scan Profiles

| Profile | Radius | Cell | Rescan | Clearance |
|---|---:|---:|---:|---:|
| COARSE | 5000 m | 50 m | 2000 m | 12 cells |
| MEDIUM | 1000 m | 10 m | 500 m | 20 cells |
| FINE | 300 m | 10 m | 200 m | 20 cells |

## Files

- `examples/space_flight/test_flight_nearest_asteroid.py` — fly to nearest asteroid
- `examples/space_flight/test_flight_10km.py` — fly 10km forward (test)
- `examples/space_flight/space_navigator_v4.py` — CLI wrapper + asteroid finding utils
- `src/secontrol/controllers/space_navigator_controller.py` — the controller itself

## Programmatic Usage (from agent)

```python
from secontrol.controllers.space_navigator_controller import SpaceNavigatorController

controller = SpaceNavigatorController(grid_name="skynet-baza0")
try:
    result = controller.navigate_to((100000.0, 5000.0, -200000.0))
    print(result.status, result.final_position, result.resolved_target)
finally:
    controller.close()
```
