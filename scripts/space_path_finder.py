#!/usr/bin/env python3
"""
Space Path Finder — A* obstacle-avoiding navigation in space.

Scans voxels around the ship, builds a 3D occupancy grid, and uses A*
pathfinding (from radar_navigation.py) to navigate around asteroids to
the target ore deposit.

Hybrid scanning strategy:
  Phase 1: Coarse scan (5000m, cell=100m) — fast, covers the area
  Phase 2: Fine scan (2000m, cell=25m) — detailed, near obstacles
  Continuous: ForwardScanner during flight — replan if new obstacles

Usage:
    python3 space_path_finder.py --grid skynet-baza0 --target "98932,81366,-131202"
    python3 space_path_finder.py --grid skynet-baza0 --ore Gold
    python3 space_path_finder.py --grid skynet-baza0 --asteroid Gold_5
"""

from __future__ import annotations

import argparse
import math
import os
import signal
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ── Setup ────────────────────────────────────────────────────────────────
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

# ── Config ───────────────────────────────────────────────────────────────
DEFAULT_GRID = "skynet-baza0"

# Scanning — main scan
SCAN_RADIUS = 1000.0
SCAN_CELL = 20.0
SCAN_BEAM = 100

# Scanning — replan detail
FINE_RADIUS = 1000.0
FINE_CELL = 20.0
FINE_BEAM = 100

# Forward scanner — continuous during flight
FWD_RADIUS = 3000.0
FWD_CELL = 50.0
FWD_BEAM = 60
FWD_INTERVAL = 1.0  # seconds between scans

# Pathfinding
SHIP_RADIUS = 30.0      # inflate obstacles by this (meters)
SAFETY_DISTANCE = 50.0  # minimum distance to keep from voxels

# Flight
FLIGHT_SPEED_FAR = 25.0   # m/s when far
FLIGHT_SPEED_NEAR = 8.0   # m/s when near
SLOW_DISTANCE = 300.0     # slow down at this distance to waypoint
MAX_FLIGHT_TIME = 120.0   # max seconds per waypoint
ARRIVAL_DISTANCE = 30.0   # arrival threshold for waypoint

# Replan
REPLAN_INTERVAL = 5.0     # seconds between replan checks
OBSTACLE_IN_PATH_DIST = 100.0  # replan if obstacle closer than this on path


# ── Helper: parse target ─────────────────────────────────────────────────

def parse_target(target_str: str) -> Tuple[float, float, float]:
    """Parse target from 'x,y,z' or 'GPS:name:x:y:z:' format."""
    if target_str.startswith("GPS:"):
        parts = target_str.split(":")
        return (float(parts[2]), float(parts[3]), float(parts[4]))
    parts = target_str.split(",")
    return (float(parts[0]), float(parts[1]), float(parts[2]))


# ── Forward scanner ──────────────────────────────────────────────────────

class SpaceForwardScanner:
    """
    Background thread that continuously scans voxels ahead.
    Detects obstacles on the current path segment and signals replan.
    """

    def __init__(
        self,
        radar: OreDetectorDevice,
        rc: RemoteControlDevice,
        stop_distance: float = SAFETY_DISTANCE,
    ):
        self.radar = radar
        self.rc = rc
        self._stop_distance = stop_distance
        self._nearest_dist = float("inf")
        self._solid_points: List[List[float]] = []
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._needs_replan = False

    @property
    def nearest_distance(self) -> float:
        with self._lock:
            return self._nearest_dist

    @property
    def needs_replan(self) -> bool:
        with self._lock:
            v = self._needs_replan
            self._needs_replan = False
            return v

    @property
    def solid_points(self) -> List[List[float]]:
        with self._lock:
            return self._solid_points.copy()

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=15)

    def _loop(self):
        ctrl = RadarController(
            self.radar,
            radius=FWD_RADIUS,
            cell_size=FWD_CELL,
            boundingBoxX=FWD_BEAM,
            boundingBoxY=FWD_BEAM,
            ore_only=False,
        )
        while self._running:
            try:
                solid, meta, contacts, ore_cells = ctrl.scan_voxels()
                ship_pos = get_world_position_safe(self.rc)
                if not ship_pos:
                    time.sleep(FWD_INTERVAL)
                    continue

                nearest = float("inf")
                if solid:
                    for pt in solid:
                        dx = pt[0] - ship_pos[0]
                        dy = pt[1] - ship_pos[1]
                        dz = pt[2] - ship_pos[2]
                        d = math.sqrt(dx * dx + dy * dy + dz * dz)
                        if d < nearest:
                            nearest = d

                with self._lock:
                    self._nearest_dist = nearest
                    self._solid_points = solid or []
                    if nearest < self._stop_distance:
                        self._needs_replan = True

                if nearest < float("inf"):
                    print(f"[FWD] nearest={nearest:.0f}m, pts={len(solid) if solid else 0}")
                else:
                    print(f"[FWD] clear, pts={len(solid) if solid else 0}")

            except Exception as e:
                print(f"[FWD] error: {e}")
            time.sleep(FWD_INTERVAL)


