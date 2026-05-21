"""
Space Navigator Controller — Multi-scale obstacle-avoiding space navigation.

Design:
  1. COARSE scan (cell=100m, radius=5000m) for long-range route planning
  2. FINE scan (cell=10m, radius=200m) for close-range obstacle avoidance
  3. Ship/grid contacts added to occupancy grid as obstacles
  4. Adaptive speed: fast in open space, slow near obstacles
  5. Continuous background scanning with replanning

Main entry point: `SpaceNavigatorController.navigate_to(target)`
"""

from __future__ import annotations

import heapq
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from secontrol.controllers.radar_controller import RadarController
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.tools.navigation_tools import fly_to_point, get_world_position, _dist
from secontrol.tools.radar_navigation import (
    RawRadarMap,
    PassabilityProfile,
    PathFinder,
    RadarContact,
)

Point3D = Tuple[float, float, float]
Index3 = Tuple[int, int, int]


# ── Scan profiles ─────────────────────────────────────────────────────

@dataclass
class ScanProfile:
    """Defines a single scan resolution level."""
    name: str
    radius: float
    cell_size: float
    beam: int  # boundingBoxX = boundingBoxY = beam * cell_size

    @property
    def beam_meters(self) -> float:
        return self.beam * self.cell_size


# Coarse: large cells, huge radius — fast overview of the area
COARSE_SCAN = ScanProfile(name="COARSE", radius=5000.0, cell_size=100.0, beam=100)

# Medium: balanced scan for mid-range replanning
MEDIUM_SCAN = ScanProfile(name="MEDIUM", radius=1000.0, cell_size=20.0, beam=100)

# Fine: small cells, small radius — detailed close-range view
FINE_SCAN = ScanProfile(name="FINE", radius=300.0, cell_size=10.0, beam=60)


# ── Speed profiles ────────────────────────────────────────────────────

@dataclass
class SpeedZone:
    """Adaptive speed based on nearest obstacle distance."""
    max_speed: float = 50.0         # open space speed (m/s)
    far_speed: float = 30.0         # obstacle > far_threshold
    medium_speed: float = 15.0      # obstacle > medium_threshold
    near_speed: float = 8.0         # obstacle > near_threshold
    close_speed: float = 3.0        # obstacle < near_threshold

    far_threshold: float = 3000.0   # meters
    medium_threshold: float = 1000.0
    near_threshold: float = 300.0

    def speed_for_distance(self, nearest_obstacle_m: float) -> float:
        """Return appropriate speed based on distance to nearest obstacle."""
        if nearest_obstacle_m >= self.far_threshold:
            return self.max_speed
        elif nearest_obstacle_m >= self.medium_threshold:
            return self.far_speed
        elif nearest_obstacle_m >= self.near_threshold:
            return self.medium_speed
        else:
            return self.close_speed


# ── Navigation state ──────────────────────────────────────────────────

@dataclass
class NavState:
    """Current navigation state, shared between main loop and scanner thread."""
    position: Optional[Point3D] = None
    target: Optional[Point3D] = None
    distance_to_target: float = float("inf")
    nearest_obstacle: float = float("inf")
    nearest_ship: float = float("inf")
    current_speed: float = 0.0
    phase: str = "idle"  # idle, coarse_plan, flying, replanning, arrived
    replan_count: int = 0
    waypoints_flown: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


# ── Forward scanner (background thread) ───────────────────────────────

