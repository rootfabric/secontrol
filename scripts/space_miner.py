#!/usr/bin/env python3
"""
Space Miner — fly to ore deposit with voxel obstacle avoidance.

Strategy:
  1. Scan voxels around ship (radius=1000m, cell=20m)
  2. If direct path to ore is clear → fly straight
  3. If obstacle detected → detour around it using waypoint offsets
  4. Continuous forward scanning during flight

Usage:
    python3 space_miner.py --grid skynet-baza0 --target "98932,81366,-131202"
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

WORKSPACE = "/workspace"
from dotenv import load_dotenv
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import close, prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import (
    fly_to_point,
    get_world_position,
    _dist,
)

DEFAULT_GRID = "skynet-baza0"

# Scan parameters (user-specified)
SCAN_RADIUS = 1000.0
SCAN_CELL = 20.0
SCAN_BEAM = 30   # smaller beam = faster scan (~1-1.5s instead of 3-4s)

# Safety
SAFETY_DISTANCE = 40.0   # minimum distance from voxel surface
DETOUR_DISTANCE = 100.0  # how far to offset when avoiding obstacle

# Forward scanner
FWD_INTERVAL = 0.5

# Flight
FLIGHT_SPEED_FAR = 20.0
FLIGHT_SPEED_NEAR = 5.0
SLOW_DISTANCE = 200.0


def parse_target(target_str: str) -> Tuple[float, float, float]:
    if target_str.startswith("GPS:"):
        parts = target_str.split(":")
        return (float(parts[2]), float(parts[3]), float(parts[4]))
    parts = target_str.split(",")
    return (float(parts[0]), float(parts[1]), float(parts[2]))


def get_world_position_safe(rc) -> Optional[Tuple[float, float, float]]:
    try:
        rc.update()
        return get_world_position(rc)
    except Exception:
        return None


def dist3(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


class ForwardObstacleDetector:
    """Background thread scanning for obstacles ahead."""

    def __init__(self, radar, rc, safety_distance=SAFETY_DISTANCE):
        self.radar = radar
        self.rc = rc
        self.safety = safety_distance
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._nearest = float("inf")
        self._solid: List[List[float]] = []

    @property
    def nearest(self):
        with self._lock:
            return self._nearest

    @property
    def solid_points(self):
        with self._lock:
            return self._solid.copy()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self):
        ctrl = RadarController(
            self.radar,
            radius=SCAN_RADIUS,
            cell_size=SCAN_CELL,
            boundingBoxX=SCAN_BEAM,
            boundingBoxY=SCAN_BEAM,
            ore_only=False,
        )
        while self._running:
            try:
                solid, meta, contacts, ore = ctrl.scan_voxels()
                ship = get_world_position_safe(self.rc)
                if not ship:
                    time.sleep(FWD_INTERVAL)
                    continue

                nearest = float("inf")
                if solid:
                    for pt in solid:
                        d = dist3(pt, ship)
                        if d < nearest:
                            nearest = d

                with self._lock:
                    self._nearest = nearest
                    self._solid = solid or []

                if nearest < float("inf"):
                    print(f"[FWD] nearest={nearest:.0f}m, pts={len(solid) if solid else 0}")
                else:
                    print(f"[FWD] clear")

            except Exception as e:
                print(f"[FWD] err: {e}")
            time.sleep(FWD_INTERVAL)


def obstacle_between(ship, target, solid_points, safety=SAFETY_DISTANCE):
    """Check if any solid voxel is close to the line ship→target."""
    if not solid_points:
        return None  # no obstacle

    dx, dy, dz = target[0]-ship[0], target[1]-ship[1], target[2]-ship[2]
    seg_len = math.sqrt(dx*dx + dy*dy + dz*dz)
    if seg_len < 1:
        return None

    ux, uy, uz = dx/seg_len, dy/seg_len, dz/seg_len

    closest_dist = float("inf")
    closest_pt = None

    for pt in solid_points:
        px, py, pz = pt[0]-ship[0], pt[1]-ship[1], pt[2]-ship[2]
        t = max(0, min(seg_len, px*ux + py*uy + pz*uz))
        cx, cy, cz = ship[0]+ux*t, ship[1]+uy*t, ship[2]+uz*t
        d = math.sqrt((pt[0]-cx)**2 + (pt[1]-cy)**2 + (pt[2]-cz)**2)
        if d < closest_dist:
            closest_dist = d
            closest_pt = pt

    if closest_dist < safety:
        return closest_pt
    return None


def compute_detour(ship, target, obstacle_pt, detour_dist=DETOUR_DISTANCE):
    """Compute a detour waypoint that goes around the obstacle."""
    # Direction from ship to target
    dx = target[0] - ship[0]
    dy = target[1] - ship[1]
    dz = target[2] - ship[2]
    d = math.sqrt(dx*dx + dy*dy + dz*dz)
    if d < 1:
        return target
    dx, dy, dz = dx/d, dy/d, dz/d

    # Direction from obstacle to ship (we want to go away from obstacle)
    ox = ship[0] - obstacle_pt[0]
    oy = ship[1] - obstacle_pt[1]
    oz = ship[2] - obstacle_pt[2]
    od = math.sqrt(ox*ox + oy*oy + oz*oz)
    if od < 1:
        # Ship is ON the obstacle, just go perpendicular
        ox, oy, oz = 0, 1, 0
    else:
        ox, oy, oz = ox/od, oy/od, oz/od

    # Cross product: forward × up = right (perpendicular direction)
    # Use cross product of forward and obstacle-direction to get a detour direction
    # Try multiple perpendicular directions and pick the one that moves away from obstacle
    detour_dir = (
        ox * detour_dist,
        oy * detour_dist,
        oz * detour_dist,
    )

    # Detour point: current position + detour direction + some forward progress
    forward_progress = min(d * 0.3, 100.0)  # move 30% forward or 100m
    detour = (
        ship[0] + detour_dir[0] + dx * forward_progress,
        ship[1] + detour_dir[1] + dy * forward_progress,
        ship[2] + detour_dir[2] + dz * forward_progress,
    )

    print(f"[DETOUR] obstacle at ({obstacle_pt[0]:.0f},{obstacle_pt[1]:.0f},{obstacle_pt[2]:.0f}), "
          f"detour→ ({detour[0]:.0f},{detour[1]:.0f},{detour[2]:.0f})")
    return detour


def main():
    parser = argparse.ArgumentParser(description="Space miner with obstacle avoidance")
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--target", required=True, help="'x,y,z' or GPS string")
    parser.add_argument("--safety", type=float, default=SAFETY_DISTANCE)
    parser.add_argument("--speed", type=float, default=FLIGHT_SPEED_FAR)
    parser.add_argument("--max-detours", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = parse_target(args.target)

    print("=" * 60)
    print("  Space Miner — ore mining with obstacle avoidance")
    print("=" * 60)
    print(f"Grid: {args.grid}")
    print(f"Target: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
    print(f"Safety distance: {args.safety:.0f}m")
    print(f"Scan: radius={SCAN_RADIUS:.0f}m, cell={SCAN_CELL:.0f}m")
    print()

    grid = prepare_grid(args.grid)
    scanner = None

    try:
        # Find devices
        radar = grid.get_first_device(OreDetectorDevice)
        rc = grid.get_first_device(RemoteControlDevice)
        if not radar or not rc:
            print("[ERROR] No radar or RC found")
            return
        print(f"Radar: {radar.name} (id={radar.device_id})")
        print(f"RC: {rc.name} (id={rc.device_id})")

        # Get position
        rc.update()
        ship_pos = get_world_position(rc)
        if not ship_pos:
            print("[ERROR] No ship position")
            return
        print(f"Ship: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")
        print(f"Distance to target: {dist3(ship_pos, target):.0f}m")

        # ── PHASE 1: Initial scan ──
        print("\n" + "=" * 60)
        print("  PHASE 1: Initial voxel scan")
        print("=" * 60)

        ctrl = RadarController(radar, radius=SCAN_RADIUS, cell_size=SCAN_CELL,
                               boundingBoxX=SCAN_BEAM, boundingBoxY=SCAN_BEAM, ore_only=False)
        solid, meta, contacts, ore = ctrl.scan_voxels()
        n = len(solid) if solid else 0
        print(f"[SCAN] {n} solid voxels")

        if n > 0:
            # Show nearest voxels to ship
            dists = [(dist3(pt, ship_pos), pt) for pt in solid]
            dists.sort(key=lambda x: x[0])
            print(f"[SCAN] 5 nearest voxels to ship:")
            for d, pt in dists[:5]:
                print(f"  {d:.0f}m at ({pt[0]:.0f},{pt[1]:.0f},{pt[2]:.0f})")

            # Check if direct path is clear
            nearest_to_line = obstacle_between(ship_pos, target, solid, args.safety)
            if nearest_to_line:
                print(f"[SCAN] ⚠️  Obstacle on direct path at ({nearest_to_line[0]:.0f},{nearest_to_line[1]:.0f},{nearest_to_line[2]:.0f})")
            else:
                print(f"[SCAN] ✅ Direct path to target is CLEAR")
        else:
            print(f"[SCAN] ✅ No voxels detected — path is clear")

        if args.dry_run:
            print("\n[DRY RUN] Done.")
            return

        # ── PHASE 2: Fly with obstacle avoidance ──
        print("\n" + "=" * 60)
        print("  PHASE 2: Flying to target")
        print("=" * 60)

        # Start forward scanner
        scanner = ForwardObstacleDetector(radar, rc, safety_distance=args.safety)
        scanner.start()
        time.sleep(1)

        # Enable autopilot
        rc.enable()
        rc.gyro_control_on()
        rc.thrusters_on()
        rc.dampeners_on()
        time.sleep(1)

        detour_count = 0
        current_target = target
        approach_mode = False  # True when we're close and approaching surface

        while detour_count < args.max_detours:
            rc.update()
            ship_pos = get_world_position(rc)
            if not ship_pos:
                time.sleep(0.5)
                continue

            d = dist3(ship_pos, current_target)
            d_final = dist3(ship_pos, target)
            nearest_voxel = scanner.nearest
            print(f"\n[FLY] → ({current_target[0]:.0f},{current_target[1]:.0f},{current_target[2]:.0f}), "
                  f"dist={d:.0f}m, voxels={nearest_voxel:.0f}m")

            # Stop condition: voxel surface is at safety distance
            if nearest_voxel < args.safety:
                print(f"[FLY] ✅ Surface reached! Nearest voxel: {nearest_voxel:.0f}m (safety={args.safety:.0f}m)")
                break

            # Also stop if very close to target coords
            if d_final < 20.0:
                print(f"[FLY] ✅ At target coordinates! Distance: {d_final:.0f}m")
                break

            # Check forward scanner for obstacles
            fwd_pts = scanner.solid_points
            obstacle = obstacle_between(ship_pos, current_target, fwd_pts, args.safety)

            if obstacle:
                detour_count += 1
                print(f"[FLY] ⚠️  Obstacle detected! Making detour #{detour_count}")
                current_target = compute_detour(ship_pos, target, obstacle)

                # Re-scan to update map
                try:
                    solid2, meta2, _, _ = ctrl.scan_voxels()
                    if solid2:
                        # Check if new path is clear
                        obs2 = obstacle_between(ship_pos, current_target, solid2, args.safety)
                        if obs2:
                            print(f"[FLY] Still blocked, trying bigger detour")
                            current_target = compute_detour(ship_pos, target, obs2, detour_dist=150)
                except Exception:
                    pass

            # Fly to current target (either final or detour)
            speed = args.speed if d > SLOW_DISTANCE else FLIGHT_SPEED_NEAR

            def cancel_check():
                if scanner.nearest < args.safety * 0.3:
                    print("[FLY] EMERGENCY: obstacle too close!")
                    return True
                return False

            fly_to_point(
                rc, current_target,
                waypoint_name=f"Target",
                speed_far=speed,
                speed_near=FLIGHT_SPEED_NEAR,
                arrival_distance=30.0,   # tighter arrival
                max_flight_time=60.0,
                cancel_check=cancel_check,
            )

            # After reaching detour waypoint, switch back to final target
            if current_target != target:
                print(f"[FLY] Reached detour, resuming to final target")
                current_target = target

        # ── Final status ──
        rc.update()
        final_pos = get_world_position(rc)
        if final_pos:
            final_d = dist3(final_pos, target)
            print(f"\n[END] Position: ({final_pos[0]:.0f}, {final_pos[1]:.0f}, {final_pos[2]:.0f})")
            print(f"[END] Distance to target: {final_d:.0f}m")
            if scanner:
                print(f"[END] Nearest voxel: {scanner.nearest:.0f}m")

        # Stop
        print("\nStopping...")
        if scanner:
            scanner.stop()
        rc.disable()
        rc.dampeners_on()
        rc.handbrake_on()
        print("Done!")

    except KeyboardInterrupt:
        print("\n[INTERRUPTED]")
        if scanner:
            scanner.stop()
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


if __name__ == "__main__":
    main()
