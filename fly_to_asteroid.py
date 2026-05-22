#!/usr/bin/env python3
"""Fly skynet-baza0 to the second farthest asteroid and scan for resources.

Uses SpaceNavigatorController for safe obstacle-avoiding flight.
"""
from __future__ import annotations

import argparse
import os
import time
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__)))
load_dotenv(os.path.join(WORKSPACE, ".env"), override=True)

# Faction Redis user lacks SELECT; use admin credentials instead
os.environ["REDIS_USERNAME"] = os.getenv("REDIS_ADMIN_USERNAME", "admin")
os.environ["REDIS_PASSWORD"] = os.getenv("REDIS_ADMIN_PASSWORD", "")
os.environ["SE_OWNER_ID"] = "144115188075855921"

from secontrol.controllers.space_navigator_controller import (  # noqa: E402
    COARSE_SCAN,
    FINE_SCAN,
    MEDIUM_SCAN,
    NavigationResult,
    ScanProfile,
    SpaceNavigatorController,
    SpeedZone,
)
from secontrol.devices.ore_detector_device import OreDetectorDevice  # noqa: E402
from secontrol.tools.navigation_tools import _dist, get_world_position  # noqa: E402


ASTEROID_SEARCH_RADIUS = 50_000.0
ASTEROID_RESULT_LIMIT = 320
ASTEROID_TIMEOUT = 15.0


def request_asteroids(
    radar: OreDetectorDevice,
    *,
    radius: float = ASTEROID_SEARCH_RADIUS,
    limit: int = ASTEROID_RESULT_LIMIT,
    timeout: float = ASTEROID_TIMEOUT,
) -> Optional[Dict[str, Any]]:
    telemetry = radar.telemetry or {}
    previous = telemetry.get("asteroidIndex")
    previous_revision = previous.get("revision") if isinstance(previous, dict) else None

    radar.send_command(
        {
            "cmd": "asteroids",
            "targetId": int(radar.device_id),
            "state": {
                "radius": float(radius),
                "limit": int(limit),
                "includePlanets": False,
            },
        }
    )

    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        asteroid_index = (radar.telemetry or {}).get("asteroidIndex")
        if not isinstance(asteroid_index, dict):
            continue
        revision = asteroid_index.get("revision")
        if asteroid_index.get("ready") and revision != previous_revision:
            return asteroid_index
    return None


def find_asteroids_sorted(asteroid_index: Dict[str, Any]) -> list[Dict[str, Any]]:
    items = asteroid_index.get("items", [])
    if not isinstance(items, list) or not items:
        return []
    asteroids = [item for item in items if isinstance(item, dict) and item.get("kind") == "asteroid"]
    if not asteroids:
        asteroids = [item for item in items if isinstance(item, dict)]
    asteroids.sort(key=lambda item: float(item.get("distance", 0)), reverse=True)
    return asteroids


