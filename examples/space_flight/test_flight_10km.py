#!/usr/bin/env python3
"""Fly 10 km along the ship forward vector using SpaceNavigatorController.

This script is intentionally different from a direct autopilot test:

- it computes the target as current RC position + current RC forward * distance;
- it does not abort when asteroids are detected on the straight line;
- it delegates routing to SpaceNavigatorController, so coarse/fine scans,
  inflated voxel clearance, safe target resolution, and A* replans are tested.

Usage:
    python examples/space_flight/test_flight_10km.py --grid skynet-baza0
    python examples/space_flight/test_flight_10km.py --grid skynet-baza0 --dry-run
    python examples/space_flight/test_flight_10km.py --grid skynet-baza0 --distance 10000 --max-speed 80
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Tuple

from dotenv import load_dotenv

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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
from secontrol.tools.navigation_tools import _dist, get_orientation, get_world_position  # noqa: E402


DEFAULT_GRID = "skynet-baza0"
DEFAULT_DISTANCE = 10_000.0


def _target_forward(
    start: Tuple[float, float, float],
    forward: Tuple[float, float, float],
    distance: float,
) -> Tuple[float, float, float]:
    return (
        start[0] + forward[0] * distance,
        start[1] + forward[1] * distance,
        start[2] + forward[2] * distance,
    )


def _print_point(label: str, point: Tuple[float, float, float]) -> None:
    print(f"{label}: ({point[0]:.2f}, {point[1]:.2f}, {point[2]:.2f})")


def _print_result(result: NavigationResult, elapsed: float) -> None:
    print()
    print("=" * 60)
    print("  Forward-vector flight complete")
    print("=" * 60)
    print(f"Status: {result.status}")
    if result.final_position:
        _print_point("Final position", result.final_position)
        print(f"Distance to requested target: {_dist(result.final_position, result.requested_target):.1f}m")
    _print_point("Requested target", result.requested_target)
    if result.resolved_target:
        _print_point("Resolved safe target", result.resolved_target)
    if result.nearest_voxel_distance < float("inf"):
        print(f"Nearest voxel in last scan: {result.nearest_voxel_distance:.1f}m")
    print(f"Profile: {result.profile}")
    print(f"Scans: {result.scan_count}")
    print(f"Replans: {result.replans}")
    if result.message:
        print(f"Message: {result.message}")
    print(f"Elapsed: {elapsed:.1f}s ({elapsed / 60.0:.1f}min)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fly forward by distance using radar-backed space navigation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python examples/space_flight/test_flight_10km.py --grid skynet-baza0
  python examples/space_flight/test_flight_10km.py --grid skynet-baza0 --dry-run
  python examples/space_flight/test_flight_10km.py --grid skynet-baza0 --distance 10000 --ship-radius 60
        """,
    )
    parser.add_argument("--grid", default=DEFAULT_GRID, help="Grid name")
    parser.add_argument(
        "--distance",
        type=float,
        default=DEFAULT_DISTANCE,
        help="Distance along current ship forward vector in meters",
    )
    parser.add_argument("--arrival", type=float, default=50.0, help="Arrival threshold in meters")
    parser.add_argument("--dry-run", action="store_true", help="Plan one bounded segment without moving")
    parser.add_argument("--ship-radius", type=float, default=None, help="Override ship radius in meters")
    parser.add_argument("--max-steps", type=int, default=200, help="Maximum scan/fly iterations")
    parser.add_argument("--max-replans", type=int, default=20, help="Maximum blocked/scan retries")

    parser.add_argument("--max-speed", type=float, default=50.0, help="Open-space coarse speed")
    parser.add_argument("--far-speed", type=float, default=30.0, help="Coarse speed with obstacles beyond 1km")
    parser.add_argument("--medium-speed", type=float, default=15.0, help="Coarse speed with nearer obstacles")
    parser.add_argument("--close-speed", type=float, default=3.0, help="Fine scan precision speed")

    parser.add_argument("--coarse-radius", type=float, default=COARSE_SCAN.radius)
    parser.add_argument("--coarse-cell", type=float, default=COARSE_SCAN.cell_size)
    parser.add_argument("--coarse-rescan", type=float, default=COARSE_SCAN.rescan_distance)
    parser.add_argument("--coarse-clearance", type=int, default=COARSE_SCAN.clearance_voxels)
    parser.add_argument("--medium-radius", type=float, default=MEDIUM_SCAN.radius)
    parser.add_argument("--medium-cell", type=float, default=MEDIUM_SCAN.cell_size)
    parser.add_argument("--medium-rescan", type=float, default=MEDIUM_SCAN.rescan_distance)
    parser.add_argument("--medium-clearance", type=int, default=MEDIUM_SCAN.clearance_voxels)
    parser.add_argument("--fine-radius", type=float, default=FINE_SCAN.radius)
    parser.add_argument("--fine-cell", type=float, default=FINE_SCAN.cell_size)
    parser.add_argument("--fine-rescan", type=float, default=FINE_SCAN.rescan_distance)
    parser.add_argument("--fine-clearance", type=int, default=FINE_SCAN.clearance_voxels)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.distance <= 0:
        raise SystemExit("--distance must be positive")

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
        max_replans=args.max_replans,
        max_steps=args.max_steps,
        dry_run=args.dry_run,
    )

    try:
        controller.rc.update()
        start = get_world_position(controller.rc)
        if start is None:
            raise RuntimeError("Cannot read current ship position from RemoteControl telemetry")

        basis = get_orientation(controller.rc)
        target = _target_forward(start, basis.forward, args.distance)

        print("=" * 60)
        print("  Forward-vector space navigation test")
        print("=" * 60)
        print(f"Grid: {args.grid}")
        print(f"Distance: {args.distance:.0f}m ({args.distance / 1000.0:.1f}km)")
        print(f"Dry run: {args.dry_run}")
        print(f"Ship radius: {controller.ship_radius:.1f}m")
        print(
            f"Coarse scan: radius={coarse.radius:.0f}m cell={coarse.cell_size:.0f}m "
            f"rescan={coarse.rescan_distance:.0f}m clearance={coarse.clearance_voxels} cells"
        )
        print(
            f"Medium scan: radius={medium.radius:.0f}m cell={medium.cell_size:.0f}m "
            f"rescan={medium.rescan_distance:.0f}m clearance={medium.clearance_voxels} cells"
        )
        print(
            f"Fine scan: radius={fine.radius:.0f}m cell={fine.cell_size:.0f}m "
            f"rescan={fine.rescan_distance:.0f}m clearance={fine.clearance_voxels} cells"
        )
        _print_point("Start", start)
        _print_point("Forward", basis.forward)
        _print_point("Requested target", target)
        print()
        print("The requested target is straight ahead; any asteroid cluster on that line")
        print("must be handled by the navigator through scanned-map routing.")

        started = time.time()
        result = controller.navigate_to(target)
        _print_result(result, time.time() - started)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        controller.close()
        print("Done.")


if __name__ == "__main__":
    main()
