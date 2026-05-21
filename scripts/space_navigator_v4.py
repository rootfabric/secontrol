#!/usr/bin/env python3
"""
Space Navigator v4 — Multi-scale obstacle-avoiding navigation in space.

Core algorithm:
  1. COARSE scan (cell=100m, radius=5km) — fast long-range overview
  2. A* pathfind around asteroids and ships
  3. Adaptive speed: 50 m/s in open space → 3 m/s near obstacles
  4. Background scanner continuously monitors for new obstacles
  5. Automatic replan when obstacles detected on path
  6. When close: FINE scan (cell=10m, radius=300m) for precision

Other ships/grids are detected via radar contacts and added as
obstacles to the occupancy grid, so A* routes around them.

Usage:
    # Navigate to a point (far away, 100km+)
    python3 space_navigator_v4.py --grid skynet-baza0 --target "100000,5000,-200000"

    # Navigate to GPS coordinate
    python3 space_navigator_v4.py --grid skynet-baza0 --target "GPS:Waypoint:100000:5000:-200000:"

    # Dry run (scan + plan, no flying)
    python3 space_navigator_v4.py --grid skynet-baza0 --target "100000,5000,-200000" --dry-run

    # Custom speed profile
    python3 space_navigator_v4.py --grid skynet-baza0 --target "..." --max-speed 40 --close-speed 5

    # Without background scanner (simpler, less reactive)
    python3 space_navigator_v4.py --grid skynet-baza0 --target "..." --no-scanner
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from typing import Optional, Tuple

# ── Setup ────────────────────────────────────────────────────────────────
WORKSPACE = "/workspace"
from dotenv import load_dotenv
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import close, prepare_grid
from secontrol.controllers.space_navigator_controller import (
    SpaceNavigatorController,
    ScanProfile,
    SpeedZone,
    COARSE_SCAN,
    MEDIUM_SCAN,
    FINE_SCAN,
)
from secontrol.tools.navigation_tools import get_world_position, _dist


DEFAULT_GRID = "skynet-baza0"


def parse_target(s: str) -> Tuple[float, float, float]:
    """Parse target from 'x,y,z' or 'GPS:name:x:y:z:' format."""
    if s.startswith("GPS:"):
        parts = s.split(":")
        return (float(parts[2]), float(parts[3]), float(parts[4]))
    parts = s.split(",")
    return (float(parts[0]), float(parts[1]), float(parts[2]))


def main():
    parser = argparse.ArgumentParser(
        description="Multi-scale obstacle-avoiding space navigation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fly to a distant point (100km away)
  python3 space_navigator_v4.py --grid skynet-baza0 --target "100000,5000,-200000"

  # Dry run to preview the route
  python3 space_navigator_v4.py --grid skynet-baza0 --target "100000,5000,-200000" --dry-run

  # Custom speeds
  python3 space_navigator_v4.py --grid skynet-baza0 --target "..." --max-speed 40 --close-speed 5
        """,
    )
    parser.add_argument("--grid", default=DEFAULT_GRID, help="Grid name")
    parser.add_argument("--target", required=True,
                        help="Target: 'x,y,z' or 'GPS:name:x:y:z:'")

    # Speed options
    parser.add_argument("--max-speed", type=float, default=50.0,
                        help="Max speed in open space (m/s, default: 50)")
    parser.add_argument("--far-speed", type=float, default=30.0,
                        help="Speed when obstacle > 3km (m/s, default: 30)")
    parser.add_argument("--medium-speed", type=float, default=15.0,
                        help="Speed when obstacle > 1km (m/s, default: 15)")
    parser.add_argument("--close-speed", type=float, default=3.0,
                        help="Speed when obstacle < 300m (m/s, default: 3)")

    # Scan options
    parser.add_argument("--coarse-cell", type=float, default=100.0,
                        help="Coarse scan cell size (m, default: 100)")
    parser.add_argument("--coarse-radius", type=float, default=5000.0,
                        help="Coarse scan radius (m, default: 5000)")
    parser.add_argument("--fine-cell", type=float, default=10.0,
                        help="Fine scan cell size (m, default: 10)")
    parser.add_argument("--fine-radius", type=float, default=300.0,
                        help="Fine scan radius (m, default: 300)")

    # Safety options
    parser.add_argument("--ship-radius", type=float, default=30.0,
                        help="Ship safety radius for obstacle inflation (m, default: 30)")
    parser.add_argument("--arrival", type=float, default=50.0,
                        help="Arrival distance threshold (m, default: 50)")

    # Control options
    parser.add_argument("--no-scanner", action="store_true",
                        help="Disable background forward scanner")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan and plan only, don't fly")
    parser.add_argument("--max-steps", type=int, default=200,
                        help="Max navigation steps (default: 200)")

    args = parser.parse_args()

    target = parse_target(args.target)

    # Build custom scan profiles if needed
    coarse = ScanProfile(
        name="COARSE",
        radius=args.coarse_radius,
        cell_size=args.coarse_cell,
        beam=max(40, int(args.coarse_radius / args.coarse_cell)),
    )
    fine = ScanProfile(
        name="FINE",
        radius=args.fine_radius,
        cell_size=args.fine_cell,
        beam=max(40, int(args.fine_radius / args.fine_cell)),
    )

    # Build speed zone
    speed_zone = SpeedZone(
        max_speed=args.max_speed,
        far_speed=args.far_speed,
        medium_speed=args.medium_speed,
        near_speed=(args.far_speed + args.close_speed) / 2,
        close_speed=args.close_speed,
    )

    print("=" * 60)
    print("  Space Navigator v4 — Multi-scale obstacle avoidance")
    print("=" * 60)
    print(f"Grid: {args.grid}")
    print(f"Target: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
    print(f"Ship radius: {args.ship_radius:.0f}m")
    print(f"Speed: max={args.max_speed}, far={args.far_speed}, "
          f"medium={args.medium_speed}, close={args.close_speed} m/s")
    print(f"Coarse scan: radius={coarse.radius:.0f}m, cell={coarse.cell_size:.0f}m")
    print(f"Fine scan: radius={fine.radius:.0f}m, cell={fine.cell_size:.0f}m")
    print(f"Background scanner: {'ON' if not args.no_scanner else 'OFF'}")
    print(f"Dry run: {args.dry_run}")
    print()

    # Create controller
    controller = SpaceNavigatorController(
        grid_name=args.grid,
        ship_radius=args.ship_radius,
        speed_zone=speed_zone,
        coarse_scan=coarse,
        fine_scan=fine,
        arrival_distance=args.arrival,
        enable_background_scanner=not args.no_scanner,
        dry_run=args.dry_run,
    )

    try:
        # Show initial position
        rc = controller.rc
        rc.update()
        ship_pos = get_world_position(rc)
        if ship_pos:
            dist = _dist(ship_pos, target)
            print(f"Ship: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")
            print(f"Distance to target: {dist:.0f}m ({dist / 1000:.1f}km)")
        print()

        # Navigate
        t0 = time.time()
        final_pos = controller.navigate_to(target)
        elapsed = time.time() - t0

        # Report
        print()
        print("=" * 60)
        print("  Navigation complete")
        print("=" * 60)
        if final_pos:
            final_dist = _dist(final_pos, target)
            print(f"Final position: ({final_pos[0]:.0f}, {final_pos[1]:.0f}, {final_pos[2]:.0f})")
            print(f"Distance to target: {final_dist:.0f}m")
            if final_dist < args.arrival:
                print("✅ ARRIVED at target!")
            else:
                print(f"⚠️ Still {final_dist:.0f}m from target")
        else:
            print("❌ Navigation failed — no final position")

        print(f"Time: {elapsed:.0f}s ({elapsed / 60:.1f}min)")
        print()

    except KeyboardInterrupt:
        print("\n[NAV] Interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        controller.close()
        print("Done.")


if __name__ == "__main__":
    main()
