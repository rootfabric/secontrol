#!/usr/bin/env python3
"""
Space Navigator v3 — fly to nearest asteroid, stop by voxel distance.

Flies toward asteroid center. Continuously scans voxels ahead.
Stops when the nearest voxel is within --stop meters (default 200m).

Two-phase approach:
  Phase 1 (far → SLOW_DISTANCE): fast flight (30 m/s)
  Phase 2 (SLOW_DISTANCE → stop): slow approach (5 m/s), stops by voxel distance

Usage:
    python3 space_navigator_v3.py                          # fly to nearest asteroid
    python3 space_navigator_v3.py --grid skynet-baza0      # specify grid
    python3 space_navigator_v3.py --speed 20 --stop 300    # custom speed/distance
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import threading
import time
from typing import Any, Dict, Optional, Tuple

# ── Setup ────────────────────────────────────────────────────────────────
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


# ── Config ───────────────────────────────────────────────────────────────
DEFAULT_GRID = "skynet-baza0"
SEARCH_RADIUS = 50_000.0
RESULT_LIMIT = 320
INCLUDE_PLANETS = False
TIMEOUT_SECONDS = 15.0

# Flight speeds
FLIGHT_SPEED_FAR = 30.0       # m/s when > SLOW_DISTANCE
FLIGHT_SPEED_NEAR = 5.0       # m/s when < SLOW_DISTANCE
SLOW_DISTANCE = 1000.0        # start slowing down at this distance (m)
STOP_DISTANCE = 200.0         # default stop distance before surface (m)
ARRIVAL_DISTANCE = 50.0       # fly_to_point arrival threshold
MAX_FLIGHT_TIME = 600.0

# Forward scanner — coarse large voxels for long-range detection
SCANNER_RADIUS = 5000.0       # detection range (m)
SCANNER_CELL_SIZE = 100.0     # coarse voxels for speed
SCANNER_BEAM_X = 100          # beam width (cells)
SCANNER_BEAM_Y = 100          # beam height (cells)
SCAN_INTERVAL = 0.3            # seconds between scans


# ── Asteroid discovery ───────────────────────────────────────────────────

def request_asteroids(
    radar: OreDetectorDevice,
    *,
    radius: float = SEARCH_RADIUS,
    limit: int = RESULT_LIMIT,
    include_planets: bool = INCLUDE_PLANETS,
    timeout: float = TIMEOUT_SECONDS,
) -> Optional[Dict[str, Any]]:
    """Force-refresh asteroid index, wait for new revision."""
    telemetry = radar.telemetry or {}
    previous = telemetry.get("asteroidIndex")
    previous_revision = previous.get("revision") if isinstance(previous, dict) else None

    radar.send_command({
        "cmd": "asteroids",
        "targetId": int(radar.device_id),
        "state": {
            "radius": float(radius),
            "limit": int(limit),
            "includePlanets": bool(include_planets),
        },
    })

    deadline = time.time() + timeout
    while time.time() < deadline:
        radar.wait_for_telemetry(timeout=0.5, wait_for_new=True, need_update=False)
        telemetry = radar.telemetry or {}
        asteroid_index = telemetry.get("asteroidIndex")
        if not isinstance(asteroid_index, dict):
            continue
        revision = asteroid_index.get("revision")
        if asteroid_index.get("ready") and revision != previous_revision:
            return asteroid_index
    return None


def find_nearest_asteroid(asteroid_index: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return nearest asteroid by distance from index."""
    items = asteroid_index.get("items", [])
    if not items:
        return None
    asteroids = [i for i in items if i.get("kind") == "asteroid"]
    if not asteroids:
        asteroids = items
    return min(asteroids, key=lambda i: i.get("distance", float("inf")))


# ── Forward scanner (background thread) ──────────────────────────────────

