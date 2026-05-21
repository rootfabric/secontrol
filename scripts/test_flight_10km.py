#!/usr/bin/env python3
"""
Test flight: scan, fly 10km forward and back, printing telemetry each second.

Phases:
  1. Pre-flight COARSE scan (5km radius) — check for obstacles in path
  2. Fly forward with collision avoidance ON
  3. Fly back with collision avoidance ON

Usage:
    python scripts/test_flight_10km.py --grid skynet-baza0
    python scripts/test_flight_10km.py --grid skynet-baza0 --distance 5000
    python scripts/test_flight_10km.py --grid skynet-baza0 --speed 30
"""

from __future__ import annotations

import argparse
import math
import os
import sys
import time
from typing import List, Optional, Tuple

WORKSPACE = "/workspace"
from dotenv import load_dotenv
load_dotenv(os.path.join(WORKSPACE, ".env"))

from secontrol.common import prepare_grid, close
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.tools.navigation_tools import (
    get_world_position,
    get_orientation,
    _dist,
    _normalize,
)


DEFAULT_GRID = "skynet-baza0"
FLIGHT_DISTANCE = 10000  # meters
CHECK_INTERVAL = 1.0     # seconds


# ── Telemetry ──────────────────────────────────────────────────────────

def print_telemetry(rc: RemoteControlDevice, label: str = "",
                    dist_to_target: Optional[float] = None) -> None:
    rc.update()
    pos = get_world_position(rc)
    tel = rc.telemetry or {}
    speed = tel.get("speed") or tel.get("currentSpeed") or 0.0
    autopilot = tel.get("autopilotEnabled", False)

    parts = []
    if pos:
        parts.append(f"pos=({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
    else:
        parts.append("pos=N/A")
    parts.append(f"spd={speed:.1f}")
    parts.append(f"ap={'ON' if autopilot else 'OFF'}")
    if dist_to_target is not None:
        parts.append(f"dist={dist_to_target:.0f}m")

    print(f"[{label}] {'  '.join(parts)}")


# ── Pre-flight scan ────────────────────────────────────────────────────

def scan_and_check_path(
    radar: OreDetectorDevice,
    ship_pos: Tuple[float, float, float],
    forward: Tuple[float, float, float],
    flight_distance: float,
    scan_radius: float = 5000.0,
    cell_size: float = 100.0,
    danger_distance: float = 200.0,
) -> Tuple[bool, List[dict]]:
    """
    Scan voxels along the flight path and check for obstacles.

    Returns:
        (path_clear, obstacles) — path_clear is True if no obstacles within danger_distance
        of the flight line.
    """
    print()
    print("=" * 60)
    print("  Pre-flight scan")
    print("=" * 60)

    ctrl = RadarController(
        radar,
        radius=scan_radius,
        cell_size=cell_size,
        boundingBoxX=100,
        boundingBoxY=100,
        boundingBoxZ=100,
        ore_only=False,
        fullSolidScan=True,
    )

    solid, metadata, contacts, ore_cells = ctrl.scan_voxels()
    if solid is None:
        solid = []

    print(f"Solid points: {len(solid)}")
    print(f"Grids/players: {len(contacts or [])}")

    # Check which solid points are near the flight path
    # Flight path: ship_pos + forward * t, where 0 <= t <= flight_distance
    # For each solid point, find closest point on the line and check distance
    obstacles = []
    fwd = _normalize(forward)

    for pt in solid:
        # Vector from ship_pos to solid point
        dx = pt[0] - ship_pos[0]
        dy = pt[1] - ship_pos[1]
        dz = pt[2] - ship_pos[2]

        # Project onto forward direction
        t = dx * fwd[0] + dy * fwd[1] + dz * fwd[2]

        # Only care about points ahead (0 to flight_distance) and behind a bit
        if t < -100 or t > flight_distance + 100:
            continue

        # Closest point on line
        closest_x = ship_pos[0] + fwd[0] * max(0, min(t, flight_distance))
        closest_y = ship_pos[1] + fwd[1] * max(0, min(t, flight_distance))
        closest_z = ship_pos[2] + fwd[2] * max(0, min(t, flight_distance))

        # Distance from solid point to the line
        perp_dist = math.sqrt(
            (pt[0] - closest_x) ** 2 +
            (pt[1] - closest_y) ** 2 +
            (pt[2] - closest_z) ** 2
        )

        if perp_dist < danger_distance:
            obstacles.append({
                "pos": (pt[0], pt[1], pt[2]),
                "distance_along_path": t,
                "perp_distance": perp_dist,
            })

    # Sort by distance along path
    obstacles.sort(key=lambda o: o["distance_along_path"])

    path_clear = len(obstacles) == 0

    if obstacles:
        print()
        print(f"  !! OBSTACLES FOUND: {len(obstacles)} points within {danger_distance:.0f}m of flight path")
        for i, obs in enumerate(obstacles[:10]):
            along = obs["distance_along_path"]
            perp = obs["perp_distance"]
            print(f"    [{i+1}] at {along:.0f}m along path, {perp:.0f}m from centerline  "
                  f"pos=({obs['pos'][0]:.0f}, {obs['pos'][1]:.0f}, {obs['pos'][2]:.0f})")
        if len(obstacles) > 10:
            print(f"    ... and {len(obstacles) - 10} more")
    else:
        print("  Path CLEAR — no obstacles detected")

    # Also check other ships/grids
    ship_obstacles = []
    if contacts:
        for c in contacts:
            if not isinstance(c, dict):
                continue
            ctype = c.get("type", "")
            cpos = c.get("pos") or c.get("position")
            if not cpos or not isinstance(cpos, (list, tuple)) or len(cpos) < 3:
                continue

            cx, cy, cz = float(cpos[0]), float(cpos[1]), float(cpos[2])

            # Skip own grid
            if _dist((cx, cy, cz), ship_pos) < 100:
                continue

            dx = cx - ship_pos[0]
            dy = cy - ship_pos[1]
            dz = cz - ship_pos[2]
            t = dx * fwd[0] + dy * fwd[1] + dz * fwd[2]

            if t < 0 or t > flight_distance:
                continue

            perp_dist = math.sqrt(
                (cx - (ship_pos[0] + fwd[0] * t)) ** 2 +
                (cy - (ship_pos[1] + fwd[1] * t)) ** 2 +
                (cz - (ship_pos[2] + fwd[2] * t)) ** 2
            )

            if perp_dist < danger_distance:
                name = c.get("name", f"id={c.get('id', '?')}")
                print(f"  !! SHIP in path: {name} at {t:.0f}m, {perp_dist:.0f}m from center")
                ship_obstacles.append(c)

    if ship_obstacles:
        path_clear = False

    print()
    return path_clear, obstacles + [{"type": "ship", **o} for o in ship_obstacles]


# ── Flight loop ────────────────────────────────────────────────────────

def fly_to(
    rc: RemoteControlDevice,
    target: Tuple[float, float, float],
    speed: float,
    arrival: float,
    label: str,
    check_interval: float = CHECK_INTERVAL,
) -> bool:
    """Fly to target using autopilot. Returns True if arrived."""
    gps = f"GPS:{label}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    rc.set_mode("oneway")
    rc.set_collision_avoidance(True)
    rc.goto(gps, speed=speed, gps_name=label)

    time.sleep(1.0)
    t0 = time.time()

    while True:
        rc.update()
        pos = get_world_position(rc)
        if not pos:
            time.sleep(check_interval)
            continue

        dist = _dist(pos, target)
        elapsed = time.time() - t0
        print_telemetry(rc, label=f"{label} {elapsed:5.0f}s", dist_to_target=dist)

        if dist < arrival:
            print(f"  >> ARRIVED ({dist:.1f}m remaining)")
            return True

        if not rc.telemetry.get("autopilotEnabled"):
            print("  >> Autopilot disabled — stopping")
            return False

        time.sleep(check_interval)


# ── Main ───────────────────────────────────────────────────────────────

def fly_roundtrip(
    grid_name: str,
    distance: float = FLIGHT_DISTANCE,
    speed: float = 20.0,
    arrival: float = 50.0,
    check_interval: float = CHECK_INTERVAL,
    scan_radius: float = 5000.0,
    cell_size: float = 100.0,
    danger_distance: float = 200.0,
    skip_scan: bool = False,
) -> None:
    print("=" * 60)
    print("  Test Flight — scan, fly forward and back")
    print("=" * 60)
    print(f"Grid:     {grid_name}")
    print(f"Distance: {distance:.0f}m ({distance / 1000:.1f}km)")
    print(f"Speed:    {speed:.0f} m/s")
    print(f"Arrival:  {arrival:.0f}m")
    print(f"Scan:     radius={scan_radius:.0f}m, cell={cell_size:.0f}m, danger={danger_distance:.0f}m")
    print()

    grid = prepare_grid(grid_name)
    try:
        # ── Find devices ──
        rc = grid.get_first_device(RemoteControlDevice)
        if not rc:
            print("ERROR: RemoteControlDevice not found")
            return

        radars = grid.find_devices_by_type(OreDetectorDevice)
        radar = radars[0] if radars else None

        # ── Get starting position and forward ──
        rc.update()
        start_pos = get_world_position(rc)
        if not start_pos:
            print("ERROR: Cannot read ship position")
            return

        try:
            basis = get_orientation(rc)
            forward = basis.forward
        except RuntimeError as e:
            print(f"ERROR: Cannot read orientation: {e}")
            return

        target = (
            start_pos[0] + forward[0] * distance,
            start_pos[1] + forward[1] * distance,
            start_pos[2] + forward[2] * distance,
        )

        print(f"Start:   ({start_pos[0]:.0f}, {start_pos[1]:.0f}, {start_pos[2]:.0f})")
        print(f"Forward: ({forward[0]:.4f}, {forward[1]:.4f}, {forward[2]:.4f})")
        print(f"Target:  ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")

        # ── Pre-flight scan ──
        if not skip_scan and radar:
            path_clear, obstacles = scan_and_check_path(
                radar, start_pos, forward, distance,
                scan_radius=scan_radius, cell_size=cell_size,
                danger_distance=danger_distance,
            )
            if not path_clear:
                print()
                print("  !! FLIGHT PATH BLOCKED — aborting")
                print("  !! Consider reducing --distance or changing ship heading")
                return
        elif not radar:
            print()
            print("  WARNING: No OreDetectorDevice found — skipping scan")
            print("  Ship will fly with SE autopilot collision avoidance only")
        else:
            print()
            print("  Scan skipped (--skip-scan)")

        # ── Phase 1: Fly forward ──
        print()
        print("── Phase 1: Fly forward ──")
        arrived = fly_to(rc, target, speed, arrival, "FWD", check_interval)
        rc.disable()
        time.sleep(1.0)

        if not arrived:
            print("  >> Forward flight incomplete — still flying back")

        # ── Phase 2: Fly back ──
        print()
        print("── Phase 2: Fly back ──")
        arrived = fly_to(rc, start_pos, speed, arrival, "RET", check_interval)
        rc.disable()

        print()
        print("=" * 60)
        print("  Flight complete!")
        print("=" * 60)

    finally:
        close(grid)
        print("Done.")


def main():
    parser = argparse.ArgumentParser(description="Test flight with pre-flight scan")
    parser.add_argument("--grid", default=DEFAULT_GRID, help="Grid name")
    parser.add_argument("--distance", type=float, default=FLIGHT_DISTANCE,
                        help=f"One-way distance in meters (default: {FLIGHT_DISTANCE})")
    parser.add_argument("--speed", type=float, default=20.0,
                        help="Flight speed in m/s (default: 20)")
    parser.add_argument("--arrival", type=float, default=50.0,
                        help="Arrival threshold in meters (default: 50)")
    parser.add_argument("--scan-radius", type=float, default=5000.0,
                        help="Pre-flight scan radius in meters (default: 5000)")
    parser.add_argument("--cell-size", type=float, default=100.0,
                        help="Scan cell size in meters (default: 100)")
    parser.add_argument("--danger-distance", type=float, default=200.0,
                        help="Min distance from flight line to count as obstacle (default: 200)")
    parser.add_argument("--skip-scan", action="store_true",
                        help="Skip pre-flight scan")
    args = parser.parse_args()

    fly_roundtrip(
        grid_name=args.grid,
        distance=args.distance,
        speed=args.speed,
        arrival=args.arrival,
        scan_radius=args.scan_radius,
        cell_size=args.cell_size,
        danger_distance=args.danger_distance,
        skip_scan=args.skip_scan,
    )


if __name__ == "__main__":
    main()
