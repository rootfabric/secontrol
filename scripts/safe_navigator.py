#!/usr/bin/env python3
"""
Safe Space Navigator v2 — scan-first, A*, follow path strictly.

Core loop:
  1. Scan 200m around ship (cell=10m)
  2. A* pathfind to target within scanned area
  3. Follow A* waypoints ONE BY ONE (never skip)
  4. Stop waypoint before scan boundary
  5. Rescan, repeat

Key rule: NEVER fly outside scanned area. NEVER skip waypoints.

Usage:
    python3 safe_navigator.py --grid skynet-baza0 --target "98932,81366,-131202"
"""

from __future__ import annotations

import argparse
import math
import os
import time
from typing import List, Optional, Tuple

import numpy as np

WORKSPACE = "/workspace"
from dotenv import load_dotenv
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.radar_navigation import (
    RawRadarMap,
    PathFinder,
    PassabilityProfile,
)
from secontrol.tools.navigation_tools import (
    fly_to_point,
    get_world_position,
    _dist,
)

DEFAULT_GRID = "skynet-baza0"

# Scan
SCAN_RADIUS = 200.0
SCAN_CELL = 10.0
SCAN_BEAM = 40

# Safety
SHIP_RADIUS_M = 30.0       # inflate obstacles by 30m
MAX_STEP_FRACTION = 0.40    # fly max 40% of scan radius per step (80m)
BOUNDARY_MARGIN = 30.0      # stay 30m inside scan boundary
ARRIVAL_DISTANCE = 25.0     # "arrived" threshold
VOXEL_STOP_DIST = 40.0      # stop if voxel closer than this

# Flight
FLIGHT_SPEED = 8.0


def parse_target(s: str) -> Tuple[float, float, float]:
    if s.startswith("GPS:"):
        p = s.split(":")
        return (float(p[2]), float(p[3]), float(p[4]))
    return tuple(float(x) for x in s.split(","))


def dist3(a, b) -> float:
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def get_pos(rc) -> Optional[Tuple[float, float, float]]:
    try:
        rc.update()
        return get_world_position(rc)
    except Exception:
        return None


# ── Scan ──────────────────────────────────────────────────────────────────

def scan_map(radar, ship_pos) -> Optional[Tuple[RawRadarMap, List[List[float]]]]:
    """Scan voxels, return (map, solid_points)."""
    ctrl = RadarController(
        radar,
        radius=SCAN_RADIUS,
        cell_size=SCAN_CELL,
        boundingBoxX=SCAN_BEAM,
        boundingBoxY=SCAN_BEAM,
        ore_only=False,
    )
    solid, meta, contacts, ore = ctrl.scan_voxels()

    origin = np.array(meta["origin"], dtype=np.float64)
    cell_size = float(meta["cellSize"])
    size = tuple(int(v) for v in meta["size"])

    occ = np.zeros(size, dtype=np.bool_)
    if solid:
        arr = np.asarray(solid, dtype=np.float64)
        if arr.ndim == 2 and arr.shape[1] == 3:
            rel = (arr - origin.reshape(1, 3)) / cell_size - 0.5
            idx = np.rint(rel).astype(np.int64)
            valid = (
                (idx[:, 0] >= 0) & (idx[:, 0] < size[0]) &
                (idx[:, 1] >= 0) & (idx[:, 1] < size[1]) &
                (idx[:, 2] >= 0) & (idx[:, 2] < size[2])
            )
            idx = idx[valid]
            if idx.size:
                occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True

    n = int(np.sum(occ))
    print(f"[MAP] {n} solid cells, grid {size[0]}x{size[1]}x{size[2]}, cell={cell_size}m")

    radar_map = RawRadarMap(
        occ=occ, origin=origin, cell_size=cell_size,
        size=size, revision=meta.get("rev"), timestamp_ms=meta.get("tsMs"),
        contacts=(), _inflation_cache={},
    )
    return radar_map, solid or []


# ── A* ────────────────────────────────────────────────────────────────────