class ForwardScanner:
    """
    Background thread that continuously scans voxels ahead.
    Measures distance to the NEAREST voxel.
    When nearest voxel < stop_distance → sets _arrived = True.
    """

    def __init__(self, radar: OreDetectorDevice, rc: RemoteControlDevice, stop_distance: float):
        self.radar = radar
        self.rc = rc
        self._stop_distance = stop_distance
        self._arrived = False          # True when nearest voxel < stop_distance
        self._count = 0
        self._nearest_dist = float("inf")
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def arrived(self) -> bool:
        """True when nearest voxel is closer than stop_distance."""
        with self._lock:
            return self._arrived

    @property
    def solid_count(self) -> int:
        with self._lock:
            return self._count

    @property
    def nearest_distance(self) -> float:
        with self._lock:
            return self._nearest_dist

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
            radius=SCANNER_RADIUS,
            cell_size=SCANNER_CELL_SIZE,
            boundingBoxX=SCANNER_BEAM_X,
            boundingBoxY=SCANNER_BEAM_Y,
            ore_only=False,
        )
        while self._running:
            try:
                solid, meta, contacts, ore_cells = ctrl.scan_voxels()
                n = len(solid) if solid else 0

                # Calculate nearest solid point distance from ship
                nearest = float("inf")
                if solid:
                    ship_pos = get_world_position_safe(self.rc)
                    if ship_pos:
                        for pt in solid:
                            dx = pt[0] - ship_pos[0]
                            dy = pt[1] - ship_pos[1]
                            dz = pt[2] - ship_pos[2]
                            d = math.sqrt(dx * dx + dy * dy + dz * dz)
                            if d < nearest:
                                nearest = d

                with self._lock:
                    self._count = n
                    self._nearest_dist = nearest
                    self._arrived = n > 0 and nearest < self._stop_distance

                if self._arrived:
                    print(f"\n[SCAN] 🛑 ARRIVED: nearest voxel {nearest:.0f}m < {self._stop_distance:.0f}m — STOPPING")
                    try:
                        self.rc.disable()
                        self.rc.dampeners_on()
                    except Exception:
                        pass
                else:
                    if n > 0:
                        print(f"[SCAN] {n} pts, nearest={nearest:.0f}m (stop at {self._stop_distance:.0f}m)")
                    else:
                        print(f"[SCAN] ✅ clear")
            except Exception as e:
                print(f"[SCAN] error: {e}")
            time.sleep(SCAN_INTERVAL)


def get_world_position_safe(rc: RemoteControlDevice) -> Optional[Tuple[float, float, float]]:
    """Get ship position, return None on failure."""
    try:
        rc.update()
        return get_world_position(rc)
    except Exception:
        return None


# ── Main ─────────────────────────────────────────────────────────────────

def status_print(rc: RemoteControlDevice, label: str = ""):
    """Print current position and speed for monitoring."""
    rc.update()
    pos = get_world_position(rc)
    vel = (rc.telemetry or {}).get("linearVelocity") or {}
    speed = math.sqrt(
        float(vel.get("x", 0)) ** 2
        + float(vel.get("y", 0)) ** 2
        + float(vel.get("z", 0)) ** 2
    )
    if pos:
        prefix = f"[{label}] " if label else ""
        print(f"{prefix}pos=({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f}) speed={speed:.1f} m/s")