def get_world_position_safe(rc: RemoteControlDevice) -> Optional[Tuple[float, float, float]]:
    try:
        rc.update()
        return get_world_position(rc)
    except Exception:
        return None


# ── Map builder ──────────────────────────────────────────────────────────

def build_radar_map_from_scan(
    solid: List[List[float]],
    metadata: Dict[str, Any],
    contacts: List[Any],
) -> Optional[RawRadarMap]:
    """Build RawRadarMap from RadarController scan results."""
    if not solid:
        print("[MAP] No solid points in scan")
        return None

    origin = np.array(metadata["origin"], dtype=np.float64)
    cell_size = float(metadata["cellSize"])
    size = tuple(int(v) for v in metadata["size"])

    occ = np.zeros(size, dtype=np.bool_)
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

    occupied = int(np.sum(occ))
    total = int(np.prod(size))
    print(f"[MAP] Grid {size[0]}x{size[1]}x{size[2]}, cell={cell_size}m, "
          f"occupied={occupied}/{total} ({100*occupied/max(total,1):.1f}%)")

    return RawRadarMap(
        occ=occ,
        origin=origin,
        cell_size=cell_size,
        size=size,
        revision=metadata.get("rev"),
        timestamp_ms=metadata.get("tsMs"),
        contacts=tuple(contacts) if contacts else (),
        _inflation_cache={},
    )


# ── Scan helper ──────────────────────────────────────────────────────────

def do_scan(
    radar: OreDetectorDevice,
    radius: float,
    cell_size: float,
    beam: int,
    label: str = "scan",
) -> Optional[Tuple[List[List[float]], Dict[str, Any], List[Any], List[Any]]]:
    """Execute a radar scan and return results."""
    ctrl = RadarController(
        radar,
        radius=radius,
        cell_size=cell_size,
        boundingBoxX=beam,
        boundingBoxY=beam,
        ore_only=False,
    )
    print(f"\n[{label}] Scanning: radius={radius:.0f}m, cell={cell_size:.0f}m, beam={beam}...")
    solid, meta, contacts, ore_cells = ctrl.scan_voxels()
    n = len(solid) if solid else 0
    print(f"[{label}] Result: {n} solid points")
    return solid, meta, contacts, ore_cells


# ── Path replan ──────────────────────────────────────────────────────────

