from __future__ import annotations
import math
from typing import Tuple, List, Optional, Dict, Any

from secontrol.common import prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.controllers.shared_map_controller import SharedMapController


def _get_pos(dev) -> Optional[Tuple[float, float, float]]:
    tel = dev.telemetry or {}
    pos = tel.get("worldPosition") or tel.get("position")
    if not pos:
        return None
    return (pos.get("x", 0.0), pos.get("y", 0.0), pos.get("z", 0.0))


def _fly_to(
    remote: RemoteControlDevice,
    target: Tuple[float, float, float],
    name: str,
    speed_far: float = 10.0,
    speed_near: float = 5.0,
) -> None:
    remote.update()
    current = _get_pos(remote)
    distance = None
    if current:
        dx = target[0] - current[0]
        dy = target[1] - current[1]
        dz = target[2] - current[2]
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)

    speed = speed_far if distance is None or distance > 30.0 else speed_near
    gps = f"GPS:{name}:{target[0]:.2f}:{target[1]:.2f}:{target[2]:.2f}:"

    print(
        f"Sending RC to {name}: target=({target[0]:.2f}, {target[1]:.2f}, {target[2]:.2f}), "
        f"distance={distance:.2f}m" if distance is not None else "distance=unknown",
    )

    remote.set_mode("oneway")
    remote.set_collision_avoidance(False)
    remote.goto(gps, speed=speed, gps_name=name, dock=False)


