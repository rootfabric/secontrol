from typing import Optional, Tuple, List, Dict, Any
import time
import numpy as np
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.tools.navigation_tools import fly_to_point, get_world_position


class RadarController:
    """
    Controller for scanning and managing radar voxel data.
    Handles occupancy grid building and querying.
    """

    def __init__(
        self,
        radar: OreDetectorDevice,
        voxel_step: int = 1,
        cell_size: float = 10.0,
        fast_scan: bool = False,
        ore_only: bool = False,
        boundingBoxX: int = 500,
        boundingBoxY: int = 500,
        boundingBoxZ: int = 500,
        radius: float = 50.0,
        fullSolidScan = True,
        budget_ms_per_tick: Optional[float] = None,
        filter_no_stone: bool = True,
        telemetry_retries: int = 5,
        telemetry_retry_delay: float = 0.5
    ):
        self.radar: OreDetectorDevice = radar

        # Scan parameters
        self.scan_params = {
            "voxel_step": voxel_step,
            "cell_size": cell_size,
            "fast_scan": fast_scan,
            "ore_only": ore_only,
            "boundingBoxX": boundingBoxX,
            "boundingBoxY": boundingBoxY,
            "boundingBoxZ": boundingBoxZ,
            "radius": radius,
            "fullSolidScan":fullSolidScan
        }
        if budget_ms_per_tick is not None:
            self.scan_params["budget_ms_per_tick"] = budget_ms_per_tick

        # Map data
        self.occupancy_grid: Optional[np.ndarray] = None
        self.origin: Optional[Tuple[float, float, float]] = None
        self.cell_size: Optional[float] = None
        self.size: Optional[Tuple[int, int, int]] = None

        # Scan state
        self.last_scan_state: Optional[dict] = None
        self.filter_no_stone = filter_no_stone
        self.telemetry_retries = telemetry_retries
        self.telemetry_retry_delay = telemetry_retry_delay

    @staticmethod
    def _radar_marker(radar: Optional[Dict[str, Any]]) -> tuple[Any, Any, Any]:
        if not isinstance(radar, dict):
            return None, None, None
        raw = radar.get("raw")
        if not isinstance(raw, dict):
            raw = {}
        return raw.get("rev"), raw.get("tsMs"), radar.get("revision")

    def _latest_radar_snapshot(self) -> Optional[Dict[str, Any]]:
        tel = self.radar.telemetry or {}
        radar = tel.get("radar")
        if isinstance(radar, dict):
            return radar
        snapshot = self.radar.radar_snapshot()
        return snapshot if snapshot else None

    @staticmethod
    def _solid_points_from_raw(raw: Dict[str, Any]) -> List[List[float]]:
        solid_points = raw.get("solidPoints")
        if isinstance(solid_points, list):
            return solid_points

        solid = raw.get("solid")
        if not isinstance(solid, list) or not solid:
            return []

        size = raw.get("size")
        origin = raw.get("origin")
        cell_size = raw.get("cellSize")
        if not (
            isinstance(size, list)
            and len(size) >= 3
            and isinstance(origin, list)
            and len(origin) >= 3
            and cell_size is not None
        ):
            return []

        try:
            size_x, size_y, size_z = (int(size[0]), int(size[1]), int(size[2]))
            ox, oy, oz = (float(origin[0]), float(origin[1]), float(origin[2]))
            cell = float(cell_size)
        except (TypeError, ValueError):
            return []

        if size_x <= 0 or size_y <= 0 or size_z <= 0 or cell <= 0:
            return []

        points: List[List[float]] = []
        plane = size_y * size_z
        for value in solid:
            try:
                idx = int(value)
            except (TypeError, ValueError):
                continue
            if idx < 0:
                continue
            x = idx // plane
            yz = idx % plane
            y = yz // size_z
            z = yz % size_z
            if 0 <= x < size_x and 0 <= y < size_y and 0 <= z < size_z:
                points.append([
                    ox + (x + 0.5) * cell,
                    oy + (y + 0.5) * cell,
                    oz + (z + 0.5) * cell,
                ])
        return points

    def extract_solid(self, radar: Dict[str, Any]) -> tuple[List[List[float]], Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Extract solid points, metadata, contacts, and ore cells from radar data."""
        raw = radar.get("raw", {})
        if not isinstance(raw, dict):
            raw = {}
        if not raw:
            raw = radar

        solid = self._solid_points_from_raw(raw)
        if not solid and raw is not radar:
            solid = self._solid_points_from_raw(radar)

        metadata = {
            "size": raw.get("size", [100, 100, 100]),
            "cellSize": raw.get("cellSize", 1.0),
            "origin": raw.get("origin", [0.0, 0.0, 0.0]),
            "oreCellsTruncated": radar.get("oreCellsTruncated", 0),
            "rev": raw.get("rev", 0),
            "tsMs": raw.get("tsMs", 0),
        }

        contacts = radar.get("contacts", [])
        if not isinstance(contacts, list):
            contacts = []

        ore_cells = radar.get("oreCells", [])
        if not isinstance(ore_cells, list):
            ore_cells = []

        return solid, metadata, contacts, ore_cells

    def filter_valuable_ore_cells(self, ore_cells: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter ore cells to exclude Stone, keeping only valuable minerals."""
        valuable_ores = []
        for cell in ore_cells:
            material = cell.get("material") or cell.get("ore")
            if material != "Stone":
                valuable_ores.append(cell)
        return valuable_ores

    def set_scan_params(self, **kwargs):
        """Update scan parameters."""
        self.scan_params.update(kwargs)

    def scan_contacts(self):
        """Scan only contacts (grids and players), return contacts."""
        print("Scanning contacts...")

        seq = self.radar.scan(
            include_players=True,
            include_grids=True,
            include_voxels=False,
            **self.scan_params
        )
        print(f"Scan sent, seq={seq}")

        # Wait for completion
        last_progress = -1
        while True:
            time.sleep(0.1)
            self.radar.update()

            tel = self.radar.telemetry or {}
            scan = tel.get("scan", {})
            if isinstance(scan, dict):
                self.last_scan_state = scan
                in_progress = scan.get("inProgress", False)
                progress = scan.get("progressPercent", 0)
                processed = scan.get("processedTiles", 0)
                total = scan.get("totalTiles", 0)
                elapsed = scan.get("elapsedSeconds", 0)

                if in_progress and progress != last_progress:
                    print(f"[scan progress] {progress:.1f}% ({processed}/{total} tiles, {elapsed:.1f}s)")
                    last_progress = progress
                elif not in_progress:
                    print(f"[scan] Completed: {progress:.1f}% ({processed}/{total} tiles, {elapsed:.1f}s)")
                    break

        # Retry to get radar data after scan completion
        radar_data = None
        for attempt in range(self.telemetry_retries):
            self.radar.update()
            tel = self.radar.telemetry or {}
            radar_data = tel.get("radar")
            if radar_data:
                break
            time.sleep(self.telemetry_retry_delay)

        if not radar_data:
            print("No radar data received after retries.")
            return None

        contacts = radar_data.get("contacts", [])
        if not isinstance(contacts, list):
            contacts = []

        # Count grids and players
        grids = [c for c in contacts if c.get("type") == "grid"]
        players = [c for c in contacts if c.get("type") == "player"]
        print(f"Grids found: {len(grids)}, Players found: {len(players)}")

        return contacts

    def scan_voxels(self, filter_no_stone = None, max_wait_sec: float = 120.0, **scan_kwargs):
        """Scan voxels, process result and return solid, metadata, contacts.

        Args:
            max_wait_sec: Maximum seconds to wait for a complete scan (100%).
                          The scan may be interrupted by telemetry resets; this
                          timeout prevents an infinite wait.
        """
        print(f"Scanning voxels...")
        start_time = time.time()
        initial_radar = self._latest_radar_snapshot()
        initial_marker = self._radar_marker(initial_radar)

        # Send scan command
        seq = self.radar.scan(
            include_players=True,
            include_grids=True,
            include_voxels=True,
            **{**self.scan_params, **scan_kwargs}
        )
        print(f"Scan sent, seq={seq}")

        # Wait for scan completion
        last_progress = -1
        radar_data = None
        saw_scan_start = False
        last_active_scan = None
        while True:
            elapsed_total = time.time() - start_time
            if elapsed_total > max_wait_sec:
                print(f"[scan] Max wait time ({max_wait_sec:.0f}s) exceeded. Using best available data.")
                break
            if not self.radar.wait_for_telemetry(need_update=False):
                print("[scan] Timed out waiting for telemetry update.")
                break

            tel = self.radar.telemetry or {}
            scan = tel.get("scan", {})
            if isinstance(scan, dict):
                self.last_scan_state = scan
                in_progress = scan.get("inProgress", False)
                progress = scan.get("progressPercent", 0)
                processed = scan.get("processedTiles", 0)
                total = scan.get("totalTiles", 0)
                elapsed = scan.get("elapsedSeconds", 0)

                if in_progress and progress != last_progress:
                    saw_scan_start = True
                    last_active_scan = scan
                    print(f"[scan progress] {progress:.1f}% ({processed}/{total} tiles, {elapsed:.1f}s)")
                    last_progress = progress
                elif in_progress:
                    saw_scan_start = True
                    last_active_scan = scan
                elif saw_scan_start:
                    progress_val = float(progress or 0)
                    if total == 0 and isinstance(last_active_scan, dict):
                        progress_val = float(last_active_scan.get("progressPercent", progress) or 0)
                        processed = last_active_scan.get("processedTiles", processed)
                        total = last_active_scan.get("totalTiles", total)
                        elapsed = last_active_scan.get("elapsedSeconds", elapsed)

                    if progress_val >= 99.9:
                        print(f"[scan] Completed: {progress_val:.1f}% ({processed}/{total} tiles, {elapsed:.1f}s)")
                        break
                    else:
                        print(
                            f"[scan] Scan reset at {progress_val:.1f}% ({processed}/{total} tiles); "
                            "waiting for next scan cycle..."
                        )
                        saw_scan_start = False
                        last_active_scan = None
                        last_progress = -1
                        continue
                elif time.time() - start_time > 5.0:
                    print("[scan] Scan did not enter progress state within 5.0s.")
                    break

        end_time = time.time()
        scan_duration = end_time - start_time
        print(f"Total scan time: {scan_duration:.2f}s")

        # Retry to get radar data after scan completion. Telemetry can publish an
        # idle scan state before the new radar payload is visible, so avoid
        # returning a stale cached radar snapshot from before this scan.
        radar_data = None
        last_seen_radar = None
        for attempt in range(self.telemetry_retries):
            self.radar.wait_for_telemetry(
                timeout=self.telemetry_retry_delay,
                need_update=False,
            )
            candidate = self._latest_radar_snapshot()
            if isinstance(candidate, dict):
                last_seen_radar = candidate
            marker = self._radar_marker(candidate)
            if candidate and (initial_marker == (None, None, None) or marker != initial_marker):
                radar_data = candidate
                break
            if attempt == 0 and candidate:
                print(
                    "[scan] Radar payload has not advanced yet "
                    f"(marker={marker}); waiting for fresh result..."
                )
            if attempt >= 1:
                self.radar.update()

        if not radar_data:
            if last_seen_radar:
                radar_data = last_seen_radar
                print("[scan] Fresh radar payload was not observed; using latest available radar snapshot.")
            else:
                print("No radar data received after retries.")
                return None, None, None, None

        if (
            isinstance(last_active_scan, dict)
            and last_active_scan.get("totalTiles")
            and float(last_active_scan.get("progressPercent", 0) or 0) < 99.9
            and not radar_data.get("done")
        ):
            print(
                "[scan] Warning: scan stopped before reaching 100% "
                f"({last_active_scan.get('processedTiles', 0)}/"
                f"{last_active_scan.get('totalTiles', 0)} tiles)."
            )

        solid, metadata, contacts, ore_cells = self.extract_solid(radar_data)
        print(f"Received solid: {len(solid)} points, rev={metadata['rev']}, truncated={metadata['oreCellsTruncated']}")
        if not solid:
            raw = radar_data.get("raw", {}) if isinstance(radar_data, dict) else {}
            if not isinstance(raw, dict):
                raw = {}
            print(
                "[scan] Radar returned no solid voxels "
                f"(solidCellCount={radar_data.get('solidCellCount')}, "
                f"raw keys={sorted(raw.keys())})."
            )

        # Determine filter setting
        if filter_no_stone is None:
            filter_no_stone = self.filter_no_stone

        # Filter valuable ore cells (exclude Stone)
        if filter_no_stone:
            ore_cells = self.filter_valuable_ore_cells(ore_cells)

        # Count grids and players
        grids = [c for c in contacts if c.get("type") == "grid"]
        players = [c for c in contacts if c.get("type") == "player"]
        ore_label = "Valuable ores" if filter_no_stone else "Ores"
        print(f"Grids found: {len(grids)}, Players found: {len(players)}, {ore_label} found: {len(ore_cells)}")

        # Show ore data
        if ore_cells:
            print(f"{ore_label}:")
            for cell in ore_cells:
                material = cell.get("material") or cell.get("ore") or "Unknown"
                content = cell.get("content", "N/A")
                position = cell.get("position", "N/A")
                print(f"  {material}: content={content}, position={position}")

        # Build occupancy grid for compatibility
        if solid:
            origin = np.array(metadata["origin"], dtype=float)
            cell_sz = float(metadata["cellSize"])
            sz = metadata["size"]
            size_x, size_y, size_z = sz

            occ = np.zeros((size_x, size_y, size_z), dtype=bool)

            try:
                arr = np.asarray(solid, dtype=np.float64)
                if arr.ndim == 2 and arr.shape[1] == 3:
                    rel = (arr - origin.reshape(1, 3)) / cell_sz - 0.5
                    idx = np.rint(rel).astype(np.int64)
                    valid = (
                        (idx[:, 0] >= 0) & (idx[:, 0] < size_x) &
                        (idx[:, 1] >= 0) & (idx[:, 1] < size_y) &
                        (idx[:, 2] >= 0) & (idx[:, 2] < size_z)
                    )
                    idx = idx[valid]
                    if idx.size:
                        occ[idx[:, 0], idx[:, 1], idx[:, 2]] = True
            except Exception as e:
                print(f"Failed to rebuild occupancy: {e}")

            self.occupancy_grid = occ
            self.origin = tuple(origin)
            self.cell_size = cell_sz
            self.size = (size_x, size_y, size_z)

        return solid, metadata, contacts, ore_cells

    def get_surface_height(
        self,
        world_x: float,
        world_z: float,
        search_radius: int = 1,
    ) -> Optional[float]:
        """Get surface height (max solid voxel y) at world position (x,z).

        If there is no solid voxel directly under the requested column, the
        method searches neighbouring columns within ``search_radius`` cells and
        returns the highest surface it finds. This helps when the radar scan is
        sparse and some columns are empty despite nearby solid data.
        """
        if self.occupancy_grid is None or self.origin is None or self.cell_size is None or self.size is None:
            return None

        idx_x = int((world_x - self.origin[0]) / self.cell_size)
        idx_z = int((world_z - self.origin[2]) / self.cell_size)

        if not (0 <= idx_x < self.size[0] and 0 <= idx_z < self.size[2]):
            return None

        def _column_height(ix: int, iz: int) -> Optional[float]:
            for y in range(self.size[1] - 1, -1, -1):
                if self.occupancy_grid[ix, y, iz]:
                    return self.origin[1] + (y + 0.5) * self.cell_size
            return None

        direct_height = _column_height(idx_x, idx_z)
        if direct_height is not None:
            return direct_height

        if search_radius <= 0:
            return None

        max_height = None
        for dx in range(-search_radius, search_radius + 1):
            for dz in range(-search_radius, search_radius + 1):
                nx, nz = idx_x + dx, idx_z + dz
                if not (0 <= nx < self.size[0] and 0 <= nz < self.size[2]):
                    continue
                height = _column_height(nx, nz)
                if height is not None and (max_height is None or height > max_height):
                    max_height = height

        return max_height

    def apply_scan_to_occupancy(
            self,
            solid_points,
            scan_center=None,
            scan_radius=None,
    ):
        """
        Обновить occupancy_grid по результатам скана.

        1) Очищает регион скана (делает все клетки пустыми).
        2) Записывает новые solid-ячейки.

        solid_points – список точек (x, y, z) или dict'ов с координатами.
        scan_center  – центр скана в мировых координатах (если знаем).
        scan_radius  – радиус скана (если знаем).

        Если scan_center/scan_radius не заданы, берём bbox по solid_points.
        """
        if (
                self.occupancy_grid is None
                or self.origin is None
                or self.cell_size is None
                or self.size is None
        ):
            print("RadarController.apply_scan_to_occupancy: no grid metadata, skip update.")
            return

        if not solid_points:
            print("RadarController.apply_scan_to_occupancy: no solid points, clearing scanned region only.")

        ox, oy, oz = self.origin
        cell = self.cell_size
        size_x, size_y, size_z = self.size

        # --- 1. Определяем регион, который надо очистить ---

        if scan_center is not None and scan_radius is not None:
            cx, cy, cz = scan_center
            r = scan_radius

            min_x = cx - r
            max_x = cx + r
            min_y = cy - r
            max_y = cy + r
            min_z = cz - r
            max_z = cz + r
        else:
            # Берём AABB по фактическим solid-точкам
            xs = []
            ys = []
            zs = []
            for p in solid_points:
                if isinstance(p, dict):
                    x = p.get("x") or p.get("X")
                    y = p.get("y") or p.get("Y")
                    z = p.get("z") or p.get("Z")
                elif isinstance(p, (list, tuple)) and len(p) >= 3:
                    x, y, z = p[0], p[1], p[2]
                else:
                    continue

                try:
                    xs.append(float(x))
                    ys.append(float(y))
                    zs.append(float(z))
                except (TypeError, ValueError):
                    continue

            if not xs:
                # Нечего чистить/переписывать — просто выходим
                print("RadarController.apply_scan_to_occupancy: no valid solid coords.")
                return

            min_x = min(xs)
            max_x = max(xs)
            min_y = min(ys)
            max_y = max(ys)
            min_z = min(zs)
            max_z = max(zs)

            # Чуть расширим на 1 клетку, чтобы покрыть погрешности
            pad = cell
            min_x -= pad
            max_x += pad
            min_y -= pad
            max_y += pad
            min_z -= pad
            max_z += pad

        # Конвертация в индексы сетки
        ix0 = max(0, int((min_x - ox) / cell))
        ix1 = min(size_x - 1, int((max_x - ox) / cell))
        iy0 = max(0, int((min_y - oy) / cell))
        iy1 = min(size_y - 1, int((max_y - oy) / cell))
        iz0 = max(0, int((min_z - oz) / cell))
        iz1 = min(size_z - 1, int((max_z - oz) / cell))

        if ix0 > ix1 or iy0 > iy1 or iz0 > iz1:
            print("RadarController.apply_scan_to_occupancy: computed empty AABB, skip.")
            return

        # --- 2. Очищаем регион скана ---
        print(
            f"Clearing occupancy region: "
            f"x[{ix0}:{ix1}], y[{iy0}:{iy1}], z[{iz0}:{iz1}]"
        )
        self.occupancy_grid[ix0:ix1 + 1, iy0:iy1 + 1, iz0:iz1 + 1] = False

        # --- 3. Записываем новые solid-пункты ---
        written = 0
        for p in solid_points:
            if isinstance(p, dict):
                x = p.get("x") or p.get("X")
                y = p.get("y") or p.get("Y")
                z = p.get("z") or p.get("Z")
            elif isinstance(p, (list, tuple)) and len(p) >= 3:
                x, y, z = p[0], p[1], p[2]
            else:
                continue

            try:
                fx = float(x)
                fy = float(y)
                fz = float(z)
            except (TypeError, ValueError):
                continue

            ix = int((fx - ox) / cell)
            iy = int((fy - oy) / cell)
            iz = int((fz - oz) / cell)

            if 0 <= ix < size_x and 0 <= iy < size_y and 0 <= iz < size_z:
                self.occupancy_grid[ix, iy, iz] = True
                written += 1

        print(f"apply_scan_to_occupancy: written {written} solid cells.")
    def clear_mined_region(
        self,
        center: Tuple[float, float, float],
        radius: float,
    ):
        """
        Пометить регион как пустой (нет твёрдых вокселей) после добычи.

        center – мировые координаты центра выработки.
        radius – радиус в метрах.
        """
        if (
            self.occupancy_grid is None
            or self.origin is None
            or self.cell_size is None
            or self.size is None
        ):
            print("clear_mined_region: no occupancy grid, skipping.")
            return

        ox, oy, oz = self.origin
        cell = self.cell_size
        size_x, size_y, size_z = self.size

        cx, cy, cz = center
        r2 = radius * radius

        # Грубый bbox по миру
        min_x = cx - radius
        max_x = cx + radius
        min_y = cy - radius
        max_y = cy + radius
        min_z = cz - radius
        max_z = cz + radius

        ix0 = max(0, int((min_x - ox) / cell))
        ix1 = min(size_x - 1, int((max_x - ox) / cell))
        iy0 = max(0, int((min_y - oy) / cell))
        iy1 = min(size_y - 1, int((max_y - oy) / cell))
        iz0 = max(0, int((min_z - oz) / cell))
        iz1 = min(size_z - 1, int((max_z - oz) / cell))

        cleared = 0
        for ix in range(ix0, ix1 + 1):
            wx = ox + (ix + 0.5) * cell
            dx = wx - cx
            dx2 = dx * dx

            for iy in range(iy0, iy1 + 1):
                wy = oy + (iy + 0.5) * cell
                dy = wy - cy
                dy2 = dy * dy

                for iz in range(iz0, iz1 + 1):
                    wz = oz + (iz + 0.5) * cell
                    dz = wz - cz
                    dz2 = dz * dz

                    if dx2 + dy2 + dz2 <= r2:
                        if self.occupancy_grid[ix, iy, iz]:
                            self.occupancy_grid[ix, iy, iz] = False
                            cleared += 1

        print(
            f"clear_mined_region: cleared {cleared} cells "
            f"around ({cx:.2f}, {cy:.2f}, {cz:.2f}) with radius {radius:.2f}m."
        )

        # Если у тебя есть отдельная структура для ore_cells с индексами – тут же можно подчистить её.