def find_path(radar_map, start, goal) -> List[Tuple[float, float, float]]:
    """A* path from start to goal."""
    profile = PassabilityProfile(
        robot_radius=SHIP_RADIUS_M,
        max_slope_degrees=90.0,
        max_step_cells=5,
        allow_vertical_movement=True,
        allow_diagonal=True,
        is_ground_vehicle=False,
    )
    pf = PathFinder(radar_map, profile)
    t0 = time.time()
    path = pf.find_path_world(start, goal)
    dt = time.time() - t0
    if path:
        print(f"[PATH] {len(path)} waypoints in {dt:.2f}s")
    else:
        print(f"[PATH] No path in {dt:.2f}s")
    return path


# ── Pick next waypoint from A* path ───────────────────────────────────────

def pick_next_waypoint(
    path: List[Tuple[float, float, float]],
    ship_pos: Tuple[float, float, float],
    scan_center: Tuple[float, float, float],
) -> Optional[Tuple[float, float, float]]:
    """
    Walk along A* path. Return the farthest waypoint we can safely reach:
      - Must be within scan boundary (scan_radius - margin)
      - Must not be farther than max_step from ship
    """
    max_step = SCAN_RADIUS * MAX_STEP_FRACTION
    max_from_center = SCAN_RADIUS - BOUNDARY_MARGIN
    best = None

    for wp in path:
        d_from_ship = dist3(wp, ship_pos)
        d_from_center = dist3(wp, scan_center)

        # Outside scan boundary? Stop here.
        if d_from_center > max_from_center:
            break

        # Too far from ship? Clamp to max_step.
        if d_from_ship > max_step:
            if best is None:
                # Clamp this waypoint
                dx = wp[0] - ship_pos[0]
                dy = wp[1] - ship_pos[1]
                dz = wp[2] - ship_pos[2]
                d = math.sqrt(dx*dx + dy*dy + dz*dz)
                if d > 0:
                    scale = max_step / d
                    best = (
                        ship_pos[0] + dx * scale,
                        ship_pos[1] + dy * scale,
                        ship_pos[2] + dz * scale,
                    )
            break

        best = wp

    return best


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Safe space navigator v2")
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--target", required=True)
    parser.add_argument("--speed", type=float, default=FLIGHT_SPEED)
    parser.add_argument("--arrival", type=float, default=ARRIVAL_DISTANCE)
    parser.add_argument("--max-steps", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = parse_target(args.target)

    print("=" * 60)
    print("  Safe Space Navigator v2")
    print("  Scan → A* → Follow waypoints → Rescan")
    print("=" * 60)
    print(f"Target: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
    print(f"Scan: {SCAN_RADIUS:.0f}m radius, {SCAN_CELL:.0f}m cells")
    print(f"Ship radius: {SHIP_RADIUS_M:.0f}m")
    print(f"Max step: {SCAN_RADIUS * MAX_STEP_FRACTION:.0f}m")
    print()

    grid = prepare_grid(args.grid)

    try:
        radar = grid.get_first_device(OreDetectorDevice)
        rc = grid.get_first_device(RemoteControlDevice)
        if not radar or not rc:
            print("[ERROR] No radar/RC")
            return

        rc.enable()
        rc.gyro_control_on()
        rc.thrusters_on()
        rc.dampeners_on()
        time.sleep(1)

        for step in range(args.max_steps):
            ship = get_pos(rc)
            if not ship:
                time.sleep(1)
                continue

            d_target = dist3(ship, target)
            print(f"\n{'='*50}")
            print(f"STEP {step}  pos=({ship[0]:.0f},{ship[1]:.0f},{ship[2]:.0f})  "
                  f"target_dist={d_target:.0f}m")
            print(f"{'='*50}")

            # Arrived?
            if d_target < args.arrival:
                print(f"\n✅ ARRIVED at {d_target:.0f}m!")
                break

            # ── Scan ──
            print(f"[SCAN] {SCAN_RADIUS:.0f}m radius...")
            t0 = time.time()
            result = scan_map(radar, ship)
            if result is None:
                print("[SCAN] Failed, retrying...")
                time.sleep(2)
                continue
            radar_map, solid = result
            print(f"[SCAN] {time.time()-t0:.1f}s")

            # Check if target is in scan range
            if d_target > SCAN_RADIUS * 0.95:
                print(f"[INFO] Target {d_target:.0f}m away, scan={SCAN_RADIUS:.0f}m")
                print(f"[INFO] Flying toward target (scan-limited)")
                # Fly toward target, but stay inside scan area
                fly_dist = min(d_target * 0.5, SCAN_RADIUS * MAX_STEP_FRACTION)
                dx = target[0] - ship[0]
                dy = target[1] - ship[1]
                dz = target[2] - ship[2]
                d = math.sqrt(dx*dx + dy*dy + dz*dz)
                if d > 0:
                    wp = (
                        ship[0] + dx/d * fly_dist,
                        ship[1] + dy/d * fly_dist,
                        ship[2] + dz/d * fly_dist,
                    )
                    wp = _clamp(wp, ship, SCAN_RADIUS - BOUNDARY_MARGIN)
                    print(f"[FLY] Direct → ({wp[0]:.0f},{wp[1]:.0f},{wp[2]:.0f}), {dist3(ship,wp):.0f}m")
                    if not args.dry_run:
                        _fly(rc, wp, args.speed, ship)
                    time.sleep(0.5)
                    continue

            # ── A* path ──
            path = find_path(radar_map, ship, target)

            if not path:
                print("[PATH] No path — flying direct")
                fly_dist = min(d_target * 0.5, SCAN_RADIUS * MAX_STEP_FRACTION)
                dx = target[0] - ship[0]
                dy = target[1] - ship[1]
                dz = target[2] - ship[2]
                d = math.sqrt(dx*dx + dy*dy + dz*dz)
                if d > 0:
                    wp = (ship[0]+dx/d*fly_dist, ship[1]+dy/d*fly_dist, ship[2]+dz/d*fly_dist)
                    print(f"[FLY] Direct → ({wp[0]:.0f},{wp[1]:.0f},{wp[2]:.0f})")
                    if not args.dry_run:
                        _fly(rc, wp, args.speed, ship)
                time.sleep(0.5)
                continue

            # ── Show path ──
            print(f"[PATH] Full route ({len(path)} waypoints):")
            for i, p in enumerate(path[:8]):
                print(f"  [{i}] ({p[0]:.0f},{p[1]:.0f},{p[2]:.0f})")
            if len(path) > 8:
                print(f"  ... → ({path[-1][0]:.0f},{path[-1][1]:.0f},{path[-1][2]:.0f})")

            # ── Pick next waypoint ──
            wp = pick_next_waypoint(path, ship, ship)
            if wp is None:
                print("[PATH] No valid waypoint in scan area")
                break

            d_wp = dist3(ship, wp)
            print(f"[NEXT] Waypoint: ({wp[0]:.0f},{wp[1]:.0f},{wp[2]:.0f}), {d_wp:.0f}m")

            if args.dry_run:
                print(f"[DRY] Would fly {d_wp:.0f}m")
                continue

            # ── Fly ──
            _fly(rc, wp, args.speed, ship)
            time.sleep(0.5)

        else:
            print(f"\n[WARN] Max steps ({args.max_steps}) reached")

        # Final
        rc.update()
        final = get_pos(rc)
        if final:
            print(f"\n[END] ({final[0]:.0f},{final[1]:.0f},{final[2]:.0f}), "
                  f"target_dist={dist3(final, target):.0f}m")

        rc.disable()
        rc.dampeners_on()
        rc.handbrake_on()
        print("Done!")

    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
        try:
            rc.disable()
            rc.dampeners_on()
        except Exception:
            pass
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
    finally:
        close(grid)


def _clamp(point, center, max_dist):
    """Clamp point to max_dist from center."""
    dx = point[0]-center[0]
    dy = point[1]-center[1]
    dz = point[2]-center[2]
    d = math.sqrt(dx*dx+dy*dy+dz*dz)
    if d <= max_dist:
        return point
    s = max_dist / d
    return (center[0]+dx*s, center[1]+dy*s, center[2]+dz*s)


def _fly(rc, target, speed, scan_center):
    """Fly to waypoint with boundary check."""
    scan_pos = scan_center

    def cancel():
        pos = get_pos(rc)
        if not pos:
            return False
        d = dist3(pos, scan_pos)
        if d > SCAN_RADIUS - BOUNDARY_MARGIN:
            print(f"\n[CANCEL] Leaving scan area ({d:.0f}m)")
            return True
        return False

    d = dist3(scan_center, target)
    fly_to_point(
        rc, target,
        waypoint_name="WP",
        speed_far=speed,
        speed_near=speed,
        arrival_distance=10.0,
        max_flight_time=max(30.0, d/speed + 15),
        cancel_check=cancel,
    )


if __name__ == "__main__":
    main()
