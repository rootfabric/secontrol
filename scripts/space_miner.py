#!/usr/bin/env python3
"""
Space Miner v2 — A* pathfinding with voxel obstacle avoidance.

Uses the same A* + inflation approach as radar_path_to_player_visualization.py:
  1. Scan voxels (radius=1000, cell=10)
  2. Build RawRadarMap with occupancy grid
  3. Inflate obstacles by ship_radius (30m) — path stays clear of voxels
  4. A* pathfinding from ship to ore
  5. Fly along waypoints with continuous forward scanning for safety

Usage:
    python3 space_miner.py --grid skynet-baza0 --target "98932,81366,-131202"
"""

from __future__ import annotations

import argparse
import math
import os
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
from secontrol.tools.radar_navigation import PathFinder, PassabilityProfile, RawRadarMap
from secontrol.tools.navigation_tools import fly_to_point, get_world_position, _dist

DEFAULT_GRID = "skynet-baza0"

# Scan parameters
SCAN_RADIUS = 1000.0
SCAN_CELL = 5.0         # finer grid = better obstacle detection
SCAN_BEAM = 100

# Pathfinding — same as reference code
SHIP_RADIUS = 30.0      # inflate obstacles by 30m (path stays this far from voxels)

# Forward scanner — continuous safety check during flight
FWD_RADIUS = 1000.0
FWD_CELL = 5.0
FWD_BEAM = 30           # smaller beam = faster scan
FWD_INTERVAL = 1.0

# Flight
FLIGHT_SPEED_FAR = 15.0
FLIGHT_SPEED_NEAR = 5.0
SLOW_DISTANCE = 200.0
ARRIVAL_DISTANCE = 15.0


def parse_target(s: str) -> Tuple[float, float, float]:
    if s.startswith("GPS:"):
        p = s.split(":")
        return (float(p[2]), float(p[3]), float(p[4]))
    p = s.split(",")
    return (float(p[0]), float(p[1]), float(p[2]))


def dist3(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)


def get_pos_safe(rc) -> Optional[Tuple[float, float, float]]:
    try:
        rc.update()
        return get_world_position(rc)
    except Exception:
        return None


# ── Build RawRadarMap from scan (same as reference code) ──────────────

def build_radar_map(
    solid: List[List[float]],
    metadata: Dict[str, Any],
    contacts: List[Any],
) -> Optional[RawRadarMap]:
    """Build RawRadarMap from RadarController scan — matches reference code exactly."""
    if not solid:
        return None

    size = tuple(int(v) for v in metadata["size"])
    origin = np.array(metadata["origin"], dtype=np.float64)
    cell_size = float(metadata["cellSize"])
    occ = np.zeros(size, dtype=np.bool_)

    arr = np.asarray(solid, dtype=np.float64)
    if arr.ndim == 2 and arr.shape[1] == 3:
        rel = (arr - origin.reshape(1, 3)) / cell_size - 0.5
        idx = np.rint(rel).astype(np.int64)
        valid = (
            (idx[:, 0] >= 0) & (idx[:, 0] < size[0])
            & (idx[:, 1] >= 0) & (idx[:, 1] < size[1])
            & (idx[:, 2] >= 0) & (idx[:, 2] < size[2])
        )
        idx = idx[valid]
        if idx.size:
            occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True

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


# ── A* path planning (same as reference code) ────────────────────────

def plan_path(
    radar_map: RawRadarMap,
    start: Tuple[float, float, float],
    goal: Tuple[float, float, float],
    ship_radius: float = SHIP_RADIUS,
) -> List[Tuple[float, float, float]]:
    """A* pathfinding with obstacle inflation — same profile as reference code."""
    profile = PassabilityProfile(
        robot_radius=ship_radius,       # inflate obstacles by ship_radius
        max_slope_degrees=90.0,         # no slope limit in space
        max_step_cells=5,               # can move up to 5 cells per step
        allow_vertical_movement=True,    # full 3D movement
        allow_diagonal=True,             # 26-connected
        is_ground_vehicle=False,         # flying, not driving
    )
    pathfinder = PathFinder(radar_map, profile)
    return pathfinder.find_path_world(start, goal)


