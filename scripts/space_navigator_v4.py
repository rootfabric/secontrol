#!/usr/bin/env python3
"""CLI wrapper for SpaceNavigatorController."""

from __future__ import annotations

import argparse
import os
import time
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
load_dotenv(os.path.join(WORKSPACE, ".env"))

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


DEFAULT_GRID = "skynet-baza0"
ASTEROID_SEARCH_RADIUS = 50_000.0
ASTEROID_RESULT_LIMIT = 320
ASTEROID_TIMEOUT = 15.0


def parse_target(value: str) -> Tuple[float, float, float]:
    value = value.strip()
    if value.upper().startswith("GPS:"):
        parts = value.split(":")
        if len(parts) < 5:
            raise ValueError("GPS target must be GPS:Name:X:Y:Z:")
        return (float(parts[2]), float(parts[3]), float(parts[4]))
    parts = [p.strip() for p in value.split(",")]
    if len(parts) != 3:
        raise ValueError("target must be 'x,y,z' or GPS:Name:X:Y:Z:")
    return (float(parts[0]), float(parts[1]), float(parts[2]))


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


def find_nearest_asteroid(asteroid_index: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    items = asteroid_index.get("items", [])
    if not isinstance(items, list) or not items:
        return None
    asteroids = [item for item in items if isinstance(item, dict) and item.get("kind") == "asteroid"]
    if not asteroids:
        asteroids = [item for item in items if isinstance(item, dict)]
    if not asteroids:
        return None
    return min(asteroids, key=lambda item: float(item.get("distance", float("inf"))))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Distance-scanned obstacle-avoiding space navigation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/space_navigator_v4.py --grid skynet-baza0 --target "100000,5000,-200000"
  python scripts/space_navigator_v4.py --grid skynet-baza0 --target "GPS:Waypoint:100000:5000:-200000:"
  python scripts/space_navigator_v4.py --grid skynet-baza0 --nearest-asteroid
  python scripts/space_navigator_v4.py --grid skynet-baza0 --target "..." --dry-run
        """,
    )
    parser.add_argument("--grid", default=DEFAULT_GRID, help="Grid name")
    parser.add_argument("--target", help="Target: 'x,y,z' or 'GPS:name:x:y:z:'")
    parser.add_argument(
        "--nearest-asteroid",
        action="store_true",
        help="Find the nearest asteroid and navigate toward its center safely",
    )

    parser.add_argument("--max-speed", type=float, default=50.0, help="Open-space speed (m/s)")
    parser.add_argument("--far-speed", type=float, default=30.0, help="Speed with obstacles beyond 1km")
    parser.add_argument("--medium-speed", type=float, default=15.0, help="Speed with obstacles beyond 300m")
    parser.add_argument("--close-speed", type=float, default=3.0, help="Fine/close speed")

    parser.add_argument("--coarse-cell", type=float, default=COARSE_SCAN.cell_size)
    parser.add_argument("--coarse-radius", type=float, default=COARSE_SCAN.radius)
    parser.add_argument("--coarse-rescan", type=float, default=COARSE_SCAN.rescan_distance)
    parser.add_argument("--coarse-clearance", type=int, default=COARSE_SCAN.clearance_voxels)
    parser.add_argument("--medium-cell", type=float, default=MEDIUM_SCAN.cell_size)
    parser.add_argument("--medium-radius", type=float, default=MEDIUM_SCAN.radius)
    parser.add_argument("--medium-rescan", type=float, default=MEDIUM_SCAN.rescan_distance)
    parser.add_argument("--medium-clearance", type=int, default=MEDIUM_SCAN.clearance_voxels)
    parser.add_argument("--fine-cell", type=float, default=FINE_SCAN.cell_size)
    parser.add_argument("--fine-radius", type=float, default=FINE_SCAN.radius)
    parser.add_argument("--fine-rescan", type=float, default=FINE_SCAN.rescan_distance)
    parser.add_argument("--fine-clearance", type=int, default=FINE_SCAN.clearance_voxels)

    parser.add_argument(
        "--ship-radius",
        type=float,
        default=None,
        help="Override ship radius in meters; auto-estimated from block AABBs if omitted",
    )
    parser.add_argument("--arrival", type=float, default=50.0, help="Arrival threshold in meters")
    parser.add_argument("--dry-run", action="store_true", help="Scan and plan one bounded segment, do not fly")
    parser.add_argument("--max-steps", type=int, default=200, help="Maximum scan/fly iterations")
    parser.add_argument(
        "--no-scanner",
        action="store_true",
        help="Deprecated compatibility flag; background scanning is not used by v4",
    )
    return parser


def print_result(result: NavigationResult, elapsed: float) -> None:
    print()
    print("=" * 60)
    print("  Navigation complete")
    print("=" * 60)
    print(f"Status: {result.status}")
    if result.final_position:
        pos = result.final_position
        print(f"Final position: ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
        print(f"Distance to requested target: {_dist(pos, result.requested_target):.0f}m")
    if result.resolved_target:
        target = result.resolved_target
        print(f"Resolved safe target: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
    if result.nearest_voxel_distance < float("inf"):
        print(f"Nearest voxel in last scan: {result.nearest_voxel_distance:.0f}m")
    print(f"Profile: {result.profile}")
    print(f"Scans: {result.scan_count}, replans: {result.replans}")
    if result.message:
        print(f"Message: {result.message}")
    print(f"Time: {elapsed:.0f}s ({elapsed / 60:.1f}min)")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.target and not args.nearest_asteroid:
        parser.error("provide --target or --nearest-asteroid")

    coarse = ScanProfile(
        name="COARSE",
        radius=args.coarse_radius,
        cell_size=args.coarse_cell,
        rescan_distance=args.coarse_rescan,
        clearance_voxels=args.coarse_clearance,
    )
    medium = ScanProfile(
        name="MEDIUM",
        radius=args.medium_radius,
        cell_size=args.medium_cell,
        rescan_distance=args.medium_rescan,
        clearance_voxels=args.medium_clearance,
    )
    fine = ScanProfile(
        name="FINE",
        radius=args.fine_radius,
        cell_size=args.fine_cell,
        rescan_distance=args.fine_rescan,
        clearance_voxels=args.fine_clearance,
    )
    speed_zone = SpeedZone(
        max_speed=args.max_speed,
        far_speed=args.far_speed,
        medium_speed=args.medium_speed,
        near_speed=(args.medium_speed + args.close_speed) / 2.0,
        close_speed=args.close_speed,
    )

    controller = SpaceNavigatorController(
        grid_name=args.grid,
        ship_radius=args.ship_radius,
        speed_zone=speed_zone,
        coarse_scan=coarse,
        medium_scan=medium,
        fine_scan=fine,
        arrival_distance=args.arrival,
        max_steps=args.max_steps,
        dry_run=args.dry_run,
        target_is_obstacle=args.nearest_asteroid,
    )

    try:
        if args.nearest_asteroid:
            print(f"Scanning asteroid index within {ASTEROID_SEARCH_RADIUS:.0f}m...")
            asteroid_index = request_asteroids(controller.radar)
            if asteroid_index is None:
                raise RuntimeError("Asteroid index scan timed out")
            nearest = find_nearest_asteroid(asteroid_index)
            if nearest is None:
                raise RuntimeError("No asteroid found")
            center = nearest.get("center")
            if not isinstance(center, (list, tuple)) or len(center) < 3:
                raise RuntimeError("Nearest asteroid has no center coordinates")
            target = (float(center[0]), float(center[1]), float(center[2]))
            print(
                "Nearest asteroid: "
                f"{nearest.get('name', '<unnamed>')} center=({target[0]:.0f},{target[1]:.0f},{target[2]:.0f}) "
                f"distance={float(nearest.get('distance', 0.0)):.0f}m"
            )
        else:
            target = parse_target(args.target or "")

        controller.rc.update()
        ship_pos = get_world_position(controller.rc)
        if ship_pos:
            print(f"Ship: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")
            print(f"Distance to target: {_dist(ship_pos, target):.0f}m")
        print(f"Ship radius: {controller.ship_radius:.1f}m")
        print(f"Coarse scan: radius={coarse.radius:.0f}m, cell={coarse.cell_size:.0f}m, bbox={coarse.beam}")
        print(f"Fine scan: radius={fine.radius:.0f}m, cell={fine.cell_size:.0f}m, bbox={fine.beam}")
        print(f"Dry run: {args.dry_run}")
        print()

        started = time.time()
        result = controller.navigate_to(target)
        print_result(result, time.time() - started)
    except KeyboardInterrupt:
        print("\n[NAV] Interrupted by user")
    except Exception as exc:
        print(f"\n[ERROR] {exc}")
        raise
    finally:
        controller.close()
        print("Done.")


if __name__ == "__main__":
    main()
