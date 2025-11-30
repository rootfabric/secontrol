"""Lift a drone to a fixed altitude above the terrain using radar voxels.

This script demonstrates how to:
- prepare a grid with a remote control and ore detector
- trigger a voxel scan
- use ``SurfaceFlightController.lift_drone_to_altitude`` to move the grid
  to a target height relative to the detected surface
"""

import argparse
from typing import Optional

from secontrol.controllers.surface_flight_controller import SurfaceFlightController


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--grid",
        default=None,
        help="Grid name (defaults to the first available grid)",
    )
    parser.add_argument(
        "--altitude",
        type=float,
        default=15.0,
        help="Desired height above the surface in meters",
    )
    parser.add_argument(
        "--scan-radius",
        type=float,
        default=120.0,
        help="Voxel scan radius for the ore detector",
    )
    parser.add_argument(
        "--trace-step",
        type=float,
        default=None,
        help="Step in meters when tracing voxels along gravity (defaults to cell size)",
    )
    parser.add_argument(
        "--trace-distance",
        type=float,
        default=None,
        help="Maximum distance in meters to search for the surface along gravity",
    )
    parser.add_argument(
        "--skip-scan",
        action="store_true",
        help="Skip the initial voxel scan if you already have recent data",
    )
    return parser.parse_args()


def lift_to_altitude(
    grid_name: Optional[str],
    altitude: float,
    scan_radius: float,
    trace_step: Optional[float],
    trace_distance: Optional[float],
    skip_scan: bool,
) -> None:
    controller = SurfaceFlightController(grid_name, scan_radius)

    if not skip_scan:
        print(f"Scanning voxels within {scan_radius}m radius...")
        controller.scan_voxels()
    else:
        print("Skipping voxel scan; using existing radar data.")

    controller.lift_drone_to_altitude(
        altitude=altitude,
        trace_step=trace_step,
        trace_distance=trace_distance,
    )
    print("Lift command sent. Visited points:", controller.get_visited_points())


def main() -> None:
    args = parse_args()
    lift_to_altitude(
        grid_name=args.grid,
        altitude=args.altitude,
        scan_radius=args.scan_radius,
        trace_step=args.trace_step,
        trace_distance=args.trace_distance,
        skip_scan=args.skip_scan,
    )


if __name__ == "__main__":
    main()