# ── Forward scanner (background safety check) ────────────────────────

class ForwardScanner:
    """Background thread scanning for obstacles during flight."""

    def __init__(self, radar, rc, stop_distance: float = SHIP_RADIUS):
        self.radar = radar
        self.rc = rc
        self._stop = stop_distance
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self._nearest = float("inf")

    @property
    def nearest(self):
        with self._lock:
            return self._nearest

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
            radius=FWD_RADIUS,
            cell_size=FWD_CELL,
            boundingBoxX=FWD_BEAM,
            boundingBoxY=FWD_BEAM,
            ore_only=False,
        )
        while self._running:
            try:
                solid, meta, _, _ = ctrl.scan_voxels()
                ship = get_pos_safe(self.rc)
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

                status = f"{nearest:.0f}m" if nearest < float("inf") else "clear"
                print(f"[FWD] {status}, pts={len(solid) if solid else 0}")

            except Exception as e:
                print(f"[FWD] err: {e}")
            time.sleep(FWD_INTERVAL)


# ── Main ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Space miner with A* obstacle avoidance")
    parser.add_argument("--grid", default=DEFAULT_GRID)
    parser.add_argument("--target", required=True)
    parser.add_argument("--ship-radius", type=float, default=SHIP_RADIUS,
                        help="Inflate obstacles by this radius for A* pathfinding (default 30m)")
    parser.add_argument("--clearance", type=float, default=30.0,
                        help="Min distance from voxels during flight (default 30m)")
    parser.add_argument("--mining-clearance", type=float, default=30.0,
                        help="Min distance from voxels near ore target (default 30m, drill reaches 50m+)")
    parser.add_argument("--speed", type=float, default=FLIGHT_SPEED_FAR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target = parse_target(args.target)
    original_target = target  # save before adjustment
    ship_radius = args.ship_radius
    clearance = args.clearance
    mining_clearance = args.mining_clearance

    print("=" * 60)
    print("  Space Miner v2 — A* pathfinding with inflation")
    print("=" * 60)
    print(f"Grid: {args.grid}")
    print(f"Target: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
    print(f"Ship radius (inflation): {ship_radius:.0f}m")
    print(f"Clearance (flight): {clearance:.0f}m")
    print(f"Mining clearance (near ore): {mining_clearance:.0f}m")
    print(f"Scan: radius={SCAN_RADIUS:.0f}m, cell={SCAN_CELL:.0f}m")
    print()

    grid = prepare_grid(args.grid)
    scanner = None

    try:
        # Find devices
        radar = grid.get_first_device(OreDetectorDevice)
        rc = grid.get_first_device(RemoteControlDevice)
        if not radar or not rc:
            print("[ERROR] No radar or RC")
            return
        print(f"Radar: {radar.name} (id={radar.device_id})")
        print(f"RC: {rc.name} (id={rc.device_id})")

        # Get position
        rc.update()
        ship_pos = get_world_position(rc)
        if not ship_pos:
            print("[ERROR] No position")
            return
        print(f"Ship: ({ship_pos[0]:.0f}, {ship_pos[1]:.0f}, {ship_pos[2]:.0f})")
        print(f"Distance to target: {dist3(ship_pos, target):.0f}m")

        # ── PHASE 1: Scan voxels ──
        print("\n" + "=" * 60)
        print("  PHASE 1: Voxel scan")
        print("=" * 60)

        ctrl = RadarController(
            radar,
            radius=SCAN_RADIUS,
            cell_size=SCAN_CELL,
            boundingBoxX=SCAN_BEAM,
            boundingBoxY=SCAN_BEAM,
            ore_only=False,
        )

        # Retry scan up to 3 times
        solid, meta, contacts, ore_cells = None, None, None, None
        for attempt in range(3):
            solid, meta, contacts, ore_cells = ctrl.scan_voxels()
            if solid and meta:
                break
            print(f"[SCAN] Attempt {attempt+1} failed, retrying...")
            time.sleep(2)

        if not solid or not meta:
            print("[ERROR] Scan returned no data after 3 attempts")
            return

        n = len(solid) if solid else 0
        print(f"[SCAN] {n} solid voxels, cell_size={meta.get('cellSize')}m")

        if n > 0:
            dists = sorted([(dist3(pt, ship_pos), pt) for pt in solid])
            print(f"[SCAN] 5 nearest to ship:")
            for d, pt in dists[:5]:
                print(f"  {d:.0f}m at ({pt[0]:.0f},{pt[1]:.0f},{pt[2]:.0f})")

        # Show ore
        if ore_cells:
            print(f"[SCAN] Ores found:")
            for cell in ore_cells:
                mat = cell.get("material") or cell.get("ore") or "?"
                pos = cell.get("position", "?")
                print(f"  {mat}: {pos}")

        # ── PHASE 2: Build map + A* pathfinding ──
        print("\n" + "=" * 60)
        print("  PHASE 2: A* pathfinding")
        print("=" * 60)

        radar_map = build_radar_map(solid or [], meta, contacts or [])
        if not radar_map:
            print("[ERROR] Failed to build map")
            return

        # Check bounds
        ship_idx = radar_map.world_to_index(ship_pos)
        target_idx = radar_map.world_to_index(target)
        print(f"[MAP] Grid {radar_map.size}, cell={radar_map.cell_size}m")
        print(f"[MAP] Ship at index {ship_idx}")
        print(f"[MAP] Target at index {target_idx}")

        if ship_idx is None:
            print("[ERROR] Ship outside scan bounds — increase --radius")
            return
        if target_idx is None:
            print("[ERROR] Target outside scan bounds — increase --radius")
            return

        # Check if target cell is blocked (inside asteroid)
        # Use mining_clearance for target adjustment — allows closer approach to ore
        occ = radar_map.occupancy(mining_clearance)
        if occ[target_idx]:
            print(f"[WARN] Target index {target_idx} is INSIDE inflated obstacle!")
            print(f"[WARN] Searching for nearest free cell to target...")
            # Find nearest free cell to target
            from collections import deque
            visited = set()
            queue = deque([target_idx])
            visited.add(target_idx)
            free_target = None
            while queue:
                cur = queue.popleft()
                if not occ[cur]:
                    free_target = cur
                    break
                x, y, z = cur
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for dz in (-1, 0, 1):
                            if dx == 0 and dy == 0 and dz == 0:
                                continue
                            nb = (x+dx, y+dy, z+dz)
                            if (0 <= nb[0] < radar_map.size[0]
                                and 0 <= nb[1] < radar_map.size[1]
                                and 0 <= nb[2] < radar_map.size[2]
                                and nb not in visited):
                                visited.add(nb)
                                queue.append(nb)
            if free_target:
                target_world = radar_map.index_to_world_center(free_target)
                print(f"[MAP] Adjusted target: {free_target} → ({target_world[0]:.0f},{target_world[1]:.0f},{target_world[2]:.0f})")
                target = target_world
            else:
                print("[ERROR] No free cell near target — too deep inside asteroid")
                return

        # Plan path
        print(f"\n[PATH] Planning: ({ship_pos[0]:.0f},{ship_pos[1]:.0f},{ship_pos[2]:.0f}) "
              f"→ ({target[0]:.0f},{target[1]:.0f},{target[2]:.0f})")
        print(f"[PATH] robot_radius={ship_radius}m (inflated obstacles)")

        t0 = time.time()
        path = plan_path(radar_map, ship_pos, target, clearance)
        dt = time.time() - t0

        if path:
            print(f"[PATH] ✅ Found: {len(path)} waypoints in {dt:.2f}s")
            # Calculate total path distance
            total_dist = sum(dist3(a, b) for a, b in zip(path, path[1:]))
            print(f"[PATH] Total distance: {total_dist:.0f}m")
            for i, wp in enumerate(path[:5]):
                print(f"  [{i}] ({wp[0]:.0f}, {wp[1]:.0f}, {wp[2]:.0f})")
            if len(path) > 5:
                print(f"  ... +{len(path)-5} more")

            # Show final adjusted target info
            last = path[-1]
            print(f"\n[PATH] Final WP: ({last[0]:.0f},{last[1]:.0f},{last[2]:.0f})")
            print(f"[PATH] Distance to ore: {dist3(last, original_target):.0f}m (drill reaches 50m+)")
        else:
            print(f"[PATH] ❌ No path found in {dt:.2f}s")
            return

        if args.dry_run:
            print("\n[DRY RUN] Path found, not flying. Exiting.")
            return

        # ── PHASE 3: Fly along A* path ──
        print("\n" + "=" * 60)
        print("  PHASE 3: Flying along A* path")
        print("=" * 60)

        # Start forward scanner
        scanner = ForwardScanner(radar, rc, stop_distance=clearance)
        scanner.start()
        time.sleep(1)

        # Enable autopilot
        rc.enable()
        rc.gyro_control_on()
        rc.thrusters_on()
        rc.dampeners_on()
        time.sleep(1)

        for wp_idx, wp in enumerate(path):
            rc.update()
            ship_pos = get_world_position(rc)
            if not ship_pos:
                continue

            d = dist3(ship_pos, wp)
            d_final = dist3(ship_pos, original_target)
            nearest_voxel = scanner.nearest

            # Use mining_clearance when close to target, clearance otherwise
            active_clearance = mining_clearance if d_final < 200 else clearance
            emergency_stop = active_clearance * 0.3

            print(f"\n[FLY] WP {wp_idx}/{len(path)-1}: ({wp[0]:.0f},{wp[1]:.0f},{wp[2]:.0f}), "
                  f"dist={d:.0f}m, to_target={d_final:.0f}m, voxels={nearest_voxel:.0f}m, "
                  f"clearance={active_clearance:.0f}m")

            # Safety check — adaptive clearance
            if nearest_voxel < emergency_stop:
                print(f"[FLY] ⚠️  Voxel too close ({nearest_voxel:.0f}m < {emergency_stop:.0f}m) — stopping!")
                break

            speed = args.speed if d > SLOW_DISTANCE else FLIGHT_SPEED_NEAR

            def cancel_check():
                nearest = scanner.nearest
                threshold = active_clearance * 0.3
                if nearest < threshold:
                    print(f"[CANCEL] Voxel {nearest:.0f}m < threshold {threshold:.0f}m")
                    return True
                return False

            # Adaptive arrival: tighter near ore
            arrival = ARRIVAL_DISTANCE
            print(f"[FLY] arrival={arrival:.0f}m, cancel_threshold={active_clearance*0.3:.0f}m")

            fly_to_point(
                rc, wp,
                waypoint_name=f"WP{wp_idx}",
                speed_far=speed,
                speed_near=FLIGHT_SPEED_NEAR,
                arrival_distance=arrival,
                max_flight_time=60.0,
                cancel_check=cancel_check,
            )

        # ── Final ──
        rc.update()
        final_pos = get_world_position(rc)
        if final_pos:
            print(f"\n[END] Position: ({final_pos[0]:.0f}, {final_pos[1]:.0f}, {final_pos[2]:.0f})")
            print(f"[END] Distance to target: {dist3(final_pos, original_target):.0f}m")
            if scanner:
                print(f"[END] Nearest voxel: {scanner.nearest:.0f}m")

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