def replan_path(
    radar_map: RawRadarMap,
    ship_pos: Tuple[float, float, float],
    target: Tuple[float, float, float],
) -> List[Tuple[float, float, float]]:
    """Run A* pathfinding from ship to target on the given map."""
    print(f"\n[PATH] Planning: ({ship_pos[0]:.0f},{ship_pos[1]:.0f},{ship_pos[2]:.0f}) "
          f"→ ({target[0]:.0f},{target[1]:.0f},{target[2]:.0f})")

    profile = PassabilityProfile(
        robot_radius=SHIP_RADIUS,
        max_slope_degrees=90.0,     # no slope limit in space
        max_step_cells=5,           # can move up to 5 cells per step
        allow_vertical_movement=True,
        allow_diagonal=True,
        is_ground_vehicle=False,
    )

    pathfinder = PathFinder(radar_map, profile)

    start_time = time.time()
    path = pathfinder.find_path_world(ship_pos, target)
    elapsed = time.time() - start_time

    if path:
        print(f"[PATH] Found: {len(path)} waypoints in {elapsed:.2f}s")
        for i, wp in enumerate(path[:5]):
            print(f"  [{i}] ({wp[0]:.0f}, {wp[1]:.0f}, {wp[2]:.0f})")
        if len(path) > 5:
            print(f"  ... +{len(path)-5} more")
    else:
        print(f"[PATH] NO PATH FOUND in {elapsed:.2f}s — target may be unreachable")

    return path


# ── Check if obstacle is on current path segment ────────────────────────