class SurfaceFlightController:
    """
    Контроллер полёта над поверхностью по воксельной карте радара.

    Логика:
    - сначала используем уже имеющуюся карту (occupancy_grid);
    - потом пробуем подгрузить карту из Redis (SharedMapController);
    - если всё ещё нет поверхности — делаем реальные сканы радара
      с увеличением radius / boundingBoxY, пока не появятся воксели
      под нужной колонкой.
    """

    def __init__(
        self,
        grid_name: str,
        scan_radius: float = 100.0,
        boundingBoxY: float = 100.0,
        **scan_kwargs: Any,
    ) -> None:
        self.grid = prepare_grid(grid_name)

        radars = self.grid.find_devices_by_type(OreDetectorDevice)
        rcs = self.grid.find_devices_by_type(RemoteControlDevice)

        if not radars:
            raise RuntimeError("No OreDetector (radar) found on grid.")
        if not rcs:
            raise RuntimeError("No RemoteControl found on grid.")

        self.radar: OreDetectorDevice = radars[0]
        self.rc: RemoteControlDevice = rcs[0]

        self.default_scan_radius = float(scan_radius)
        self.default_boundingBoxY = float(boundingBoxY)

        self.radar_controller = RadarController(
            self.radar,
            radius=scan_radius,
            boundingBoxY=boundingBoxY,
            **scan_kwargs,
        )

        self.shared_map_controller = SharedMapController(owner_id=self.grid.owner_id)
        self.visited_points: List[Tuple[float, float, float]] = []

        start_pos = _get_pos(self.rc)
        if start_pos:
            try:
                print(
                    "SurfaceFlightController: initial map load from Redis "
                    f"around position ({start_pos[0]:.2f}, {start_pos[1]:.2f}, {start_pos[2]:.2f})"
                )
                self.load_map_region_from_redis(center=start_pos, radius=self.default_scan_radius * 2.0)
            except Exception as e:
                print(f"SurfaceFlightController: failed to load initial map from Redis: {e}")

    # ------------------------------------------------------------------ #
    # Low-level helpers                                                  #
    # ------------------------------------------------------------------ #

    def scan_voxels(self, persist_to_shared_map: bool = True):
        """
        Выполнить скан радара.

        Если persist_to_shared_map=True (по умолчанию), результат
        сразу попадает в SharedMapController / Redis и в локальный
        occupancy_grid радара.
        """
        if persist_to_shared_map and self.shared_map_controller is not None:
            solid, metadata, contacts, ore_cells = self.shared_map_controller.ingest_radar_scan(
                self.radar_controller,
                persist_metadata=True,
                save=True,
            )
        else:
            solid, metadata, contacts, ore_cells = self.radar_controller.scan_voxels()

        return solid, metadata, contacts, ore_cells

    def _get_down_vector(self) -> Tuple[float, float, float]:
        gravity_vector = self.rc.telemetry.get("gravitationalVector") if self.rc.telemetry else None
        if gravity_vector:
            gx = gravity_vector.get("x", 0.0)
            gy = gravity_vector.get("y", 0.0)
            gz = gravity_vector.get("z", 0.0)
            length = math.sqrt(gx * gx + gy * gy + gz * gz)
            if length:
                return (gx / length, gy / length, gz / length)
        return (0.0, -1.0, 0.0)

    def _project_forward_to_horizontal(
        self,
        forward: Tuple[float, float, float],
        down: Tuple[float, float, float],
    ) -> Tuple[float, float, float]:
        dot_fg = forward[0] * down[0] + forward[1] * down[1] + forward[2] * down[2]
        horizontal_forward = (
            forward[0] - dot_fg * down[0],
            forward[1] - dot_fg * down[1],
            forward[2] - dot_fg * down[2],
        )

        length = math.sqrt(
            horizontal_forward[0] ** 2
            + horizontal_forward[1] ** 2
            + horizontal_forward[2] ** 2
        )
        if length == 0.0:
            print("Cannot compute horizontal forward vector, using original forward.")
            length = math.sqrt(forward[0] ** 2 + forward[1] ** 2 + forward[2] ** 2) or 1.0
            return (
                forward[0] / length,
                forward[1] / length,
                forward[2] / length,
            )

        return (
            horizontal_forward[0] / length,
            horizontal_forward[1] / length,
            horizontal_forward[2] / length,
        )

    def _sample_surface_along_path(
        self,
        start: Tuple[float, float, float],
        direction: Tuple[float, float, float],
        distance: float,
        step: float,
    ) -> Tuple[float, float]:
        max_surface_y = None
        last_surface_y = None

        steps = max(1, int(distance / max(step, 1e-3)))
        print(f"Sampling {steps} points along path, distance={distance:.2f}, step={step:.2f}")

        for i in range(1, steps + 1):
            t = min(distance, i * step)
            sample = (
                start[0] + direction[0] * t,
                start[1] + direction[1] * t,
                start[2] + direction[2] * t,
            )

            print(f"  Sampling at ({sample[0]:.2f}, {sample[1]:.2f}, {sample[2]:.2f})")
            surface_y = self.radar_controller.get_surface_height(sample[0], sample[2])

            if surface_y is None:
                if (
                    self.radar_controller.occupancy_grid is None
                    or self.radar_controller.origin is None
                    or self.radar_controller.cell_size is None
                    or self.radar_controller.size is None
                ):
                    print("    No occupancy grid data available")
                else:
                    idx_x = int((sample[0] - self.radar_controller.origin[0]) / self.radar_controller.cell_size)
                    idx_z = int((sample[2] - self.radar_controller.origin[2]) / self.radar_controller.cell_size)
                    in_bounds = (
                        0 <= idx_x < self.radar_controller.size[0]
                        and 0 <= idx_z < self.radar_controller.size[2]
                    )
                    if not in_bounds:
                        print(
                            f"    Out of bounds: idx_x={idx_x}, idx_z={idx_z}, "
                            f"grid_size=({self.radar_controller.size[0]}, {self.radar_controller.size[2]})"
                        )
                    else:
                        has_solid = False
                        for y in range(self.radar_controller.size[1] - 1, -1, -1):
                            if self.radar_controller.occupancy_grid[idx_x, y, idx_z]:
                                has_solid = True
                                break
                        if not has_solid:
                            print(f"    No solid voxels in column idx_x={idx_x}, idx_z={idx_z}")
                        else:
                            print("    Unexpected None despite solid voxels in column")
                continue

            print(f"    Surface height: {surface_y:.2f}")
            last_surface_y = surface_y
            if max_surface_y is None or surface_y > max_surface_y:
                max_surface_y = surface_y

        return max_surface_y if max_surface_y is not None else last_surface_y, last_surface_y

    def _find_surface_point_along_gravity(
        self,
        position: Tuple[float, float, float],
        down: Tuple[float, float, float],
        max_distance: float,
        step: float,
    ) -> Optional[Tuple[float, float, float]]:
        if (
            self.radar_controller.occupancy_grid is None
            or self.radar_controller.origin is None
            or self.radar_controller.cell_size is None
            or self.radar_controller.size is None
        ):
            print("No voxel grid to trace against.")
            return None

        origin = self.radar_controller.origin
        cell_size = self.radar_controller.cell_size
        size_x, size_y, size_z = self.radar_controller.size

        traveled = 0.0
        while traveled <= max_distance:
            sample = (
                position[0] + down[0] * traveled,
                position[1] + down[1] * traveled,
                position[2] + down[2] * traveled,
            )

            idx_x = int((sample[0] - origin[0]) / cell_size)
            idx_y = int((sample[1] - origin[1]) / cell_size)
            idx_z = int((sample[2] - origin[2]) / cell_size)

            if 0 <= idx_x < size_x and 0 <= idx_y < size_y and 0 <= idx_z < size_z:
                if self.radar_controller.occupancy_grid[idx_x, idx_y, idx_z]:
                    return (
                        origin[0] + (idx_x + 0.5) * cell_size,
                        origin[1] + (idx_y + 0.5) * cell_size,
                        origin[2] + (idx_z + 0.5) * cell_size,
                    )

            traveled += step

        return None

    # ------------------------------------------------------------------ #
    # Высота над поверхностью                                           #
    # ------------------------------------------------------------------ #

    def calculate_surface_point_at_altitude(
        self,
        position: Tuple[float, float, float],
        altitude: float,
    ) -> Tuple[float, float, float]:
        """
        Calculate a point at the specified altitude above the surface for given coordinates.

        Новая логика:
        1. ВСЕГДА сначала ищем поверхность трассировкой вдоль гравитации (ray-march).
        2. Если не нашли — подгружаем карту из Redis вокруг точки и пробуем ещё раз.
        3. Если всё ещё нет — делаем несколько активных сканов с ростом radius/boundingBoxY,
           каждый раз заново пробуем трассировку вдоль гравитации.
        4. Если поверхность найдена — целевая точка = surface_point + up * altitude.
        5. Если не нашли вообще ничего — просто уходим вверх по гравитации от исходной точки.
        """

        px, py, pz = position

        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        surface_point: Optional[Tuple[float, float, float]] = None
        surface_source = "none"

        def _trace_surface_along_gravity() -> Optional[Tuple[float, float, float]]:
            """Основной способ: трассировка вдоль гравитации от заданной точки."""
            grid = getattr(self.radar_controller, "occupancy_grid", None)
            origin = getattr(self.radar_controller, "origin", None)
            cell_size = getattr(self.radar_controller, "cell_size", None)
            size = getattr(self.radar_controller, "size", None)

            if grid is None or origin is None or cell_size is None or size is None:
                return None

            size_x, size_y, size_z = size
            cell_size_local = cell_size or 5.0

            # Максимальное расстояние трассировки — по высоте текущей сетки
            max_trace = cell_size_local * size_y
            step = cell_size_local

            return self._find_surface_point_along_gravity(
                position,
                down,
                max_distance=max_trace,
                step=step,
            )

        # 1) Пробуем найти поверхность по уже существующей сетке (только трассировка вдоль гравитации)
        surface_point = _trace_surface_along_gravity()
        if surface_point is not None:
            surface_source = "grid_gravity"

        # 2) Если не нашли — пробуем подгрузить карту из Redis вокруг точки
        if surface_point is None:
            print(
                f"calculate_surface_point_at_altitude: поверхности под точкой "
                f"({px:.2f}, {py:.2f}, {pz:.2f}) нет в текущей сетке, "
                f"пробую загрузить карту из Redis..."
            )
            try:
                self.load_map_region_from_redis(center=position, radius=self.default_scan_radius * 2.0)
            except Exception as e:
                print(f"Ошибка при загрузке карты из Redis: {e}")

            surface_point = _trace_surface_along_gravity()
            if surface_point is not None:
                surface_source = "redis_gravity"

        # 3) Если всё ещё нет поверхности — делаем несколько активных сканов с ростом радиуса
        max_scan_attempts = 3
        scan_attempt = 0

        while surface_point is None and scan_attempt < max_scan_attempts:
            current_radius = float(self.radar_controller.scan_params.get("radius", self.default_scan_radius))
            current_bbY = float(self.radar_controller.scan_params.get("boundingBoxY", self.default_boundingBoxY))

            max_allowed_radius = 800.0
            max_allowed_bbY = 800.0

            if scan_attempt == 0:
                # Первый скан — гарантируем хотя бы дефолтные значения
                new_radius = min(max(current_radius, self.default_scan_radius), max_allowed_radius)
                new_bbY = min(max(current_bbY, self.default_boundingBoxY), max_allowed_bbY)
            else:
                # Последующие — увеличиваем радиус и высоту
                new_radius = min(current_radius * 1.5, max_allowed_radius)
                new_bbY = min(current_bbY * 1.5, max_allowed_bbY)

            print(
                f"calculate_surface_point_at_altitude: поверхность под точкой "
                f"({px:.2f}, {py:.2f}, {pz:.2f}) не найдена, "
                f"[SCAN_ATTEMPT {scan_attempt + 1}/{max_scan_attempts}] "
                f"radius {current_radius:.1f} → {new_radius:.1f}, "
                f"boundingBoxY {current_bbY:.1f} → {new_bbY:.1f}"
            )

            self.radar_controller.set_scan_params(radius=new_radius, boundingBoxY=new_bbY)
            # ВАЖНО: новый скан сразу же сохраняем в SharedMap / Redis
            self.scan_voxels()

            surface_point = _trace_surface_along_gravity()
            if surface_point is not None:
                surface_source = f"scan_gravity#{scan_attempt + 1}"
                break

            scan_attempt += 1

        # 4) Если поверхность так и не найдена — но в сетке есть твёрдые воксели,
        #    просто логируем, что ситуация странная.
        grid = getattr(self.radar_controller, "occupancy_grid", None)
        if surface_point is None and grid is not None:
            try:
                has_any_solids = bool(grid.any())
            except Exception:
                has_any_solids = True

            if has_any_solids:
                print(
                    "calculate_surface_point_at_altitude: после всех попыток трассировки "
                    "поверхность не найдена, хотя в сетке есть твёрдые воксели. "
                    "Возможна геометрия вне зоны трассировки."
                )

        # 5) Если поверхность найдена — выставляем точку на altitude метров ВДОЛЬ up
        if surface_point is not None:
            sx, sy, sz = surface_point

            target_point = (
                sx + up[0] * altitude,
                sy + up[1] * altitude,
                sz + up[2] * altitude,
            )

            # Высота по проекции для проверки/логов
            alt_vec = (
                target_point[0] - sx,
                target_point[1] - sy,
                target_point[2] - sz,
            )
            altitude_proj = (
                alt_vec[0] * up[0]
                + alt_vec[1] * up[1]
                + alt_vec[2] * up[2]
            )

            print(
                f"Calculated point at altitude (source={surface_source}): "
                f"position=({px:.2f}, {py:.2f}, {pz:.2f}), "
                f"surface_point=({sx:.2f}, {sy:.2f}, {sz:.2f}), "
                f"requested_altitude={altitude:.2f}, "
                f"altitude_along_up≈{altitude_proj:.2f}, "
                f"target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
            )

            # Откатываем параметры радара к дефолтным, если их расширяли
            current_radius = float(self.radar_controller.scan_params.get("radius", self.default_scan_radius))
            current_bbY = float(self.radar_controller.scan_params.get("boundingBoxY", self.default_boundingBoxY))

            if (
                abs(current_radius - self.default_scan_radius) > 1e-3
                or abs(current_bbY - self.default_boundingBoxY) > 1e-3
            ):
                print(
                    f"Сканирование / поиск поверхности успешны, откатываю параметры радара к умолчанию: "
                    f"radius={self.default_scan_radius:.1f}, "
                    f"boundingBoxY={self.default_boundingBoxY:.1f}"
                )
                self.radar_controller.set_scan_params(
                    radius=self.default_scan_radius,
                    boundingBoxY=self.default_boundingBoxY,
                )

            return target_point

        # 6) Полный fallback: поверхности вообще не нашли — уходим вверх по гравитации от ИСХОДНОЙ точки
        safe_up = max(altitude, 20.0)
        target_point = (
            px + up[0] * safe_up,
            py + up[1] * safe_up,
            pz + up[2] * safe_up,
        )
        print(
            f"[NO_SURFACE] Поверхность под точкой ({px:.2f}, {py:.2f}, {pz:.2f}) "
            f"не найдена даже после Redis и нескольких сканов, "
            f"смещаюсь на {safe_up:.1f}м вверх по гравитации: "
            f"target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
        )
        return target_point


    # ------------------------------------------------------------------ #
    # Движение относительно поверхности                                  #
    # ------------------------------------------------------------------ #

    def lift_drone_to_altitude(
        self,
        altitude: float,
        trace_step: Optional[float] = None,
        trace_distance: Optional[float] = None,
    ) -> None:
        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        if self.radar_controller.occupancy_grid is None:
            print("No radar occupancy grid, performing scan...")
            self.scan_voxels()

        cell_size = self.radar_controller.cell_size or 5.0
        max_trace = trace_distance or cell_size * (
            self.radar_controller.size[1] if self.radar_controller.size else 50
        )
        step = trace_step or cell_size

        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        surface_point = self._find_surface_point_along_gravity(pos, down, max_trace, step)
        if surface_point is None:
            surface_height = self.radar_controller.get_surface_height(pos[0], pos[2])
            if surface_height is not None:
                surface_point = (pos[0], surface_height, pos[2])
                print("Surface found via vertical lookup.")
            else:
                print("Surface not found; moving along up vector from current position.")
                surface_point = pos

        target_point = (
            surface_point[0] + up[0] * altitude,
            surface_point[1] + up[1] * altitude,
            surface_point[2] + up[2] * altitude,
        )

        print(
            f"Lifting to altitude: surface={surface_point}, "
            f"target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
        )

        self.visited_points.append(pos)
        self.grid.create_gps_marker("LiftTarget", coordinates=target_point)
        _fly_to(self.rc, target_point, "LiftToAltitude", speed_far=10.0, speed_near=5.0)

        new_pos = _get_pos(self.rc)
        if new_pos:
            self.visited_points.append(new_pos)

    def fly_forward_to_altitude(self, distance: float, altitude: float) -> None:
        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Forward vector: {forward}")

        forward_point = (
            pos[0] + forward[0] * distance,
            pos[1] + forward[1] * distance,
            pos[2] + forward[2] * distance,
        )
        print(
            "Forward point: "
            f"({forward_point[0]:.2f}, {forward_point[1]:.2f}, {forward_point[2]:.2f})"
        )

        target_point = self.calculate_surface_point_at_altitude(forward_point, altitude)

        print(
            "Flying to target: "
            f"({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
        )

        self.grid.create_gps_marker(
            f"ForwardAlt{distance:.0f}m_{altitude:.0f}m",
            coordinates=target_point,
        )
        _fly_to(
            self.rc,
            target_point,
            f"FlyForwardAlt{distance:.0f}m_{altitude:.0f}m",
            speed_far=10.0,
            speed_near=5.0,
        )

        new_pos = _get_pos(self.rc)
        if new_pos:
            self.visited_points.append(new_pos)

        print("Flight to forward altitude complete.")

    def fly_forward_over_surface(self, distance: float, altitude: float) -> None:
        print(f"Flying forward {distance}m at {altitude}m above surface.")

        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Forward vector: {forward}")

        target_point = self._compute_target_over_surface(pos, forward, distance, altitude)
        self.grid.create_gps_marker(f"Target{distance:.0f}m", coordinates=target_point)

        pos2 = _get_pos(self.rc)
        if pos2:
            self.visited_points.append(pos2)

        print(f"Flight complete. Visited points: {len(self.visited_points)}")

    def _compute_target_over_surface(
        self,
        pos: Tuple[float, float, float],
        forward: Tuple[float, float, float],
        distance: float,
        altitude: float,
    ) -> Tuple[float, float, float]:
        down = self._get_down_vector()
        horiz_dir = self._project_forward_to_horizontal(forward, down)

        target_base = (
            pos[0] + horiz_dir[0] * distance,
            pos[1] + horiz_dir[1] * distance,
            pos[2] + horiz_dir[2] * distance,
        )

        if self.radar_controller.occupancy_grid is None:
            print("Occupancy grid is None, no surface data available.")
        else:
            print(
                "Occupancy grid origin: "
                f"{self.radar_controller.origin}, "
                f"size: {self.radar_controller.size}, "
                f"cell_size: {self.radar_controller.cell_size}"
            )

        cell_step = self.radar_controller.cell_size or 5.0
        max_surf, last_surf = self._sample_surface_along_path(
            pos,
            horiz_dir,
            distance,
            step=max(cell_step, 5.0),
        )

        if max_surf is not None:
            surface_y = max_surf
            target_y = surface_y + altitude
            print(
                "Computed target above surface:",
                f"base={target_base}",
                f"surface_y(max)={surface_y:.2f}",
                f"target_y={target_y:.2f}",
            )
        elif last_surf is not None:
            target_y = last_surf + altitude
            print(
                "Surface sampled only near end of path, using last point:",
                f"base={target_base}",
                f"surface_y(last)={last_surf:.2f}",
                f"target_y={target_y:.2f}",
            )
        else:
            target_y = pos[1]
            print(
                "Surface not found along path, keeping current altitude:",
                f"base={target_base}",
                f"target_y={target_y:.2f}",
            )

        return (target_base[0], target_y, target_base[2])

    # ------------------------------------------------------------------ #
    # Сервисные методы / работа с картой                                #
    # ------------------------------------------------------------------ #

    def get_visited_points(self) -> List[Tuple[float, float, float]]:
        return self.visited_points.copy()

    def load_map_region_from_redis(
        self,
        center: Optional[Tuple[float, float, float]] = None,
        radius: float = 1500.0,
    ):
        if center is None:
            pos = _get_pos(self.rc)
            if not pos:
                print("load_map_region_from_redis: cannot get current RC position.")
                return None, None, None, None, None
            center = pos

        cx, cy, cz = center
        print(
            "load_map_region_from_redis: "
            f"center=({cx:.2f}, {cy:.2f}, {cz:.2f}), radius={radius:.1f}m"
        )

        data = self.shared_map_controller.load()

        solid = data.voxels
        ore_cells = [
            {
                "material": ore.material,
                "position": list(ore.position),
                "content": ore.content,
            }
            for ore in data.ores
        ]
        visited = data.visited

        cell_size = 10.0
        size_x = int(2 * radius / cell_size) + 2
        size_y = 100
        size_z = int(2 * radius / cell_size) + 2

        origin = [
            center[0] - radius,
            center[1] - radius,
            center[2] - radius,
        ]

        metadata = {
            "size": [size_x, size_y, size_z],
            "cellSize": cell_size,
            "origin": origin,
            "oreCellsTruncated": 0,
            "rev": 0,
            "tsMs": 0,
        }
        contacts: List[Dict[str, Any]] = []

        try:
            import numpy as np

            self.radar_controller.origin = (origin[0], origin[1], origin[2])
            self.radar_controller.cell_size = cell_size
            self.radar_controller.size = (size_x, size_y, size_z)

            self.radar_controller.occupancy_grid = np.zeros(
                (size_x, size_y, size_z), dtype=bool
            )

            if solid:
                print(
                    "load_map_region_from_redis: applying "
                    f"{len(solid)} voxels into occupancy grid..."
                )
                self.radar_controller.apply_scan_to_occupancy(
                    solid_points=solid,
                    scan_center=center,
                    scan_radius=radius,
                )
            else:
                print(
                    "load_map_region_from_redis: no solid voxels loaded, "
                    "occupancy grid is empty for this region."
                )

        except Exception as e:
            print(f"load_map_region_from_redis: failed to build occupancy grid: {e}")

        self.radar_controller.ore_cells = ore_cells

        print(
            "load_map_region_from_redis: loaded "
            f"{len(solid)} voxels, {len(ore_cells)} ore cells, "
            f"{len(visited)} visited points."
        )

        return solid, metadata, contacts, ore_cells, visited



    def measure_altitude_to_surface(
        self,
        position: Optional[Tuple[float, float, float]] = None,
        trace_distance: Optional[float] = None,
        trace_step: Optional[float] = None,
    ) -> Optional[float]:
        """
        Измерить высоту над поверхностью для заданной точки.

        :param position: мировая точка (x, y, z). Если None — берём текущую позицию RC.
        :param trace_distance: максимальная дистанция трассировки вдоль гравитации (опционально).
        :param trace_step: шаг трассировки (опционально).
        :return: высота над поверхностью по оси Y (float) или None, если поверхность не найдена.
        """

        # 1) Берём позицию
        if position is None:
            pos = _get_pos(self.rc)
            if not pos:
                print("measure_altitude_to_surface: cannot get current RC position.")
                return None
        else:
            pos = position

        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])

        # 2) Вектор гравитации / up
        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        # 3) Проверяем, что есть воксельная сетка, при необходимости загружаем / сканируем
        if (
            self.radar_controller.occupancy_grid is None
            or self.radar_controller.origin is None
            or self.radar_controller.size is None
        ):
            print(
                "measure_altitude_to_surface: no occupancy grid, "
                "trying to load map from Redis around position..."
            )
            try:
                self.load_map_region_from_redis(
                    center=pos,
                    radius=self.default_scan_radius * 2.0,
                )
            except Exception as e:
                print(
                    "measure_altitude_to_surface: failed to load map from Redis: "
                    f"{e}"
                )

            if (
                self.radar_controller.occupancy_grid is None
                or self.radar_controller.origin is None
                or self.radar_controller.size is None
            ):
                print(
                    "measure_altitude_to_surface: still no occupancy grid, "
                    "performing radar scan..."
                )
                try:
                    self.scan_voxels()
                except Exception as e:
                    print(
                        "measure_altitude_to_surface: scan_voxels() failed: "
                        f"{e}"
                    )

        # 4) Параметры трассировки вдоль гравитации
        cell_size = self.radar_controller.cell_size or 5.0
        max_trace = trace_distance or cell_size * (
            self.radar_controller.size[1] if self.radar_controller.size else 50
        )
        step = trace_step or cell_size

        surface_point = self._find_surface_point_along_gravity(
            pos,
            down,
            max_distance=max_trace,
            step=step,
        )

        surface_source = "gravity_trace"

        # 5) Fallback: vertical lookup через get_surface_height
        if surface_point is None:
            surface_height = self.radar_controller.get_surface_height(px, pz)
            if surface_height is not None:
                surface_point = (px, surface_height, pz)
                surface_source = "vertical_lookup"
                print(
                    "measure_altitude_to_surface: surface found via vertical lookup "
                    f"at ({px:.2f}, {surface_height:.2f}, {pz:.2f})"
                )
            else:
                print(
                    "measure_altitude_to_surface: surface not found via gravity trace "
                    "or vertical lookup."
                )
                return None

        sx, sy, sz = surface_point

        # 6) Считаем высоту над поверхностью
        alt_vec = (px - sx, py - sy, pz - sz)
        altitude_up = (
            alt_vec[0] * up[0]
            + alt_vec[1] * up[1]
            + alt_vec[2] * up[2]
        )
        altitude_y = py - sy

        print(
            f"measure_altitude_to_surface: source={surface_source}, "
            f"position=({px:.2f}, {py:.2f}, {pz:.2f}), "
            f"surface_point=({sx:.2f}, {sy:.2f}, {sz:.2f}), "
            f"altitude_Y≈{altitude_y:.2f}м, "
            f"altitude_along_up≈{altitude_up:.2f}м"
        )

        # Возвращаем высоту по Y, т.к. по ней удобно смотреть в логах
        return altitude_y

    def calculate_safe_target_along_path(
            self,
            start: Tuple[float, float, float],
            end: Tuple[float, float, float],
            altitude: float,
            step: float = 10.0,
    ) -> Tuple[Tuple[float, float, float], Optional[float], str]:
        """
        Рассчитывает безопасную целевую точку, гарантируя, что дрон не врежется
        в холм посередине пути. Берет МАКСИМАЛЬНУЮ высоту рельефа на всем отрезке.
        """

        # 1. Вычисляем вектор и дистанцию
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dz = end[2] - start[2]
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)

        if dist < 0.01:
            return end, None, "zero_dist"

        direction = (dx / dist, dy / dist, dz / dist)

        # 2. Семплим высоты вдоль пути
        # Метод _sample_surface_along_path возвращает (max_y, last_y)
        # Нам критически важно использовать именнно max_y!
        max_surface_y_on_path, last_surface_y = self._sample_surface_along_path(
            start, direction, dist, step
        )

        # 3. Также проверяем высоту конкретно в конечной точке (end),
        # так как шаг семплинга мог её перешагнуть.
        # Для этого используем trace вдоль гравитации в точке end.
        down = self._get_down_vector()

        # Попытка найти точную поверхность под конечной точкой
        surface_at_end = self._find_surface_point_along_gravity(
            end, down, max_distance=200.0, step=5.0
        )

        surface_y_at_end_val = -999999.0
        if surface_at_end:
            # Предполагаем, что Y - это высота (в локальной сетке или мире)
            # Если гравитация сложная, тут нужно проецировать, но для Y-ориентированных сеток так:
            surface_y_at_end_val = surface_at_end[1]

            # 4. Определяем "Безопасную Базовую Высоту"
        # Это максимум между самым высоким холмом на пути и точкой назначения.

        safe_base_y = surface_y_at_end_val
        if max_surface_y_on_path is not None:
            if max_surface_y_on_path > safe_base_y:
                safe_base_y = max_surface_y_on_path

        # Если поверхность вообще не найдена, летим по высоте конечной точки (рискованно, но выхода нет)
        if safe_base_y < -900000:
            # Fallback: если вообще ничего не нашли, берем Y конечной точки плоского маршрута
            safe_base_y = end[1]
            source = "no_surface_data"
        else:
            source = "path_max_height"

        # 5. Формируем итоговую точку
        # X и Z берем от конечной цели (end), а Y поднимаем над САМОЙ ВЫСОКОЙ точкой пути.

        # Вектор "Вверх" (против гравитации)
        up = (-down[0], -down[1], -down[2])

        # ВНИМАНИЕ: Если мы просто заменим Y, это сработает для плоской планеты/луны.
        # Для сферической гравитации правильно делать смещение вдоль UP от точки проекции.
        # Но судя по твоим логам (target Y меняется явно), проще всего скорректировать Y компонент,
        # если сетка радара выровнена по гравитации.

        # Вариант А (Простой, если сетка выровнена):
        # final_target = (end[0], safe_base_y + altitude, end[2])

        # Вариант Б (Более точный для векторов):
        # Мы берем точку end, находим её проекцию на высоту safe_base_y и добавляем altitude.
        # Упростим до работы с Y, так как в логах Y явно доминирует как высота.

        final_y = safe_base_y + altitude
        final_target = (end[0], final_y, end[2])

        return final_target, safe_base_y, source