def scan_resources(radar: OreDetectorDevice, timeout: float = 60.0) -> Dict[str, list]:
    print("\nScanning for resources (ore_only=True)...")
    radar.update()
    radar.scan(
        include_players=False,
        include_grids=False,
        include_voxels=True,
        radius=500,
        cell_size=10,
        boundingBoxX=500,
        boundingBoxY=500,
        boundingBoxZ=500,
        ore_only=True,
        voxel_step=2,
    )

    start = time.time()
    while time.time() - start < timeout:
        time.sleep(1)
        radar.update()
        tel = radar.telemetry or {}
        scan = tel.get("scan", {})
        if isinstance(scan, dict):
            progress = scan.get("progressPercent", 0)
            in_progress = scan.get("inProgress", False)
            done = scan.get("done", False)
            if done or (not in_progress and progress > 50):
                print(f"Resource scan done: {progress}%")
                break

    time.sleep(2)
    radar.update()
    ore_cells = radar.ore_cells()
    print(f"Raw ore cells: {len(ore_cells)}")

    resources: Dict[str, list] = {}
    for cell in ore_cells:
        material = cell.get("material") or cell.get("ore") or "Unknown"
        if material not in resources:
            resources[material] = []
        resources[material].append(cell)

    return resources


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fly to second farthest asteroid and scan resources",
    )
    parser.add_argument("--grid", default="skynet-baza0", help="Grid name")
    parser.add_argument("--search-radius", type=float, default=ASTEROID_SEARCH_RADIUS)
    parser.add_argument("--arrival", type=float, default=50.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    coarse = ScanProfile(
        name="COARSE",
        radius=COARSE_SCAN.radius,
        cell_size=COARSE_SCAN.cell_size,
        rescan_distance=COARSE_SCAN.rescan_distance,
        clearance_voxels=COARSE_SCAN.clearance_voxels,
    )
    medium = ScanProfile(
        name="MEDIUM",
        radius=MEDIUM_SCAN.radius,
        cell_size=MEDIUM_SCAN.cell_size,
        rescan_distance=MEDIUM_SCAN.rescan_distance,
        clearance_voxels=MEDIUM_SCAN.clearance_voxels,
    )
    fine = ScanProfile(
        name="FINE",
        radius=FINE_SCAN.radius,
        cell_size=FINE_SCAN.cell_size,
        rescan_distance=FINE_SCAN.rescan_distance,
        clearance_voxels=FINE_SCAN.clearance_voxels,
    )
    speed_zone = SpeedZone(
        max_speed=100.0,
        far_speed=50.0,
        medium_speed=30.0,
        near_speed=15.0,
        close_speed=5.0,
    )

    controller = SpaceNavigatorController(
        grid_name=args.grid,
        speed_zone=speed_zone,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=args.arrival,
        max_steps=200,
        dry_run=args.dry_run,
        target_is_obstacle=True,
    )

    try:
        controller.rc.update()
        ship_pos = get_world_position(controller.rc)
        print("=" * 60)
        print("  Fly to second farthest asteroid")
        print("=" * 60)
        print(f"Grid: {args.grid}")
        if ship_pos:
            print(f"Ship: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")

        print(f"\nScanning asteroid index within {args.search_radius:.0f}m...")
        asteroid_index = request_asteroids(
            controller.radar,
            radius=args.search_radius,
            limit=ASTEROID_RESULT_LIMIT,
            timeout=ASTEROID_TIMEOUT,
        )
        if asteroid_index is None:
            raise RuntimeError("Asteroid index scan timed out")

        all_asteroids = find_asteroids_sorted(asteroid_index)
        if len(all_asteroids) < 2:
            raise RuntimeError(f"Need at least 2 asteroids, found {len(all_asteroids)}")

        print(f"\nAll asteroids (sorted by distance, farthest first):")
        for i, a in enumerate(all_asteroids[:10]):
            dist = float(a.get("distance", 0))
            name = a.get("name", "<unnamed>")
            marker = " <-- TARGET" if i == 1 else ""
            print(f"  {i+1}. {name}: {dist:.0f}m{marker}")

        target_asteroid = all_asteroids[1]
        target_center = target_asteroid.get("center")
        if not isinstance(target_center, (list, tuple)) or len(target_center) < 3:
            raise RuntimeError("Second farthest asteroid has no center coordinates")
        target = (float(target_center[0]), float(target_center[1]), float(target_center[2]))
        target_name = target_asteroid.get("name", "<unnamed>")
        target_dist = float(target_asteroid.get("distance", 0))

        print(f"\nTarget: {target_name}")
        print(f"Center: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        print(f"Distance: {target_dist:.0f}m")
        print(f"\nNavigating to asteroid...")

        started = time.time()
        result = controller.navigate_to(target)
        elapsed = time.time() - started

        print()
        print("=" * 60)
        print("  Flight complete")
        print("=" * 60)
        print(f"Status: {result.status}")
        if result.final_position:
            fp = result.final_position
            print(f"Final position: ({fp[0]:.0f}, {fp[1]:.0f}, {fp[2]:.0f})")
            print(f"Distance to asteroid center: {_dist(fp, target):.0f}m")
        print(f"Asteroid: {target_name}")
        print(f"Elapsed: {elapsed:.0f}s ({elapsed/60:.1f}min)")

        if result.status in ("arrived", "near"):
            resources = scan_resources(controller.radar)
            print("\n" + "=" * 60)
            print("  Resources on asteroid")
            print("=" * 60)
            if resources:
                for material, cells in sorted(resources.items()):
                    total = sum(
                        c.get("content", 0) if isinstance(c.get("content"), (int, float)) else 0
                        for c in cells
                    )
                    print(f"  {material}: {len(cells)} deposits, total content: {total}")
            else:
                print("  (no valuable ores detected)")
        else:
            print(f"\nDid not arrive (status={result.status}), skipping resource scan")

    except KeyboardInterrupt:
        print("\nInterrupted by user")
    except Exception as exc:
        print(f"\nERROR: {exc}")
        raise
    finally:
        controller.close()
        print("Done.")


if __name__ == "__main__":
    main()