class BackgroundScanner:
    """
    Continuously scans voxels in the background during flight.
    Detects obstacles ahead and signals when replanning is needed.
    Also detects other ships/grids and tracks their positions.
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
        self.safety_distance = safety_distance

        self._nearest_obstacle: float = float("inf")
        self._nearest_ship: float = float("inf")
        self._solid_points: List[List[float]] = []
        self._contacts: List[Dict[str, Any]] = []
        self._needs_replan: bool = False
        self._ship_positions: Dict[int, Point3D] = {}  # ship_id -> position
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
            v = self._needs_replan
            self._needs_replan = False
            return v

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
            radius=self.scan_profile.radius,
            cell_size=self.scan_profile.cell_size,
            boundingBoxX=self.scan_profile.beam,
            boundingBoxY=self.scan_profile.beam,
            ore_only=False,
        )

        while self._running:
            try:
                solid, meta, contacts, ore_cells = ctrl.scan_voxels()

                ship_pos = _safe_get_position(self.rc)
                if not ship_pos:
                    time.sleep(0.3)
                    continue

                # Calculate nearest voxel distance
                nearest_voxel = float("inf")
                if solid:
                    for pt in solid:
                        dx = pt[0] - ship_pos[0]
                        dy = pt[1] - ship_pos[1]
                        dz = pt[2] - ship_pos[2]
                        d = math.sqrt(dx * dx + dy * dy + dz * dz)
                        if d < nearest_voxel:
                            nearest_voxel = d

                # Process contacts (other ships/grids)
                nearest_ship = float("inf")
                ship_positions = {}
                if contacts:
                    for c in contacts:
                        if not isinstance(c, dict):
                            continue
                        ctype = c.get("type", "")
                        cid = c.get("id", 0)
                        cpos = c.get("pos") or c.get("position")
                        if cpos and isinstance(cpos, (list, tuple)) and len(cpos) >= 3:
                            pos = (float(cpos[0]), float(cpos[1]), float(cpos[2]))
                            if ctype == "grid":
                                ship_positions[int(cid)] = pos
                                dx = pos[0] - ship_pos[0]
                                dy = pos[1] - ship_pos[1]
                                dz = pos[2] - ship_pos[2]
                                d = math.sqrt(dx * dx + dy * dy + dz * dz)
                                if d < nearest_ship:
                                    nearest_ship = d

                with self._lock:
                    self._nearest_obstacle = nearest_voxel
                    self._nearest_ship = nearest_ship
                    self._solid_points = solid or []
                    self._contacts = contacts or []
                    self._ship_positions = ship_positions
                    if nearest_voxel < self.safety_distance:
                        self._needs_replan = True

                # Log status
                parts = []
                if nearest_voxel < float("inf"):
                    parts.append(f"voxel={nearest_voxel:.0f}m")
                if nearest_ship < float("inf"):
                    parts.append(f"ship={nearest_ship:.0f}m")
                n_pts = len(solid) if solid else 0
                n_ships = len(ship_positions)
                status = ", ".join(parts) if parts else "clear"
                print(f"[SCAN] pts={n_pts}, ships={n_ships}, {status}")

            except Exception as e:
                print(f"[SCAN] error: {e}")

            time.sleep(0.3)


# ── Map builder with ship obstacles ──────────────────────────────────

def build_map_with_ships(
    solid: List[List[float]],
    metadata: Dict[str, Any],
    contacts: List[Dict[str, Any]],
    ship_radius: float = 30.0,
    own_position: Optional[Point3D] = None,
) -> Optional[RawRadarMap]:
    """
    Build RawRadarMap from scan results, including other ships as obstacles.

    Ship contacts are added as inflated AABB blocks in the occupancy grid.
    """
    if not solid and not contacts:
        return None

    origin = np.array(metadata["origin"], dtype=np.float64)
    cell_size = float(metadata["cellSize"])
    size = tuple(int(v) for v in metadata["size"])

    occ = np.zeros(size, dtype=np.bool_)

    # Add voxel obstacles
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

    # Add ship/grid contacts as obstacles
    ship_cells_added = 0
    ship_radius_cells = max(1, int(math.ceil(ship_radius / cell_size)))

    if contacts:
        for c in contacts:
            if not isinstance(c, dict):
                continue
            ctype = c.get("type", "")
            if ctype != "grid":
                continue

            cpos = c.get("pos") or c.get("position")
            if not cpos or not isinstance(cpos, (list, tuple)) or len(cpos) < 3:
                continue

            cx, cy, cz = float(cpos[0]), float(cpos[1]), float(cpos[2])

            # Skip our own grid (within 50m of our position)
            if own_position:
                dx = cx - own_position[0]
                dy = cy - own_position[1]
                dz = cz - own_position[2]
                if math.sqrt(dx * dx + dy * dy + dz * dz) < 50.0:
                    continue

            # Get bounding box from contact if available
            aabb = c.get("aabb") or c.get("boundingBox")
            if aabb and isinstance(aabb, (list, tuple)) and len(aabb) >= 6:
                minx, miny, minz, maxx, maxy, maxz = (
                    float(aabb[0]), float(aabb[1]), float(aabb[2]),
                    float(aabb[3]), float(aabb[4]), float(aabb[5]),
                )
            else:
                # Estimate ship size: assume 50m radius sphere around contact position
                ship_est_radius = 50.0
                minx = cx - ship_est_radius
                miny = cy - ship_est_radius
                minz = cz - ship_est_radius
                maxx = cx + ship_est_radius
                maxy = cy + ship_est_radius
                maxz = cz + ship_est_radius

            # Add inflation around ship
            inflation = ship_radius
            minx -= inflation
            miny -= inflation
            minz -= inflation
            maxx += inflation
            maxy += inflation
            maxz += inflation

            # Convert to grid indices
            ix0 = max(0, int(math.floor((minx - origin[0]) / cell_size)))
            iy0 = max(0, int(math.floor((miny - origin[1]) / cell_size)))
            iz0 = max(0, int(math.floor((minz - origin[2]) / cell_size)))
            ix1 = min(size[0] - 1, int(math.floor((maxx - origin[0]) / cell_size)))
            iy1 = min(size[1] - 1, int(math.floor((maxy - origin[1]) / cell_size)))
            iz1 = min(size[2] - 1, int(math.floor((maxz - origin[2]) / cell_size)))

            if ix1 >= ix0 and iy1 >= iy0 and iz1 >= iz0:
                occ[ix0:ix1 + 1, iy0:iy1 + 1, iz0:iz1 + 1] = True
                ship_cells_added += (ix1 - ix0 + 1) * (iy1 - iy0 + 1) * (iz1 - iz0 + 1)

    occupied = int(np.sum(occ))
    total = int(np.prod(size))
    print(
        f"[MAP] Grid {size[0]}x{size[1]}x{size[2]}, cell={cell_size}m, "
        f"occupied={occupied}/{total} ({100 * occupied / max(total, 1):.1f}%), "
        f"ship_cells={ship_cells_added}"
    )

    # Parse radar contacts for the map
    radar_contacts = []
    if contacts:
        for c in contacts:
            if not isinstance(c, dict):
                continue
            cpos = c.get("pos") or c.get("position")
            if cpos and isinstance(cpos, (list, tuple)) and len(cpos) >= 3:
                radar_contacts.append(
                    RadarContact(
                        type=str(c.get("type", "")),
                        id=int(c.get("id", 0)),
                        position=(float(cpos[0]), float(cpos[1]), float(cpos[2])),
                    )
                )

    return RawRadarMap(
        occ=occ,
        origin=origin,
        cell_size=cell_size,
        size=size,
        revision=metadata.get("rev"),
        timestamp_ms=metadata.get("tsMs"),
        contacts=tuple(radar_contacts),
        _inflation_cache={},
    )


# ── Multi-scale A* pathfinding ────────────────────────────────────────

def find_path_multiscale(
    radar_map: RawRadarMap,
    start: Point3D,
    goal: Point3D,
    ship_radius: float = 30.0,
) -> List[Point3D]:
    """Run A* pathfinding on the given map."""
    profile = PassabilityProfile(
        robot_radius=ship_radius,
        max_slope_degrees=90.0,     # no slope limit in space
        max_step_cells=5,
        allow_vertical_movement=True,
        allow_diagonal=True,
        is_ground_vehicle=False,
    )

    pathfinder = PathFinder(radar_map, profile)
    t0 = time.time()
    path = pathfinder.find_path_world(start, goal)
    dt = time.time() - t0

    if path:
        print(f"[PATH] {len(path)} waypoints in {dt:.2f}s")
    else:
        print(f"[PATH] No path in {dt:.2f}s")

    return path


# ── Waypoint selection ────────────────────────────────────────────────

def pick_waypoint_along_path(
    path: List[Point3D],
    ship_pos: Point3D,
    scan_radius: float,
    boundary_margin: float = 30.0,
    max_step_fraction: float = 0.4,
) -> Optional[Point3D]:
    """
    Pick the farthest safe waypoint along the A* path.

    Constraints:
    - Must stay within scan boundary (scan_radius - margin)
    - Must not exceed max_step from current position
    """
    if not path:
        return None

    max_step = scan_radius * max_step_fraction
    max_from_start = scan_radius - boundary_margin
    best = None

    for wp in path:
        d_from_ship = _dist(wp, ship_pos)

        # Too far from ship?
        if d_from_ship > max_step:
            if best is None:
                # Clamp this waypoint to max_step
                dx = wp[0] - ship_pos[0]
                dy = wp[1] - ship_pos[1]
                dz = wp[2] - ship_pos[2]
                d = math.sqrt(dx * dx + dy * dy + dz * dz)
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


# ── Main controller ───────────────────────────────────────────────────

class SpaceNavigatorController:
    """
    Multi-scale obstacle-avoiding space navigator.

    Usage:
        controller = SpaceNavigatorController(grid_name="skynet-baza0")
        controller.navigate_to((100000.0, 5000.0, -200000.0))
    """

    def __init__(
        self,
        grid_name: str,
        *,
        ship_radius: float = 30.0,
        speed_zone: Optional[SpeedZone] = None,
        coarse_scan: Optional[ScanProfile] = None,
        medium_scan: Optional[ScanProfile] = None,
        fine_scan: Optional[ScanProfile] = None,
        arrival_distance: float = 50.0,
        max_replans: int = 20,
        max_flight_time: float = 600.0,
        enable_background_scanner: bool = True,
        dry_run: bool = False,
    ):
        from secontrol.common import prepare_grid

        self.grid = prepare_grid(grid_name)
        self.ship_radius = ship_radius
        self.speed_zone = speed_zone or SpeedZone()
        self.coarse_scan = coarse_scan or COARSE_SCAN
        self.medium_scan = medium_scan or MEDIUM_SCAN
        self.fine_scan = fine_scan or FINE_SCAN
        self.arrival_distance = arrival_distance
        self.max_replans = max_replans
        self.max_flight_time = max_flight_time
        self.enable_background_scanner = enable_background_scanner
        self.dry_run = dry_run

        # Find devices
        radars = self.grid.find_devices_by_type(OreDetectorDevice)
        rcs = self.grid.find_devices_by_type(RemoteControlDevice)

        if not radars:
            raise RuntimeError("No OreDetector (radar) found on grid")
        if not rcs:
            raise RuntimeError("No RemoteControl found on grid")

        self.radar: OreDetectorDevice = radars[0]
        self.rc: RemoteControlDevice = rcs[0]

        # State
        self.state = NavState()
        self.scanner: Optional[BackgroundScanner] = None
        self._current_map: Optional[RawRadarMap] = None

    # ── Scan helpers ──────────────────────────────────────────────────

    def _do_scan(
        self,
        profile: ScanProfile,
        label: str = "SCAN",
        include_voxels: bool = True,
        include_contacts: bool = True,
    ) -> Optional[Tuple[List[List[float]], Dict[str, Any], List[Any], List[Any]]]:
        """Execute a radar scan with the given profile."""
        ctrl = RadarController(
            self.radar,
            radius=profile.radius,
            cell_size=profile.cell_size,
            boundingBoxX=profile.beam,
            boundingBoxY=profile.beam,
            ore_only=False,
        )

        beam_m = profile.beam * profile.cell_size
        print(
            f"[{label}] Scanning: radius={profile.radius:.0f}m, "
            f"cell={profile.cell_size:.0f}m, beam={beam_m:.0f}m..."
        )

        t0 = time.time()
        solid, meta, contacts, ore_cells = ctrl.scan_voxels()
        dt = time.time() - t0

        n = len(solid) if solid else 0
        nc = len(contacts) if contacts else 0
        print(f"[{label}] {n} voxels, {nc} contacts in {dt:.1f}s")

        return solid, meta, contacts, ore_cells

    def _build_map(
        self,
        scan_result: Tuple[List[List[float]], Dict[str, Any], List[Any], List[Any]],
    ) -> Optional[RawRadarMap]:
        """Build a RawRadarMap from scan results, including ships as obstacles."""
        solid, meta, contacts, ore_cells = scan_result

        ship_pos = _safe_get_position(self.rc)
        return build_map_with_ships(
            solid, meta, contacts,
            ship_radius=self.ship_radius,
            own_position=ship_pos,
        )

    # ── Speed control ─────────────────────────────────────────────────

    def _get_current_speed(self, nearest_obstacle: float) -> float:
        """Determine appropriate speed based on obstacle distance."""
        return self.speed_zone.speed_for_distance(nearest_obstacle)

    # ── Core navigation ───────────────────────────────────────────────

    def navigate_to(
        self,
        target: Point3D,
        *,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Optional[Point3D]:
        """
        Navigate to target with multi-scale scanning and obstacle avoidance.

        Algorithm:
        1. Get current position, calculate distance to target
        2. Choose scan profile based on distance
        3. Scan → build map with ships → A* pathfind
        4. Pick best waypoint along path
        5. Fly to waypoint with adaptive speed
        6. Rescan, replan if needed
        7. Repeat until arrived

        Returns final position or None if failed.
        """
        print("=" * 60)
        print("  Space Navigator — Multi-scale obstacle avoidance")
        print("=" * 60)
        print(f"Target: ({target[0]:.0f}, {target[1]:.0f}, {target[2]:.0f})")
        print(f"Ship radius: {self.ship_radius:.0f}m")
        print(f"Speeds: max={self.speed_zone.max_speed}, far={self.speed_zone.far_speed}, "
              f"medium={self.speed_zone.medium_speed}, close={self.speed_zone.close_speed}")
        print()

        # Enable autopilot
        self.rc.enable()
        self.rc.gyro_control_on()
        self.rc.thrusters_on()
        self.rc.dampeners_on()
        time.sleep(1)

        # Start background scanner
        if self.enable_background_scanner:
            self.scanner = BackgroundScanner(
                self.radar, self.rc,
                scan_profile=self.medium_scan,
                safety_distance=self.ship_radius * 3,
            )
            self.scanner.start()
            time.sleep(1)

        try:
            return self._navigate_loop(target, cancel_check)
        finally:
            if self.scanner:
                self.scanner.stop()

    def _navigate_loop(
        self,
        target: Point3D,
        cancel_check: Optional[Callable[[], bool]],
    ) -> Optional[Point3D]:
        """Main navigation loop."""
        replan_count = 0
        waypoints_flown = 0
        last_pos: Optional[Point3D] = None
        stuck_count = 0

        for step in range(200):  # max 200 steps
            # Check cancellation
            if cancel_check and cancel_check():
                print("[NAV] Cancelled by caller")
                return _safe_get_position(self.rc)

            # Get current position
            ship_pos = _safe_get_position(self.rc)
            if not ship_pos:
                time.sleep(0.5)
                continue

            dist_to_target = _dist(ship_pos, target)
            print(f"\n{'=' * 50}")
            print(f"STEP {step}  pos=({ship_pos[0]:.0f},{ship_pos[1]:.0f},{ship_pos[2]:.0f})  "
                  f"target_dist={dist_to_target:.0f}m")
            print(f"{'=' * 50}")

            # Arrived?
            if dist_to_target < self.arrival_distance:
                print(f"\n✅ ARRIVED at {dist_to_target:.0f}m!")
                return ship_pos

            # Stuck detection
            if last_pos and _dist(ship_pos, last_pos) < 5.0:
                stuck_count += 1
                if stuck_count > 5:
                    print("[NAV] ⚠️ Ship appears stuck, forcing replan...")
                    stuck_count = 0
            else:
                stuck_count = 0
            last_pos = ship_pos

            # ── Choose scan profile based on distance ──
            if dist_to_target > 5000.0:
                scan_profile = self.coarse_scan
            elif dist_to_target > 500.0:
                scan_profile = self.medium_scan
            else:
                scan_profile = self.fine_scan

            # ── Scan ──
            print(f"[NAV] Using {scan_profile.name} scan profile")
            scan_result = self._do_scan(scan_profile)

            if not scan_result or not scan_result[0]:
                print("[NAV] Scan failed, retrying...")
                time.sleep(2)
                continue

            # ── Build map with ship obstacles ──
            radar_map = self._build_map(scan_result)
            if not radar_map:
                print("[NAV] Failed to build map, retrying...")
                time.sleep(2)
                continue

            self._current_map = radar_map

            # ── Check if target is within scan bounds ──
            target_idx = radar_map.world_to_index(target)
            if target_idx is None:
                print(f"[NAV] Target outside {scan_profile.name} scan bounds")
                # Fly toward target using direct path with obstacle check
                wp = self._compute_direct_waypoint(ship_pos, target, scan_profile)
                if wp:
                    self._fly_to_waypoint(wp, ship_pos, scan_profile)
                else:
                    print("[NAV] Cannot compute waypoint, retrying...")
                    time.sleep(2)
                continue

            # ── A* pathfinding ──
            path = find_path_multiscale(
                radar_map, ship_pos, target,
                ship_radius=self.ship_radius,
            )

            if not path:
                print("[NAV] No A* path found, trying direct approach...")
                wp = self._compute_direct_waypoint(ship_pos, target, scan_profile)
                if wp:
                    self._fly_to_waypoint(wp, ship_pos, scan_profile)
                continue

            # ── Show path overview ──
            print(f"[PATH] Route ({len(path)} waypoints):")
            for i, p in enumerate(path[:5]):
                print(f"  [{i}] ({p[0]:.0f},{p[1]:.0f},{p[2]:.0f})")
            if len(path) > 5:
                print(f"  ... → ({path[-1][0]:.0f},{path[-1][1]:.0f},{path[-1][2]:.0f})")

            # ── Pick best waypoint ──
            wp = pick_waypoint_along_path(
                path, ship_pos,
                scan_radius=scan_profile.radius,
            )

            if wp is None:
                print("[NAV] No valid waypoint found")
                time.sleep(1)
                continue

            # ── Fly to waypoint ──
            self._fly_to_waypoint(wp, ship_pos, scan_profile)
            waypoints_flown += 1

            # ── Check for replan signal from background scanner ──
            if self.scanner and self.scanner.needs_replan:
                replan_count += 1
                if replan_count <= self.max_replans:
                    print(f"[REPLAN] Background scanner triggered replan #{replan_count}")
                else:
                    print(f"[REPLAN] Max replans ({self.max_replans}) reached, continuing")

        print("[NAV] Max steps reached")
        return _safe_get_position(self.rc)

    def _compute_direct_waypoint(
        self,
        ship_pos: Point3D,
        target: Point3D,
        scan_profile: ScanProfile,
    ) -> Optional[Point3D]:
        """Compute a direct waypoint toward target, respecting scan bounds."""
        dx = target[0] - ship_pos[0]
        dy = target[1] - ship_pos[1]
        dz = target[2] - ship_pos[2]
        d = math.sqrt(dx * dx + dy * dy + dz * dz)

        if d < 1e-3:
            return None

        max_step = scan_profile.radius * 0.4
        fly_dist = min(d * 0.5, max_step)

        # Check if background scanner sees obstacles ahead
        if self.scanner:
            nearest = self.scanner.nearest_obstacle
            if nearest < self.ship_radius * 3:
                # Slow down or stop
                fly_dist = min(fly_dist, max(nearest - self.ship_radius, 10.0))

        return (
            ship_pos[0] + dx / d * fly_dist,
            ship_pos[1] + dy / d * fly_dist,
            ship_pos[2] + dz / d * fly_dist,
        )

    def _fly_to_waypoint(
        self,
        wp: Point3D,
        ship_pos: Point3D,
        scan_profile: ScanProfile,
    ):
        """Fly to a single waypoint with adaptive speed and safety checks."""
        # Determine speed
        nearest = float("inf")
        if self.scanner:
            nearest = min(self.scanner.nearest_obstacle, self.scanner.nearest_ship)

        speed = self._get_current_speed(nearest)
        d_wp = _dist(ship_pos, wp)

        print(f"[FLY] → ({wp[0]:.0f},{wp[1]:.0f},{wp[2]:.0f}), "
              f"dist={d_wp:.0f}m, speed={speed:.0f}m/s")

        if self.dry_run:
            print("[DRY RUN] Skipping flight")
            time.sleep(1)
            return

        # Cancel check: stop if obstacle too close
        def cancel() -> bool:
            if self.scanner and self.scanner.nearest_obstacle < self.ship_radius:
                print("[FLY] ⚠️ Emergency stop — obstacle too close!")
                return True
            return False

        fly_to_point(
            self.rc,
            wp,
            waypoint_name=f"WP",
            speed_far=speed,
            speed_near=speed,
            arrival_distance=max(10.0, self.ship_radius),
            max_flight_time=max(30.0, d_wp / max(speed, 1.0) + 15),
            cancel_check=cancel,
        )

    # ── Cleanup ───────────────────────────────────────────────────────

    def stop(self):
        """Stop the ship and clean up."""
        if self.scanner:
            self.scanner.stop()
        self.rc.disable()
        self.rc.dampeners_on()
        self.rc.handbrake_on()

    def close(self):
        """Clean up all resources."""
        self.stop()
        from secontrol.common import close
        close(self.grid)


# ── Utility ───────────────────────────────────────────────────────────

def _safe_get_position(rc: RemoteControlDevice) -> Optional[Point3D]:
    """Get position, return None on failure."""
    try:
        rc.update()
        return get_world_position(rc)
    except Exception:
        return None


__all__ = [
    "SpaceNavigatorController",
    "ScanProfile",
    "SpeedZone",
    "BackgroundScanner",
    "NavState",
    "build_map_with_ships",
    "find_path_multiscale",
    "pick_waypoint_along_path",
    "COARSE_SCAN",
    "MEDIUM_SCAN",
    "FINE_SCAN",
]