def main():
    parser = argparse.ArgumentParser(
        description="Fly to nearest asteroid, stop by voxel distance"
    )
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--speed", type=float, default=FLIGHT_SPEED_FAR)
    parser.add_argument("--stop", type=float, default=STOP_DISTANCE,
                        help="Stop when nearest voxel is within N meters (default: 200)")
    parser.add_argument("--no-scan", action="store_true", help="Disable forward scanner")
    args = parser.parse_args()

    print(f"=== Space Navigator v3 ===")
    print(f"Grid: {args.grid}")
    print(f"Speed: {args.speed} m/s (far), {FLIGHT_SPEED_NEAR} m/s (near)")
    print(f"Slow down at: {SLOW_DISTANCE}m")
    print(f"Stop when nearest voxel < {args.stop:.0f}m")
    beam_w = SCANNER_BEAM_X * SCANNER_CELL_SIZE
    beam_h = SCANNER_BEAM_Y * SCANNER_CELL_SIZE
    print(f"Scanner: radius={SCANNER_RADIUS:.0f}m, cell={SCANNER_CELL_SIZE:.0f}m, beam={beam_w:.0f}x{beam_h:.0f}m")
    print()

    grid = prepare_grid(args.grid)
    scanner: Optional[ForwardScanner] = None

    try:
        # ── Find devices ──
        radar = grid.get_first_device(OreDetectorDevice)
        rc = grid.get_first_device(RemoteControlDevice)
        if not radar:
            print("[ERROR] No Ore Detector found on this grid")
            return
        if not rc:
            print("[ERROR] No Remote Control found on this grid")
            return
        print(f"Radar: {radar.name} (id={radar.device_id})")
        print(f"Remote control: {rc.name} (id={rc.device_id})")

        # ── Get ship position ──
        rc.update()
        ship_pos = get_world_position(rc)
        if not ship_pos:
            print("[ERROR] Cannot get ship position")
            return
        print(f"Ship at ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")

        # ── Scan for asteroids ──
        print(f"\nScanning for asteroids (radius={SEARCH_RADIUS}m)...")
        asteroid_index = request_asteroids(radar, radius=SEARCH_RADIUS)
        if asteroid_index is None:
            print("[ERROR] Asteroid scan timed out")
            return

        nearest = find_nearest_asteroid(asteroid_index)
        if nearest is None:
            print("[ERROR] No asteroids found")
            return

        name = nearest.get("name") or "<unnamed>"
        center = nearest.get("center", [0, 0, 0])
        distance = nearest.get("distance", 0)
        surface_dist = nearest.get("surfaceDistance", 0)
        radius = nearest.get("approxRadius", 50)
        print(f"\nNearest asteroid: {name}")
        print(f"  Center: {center}")
        print(f"  Distance: {distance:.0f}m")
        print(f"  Surface: {surface_dist:.0f}m")
        print(f"  Radius: {radius:.0f}m")

        # ── Target = asteroid center (fly toward it, stop by voxel distance) ──
        target = (float(center[0]), float(center[1]), float(center[2]))
        rc.update()
        ship_pos = get_world_position(rc)
        dist_to_target = _dist(ship_pos, target)
        print(f"\nTarget: asteroid center ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        print(f"Distance to target: {dist_to_target:.0f}m")

        # ── Start forward scanner ──
        if not args.no_scan:
            print(f"\nStarting forward scanner (stop at {args.stop:.0f}m voxel distance)...")
            scanner = ForwardScanner(radar, rc, stop_distance=args.stop)
            scanner.start()
            time.sleep(1)  # let first scan fire

        # ── Enable autopilot ──
        print("\nEnabling autopilot...")
        rc.enable()
        rc.gyro_control_on()
        rc.thrusters_on()
        rc.dampeners_on()
        time.sleep(1)

        # ── Build cancel check ──
        def should_cancel() -> bool:
            """Cancel flight if scanner detected voxels closer than stop distance."""
            if scanner and scanner.arrived:
                print("[NAV] Voxel distance reached — stopping")
                return True
            return False

        # ── Phase 1: Fast approach (far → SLOW_DISTANCE) ──
        print(f"\n─── Phase 1: Fast approach ({args.speed} m/s) ───")
        status_print(rc, "START")

        if dist_to_target > SLOW_DISTANCE:
            # Fly toward asteroid center, stop at SLOW_DISTANCE from it
            center_tuple = (float(center[0]), float(center[1]), float(center[2]))
            dx = center_tuple[0] - ship_pos[0]
            dy = center_tuple[1] - ship_pos[1]
            dz = center_tuple[2] - ship_pos[2]
            d = math.sqrt(dx * dx + dy * dy + dz * dz)
            if d > 1e-3:
                direction = (dx / d, dy / d, dz / d)
                fly_dist = max(0, dist_to_target - SLOW_DISTANCE)
                phase1_target = (
                    ship_pos[0] + direction[0] * fly_dist,
                    ship_pos[1] + direction[1] * fly_dist,
                    ship_pos[2] + direction[2] * fly_dist,
                )
                print(f"Phase 1 target: ({phase1_target[0]:.0f}, {phase1_target[1]:.0f}, {phase1_target[2]:.0f})")
                print(f"Phase 1 distance: {fly_dist:.0f}m")

                fly_to_point(
                    rc,
                    phase1_target,
                    waypoint_name=f"{name} (fast)",
                    speed_far=args.speed,
                    speed_near=args.speed,
                    arrival_distance=ARRIVAL_DISTANCE,
                    max_flight_time=MAX_FLIGHT_TIME,
                    cancel_check=should_cancel,
                )
                status_print(rc, "PHASE1 END")
            else:
                print("[NAV] Already near target, skipping phase 1")
        else:
            print(f"[NAV] Distance {dist_to_target:.0f}m < {SLOW_DISTANCE}m, skipping phase 1")

        # ── Phase 2: Slow approach (SLOW_DISTANCE → voxel stop) ──
        if scanner and scanner.arrived:
            print("\n[NAV] Already close enough to voxels — stopped.")
        else:
            print(f"\n─── Phase 2: Slow approach ({FLIGHT_SPEED_NEAR} m/s) ───")
            print(f"Flying toward asteroid center, stopping when voxel < {args.stop:.0f}m")

            fly_to_point(
                rc,
                target,
                waypoint_name=name,
                speed_far=FLIGHT_SPEED_NEAR,
                speed_near=FLIGHT_SPEED_NEAR,
                arrival_distance=ARRIVAL_DISTANCE,
                max_flight_time=MAX_FLIGHT_TIME,
                cancel_check=should_cancel,
            )

        # ── Final status ──
        rc.update()
        final_pos = get_world_position(rc)
        if final_pos:
            # Measure actual nearest voxel distance
            print(f"\nFinal position: ({final_pos[0]:.0f}, {final_pos[1]:.0f}, {final_pos[2]:.0f})")
            if scanner:
                print(f"Nearest voxel: {scanner.nearest_distance:.0f}m")
        status_print(rc, "END")

        # ── Stop ──
        print("\nStopping...")
        if scanner:
            scanner.stop()
        rc.disable()
        rc.dampeners_on()
        rc.handbrake_on()
        print("Done.")

    except KeyboardInterrupt:
        print("\n[NAV] Interrupted")
        if scanner:
            scanner.stop()
        try:
            rc.disable()
            rc.dampeners_on()
        except Exception:
            pass
    except Exception as e:
        print(f"\n[ERROR] {e}")
        if scanner:
            scanner.stop()
        raise
    finally:
        close(grid)


if __name__ == "__main__":
    main()
