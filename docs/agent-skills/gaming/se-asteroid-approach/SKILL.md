---
name: se-asteroid-approach
description: "Fly a Space Engineers ship to the nearest asteroid and stop at a precise distance from the voxel surface. Uses continuous voxel scanning to stop by real surface distance, not geometric approximation."
triggers:
  - "подлететь к астероиду"
  - "fly to asteroid"
  - "подлёт к астероиду"
  - "approach asteroid"
  - "лететь к астероиду"
  - "asteroid approach"
---

# SE Asteroid Approach

Fly ship to nearest asteroid, stop at precise voxel distance.

## Key Principle

**NEVER use geometric approximation** (center + radius + stop_distance). Always stop by **real voxel distance** from the scanner. The asteroid surface is irregular — voxels are the truth.

## Quick Run

```bash
cd /workspace && python3 scripts/space_navigator_v3.py --grid <grid_name> --stop <meters>
```

Examples:
```bash
python3 scripts/space_navigator_v3.py --grid skynet-baza0 --stop 200   # 200m from surface
python3 scripts/space_navigator_v3.py --grid skynet-baza0 --stop 100   # 100m from surface
python3 scripts/space_navigator_v3.py --grid skynet-baza0 --stop 50 --speed 10  # slow & close
```

## How It Works

1. **Scan asteroids** — `asteroidIndex` from OreDetector, pick nearest by `distance`
2. **Target = asteroid center** — fly toward it with `fly_to_point()`
3. **ForwardScanner** — background thread, continuous voxel scan (radius=5000, cell=100, beam=100×100)
4. **Stop condition** — when `nearest_voxel_distance < --stop`, scanner disables RC + dampeners
5. **Two-phase flight** — Phase 1: 30 m/s (far→1000m), Phase 2: 5 m/s (1000m→stop)
6. **cancel_check** — `fly_to_point()` callback checks `scanner.arrived`

## Scanner Config

| Param | Value | Why |
|---|---|---|
| radius | 5000m | Detect asteroids at range |
| cell_size | 100m | Coarse = fast (~0.3s/scan) |
| beam X/Y | 100 cells | Wide beam = 10km coverage |
| scan_interval | 0.3s | Frequent checks during flight |

## Pitfalls

- **solidPoints are WORLD coordinates** — do NOT convert from indices. Distance = `sqrt((pt[0]-ship[0])² + ...)`
- **Voxel distance ≠ geometric distance** — nearest voxel at 240m when geometric surface at 100m is normal (discrete grid)
- **Scanner sees target's own voxels** — old code had `nearest < target_dist` check; new code doesn't need it since we stop by absolute voxel distance
- **ARRIVAL_DISTANCE=50** in `fly_to_point()` — if approach point is within 50m, ship "arrives" immediately. That's why we fly to CENTER, not to a computed approach point
- **Missing `if __name__ == "__main__"`** — script silently does nothing without it

## Device IDs (may change between sessions)

- skynet-baza0: OreDetector 72293940608757363, RC 117976856165503248
- skynet-baza1: OreDetector 137957581103677737, RC 119230182949753273

## Files

- `/workspace/scripts/space_navigator_v3.py` — main script
- `/workspace/examples/organized/autopilot/space/space_navigator_v3.py` — synced copy
- `/workspace/scripts/voxel_distance_meter.py` — diagnostic: measure voxel distances

## Programmatic Usage (from agent)

```python
# Quick fly-to-asteroid from agent code
import subprocess
result = subprocess.run(
    ["python3", "/workspace/scripts/space_navigator_v3.py", "--grid", "skynet-baza0", "--stop", "200"],
    capture_output=True, text=True, timeout=600
)
# Check: "ARRIVED" in output = success, "Nearest voxel: XXXm" = final distance
```