def obstacle_on_path(
    ship_pos: Tuple[float, float, float],
    waypoint: Tuple[float, float, float],
    solid_points: List[List[float]],
    threshold: float = OBSTACLE_IN_PATH_DIST,
) -> bool:
    """Check if any solid point is close to the line segment ship→waypoint."""
    if not solid_points:
        return False

    dx = waypoint[0] - ship_pos[0]
    dy = waypoint[1] - ship_pos[1]
    dz = waypoint[2] - ship_pos[2]
    seg_len = math.sqrt(dx*dx + dy*dy + dz*dz)
    if seg_len < 1e-3:
        return False

    # Unit vector along segment
    ux, uy, uz = dx/seg_len, dy/seg_len, dz/seg_len

    for pt in solid_points:
        # Vector from ship to point
        px = pt[0] - ship_pos[0]
        py = pt[1] - ship_pos[1]
        pz = pt[2] - ship_pos[2]

        # Project onto segment
        t = max(0, min(seg_len, px*ux + py*uy + pz*uz))

        # Closest point on segment
        cx = ship_pos[0] + ux * t
        cy = ship_pos[1] + uy * t
        cz = ship_pos[2] + uz * t

        # Distance from point to segment
        d = math.sqrt((pt[0]-cx)**2 + (pt[1]-cy)**2 + (pt[2]-cz)**2)
        if d < threshold:
            return True

    return False


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="A* obstacle-avoiding space navigation"
    )
    parser.add_argument("--grid", default=DEFAULT_GRID, help="Grid name")
    parser.add_argument("--target", required=True,
                        help="Target: 'x,y,z' or 'GPS:name:x:y:z:'")
    parser.add_argument("--ship-radius", type=float, default=SHIP_RADIUS,
                        help=f"Ship safety radius in meters (default: {SHIP_RADIUS})")
    parser.add_argument("--scan-cell", type=float, default=SCAN_CELL,
                        help=f"Coarse scan cell size (default: {SCAN_CELL})")
    parser.add_argument("--fine-cell", type=float, default=FINE_CELL,
                        help=f"Fine scan cell size (default: {FINE_CELL})")
    parser.add_argument("--speed", type=float, default=FLIGHT_SPEED_FAR,
                        help=f"Flight speed far (default: {FLIGHT_SPEED_FAR})")
    parser.add_argument("--no-forward-scan", action="store_true",
                        help="Disable continuous forward scanning")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scan and plan only, don't fly")
    args = parser.parse_args()

    target = parse_target(args.target)

    # Update module-level config
    globals()["SHIP_RADIUS"] = args.ship_radius

    print("=" * 60)
    print("  Space Path Finder — A* obstacle-avoiding navigation")
    print("=" * 60)
    print(f"Grid: {args.grid}")
    print(f"Target: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
    print(f"Ship radius: {SHIP_RADIUS:.0f}m")
    print(f"Coarse scan: {SCAN_RADIUS:.0f}m, cell={args.scan_cell:.0f}m")
    print(f"Fine scan: {FINE_RADIUS:.0f}m, cell={args.fine_cell:.0f}m")
    print(f"Flight speed: {args.speed:.0f} m/s")
    print()

    grid = prepare_grid(args.grid)
    scanner: Optional[SpaceForwardScanner] = None

    try:
        # ── Find devices ──
        radar = grid.get_first_device(OreDetectorDevice)
        rc = grid.get_first_device(RemoteControlDevice)
        if not radar:
            print("[ERROR] No Ore Detector found")
            return
        if not rc:
            print("[ERROR] No Remote Control found")
            return
        print(f"Radar: {radar.name} (id={radar.device_id})")
        print(f"RC: {rc.name} (id={rc.device_id})")

        # ── Get ship position ──
        rc.update()
        ship_pos = get_world_position(rc)
        if not ship_pos:
            print("[ERROR] Cannot get ship position")
            return
        dist_to_target = _dist(ship_pos, target)
        print(f"Ship: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")
        print(f"Distance to target: {dist_to_target:.0f}m")

        # ══════════════════════════════════════════════════════════════
        # Phase 1: SCAN SCAN — build initial map
        # ══════════════════════════════════════════════════════════════
        print("\n" + "=" * 60)
        print("  PHASE 1: Coarse scan — building initial occupancy map")
        print("=" * 60)

        result = do_scan(radar, SCAN_RADIUS, args.scan_cell, SCAN_BEAM, "SCAN")
        if not result or not result[0]:
            print("[ERROR] Coarse scan returned no data")
            return

        solid, meta, contacts, ore_cells = result
        radar_map = build_radar_map_from_scan(solid, meta, contacts)
        if not radar_map:
            print("[ERROR] Failed to build map from main scan")
            return

        # Check if target is within scan bounds
        target_idx = radar_map.world_to_index(target)
        if target_idx is None:
            print(f"[WARN] Target outside scan bounds — need to expand scan")
            # TODO: expand scan toward target
            print("[INFO] Try running with a larger --scan-cell or closer to target")
            return
        print(f"[MAP] Target at grid index {target_idx}")

        # ══════════════════════════════════════════════════════════════
        # Phase 2: A* PATHFINDING
        # ══════════════════════════════════════════════════════════════
        print("\n" + "=" * 60)
        print("  PHASE 2: A* pathfinding")
        print("=" * 60)

        path = replan_path(radar_map, ship_pos, target)
        if not path:
            print("[ERROR] No path found — trying fine scan for better resolution...")

            # Try fine scan for better detail
            result2 = do_scan(radar, FINE_RADIUS, args.fine_cell, FINE_BEAM, "FINE")
            if result2 and result2[0]:
                radar_map2 = build_radar_map_from_scan(result2[0], result2[1], result2[2])
                if radar_map2:
                    path = replan_path(radar_map2, ship_pos, target)

            if not path:
                print("[ERROR] Still no path found. Target may be unreachable.")
                return

        if args.dry_run:
            print("\n[DRY RUN] Path found, not flying. Exiting.")
            return

        # ══════════════════════════════════════════════════════════════
        # Phase 3: FLY WITH FORWARD SCANNING
        # ══════════════════════════════════════════════════════════════
        print("\n" + "=" * 60)
        print("  PHASE 3: Flying with obstacle avoidance")
        print("=" * 60)

        # Start forward scanner
        if not args.no_forward_scan:
            print("Starting forward scanner...")
            scanner = SpaceForwardScanner(radar, rc, stop_distance=SAFETY_DISTANCE)
            scanner.start()
            time.sleep(1)

        # Enable autopilot
        rc.enable()
        rc.gyro_control_on()
        rc.thrusters_on()
        rc.dampeners_on()
        time.sleep(1)

        waypoint_idx = 0
        last_replan_time = 0
        replan_count = 0
        MAX_REPLANS = 5

        while waypoint_idx < len(path):
            wp = path[waypoint_idx]
            rc.update()
            ship_pos = get_world_position(rc)
            if not ship_pos:
                time.sleep(0.5)
                continue

            dist_to_wp = _dist(ship_pos, wp)
            print(f"\n[FLY] Waypoint {waypoint_idx}/{len(path)-1}: "
                  f"({wp[0]:.0f},{wp[1]:.0f},{wp[2]:.0f}), dist={dist_to_wp:.0f}m")

            # Check if we should replan
            now = time.time()
            if scanner and now - last_replan_time > REPLAN_INTERVAL:
                # Check if new obstacles detected
                if scanner.nearest_distance < SAFETY_DISTANCE:
                    print(f"[REPLAN] Obstacle at {scanner.nearest_distance:.0f}m — replanning!")
                    replan_count += 1
                    if replan_count > MAX_REPLANS:
                        print("[REPLAN] Max replans reached — continuing on current path")
                    else:
                        # Re-scan and replan
                        rc.update()
                        ship_pos = get_world_position(rc)
                        if ship_pos:
                            result_r = do_scan(radar, FINE_RADIUS, args.fine_cell, FINE_BEAM, "REPLAN")
                            if result_r and result_r[0]:
                                radar_map_r = build_radar_map_from_scan(result_r[0], result_r[1], result_r[2])
                                if radar_map_r:
                                    new_path = replan_path(radar_map_r, ship_pos, target)
                                    if new_path:
                                        path = new_path
                                        waypoint_idx = 0
                                        print(f"[REPLAN] New path: {len(path)} waypoints")
                                    else:
                                        print("[REPLAN] No new path — continuing on old path")
                        last_replan_time = now

                # Also check if obstacle is directly on our path segment
                if scanner:
                    fwd_pts = scanner.solid_points
                    if obstacle_on_path(ship_pos, wp, fwd_pts, OBSTACLE_IN_PATH_DIST):
                        print(f"[REPLAN] Obstacle detected on path segment — replanning!")
                        replan_count += 1
                        if replan_count <= MAX_REPLANS:
                            rc.update()
                            ship_pos = get_world_position(rc)
                            if ship_pos:
                                result_r = do_scan(radar, FINE_RADIUS, args.fine_cell, FINE_BEAM, "REPLAN")
                                if result_r and result_r[0]:
                                    radar_map_r = build_radar_map_from_scan(result_r[0], result_r[1], result_r[2])
                                    if radar_map_r:
                                        new_path = replan_path(radar_map_r, ship_pos, target)
                                        if new_path:
                                            path = new_path
                                            waypoint_idx = 0
                                            print(f"[REPLAN] New path: {len(path)} waypoints")
                        last_replan_time = now

            # Fly to waypoint
            speed = args.speed if dist_to_wp > SLOW_DISTANCE else FLIGHT_SPEED_NEAR

            def cancel_check() -> bool:
                if scanner and scanner.nearest_distance < SAFETY_DISTANCE * 0.5:
                    print("[FLY] Emergency stop — obstacle too close!")
                    return True
                return False

            fly_to_point(
                rc,
                wp,
                waypoint_name=f"WP{waypoint_idx}",
                speed_far=speed,
                speed_near=FLIGHT_SPEED_NEAR,
                arrival_distance=ARRIVAL_DISTANCE,
                max_flight_time=MAX_FLIGHT_TIME,
                cancel_check=cancel_check if not args.no_forward_scan else None,
            )

            waypoint_idx += 1

        # ══════════════════════════════════════════════════════════════
        # Phase 4: ARRIVAL
        # ══════════════════════════════════════════════════════════════
        rc.update()
        final_pos = get_world_position(rc)
        if final_pos:
            final_dist = _dist(final_pos, target)
            print(f"\n[ARRIVED] Final position: ({final_pos[0]:.0f}, {final_pos[1]:.0f}, {final_pos[2]:.0f})")
            print(f"[ARRIVED] Distance to target: {final_dist:.0f}m")
            if scanner:
                print(f"[ARRIVED] Nearest voxel: {scanner.nearest_distance:.0f}m")

        # Stop
        print("\nStopping...")
        if scanner:
            scanner.stop()
        rc.disable()
        rc.dampeners_on()
        rc.handbrake_on()
        print("Done!")

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
        import traceback
        traceback.print_exc()
        if scanner:
            scanner.stop()
    finally:
        close(grid)


if __name__ == "__main__":
    main()
