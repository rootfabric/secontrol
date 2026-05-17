#!/usr/bin/env python3
"""
Space Navigator v3 — fly to nearest asteroid with forward voxel scanning.

Based on working fly_to_point() pattern + background forward beam scanner.
If scanner detects voxels ahead → brakes via cancel_check callback.

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
FLIGHT_SPEED_FAR = 50.0
FLIGHT_SPEED_NEAR = 5.0
STOP_DISTANCE = 200.0          # meters before asteroid surface
ARRIVAL_DISTANCE = 50.0        # fly_to_point arrival threshold
MAX_FLIGHT_TIME = 600.0

# Forward scanner beam — fast narrow beam for real-time detection
BEAM_X = 20                    # beam width (voxel cells)
BEAM_Y = 20                    # beam height (voxel cells)
BEAM_Z = 1000                   # beam depth forward (voxel cells)
CELL_SIZE = 10.0               # meters per voxel cell
SCAN_RADIUS = 1000.0           # meters
OBSTACLE_THRESHOLD = 1         # ANY solid point = obstacle → stop
SCAN_INTERVAL = 0.3            # seconds between scans (fast polling)


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


def compute_approach_point(
    ship_pos: Tuple[float, float, float],
    asteroid: Dict[str, Any],
    stop_distance: float = STOP_DISTANCE,
) -> Tuple[float, float, float]:
    """Point along ship→asteroid line, stop_distance before surface."""
    center = asteroid.get("center", [0, 0, 0])
    ast = (float(center[0]), float(center[1]), float(center[2]))
    radius = float(asteroid.get("approxRadius", 50.0))
    dx = ast[0] - ship_pos[0]
    dy = ast[1] - ship_pos[1]
    dz = ast[2] - ship_pos[2]
    dist = math.sqrt(dx * dx + dy * dy + dz * dz)
    if dist < 1e-3:
        return ast
    d = (dx / dist, dy / dist, dz / dist)
    approach_dist = max(0, dist - radius - stop_distance)
    return (
        ship_pos[0] + d[0] * approach_dist,
        ship_pos[1] + d[1] * approach_dist,
        ship_pos[2] + d[2] * approach_dist,
    )


# ── Forward scanner (background thread) ──────────────────────────────────

class ForwardScanner:
    """
    Background thread that continuously scans a forward voxel beam.
    When ANY solid voxel is detected → sets obstacle_detected = True.
    The cancel_check callback then returns True to stop fly_to_point().
    """

    def __init__(self, radar: OreDetectorDevice, rc: RemoteControlDevice):
        self.radar = radar
        self.rc = rc
        self._obstacle = False
        self._count = 0
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def obstacle_detected(self) -> bool:
        with self._lock:
            return self._obstacle

    @property
    def solid_count(self) -> int:
        with self._lock:
            return self._count

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
            cell_size=CELL_SIZE,
            boundingBoxX=BEAM_X,
            boundingBoxY=BEAM_Y,
            boundingBoxZ=BEAM_Z,
            ore_only=False,
        )
        while self._running:
            try:
                solid, meta, contacts, ore_cells = ctrl.scan_voxels()
                n = len(solid) if solid else 0
                with self._lock:
                    self._count = n
                    self._obstacle = n >= OBSTACLE_THRESHOLD
                if self._obstacle:
                    print(f"\n[SCAN] ⚠️  OBSTACLE: {n} solid points — STOPPING")
                    # Immediately disable autopilot
                    try:
                        self.rc.disable()
                        self.rc.dampeners_on()
                    except Exception:
                        pass
                else:
                    print(f"[SCAN] ✅ clear ({n} pts)")
            except Exception as e:
                print(f"[SCAN] error: {e}")
            time.sleep(SCAN_INTERVAL)


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
        description="Fly to nearest asteroid with forward scanning"
    )
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--speed", type=float, default=FLIGHT_SPEED_FAR)
    parser.add_argument("--stop", type=float, default=STOP_DISTANCE)
    parser.add_argument("--no-scan", action="store_true", help="Disable forward scanner")
    args = parser.parse_args()

    print(f"=== Space Navigator v3 ===")
    print(f"Grid: {args.grid}  Speed: {args.speed} m/s  Stop: {args.stop}m")
    beam_w = BEAM_X * CELL_SIZE
    beam_h = BEAM_Y * CELL_SIZE
    beam_d = BEAM_Z * CELL_SIZE
    print(f"Beam: {BEAM_X}x{BEAM_Y}x{BEAM_Z} cells = {beam_w:.0f}x{beam_h:.0f}x{beam_d:.0f}m")
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
            print("  Add a Remote Control block in-game and try again.")
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

        # ── Compute approach point ──
        # Refresh position before computing approach
        rc.update()
        ship_pos = get_world_position(rc)
        target = compute_approach_point(ship_pos, nearest, args.stop)
        print(f"\nApproach point: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        dist_to_approach = _dist(ship_pos, target)
        print(f"Distance to approach: {dist_to_approach:.0f}m")

        # ── Start forward scanner ──
        if not args.no_scan:
            print("\nStarting forward scanner...")
            scanner = ForwardScanner(radar, rc)
            scanner.start()
            time.sleep(2)  # let first scan complete

        # ── Enable autopilot ──
        print("\nEnabling autopilot...")
        rc.enable()
        rc.gyro_control_on()
        rc.thrusters_on()
        rc.dampeners_on()
        time.sleep(1)

        # ── Build cancel check — returns True to stop fly_to_point ──
        def should_cancel() -> bool:
            """Cancel flight if scanner detected voxels ahead."""
            if scanner and scanner.obstacle_detected:
                print("[NAV] Obstacle detected — cancelling flight")
                return True
            return False

        # ── Fly ──
        print(f"\nFlying to {name}...")
        status_print(rc, "START")

        final_pos = fly_to_point(
            rc,
            target,
            waypoint_name=name,
            speed_far=args.speed,
            speed_near=FLIGHT_SPEED_NEAR,
            arrival_distance=ARRIVAL_DISTANCE,
            max_flight_time=MAX_FLIGHT_TIME,
            cancel_check=should_cancel,
        )

        # ── Result ──
        if final_pos:
            final_dist = _dist(final_pos, target)
            print(f"\nArrived! Distance to approach point: {final_dist:.0f}m")
            status_print(rc, "END")
        else:
            print("\nAutopilot did not engage or was cancelled.")
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
