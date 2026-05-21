"""Distance-scanned obstacle-avoiding space navigation.

The controller uses one radar scan at a time, builds an inflated voxel map, and
flies only to waypoints that remain inside the current scan volume. Coarse scans
cover long-range cruise; fine scans handle the last kilometer and targets that
are inside or near asteroid voxels.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.tools.navigation_tools import fly_to_point, get_world_position, _dist
from secontrol.tools.radar_navigation import (
    PassabilityProfile,
    PathFinder,
    RadarContact,
    RawRadarMap,
)

Point3D = Tuple[float, float, float]
Index3 = Tuple[int, int, int]


@dataclass
class ScanProfile:
    """Defines a single radar resolution level."""

    name: str
    radius: float
    cell_size: float
    beam: Optional[int] = None
    rescan_distance: Optional[float] = None
    clearance_voxels: int = 5
    max_leg_distance: Optional[float] = None

    def __post_init__(self) -> None:
        self.radius = float(self.radius)
        self.cell_size = float(self.cell_size)
        if self.radius <= 0:
            raise ValueError("radius must be positive")
        if self.cell_size <= 0:
            raise ValueError("cell_size must be positive")

        if self.beam is None:
            self.beam = max(1, int(math.ceil((2.0 * self.radius) / self.cell_size)))
        else:
            self.beam = max(1, int(self.beam))

        if self.rescan_distance is None:
            self.rescan_distance = min(self.radius * 0.2, 1000.0)
        else:
            self.rescan_distance = float(self.rescan_distance)

        if self.max_leg_distance is None:
            self.max_leg_distance = self.rescan_distance
        else:
            self.max_leg_distance = float(self.max_leg_distance)

        self.clearance_voxels = max(0, int(self.clearance_voxels))

    @property
    def beam_meters(self) -> float:
        return float(self.beam or 0) * self.cell_size

    @property
    def scan_kwargs(self) -> Dict[str, float]:
        return {
            "radius": self.radius,
            "cell_size": self.cell_size,
            "boundingBoxX": float(self.beam or 0),
            "boundingBoxY": float(self.beam or 0),
            "boundingBoxZ": float(self.beam or 0),
        }


COARSE_SCAN = ScanProfile(
    name="COARSE",
    radius=5000.0,
    cell_size=50.0,
    rescan_distance=1000.0,
    clearance_voxels=10,
)
MEDIUM_SCAN = ScanProfile(
    name="MEDIUM",
    radius=1000.0,
    cell_size=20.0,
    rescan_distance=500.0,
    clearance_voxels=5,
)
FINE_SCAN = ScanProfile(
    name="FINE",
    radius=1000.0,
    cell_size=10.0,
    rescan_distance=500.0,
    clearance_voxels=8,
)


@dataclass
class SpeedZone:
    """Adaptive speed based on nearest obstacle distance."""

    max_speed: float = 50.0
    far_speed: float = 30.0
    medium_speed: float = 15.0
    near_speed: float = 8.0
    close_speed: float = 3.0
    far_threshold: float = 3000.0
    medium_threshold: float = 1000.0
    near_threshold: float = 300.0

    def speed_for_distance(self, nearest_obstacle_m: float) -> float:
        if nearest_obstacle_m >= self.far_threshold:
            return self.max_speed
        if nearest_obstacle_m >= self.medium_threshold:
            return self.far_speed
        if nearest_obstacle_m >= self.near_threshold:
            return self.medium_speed
        return self.close_speed


@dataclass
class NavigationResult:
    """Result returned by SpaceNavigatorController.navigate_to."""

    status: str
    final_position: Optional[Point3D]
    requested_target: Point3D
    resolved_target: Optional[Point3D]
    profile: Optional[str]
    scan_count: int
    replans: int
    nearest_voxel_distance: float = float("inf")
    message: str = ""

    @property
    def arrived(self) -> bool:
        return self.status in {"arrived", "safe_target_reached"}

    def __bool__(self) -> bool:
        return self.arrived


@dataclass
class NavState:
    """Current navigation state, mostly useful for external observers."""

    position: Optional[Point3D] = None
    target: Optional[Point3D] = None
    distance_to_target: float = float("inf")
    nearest_obstacle: float = float("inf")
    nearest_ship: float = float("inf")
    current_speed: float = 0.0
    phase: str = "idle"
    replan_count: int = 0
    waypoints_flown: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


class BackgroundScanner:
    """Compatibility shim for older code.

    The main controller no longer starts this scanner by default because the new
    routing loop uses coordinated distance-based scans. Existing callers that
    instantiate BackgroundScanner directly still get the old nearest-obstacle
    behavior.
    """

    def __init__(
        self,
        radar: OreDetectorDevice,
        rc: RemoteControlDevice,
        scan_profile: ScanProfile,
        safety_distance: float = 200.0,
    ):
        self.radar = radar
        self.rc = rc
        self.scan_profile = scan_profile
        self.safety_distance = float(safety_distance)
        self._nearest_obstacle = float("inf")
        self._nearest_ship = float("inf")
        self._solid_points: List[List[float]] = []
        self._contacts: List[Dict[str, Any]] = []
        self._needs_replan = False
        self._ship_positions: Dict[int, Point3D] = {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    @property
    def nearest_obstacle(self) -> float:
        with self._lock:
            return self._nearest_obstacle

    @property
    def nearest_ship(self) -> float:
        with self._lock:
            return self._nearest_ship

    @property
    def needs_replan(self) -> bool:
        with self._lock:
            value = self._needs_replan
            self._needs_replan = False
            return value

    @property
    def solid_points(self) -> List[List[float]]:
        with self._lock:
            return self._solid_points.copy()

    @property
    def contacts(self) -> List[Dict[str, Any]]:
        with self._lock:
            return self._contacts.copy()

    @property
    def ship_positions(self) -> Dict[int, Point3D]:
        with self._lock:
            return dict(self._ship_positions)

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=15)

    def _loop(self) -> None:
        ctrl = RadarController(
            self.radar,
            radius=self.scan_profile.radius,
            cell_size=self.scan_profile.cell_size,
            boundingBoxX=self.scan_profile.beam,
            boundingBoxY=self.scan_profile.beam,
            boundingBoxZ=self.scan_profile.beam,
            ore_only=False,
        )
        while self._running:
            try:
                solid, _meta, contacts, _ore_cells = ctrl.scan_voxels()
                ship_pos = _safe_get_position(self.rc)
                nearest_voxel = nearest_point_distance(solid or [], ship_pos)
                nearest_ship, ship_positions = _nearest_grid_contact(contacts or [], ship_pos)
                with self._lock:
                    self._nearest_obstacle = nearest_voxel
                    self._nearest_ship = nearest_ship
                    self._solid_points = solid or []
                    self._contacts = contacts or []
                    self._ship_positions = ship_positions
                    if nearest_voxel < self.safety_distance:
                        self._needs_replan = True
            except Exception as exc:
                print(f"[SCAN] error: {exc}")
            time.sleep(0.3)


def effective_clearance_radius(ship_radius: float, profile: ScanProfile) -> float:
    return float(ship_radius) + profile.clearance_voxels * profile.cell_size


def estimate_ship_radius_from_blocks(grid: Any, fallback: float = 50.0) -> float:
    """Estimate a conservative spherical radius from block world AABBs."""

    mins: List[float] = [float("inf"), float("inf"), float("inf")]
    maxs: List[float] = [float("-inf"), float("-inf"), float("-inf")]
    found = False

    blocks = getattr(grid, "blocks", {}) or {}
    values = blocks.values() if isinstance(blocks, dict) else blocks
    for block in values:
        bbox = getattr(block, "bounding_box", None)
        if not isinstance(bbox, dict):
            continue
        bmin = bbox.get("min")
        bmax = bbox.get("max")
        if not _is_vec3(bmin) or not _is_vec3(bmax):
            continue
        for axis in range(3):
            mins[axis] = min(mins[axis], float(bmin[axis]))
            maxs[axis] = max(maxs[axis], float(bmax[axis]))
        found = True

    if not found:
        return float(fallback)

    dims = [maxs[i] - mins[i] for i in range(3)]
    radius = math.sqrt(sum(d * d for d in dims)) * 0.5
    return max(1.0, radius)


def build_map_with_ships(
    solid: Sequence[Sequence[float]] | None,
    metadata: Dict[str, Any],
    contacts: Sequence[Dict[str, Any]] | None,
    ship_radius: float = 50.0,
    own_position: Optional[Point3D] = None,
) -> Optional[RawRadarMap]:
    """Build RawRadarMap from scan results, including grid contacts."""

    if not metadata:
        return None

    try:
        origin = np.array(metadata["origin"], dtype=np.float64)
        cell_size = float(metadata["cellSize"])
        size = tuple(int(v) for v in metadata["size"])
    except (KeyError, TypeError, ValueError):
        return None

    if len(size) != 3 or cell_size <= 0:
        return None

    occ = np.zeros(size, dtype=np.bool_)

    if solid:
        arr = np.asarray(solid, dtype=np.float64)
        if arr.ndim == 2 and arr.shape[1] == 3:
            rel = (arr - origin.reshape(1, 3)) / cell_size - 0.5
            idx = np.rint(rel).astype(np.int64)
            valid = (
                (idx[:, 0] >= 0)
                & (idx[:, 0] < size[0])
                & (idx[:, 1] >= 0)
                & (idx[:, 1] < size[1])
                & (idx[:, 2] >= 0)
                & (idx[:, 2] < size[2])
            )
            idx = idx[valid]
            if idx.size:
                occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True

    ship_cells_added = 0
    radar_contacts: List[RadarContact] = []
    for contact in contacts or []:
        if not isinstance(contact, dict):
            continue
        cpos = contact.get("pos") or contact.get("position")
        if not _is_vec3(cpos):
            continue

        pos = (float(cpos[0]), float(cpos[1]), float(cpos[2]))
        try:
            cid = int(contact.get("id", 0))
        except (TypeError, ValueError):
            cid = 0

        ctype = str(contact.get("type", ""))
        radar_contacts.append(RadarContact(type=ctype, id=cid, position=pos))
        if ctype != "grid":
            continue

        if own_position and _dist(pos, own_position) < max(50.0, ship_radius * 1.5):
            continue

        minx, miny, minz, maxx, maxy, maxz = _contact_aabb(contact, pos)
        ix0 = max(0, int(math.floor((minx - origin[0]) / cell_size)))
        iy0 = max(0, int(math.floor((miny - origin[1]) / cell_size)))
        iz0 = max(0, int(math.floor((minz - origin[2]) / cell_size)))
        ix1 = min(size[0] - 1, int(math.floor((maxx - origin[0]) / cell_size)))
        iy1 = min(size[1] - 1, int(math.floor((maxy - origin[1]) / cell_size)))
        iz1 = min(size[2] - 1, int(math.floor((maxz - origin[2]) / cell_size)))
        if ix1 >= ix0 and iy1 >= iy0 and iz1 >= iz0:
            occ[ix0 : ix1 + 1, iy0 : iy1 + 1, iz0 : iz1 + 1] = True
            ship_cells_added += (ix1 - ix0 + 1) * (iy1 - iy0 + 1) * (iz1 - iz0 + 1)

    occupied = int(np.sum(occ))
    total = int(np.prod(size))
    print(
        f"[MAP] Grid {size[0]}x{size[1]}x{size[2]}, cell={cell_size:.1f}m, "
        f"occupied={occupied}/{total} ({100 * occupied / max(total, 1):.2f}%), "
        f"ship_cells={ship_cells_added}"
    )

    return RawRadarMap(
        occ=occ,
        origin=origin,
        cell_size=cell_size,
        size=size,  # type: ignore[arg-type]
        revision=metadata.get("rev"),
        timestamp_ms=metadata.get("tsMs"),
        contacts=tuple(radar_contacts),
        _inflation_cache={},
    )


def find_path_multiscale(
    radar_map: RawRadarMap,
    start: Point3D,
    goal: Point3D,
    ship_radius: float = 50.0,
    scan_profile: Optional[ScanProfile] = None,
) -> List[Point3D]:
    """Run A* with obstacle inflation for the current scan profile."""

    robot_radius = float(ship_radius)
    if scan_profile is not None:
        robot_radius = effective_clearance_radius(ship_radius, scan_profile)

    profile = PassabilityProfile(
        robot_radius=robot_radius,
        max_slope_degrees=90.0,
        max_step_cells=5,
        allow_vertical_movement=True,
        allow_diagonal=True,
        is_ground_vehicle=False,
    )
    pathfinder = PathFinder(radar_map, profile)
    start_time = time.time()
    path = pathfinder.find_path_world(start, goal)
    elapsed = time.time() - start_time
    if path:
        print(f"[PATH] {len(path)} waypoints in {elapsed:.2f}s")
    else:
        print(f"[PATH] No path in {elapsed:.2f}s")
    return path


def resolve_nearest_safe_point(
    radar_map: RawRadarMap,
    target: Point3D,
    safety_radius: float,
) -> Optional[Point3D]:
    """Resolve target to the nearest free cell in the inflated map."""

    target_idx = radar_map.world_to_index(target)
    if target_idx is None:
        return None

    occ = radar_map.occupancy(safety_radius)
    if not bool(occ[target_idx]):
        return radar_map.index_to_world_center(target_idx)

    visited = {target_idx}
    queue: deque[Index3] = deque([target_idx])
    best_idx: Optional[Index3] = None
    best_dist = float("inf")

    while queue:
        current = queue.popleft()
        if not bool(occ[current]):
            world = radar_map.index_to_world_center(current)
            dist = _dist(world, target)
            if dist < best_dist:
                best_idx = current
                best_dist = dist
            # The first free BFS shell is enough; drain no deeper shell.
            if best_idx is not None:
                return radar_map.index_to_world_center(best_idx)

        x, y, z = current
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    neighbor = (x + dx, y + dy, z + dz)
                    if neighbor in visited or not radar_map.is_within_bounds(neighbor):
                        continue
                    visited.add(neighbor)
                    queue.append(neighbor)

    return None


def pick_waypoint_along_path(
    path: Sequence[Point3D],
    ship_pos: Point3D,
    scan_radius: Optional[float] = None,
    boundary_margin: float = 30.0,
    max_step_fraction: float = 0.4,
    *,
    scan_center: Optional[Point3D] = None,
    rescan_distance: Optional[float] = None,
    max_leg_distance: Optional[float] = None,
) -> Optional[Point3D]:
    """Pick the farthest path waypoint that remains inside scan limits."""

    if not path:
        return None

    limits: List[float] = []
    if scan_radius is not None:
        limits.append(max(0.0, float(scan_radius) * max_step_fraction))
    if rescan_distance is not None:
        limits.append(float(rescan_distance))
    if max_leg_distance is not None:
        limits.append(float(max_leg_distance))
    max_from_ship = min(limits) if limits else float("inf")

    if scan_center is None:
        scan_center = ship_pos
    max_from_center = (
        max(0.0, float(scan_radius) - boundary_margin)
        if scan_radius is not None
        else float("inf")
    )

    best: Optional[Point3D] = None
    for waypoint in path:
        if _dist(waypoint, ship_pos) < 1e-6:
            continue
        if _dist(waypoint, ship_pos) > max_from_ship:
            break
        if _dist(waypoint, scan_center) > max_from_center:
            break
        best = waypoint

    return best


class SpaceNavigatorController:
    """Reusable obstacle-avoiding navigator for space grids."""

    def __init__(
        self,
        grid_name: str,
        *,
        ship_radius: Optional[float] = None,
        speed_zone: Optional[SpeedZone] = None,
        coarse_scan: Optional[ScanProfile] = None,
        medium_scan: Optional[ScanProfile] = None,
        fine_scan: Optional[ScanProfile] = None,
        arrival_distance: float = 50.0,
        max_replans: int = 20,
        max_steps: int = 200,
        max_flight_time: float = 600.0,
        enable_background_scanner: bool = False,
        dry_run: bool = False,
    ):
        from secontrol.common import prepare_grid

        self.grid = prepare_grid(grid_name)
        self.speed_zone = speed_zone or SpeedZone()
        self.coarse_scan = coarse_scan or COARSE_SCAN
        self.medium_scan = medium_scan or MEDIUM_SCAN
        self.fine_scan = fine_scan or FINE_SCAN
        self.arrival_distance = float(arrival_distance)
        self.max_replans = int(max_replans)
        self.max_steps = int(max_steps)
        self.max_flight_time = float(max_flight_time)
        self.enable_background_scanner = bool(enable_background_scanner)
        self.dry_run = bool(dry_run)

        radars = self.grid.find_devices_by_type(OreDetectorDevice)
        rcs = self.grid.find_devices_by_type(RemoteControlDevice)
        if not radars:
            raise RuntimeError("No OreDetector (radar) found on grid")
        if not rcs:
            raise RuntimeError("No RemoteControl found on grid")

        self.radar: OreDetectorDevice = radars[0]
        self.rc: RemoteControlDevice = rcs[0]
        self.ship_radius = (
            float(ship_radius)
            if ship_radius is not None
            else estimate_ship_radius_from_blocks(self.grid, fallback=50.0)
        )

        self.state = NavState()
        self.scanner: Optional[BackgroundScanner] = None
        self._current_map: Optional[RawRadarMap] = None
        self._scan_count = 0
        self._replans = 0
        self._nearest_voxel_distance = float("inf")

    def navigate_to(
        self,
        target: Point3D,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> NavigationResult:
        """Navigate to target using coarse and fine distance-based scans."""

        requested_target = _vec3(target)
        self._scan_count = 0
        self._replans = 0
        self._nearest_voxel_distance = float("inf")

        print("=" * 60)
        print("  Space Navigator - distance-scanned obstacle avoidance")
        print("=" * 60)
        print(f"Target: ({requested_target[0]:.0f}, {requested_target[1]:.0f}, {requested_target[2]:.0f})")
        print(f"Ship radius: {self.ship_radius:.1f}m")
        print(
            f"Coarse: radius={self.coarse_scan.radius:.0f}m, "
            f"cell={self.coarse_scan.cell_size:.0f}m, "
            f"rescan={self.coarse_scan.rescan_distance:.0f}m"
        )
        print(
            f"Fine: radius={self.fine_scan.radius:.0f}m, "
            f"cell={self.fine_scan.cell_size:.0f}m, "
            f"rescan={self.fine_scan.rescan_distance:.0f}m"
        )
        print()

        self.rc.enable()
        self.rc.gyro_control_on()
        self.rc.thrusters_on()
        self.rc.dampeners_on()
        try:
            self.rc.handbrake_off()
        except Exception:
            pass
        self.rc.set_collision_avoidance(False)
        time.sleep(1)

        try:
            return self._navigate_loop(requested_target, cancel_check)
        finally:
            if self.scanner:
                self.scanner.stop()

    def _navigate_loop(
        self,
        requested_target: Point3D,
        cancel_check: Optional[Callable[[], bool]],
    ) -> NavigationResult:
        fine_mode = False
        last_profile: Optional[ScanProfile] = None
        consecutive_failures = 0
        resolved_target: Optional[Point3D] = None

        for step in range(self.max_steps):
            if cancel_check and cancel_check():
                return self._result(
                    "cancelled",
                    requested_target,
                    resolved_target,
                    last_profile,
                    "Cancelled by caller.",
                )

            ship_pos = _safe_get_position(self.rc)
            if ship_pos is None:
                time.sleep(0.5)
                continue

            dist_to_target = _dist(ship_pos, requested_target)
            if self._scan_count > 0 and dist_to_target <= self.fine_scan.radius:
                fine_mode = True

            profile = self.fine_scan if fine_mode else self.coarse_scan
            last_profile = profile
            with self.state.lock:
                self.state.position = ship_pos
                self.state.target = requested_target
                self.state.distance_to_target = dist_to_target
                self.state.phase = profile.name.lower()

            print()
            print(
                f"[NAV] step={step} profile={profile.name} "
                f"pos=({ship_pos[0]:.0f},{ship_pos[1]:.0f},{ship_pos[2]:.0f}) "
                f"target_dist={dist_to_target:.0f}m"
            )

            scan_result = self._do_scan(profile, label=profile.name)
            if scan_result is None:
                consecutive_failures += 1
                self._stop_for_retry()
                if consecutive_failures > self.max_replans:
                    return self._result(
                        "scan_failed",
                        requested_target,
                        resolved_target,
                        profile,
                        "Scan failed too many times.",
                    )
                continue

            solid, metadata, contacts, _ore_cells = scan_result
            self._nearest_voxel_distance = nearest_point_distance(solid or [], ship_pos)
            with self.state.lock:
                self.state.nearest_obstacle = self._nearest_voxel_distance

            radar_map = self._build_map(scan_result)
            if radar_map is None:
                consecutive_failures += 1
                self._stop_for_retry()
                if consecutive_failures > self.max_replans:
                    return self._result(
                        "scan_failed",
                        requested_target,
                        resolved_target,
                        profile,
                        "Failed to build radar map.",
                    )
                continue

            self._current_map = radar_map
            safety_radius = effective_clearance_radius(self.ship_radius, profile)
            local_goal = self._resolve_local_goal(
                radar_map,
                ship_pos,
                requested_target,
                profile,
                safety_radius,
            )
            resolved_target = local_goal

            if local_goal is None:
                consecutive_failures += 1
                self._stop_for_retry()
                if consecutive_failures > self.max_replans:
                    return self._result(
                        "blocked",
                        requested_target,
                        None,
                        profile,
                        "No safe target exists in the scanned volume.",
                    )
                continue

            dist_to_local = _dist(ship_pos, local_goal)
            dist_local_to_requested = _dist(local_goal, requested_target)
            print(
                f"[NAV] safe_goal=({local_goal[0]:.0f},{local_goal[1]:.0f},{local_goal[2]:.0f}) "
                f"goal_dist={dist_to_local:.0f}m requested_delta={dist_local_to_requested:.0f}m "
                f"clearance={safety_radius:.0f}m"
            )

            if dist_to_local <= self.arrival_distance:
                status = "arrived" if dist_to_target <= self.arrival_distance else "safe_target_reached"
                return self._result(status, requested_target, local_goal, profile, "Target reached.")

            path = find_path_multiscale(
                radar_map,
                ship_pos,
                local_goal,
                ship_radius=self.ship_radius,
                scan_profile=profile,
            )
            if not path:
                consecutive_failures += 1
                self._replans += 1
                self._stop_for_retry()
                if not fine_mode and self._target_is_in_scan(radar_map, requested_target):
                    fine_mode = True
                if consecutive_failures > self.max_replans:
                    return self._result(
                        "blocked",
                        requested_target,
                        local_goal,
                        profile,
                        "No A* path to the safe target.",
                    )
                continue

            consecutive_failures = 0
            waypoint = pick_waypoint_along_path(
                path,
                ship_pos,
                scan_radius=profile.radius,
                boundary_margin=self._boundary_margin(profile),
                scan_center=ship_pos,
                rescan_distance=profile.rescan_distance,
                max_leg_distance=profile.max_leg_distance,
            )
            if waypoint is None:
                if dist_to_local <= max(self.arrival_distance, profile.cell_size):
                    status = "arrived" if dist_to_target <= self.arrival_distance else "safe_target_reached"
                    return self._result(status, requested_target, local_goal, profile, "Target reached.")
                self._replans += 1
                self._stop_for_retry()
                if self._replans > self.max_replans:
                    return self._result(
                        "blocked",
                        requested_target,
                        local_goal,
                        profile,
                        "Could not choose a bounded waypoint.",
                    )
                continue

            print(
                f"[FLY] waypoint=({waypoint[0]:.0f},{waypoint[1]:.0f},{waypoint[2]:.0f}) "
                f"dist={_dist(ship_pos, waypoint):.0f}m"
            )

            if self.dry_run:
                return self._result(
                    "dry_run",
                    requested_target,
                    local_goal,
                    profile,
                    "Dry run planned one bounded segment.",
                )

            flight_ok = self._fly_to_waypoint(
                waypoint,
                ship_pos,
                profile,
                nearest_obstacle=self._nearest_voxel_distance,
                cancel_check=cancel_check,
            )
            if not flight_ok:
                consecutive_failures += 1
                self._replans += 1
                self._stop_for_retry()
                if consecutive_failures > self.max_replans:
                    return self._result(
                        "flight_failed",
                        requested_target,
                        local_goal,
                        profile,
                        "Autopilot failed to execute the planned waypoint.",
                    )
                continue

            with self.state.lock:
                self.state.waypoints_flown += 1

            new_pos = _safe_get_position(self.rc) or ship_pos
            if not fine_mode and (
                _dist(new_pos, requested_target) <= self.fine_scan.radius
                or _dist(local_goal, requested_target) <= self.fine_scan.radius
            ):
                fine_mode = True

        return self._result(
            "max_steps",
            requested_target,
            resolved_target,
            last_profile,
            f"Max steps reached ({self.max_steps}).",
        )

    def _do_scan(
        self,
        profile: ScanProfile,
        label: str = "SCAN",
        include_voxels: bool = True,
        include_contacts: bool = True,
    ) -> Optional[Tuple[List[List[float]], Dict[str, Any], List[Any], List[Any]]]:
        ctrl = RadarController(
            self.radar,
            radius=profile.radius,
            cell_size=profile.cell_size,
            boundingBoxX=profile.beam,
            boundingBoxY=profile.beam,
            boundingBoxZ=profile.beam,
            ore_only=False,
        )

        print(
            f"[{label}] scan radius={profile.radius:.0f}m "
            f"cell={profile.cell_size:.0f}m bbox={profile.beam} cells"
        )
        self._scan_count += 1
        started = time.time()
        solid, meta, contacts, ore_cells = ctrl.scan_voxels()
        elapsed = time.time() - started
        if meta is None:
            print(f"[{label}] scan returned no metadata")
            return None
        print(
            f"[{label}] {len(solid or [])} voxels, {len(contacts or [])} contacts "
            f"in {elapsed:.1f}s"
        )
        return solid or [], meta, contacts or [], ore_cells or []

    def _build_map(
        self,
        scan_result: Tuple[List[List[float]], Dict[str, Any], List[Any], List[Any]],
    ) -> Optional[RawRadarMap]:
        solid, meta, contacts, _ore_cells = scan_result
        ship_pos = _safe_get_position(self.rc)
        return build_map_with_ships(
            solid,
            meta,
            contacts,
            ship_radius=self.ship_radius,
            own_position=ship_pos,
        )

    def _resolve_local_goal(
        self,
        radar_map: RawRadarMap,
        ship_pos: Point3D,
        requested_target: Point3D,
        profile: ScanProfile,
        safety_radius: float,
    ) -> Optional[Point3D]:
        candidate = requested_target
        if (
            radar_map.world_to_index(candidate) is None
            or _dist(candidate, ship_pos) > profile.radius - self._boundary_margin(profile)
        ):
            candidate = _point_toward(
                ship_pos,
                requested_target,
                max(0.0, profile.radius - self._boundary_margin(profile)),
            )
        candidate = _clamp_to_map_bounds(candidate, radar_map, profile.cell_size)
        return resolve_nearest_safe_point(radar_map, candidate, safety_radius)

    def _fly_to_waypoint(
        self,
        waypoint: Point3D,
        scan_center: Point3D,
        profile: ScanProfile,
        *,
        nearest_obstacle: float,
        cancel_check: Optional[Callable[[], bool]],
    ) -> bool:
        distance = _dist(scan_center, waypoint)
        speed = self._speed_for_profile(profile, nearest_obstacle)
        with self.state.lock:
            self.state.current_speed = speed

        def should_cancel() -> bool:
            if cancel_check and cancel_check():
                return True
            pos = _safe_get_position(self.rc)
            if pos is None:
                return False
            limit = profile.radius - self._boundary_margin(profile)
            if _dist(pos, scan_center) > limit:
                print(f"[FLY] stopping before leaving scanned volume ({limit:.0f}m)")
                return True
            return False

        stop_pos = fly_to_point(
            self.rc,
            waypoint,
            waypoint_name=f"{profile.name}_WP",
            speed_far=speed,
            speed_near=speed,
            arrival_distance=max(10.0, min(self.arrival_distance, profile.cell_size * 2)),
            max_flight_time=min(
                self.max_flight_time,
                max(30.0, distance / max(speed, 1.0) + 20.0),
            ),
            cancel_check=should_cancel,
        )
        if stop_pos is None:
            print("[FLY] autopilot did not engage for waypoint")
            return False

        remaining = _dist(stop_pos, waypoint)
        progress = _dist(scan_center, stop_pos)
        print(
            f"[FLY] stopped=({stop_pos[0]:.0f},{stop_pos[1]:.0f},{stop_pos[2]:.0f}) "
            f"progress={progress:.0f}m remaining={remaining:.0f}m"
        )

        arrival = max(10.0, min(self.arrival_distance, profile.cell_size * 2))
        if distance > arrival * 2.0 and remaining > arrival * 2.0:
            min_progress = min(25.0, max(5.0, distance * 0.1))
            if progress < min_progress:
                print(
                    f"[FLY] waypoint made no useful progress "
                    f"(progress={progress:.1f}m, expected>{min_progress:.1f}m)"
                )
                return False
        return True

    def _speed_for_profile(self, profile: ScanProfile, nearest_obstacle: float) -> float:
        if profile.name.upper() == "FINE":
            return self.speed_zone.close_speed
        return self.speed_zone.speed_for_distance(nearest_obstacle)

    def _boundary_margin(self, profile: ScanProfile) -> float:
        return max(profile.cell_size * 2.0, self.ship_radius)

    def _target_is_in_scan(self, radar_map: RawRadarMap, target: Point3D) -> bool:
        return radar_map.world_to_index(target) is not None

    def _stop_for_retry(self) -> None:
        try:
            self.rc.disable()
            self.rc.dampeners_on()
        except Exception:
            pass
        time.sleep(0.5)

    def _result(
        self,
        status: str,
        requested_target: Point3D,
        resolved_target: Optional[Point3D],
        profile: Optional[ScanProfile],
        message: str,
    ) -> NavigationResult:
        final_position = _safe_get_position(self.rc)
        return NavigationResult(
            status=status,
            final_position=final_position,
            requested_target=requested_target,
            resolved_target=resolved_target,
            profile=profile.name if profile else None,
            scan_count=self._scan_count,
            replans=self._replans,
            nearest_voxel_distance=self._nearest_voxel_distance,
            message=message,
        )

    def stop(self) -> None:
        if self.scanner:
            self.scanner.stop()
        self.rc.disable()
        self.rc.dampeners_on()
        self.rc.handbrake_on()

    def close(self) -> None:
        self.stop()
        from secontrol.common import close

        close(self.grid)


def nearest_point_distance(
    points: Sequence[Sequence[float]],
    origin: Optional[Point3D],
) -> float:
    if origin is None or not points:
        return float("inf")
    nearest = float("inf")
    ox, oy, oz = origin
    for point in points:
        if not _is_vec3(point):
            continue
        dx = float(point[0]) - ox
        dy = float(point[1]) - oy
        dz = float(point[2]) - oz
        nearest = min(nearest, math.sqrt(dx * dx + dy * dy + dz * dz))
    return nearest


def _safe_get_position(rc: RemoteControlDevice) -> Optional[Point3D]:
    try:
        rc.update()
        return get_world_position(rc)
    except Exception:
        return None


def _nearest_grid_contact(
    contacts: Sequence[Dict[str, Any]],
    ship_pos: Optional[Point3D],
) -> Tuple[float, Dict[int, Point3D]]:
    if ship_pos is None:
        return float("inf"), {}
    nearest = float("inf")
    positions: Dict[int, Point3D] = {}
    for contact in contacts:
        if not isinstance(contact, dict) or contact.get("type") != "grid":
            continue
        cpos = contact.get("pos") or contact.get("position")
        if not _is_vec3(cpos):
            continue
        pos = (float(cpos[0]), float(cpos[1]), float(cpos[2]))
        try:
            cid = int(contact.get("id", 0))
        except (TypeError, ValueError):
            cid = 0
        positions[cid] = pos
        nearest = min(nearest, _dist(pos, ship_pos))
    return nearest, positions


def _contact_aabb(contact: Dict[str, Any], pos: Point3D) -> Tuple[float, float, float, float, float, float]:
    raw = contact.get("aabb") or contact.get("boundingBox")
    if isinstance(raw, dict):
        bmin = raw.get("min")
        bmax = raw.get("max")
        if _is_vec3(bmin) and _is_vec3(bmax):
            return (
                float(bmin[0]),
                float(bmin[1]),
                float(bmin[2]),
                float(bmax[0]),
                float(bmax[1]),
                float(bmax[2]),
            )
    if isinstance(raw, (list, tuple)) and len(raw) >= 6:
        return tuple(float(raw[i]) for i in range(6))  # type: ignore[return-value]

    radius = 50.0
    return (
        pos[0] - radius,
        pos[1] - radius,
        pos[2] - radius,
        pos[0] + radius,
        pos[1] + radius,
        pos[2] + radius,
    )


def _point_toward(start: Point3D, target: Point3D, distance: float) -> Point3D:
    dx = target[0] - start[0]
    dy = target[1] - start[1]
    dz = target[2] - start[2]
    total = math.sqrt(dx * dx + dy * dy + dz * dz)
    if total <= 1e-6:
        return start
    step = min(max(0.0, distance), total)
    scale = step / total
    return (start[0] + dx * scale, start[1] + dy * scale, start[2] + dz * scale)


def _clamp_to_map_bounds(point: Point3D, radar_map: RawRadarMap, margin: float) -> Point3D:
    mins = radar_map.origin + margin
    maxs = radar_map.origin + np.asarray(radar_map.size, dtype=np.float64) * radar_map.cell_size - margin
    values = []
    for axis in range(3):
        lo = float(mins[axis])
        hi = float(maxs[axis])
        if lo > hi:
            lo, hi = hi, lo
        values.append(max(lo, min(hi, float(point[axis]))))
    return (values[0], values[1], values[2])


def _vec3(value: Sequence[float]) -> Point3D:
    if len(value) != 3:
        raise ValueError("Point must have exactly three coordinates")
    return (float(value[0]), float(value[1]), float(value[2]))


def _is_vec3(value: Any) -> bool:
    return isinstance(value, (list, tuple)) and len(value) >= 3


__all__ = [
    "SpaceNavigatorController",
    "ScanProfile",
    "SpeedZone",
    "NavigationResult",
    "BackgroundScanner",
    "NavState",
    "build_map_with_ships",
    "effective_clearance_radius",
    "estimate_ship_radius_from_blocks",
    "find_path_multiscale",
    "nearest_point_distance",
    "pick_waypoint_along_path",
    "resolve_nearest_safe_point",
    "COARSE_SCAN",
    "MEDIUM_SCAN",
    "FINE_SCAN",
]
