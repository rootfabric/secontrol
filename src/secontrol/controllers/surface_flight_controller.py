from __future__ import annotations
import math
from typing import Tuple, List, Optional, Dict, Any

from dataclasses import dataclass

from secontrol.common import prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController
from secontrol.controllers.shared_map_controller import SharedMapController
from secontrol.tools.navigation_tools import goto

Point3D = Tuple[float, float, float]

@dataclass
class AltitudeInfo:
    position: Tuple[float, float, float]
    surface_point: Optional[Tuple[float, float, float]]
    altitude_Y: float
    altitude_along_up: float
    source: str


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

        # Check device functionality at startup
        radar_tel = self.radar.telemetry or {}
        if not radar_tel.get("isFunctional", True) or not radar_tel.get("isWorking", True) or not radar_tel.get("enabled", True):
            raise RuntimeError("Radar device is not functional/working/enabled")

        # rc_tel = self.rc.telemetry or {}
        # if not rc_tel.get("isFunctional", True) or not rc_tel.get("isWorking", True) or not rc_tel.get("enabled", True):
        #     raise RuntimeError("Remote control device is not functional/working/enabled")

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
                self.load_map_region(
                    center=start_pos,
                    radius=self.default_scan_radius * 2.0,
                )
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

    def _get_surface_height_for_world_xz(self, x: float, z: float) -> Optional[float]:
        """
        Упрощённый помощник: возвращает высоту поверхности под (x, z)
        по данным радара или None, если ничего нет.
        """
        rc = self.radar_controller

        # Если у RadarController есть удобный метод — используем его
        if hasattr(rc, "get_surface_height"):
            return rc.get_surface_height(x, z)

        # Иначе пробуем руками по occupancy_grid
        if (
            rc.occupancy_grid is None
            or rc.origin is None
            or rc.cell_size is None
            or rc.size is None
        ):
            return None

        ox, oy, oz = rc.origin
        cs = rc.cell_size
        size_x, size_y, size_z = rc.size

        idx_x = int((x - ox) / cs)
        idx_z = int((z - oz) / cs)

        if not (0 <= idx_x < size_x and 0 <= idx_z < size_z):
            return None

        # Ищем сверху вниз первый solid
        for y in range(size_y - 1, -1, -1):
            if rc.occupancy_grid[idx_x, y, idx_z]:
                return oy + (y + 0.5) * cs

        return None

    def _sample_surface_along_path(
        self,
        start: Tuple[float, float, float],
        direction: Tuple[float, float, float],
        distance: float,
        step: float,
    ) -> Tuple[Optional[float], Optional[float], bool, Optional[float]]:
        """
        Семплирует высоту поверхности вдоль пути.

        Возвращает:
        - max_surface_y: максимальная высота по пути (или None, если вообще ничего не нашли);
        - last_surface_y: последняя увиденная высота (может быть None);
        - had_oob: True, если была хотя бы одна проблемная колонка:
            * Out of bounds (за пределами occupancy_grid),
            * или "No solid voxels in column";
        - nearest_oob_dist: минимальная дистанция от start до такой проблемной точки,
                            либо None, если проблем не было.
        """
        max_surface_y: Optional[float] = None
        last_surface_y: Optional[float] = None
        had_oob = False
        nearest_oob_dist: Optional[float] = None

        rc = self.radar_controller

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
            surface_y = rc.get_surface_height(sample[0], sample[2])

            if surface_y is None:
                # Разбираемся, почему None: вне сетки или просто нет вокселей.
                if (
                    rc.occupancy_grid is None
                    or rc.origin is None
                    or rc.cell_size is None
                    or rc.size is None
                ):
                    print("    No occupancy grid data available")
                    had_oob = True
                    if nearest_oob_dist is None or t < nearest_oob_dist:
                        nearest_oob_dist = t
                else:
                    idx_x = int((sample[0] - rc.origin[0]) / rc.cell_size)
                    idx_z = int((sample[2] - rc.origin[2]) / rc.cell_size)
                    in_bounds = (
                        0 <= idx_x < rc.size[0]
                        and 0 <= idx_z < rc.size[2]
                    )
                    if not in_bounds:
                        print(
                            f"    Out of bounds: idx_x={idx_x}, idx_z={idx_z}, "
                            f"grid_size=({rc.size[0]}, {rc.size[2]})"
                        )
                        had_oob = True
                        if nearest_oob_dist is None or t < nearest_oob_dist:
                            nearest_oob_dist = t
                    else:
                        has_solid = False
                        for y in range(rc.size[1] - 1, -1, -1):
                            if rc.occupancy_grid[idx_x, y, idx_z]:
                                has_solid = True
                                break
                        if not has_solid:
                            print(f"    No solid voxels in column idx_x={idx_x}, idx_z={idx_z}")
                            # Пустая колонка тоже считаем как "сомнительные данные"
                            had_oob = True
                            if nearest_oob_dist is None or t < nearest_oob_dist:
                                nearest_oob_dist = t
                        else:
                            print("    Unexpected None despite solid voxels in column")
                continue

            print(f"    Surface height: {surface_y:.2f}")
            last_surface_y = surface_y
            if max_surface_y is None or surface_y > max_surface_y:
                max_surface_y = surface_y

        return (
            max_surface_y if max_surface_y is not None else last_surface_y,
            last_surface_y,
            had_oob,
            nearest_oob_dist,
        )

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
    # Проверка близости к границе воксельной карты                       #
    # ------------------------------------------------------------------ #

    def _is_close_to_scan_border(
        self,
        position: Point3D,
        margin_cells: int = 3,
        coverage_radius_cells: int = 5,
        min_known_fraction: float = 0.7,
    ) -> bool:
        """
        Строгая, но не параноидальная проверка «края карты».

        True  -> точка реально у края:
                - либо очень близко к геометрической границе массива,
                - либо в переходной зоне у края + вокруг мало известных колонок.
        False -> точка в «ядре» карты, можно лететь даже при дырявом покрытии.
        """
        rc = self.radar_controller

        if (
            rc.occupancy_grid is None
            or rc.origin is None
            or rc.cell_size is None
            or rc.size is None
        ):
            # Карты нет – считаем, что на краю и нужно сканировать
            return True

        ox, oy, oz = rc.origin
        cs = rc.cell_size
        size_x, size_y, size_z = rc.size

        px, py, pz = position

        idx_x = int((px - ox) / cs)
        idx_y = int((py - oy) / cs)
        idx_z = int((pz - oz) / cs)

        # Вне сетки – однозначно край
        if not (0 <= idx_x < size_x and 0 <= idx_y < size_y and 0 <= idx_z < size_z):
            return True

        # Геометрическое расстояние до границ по XZ
        dist_left = idx_x
        dist_right = size_x - 1 - idx_x
        dist_front = idx_z
        dist_back = size_z - 1 - idx_z

        min_dist = min(dist_left, dist_right, dist_front, dist_back)

        # 1) Очень близко к краю массива – считаем краем без разговоров
        strict_margin = margin_cells
        if min_dist <= strict_margin:
            return True

        # 2) Далеко от геометрического края – считаем «ядром» карты,
        #    даже если покрытие неидеальное. Здесь не блокируем движение.
        soft_margin = margin_cells * 3  # напр. 3*3 = 9 ячеек от края
        if min_dist >= soft_margin:
            return False

        # 3) Переходная зона: не совсем край, но рядом.
        #    Здесь включаем строгий детектор по покрытию.
        return self._is_poorly_mapped_region(
            position,
            radius_cells=coverage_radius_cells,
            min_known_fraction=min_known_fraction,
        )


    def ensure_map_coverage_for_point(
        self,
        position: Tuple[float, float, float],
        margin_cells: int = 3,
        min_scan_radius: Optional[float] = None,
    ) -> None:
        """
        Гарантирует, что вокруг заданной точки есть достаточное покрытие картой.

        - Если точки НЕТ или МАЛО внутри occupancy_grid (близко к краю),
          пытается:
            1) Подгрузить карту из Redis вокруг этой позиции.
            2) Если всё ещё у края — делает живой radar-сетевой скан
               с увеличенным радиусом.
        """
        if min_scan_radius is None:
            min_scan_radius = self.default_scan_radius

        # Если мы НЕ у края карты — ничего делать не надо
        if not self._is_close_to_scan_border(position, margin_cells=margin_cells):
            return

        px, py, pz = position
        print(
            "ensure_map_coverage_for_point: position=("
            f"{px:.2f}, {py:.2f}, {pz:.2f}) "
            "находится близко к границе текущей воксельной карты, "
            "обновляю карту вокруг неё..."
        )

        # 1) Сначала пробуем расширить карту за счёт Redis (общая карта)
        try:
            self.load_map_region(
                center=position,
                radius=min_scan_radius * 2.0,
            )
        except Exception as e:
            print(f"ensure_map_coverage_for_point: load_map_region_from_redis failed: {e}")

        # После подгрузки пересчитаем: может, теперь граница далеко
        if not self._is_close_to_scan_border(position, margin_cells=margin_cells):
            return

        # 2) Если всё ещё на краю — делаем живой radar-скан с увеличенным радиусом
        rc = self.radar_controller
        old_radius = None
        old_boundingBoxY = None

        try:
            scan_params = getattr(rc, "scan_params", {}) or {}
            old_radius = scan_params.get("radius", self.default_scan_radius)
            old_boundingBoxY = scan_params.get("boundingBoxY", self.default_boundingBoxY)
            new_radius = max(old_radius, min_scan_radius * 1.5)
            new_boundingBoxY = new_radius * 2

            if hasattr(rc, "set_scan_params"):
                rc.set_scan_params(radius=new_radius, boundingBoxY=new_boundingBoxY)

            print(
                "ensure_map_coverage_for_point: performing live radar scan "
                f"with radius={new_radius:.1f}m, boundingBoxY={new_boundingBoxY:.1f}m..."
            )
            self.scan_voxels()
        except Exception as e:
            print(f"ensure_map_coverage_for_point: scan_voxels failed: {e}")
        finally:
            if hasattr(rc, "set_scan_params"):
                restore_params = {}
                if old_radius is not None:
                    restore_params["radius"] = old_radius
                if old_boundingBoxY is not None:
                    restore_params["boundingBoxY"] = old_boundingBoxY
                if restore_params:
                    rc.set_scan_params(**restore_params)

    # ------------------------------------------------------------------ #
    # Высота над поверхностью                                           #
    # ------------------------------------------------------------------ #

    def measure_altitude_to_surface(
            self,
            position: Point3D,
            max_trace_distance: float = 500.0,
            allow_live_scan_on_miss: bool = True,
            scan_radius: float = 200.0,
    ) -> Tuple[Point3D, float, float]:
        """
        Возвращает:
          surface_point  – точка на поверхности
          altitude_Y      – высота цели над поверхностью по оси Y
          altitude_along_up – высота вдоль вектора "up"

        Если поверхности не нашли:
          - при первом проходе делаем живой скан и повторяем попытку;
          - если и после скана поверхности нет – возвращаем altitude_Y=0.
        """

        # 1) Пытаемся вертикальным просмотром по сетке
        surface_point = self._vertical_lookup_surface(position)
        if surface_point is not None:
            altitude_Y = position[1] - surface_point[1]
            altitude_along_up = self._altitude_along_up(position, surface_point)
            print(
                "measure_altitude_to_surface: source=vertical_lookup, "
                f"position={position}, surface_point={surface_point}, "
                f"altitude_Y≈{altitude_Y:.2f}м, altitude_along_up≈{altitude_along_up:.2f}м"
            )
            return surface_point, altitude_Y, altitude_along_up

        # 2) Пробуем трассировку вдоль гравитации
        surface_point = self._gravity_trace_to_surface(position, max_trace_distance=max_trace_distance)
        if surface_point is not None:
            altitude_Y = position[1] - surface_point[1]
            altitude_along_up = self._altitude_along_up(position, surface_point)
            print(
                "measure_altitude_to_surface: source=gravity_trace, "
                f"position={position}, surface_point={surface_point}, "
                f"altitude_Y≈{altitude_Y:.2f}м, altitude_along_up≈{altitude_along_up:.2f}м"
            )
            return surface_point, altitude_Y, altitude_along_up

        # 3) Поверхности нет ни в сетке, ни по трассировке
        if allow_live_scan_on_miss:
            print(
                "measure_altitude_to_surface: no surface found for "
                f"position={position}, performing live radar scan and retry..."
            )
            # Сканируем вокруг текущего положения грида
            self.perform_surface_scan_blocking(scan_radius=scan_radius)

            # Рекурсивно повторяем попытку, но больше не сканируем, чтобы не уйти в цикл
            surface_point, altitude_Y, altitude_along_up = self.measure_altitude_to_surface(
                position,
                max_trace_distance=max_trace_distance,
                allow_live_scan_on_miss=False,
                scan_radius=scan_radius,
            )
            if altitude_Y > 0.0:
                return surface_point, altitude_Y, altitude_along_up

        # 4) Даже после скана нет поверхности – честно говорим об этом
        print(
            "measure_altitude_to_surface: no surface found for "
            f"position={position} even after live scan, returning altitude=0."
        )
        return position, 0.0, 0.0

    def perform_surface_scan_blocking(self, scan_radius: float) -> None:
        """
        Выполнить живой скан поверхности с заданным радиусом, синхронно.

        - Временнно увеличиваем radius у RadarController (если нужно);
        - Делаем scan_voxels с сохранением в SharedMap/Redis;
        - Возвращаем старые параметры скана.
        """
        rc = self.radar_controller

        old_radius = None
        old_bounding_box_y = None

        try:
            # Текущие параметры скана
            scan_params = getattr(rc, "scan_params", {}) or {}
            old_radius = scan_params.get("radius", self.default_scan_radius)
            old_bounding_box_y = scan_params.get(
                "boundingBoxY",
                self.default_boundingBoxY,
            )

            new_radius = max(float(scan_radius), float(old_radius))

            if hasattr(rc, "set_scan_params"):
                rc.set_scan_params(
                    radius=new_radius,
                    boundingBoxY=old_bounding_box_y,
                )

            print(
                f"perform_surface_scan_blocking: live radar scan "
                f"with radius={new_radius:.1f}m (old_radius={old_radius:.1f}m)"
            )

            # Живой скан + сохранение в общую карту
            self.scan_voxels(persist_to_shared_map=True)

        except Exception as e:
            print(f"perform_surface_scan_blocking: scan failed: {e}")

        finally:
            # Восстанавливаем параметры скана
            if hasattr(rc, "set_scan_params"):
                try:
                    rc.set_scan_params(
                        radius=old_radius or self.default_scan_radius,
                        boundingBoxY=old_bounding_box_y or self.default_boundingBoxY,
                    )
                except Exception as e:
                    print(f"perform_surface_scan_blocking: failed to restore scan params: {e}")


    def _measure_altitude_to_surface_impl(
        self,
        position: Optional[Tuple[float, float, float]],
        trace_distance: Optional[float] = None,
        trace_step: Optional[float] = None,
    ) -> Optional[AltitudeInfo]:
        if position is None:
            pos = _get_pos(self.rc)
            if not pos:
                print("measure_altitude_to_surface: cannot get current RC position.")
                return None
        else:
            pos = position

        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])

        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])

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
                self.load_map_region(
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

        cell_size = self.radar_controller.cell_size or 5.0
        max_trace = trace_distance or cell_size * (
            self.radar_controller.size[1] if self.radar_controller.size else 50
        )
        step = trace_step or cell_size

        surface_point = None
        source = "none"

        if (
            self.radar_controller.occupancy_grid is not None
            and self.radar_controller.origin is not None
            and self.radar_controller.cell_size is not None
            and self.radar_controller.size is not None
        ):
            surface_point = self._find_surface_point_along_gravity(
                pos,
                down,
                max_distance=max_trace,
                step=step,
            )
            if surface_point is not None:
                source = "gravity_trace"

        if surface_point is None and hasattr(self.radar_controller, "get_surface_height"):
            surface_y = self.radar_controller.get_surface_height(px, pz)
            if surface_y is not None:
                surface_point = (px, surface_y, pz)
                source = "vertical_lookup"

        if surface_point is None:
            print(
                "measure_altitude_to_surface: no surface found for "
                f"position=({px:.2f}, {py:.2f}, {pz:.2f}), returning altitude=0."
            )
            return AltitudeInfo(
                position=pos,
                surface_point=None,
                altitude_Y=0.0,
                altitude_along_up=0.0,
                source="no_surface",
            )

        sx, sy, sz = surface_point

        altitude_vec = (px - sx, py - sy, pz - sz)
        altitude_Y = py - sy
        altitude_along_up = (
            altitude_vec[0] * up[0]
            + altitude_vec[1] * up[1]
            + altitude_vec[2] * up[2]
        )

        print(
            "measure_altitude_to_surface: "
            f"source={source}, "
            f"position=({px:.2f}, {py:.2f}, {pz:.2f}), "
            f"surface_point=({sx:.2f}, {sy:.2f}, {sz:.2f}), "
            f"altitude_Y≈{altitude_Y:.2f}м, "
            f"altitude_along_up≈{altitude_along_up:.2f}м"
        )

        return AltitudeInfo(
            position=pos,
            surface_point=surface_point,
            altitude_Y=altitude_Y,
            altitude_along_up=altitude_along_up,
            source=source,
        )

    def ensure_safe_altitude_for_target(
        self,
        target: Tuple[float, float, float],
        desired_altitude: float,
        min_margin: float = 5.0,
    ) -> Tuple[Tuple[float, float, float], AltitudeInfo]:
        """
        Дополнительная проверка цели по высоте.

        1) Гарантирует покрытие картой вокруг цели (ensure_map_coverage_for_point).
        2) Замеряет фактическую высоту цели над поверхностью.
        3) Если цель ниже desired_altitude (с допуском), поднимает её
           ИМЕННО по оси Y над уровнем поверхности.
        """
        self.ensure_map_coverage_for_point(target, margin_cells=3)

        info = self._measure_altitude_to_surface_impl(target)
        if info is None:
            return target, AltitudeInfo(
                position=target,
                surface_point=None,
                altitude_Y=0.0,
                altitude_along_up=0.0,
                source="no_surface",
            )

        if info.surface_point is None:
            # Нет поверхности — нечего поднимать, возвращаем как есть
            return target, info

        required_alt = max(desired_altitude, min_margin)

        # Уже достаточно высоко
        if info.altitude_Y >= required_alt:
            return target, info

        # Поднять по оси Y на required_alt относительно поверхности
        sx, sy, sz = info.surface_point
        tx, ty, tz = target

        new_y = sy + required_alt
        new_target = (tx, new_y, tz)

        print(
            "ensure_safe_altitude_for_target: target too low, "
            f"alt≈{info.altitude_Y:.2f}м, lifting to {required_alt:.1f}м "
            f"over surface_Y={sy:.2f} -> target_y={new_y:.2f}"
        )

        return new_target, info


    def calculate_safe_target_along_path(
        self,
        current_pos: Point3D,
        flat_target: Point3D,
        desired_alt_over_surface: float,
        max_step: float = 10.0,
        unknown_proximity_threshold: float = 30.0,  # оставляем для совместимости, сейчас не используем
        scan_radius: float = 200.0,
    ) -> Tuple[Point3D, Optional[float], float]:
        """
        Возвращает безопасную цель вдоль пути к flat_target.

        Логика:
        1) Гарантируем покрытие карты вокруг старта и цели.
        2) Семплируем рельеф вдоль горизонтальной проекции пути
           с шагом max_step, находим max_surface_y по пути.
        3) Строим цель так, чтобы её высота по Y была не ниже
           max_surface_y + desired_alt_over_surface.
        4) При плохом покрытии (дыры/края сетки) пробуем расширить карту
           и пересемплировать один раз.

        Возвращает:
          target_point       – безопасная точка для полёта
          base_surface_y     – максимум высоты поверхности по пути (или None)
          alt_over_surface_Y – желаемая высота над surface по оси Y
        """

        # 0. Гарантируем, что вокруг старта и цели есть карта
        self.ensure_map_coverage_for_point(current_pos, margin_cells=3, min_scan_radius=scan_radius)
        self.ensure_map_coverage_for_point(flat_target, margin_cells=3, min_scan_radius=scan_radius)

        # 1. Горизонтальное направление и дистанция
        dx = flat_target[0] - current_pos[0]
        dz = flat_target[2] - current_pos[2]
        horizontal_dist = math.sqrt(dx * dx + dz * dz)

        if horizontal_dist < 1e-3:
            # Практически нет движения по XZ – просто держим/поднимаем высоту на месте
            rc = self.radar_controller
            surface_y = rc.get_surface_height(current_pos[0], current_pos[2]) if rc else None
            if surface_y is not None:
                target_y = surface_y + max(desired_alt_over_surface, 0.0)
            else:
                target_y = current_pos[1]

            target_point = (current_pos[0], target_y, current_pos[2])
            print(
                "calculate_safe_target_along_path: degenerate segment, "
                f"surface_y={surface_y}, target_y={target_y:.2f}"
            )
            return target_point, surface_y, target_y - (surface_y or 0.0)

        horiz_dir = (dx / horizontal_dist, 0.0, dz / horizontal_dist)

        # 2. Первый проход: семплируем поверхность вдоль пути
        max_surf, last_surf, had_oob, nearest_oob_dist = self._sample_surface_along_path(
            start=current_pos,
            direction=horiz_dir,
            distance=horizontal_dist,
            step=max_step,
        )

        rc = self.radar_controller

        # 3. Если по пути были дыры / край сетки – пробуем расширить карту и пересемплировать
        if had_oob and nearest_oob_dist is not None and nearest_oob_dist <= scan_radius * 0.9:
            mid_dist = max(0.0, min(nearest_oob_dist, horizontal_dist))
            mid_pos = (
                current_pos[0] + horiz_dir[0] * mid_dist,
                current_pos[1],
                current_pos[2] + horiz_dir[2] * mid_dist,
            )
            print(
                "calculate_safe_target_along_path: poor coverage along path, "
                f"nearest_oob_dist≈{nearest_oob_dist:.1f}м, "
                f"expanding map around mid_pos=({mid_pos[0]:.2f}, {mid_pos[1]:.2f}, {mid_pos[2]:.2f}) "
                f"and performing live scan..."
            )

            # 3.1. Подгружаем карту из Redis вокруг проблемной точки
            self.ensure_map_coverage_for_point(
                mid_pos,
                margin_cells=3,
                min_scan_radius=scan_radius,
            )

            # 3.2. ОБЯЗАТЕЛЬНО делаем живой скан, чтобы расширить «исследованную» область
            self.perform_surface_scan_blocking(scan_radius=scan_radius)

            # 3.3. Повторно семплируем профиль рельефа вдоль пути
            max_surf, last_surf, had_oob, nearest_oob_dist = self._sample_surface_along_path(
                start=current_pos,
                direction=horiz_dir,
                distance=horizontal_dist,
                step=max_step,
            )


        surface_candidates: list[float] = []

        # максимум по пути
        if max_surf is not None:
            surface_candidates.append(max_surf)

        # поверхность под целью
        if rc is not None:
            surf_target = rc.get_surface_height(flat_target[0], flat_target[2])
            if surf_target is not None:
                surface_candidates.append(surf_target)

            # поверхность под стартом
            surf_start = rc.get_surface_height(current_pos[0], current_pos[2])
            if surf_start is not None:
                surface_candidates.append(surf_start)

        if surface_candidates:
            base_surface_y = max(surface_candidates)
        else:
            base_surface_y = None

        if base_surface_y is None:
            # Совсем нет данных по поверхности – держим текущую высоту
            print(
                "calculate_safe_target_along_path: no surface data along path, "
                "keeping current altitude."
            )
            target_point = (flat_target[0], current_pos[1], flat_target[2])
            return target_point, None, 0.0

        # 4. Строим цель на desired_alt_over_surface выше максимума рельефа по пути
        target_y = base_surface_y + max(desired_alt_over_surface, 0.0)
        target_point = (flat_target[0], target_y, flat_target[2])

        print(
            "calculate_safe_target_along_path: using path profile, "
            f"max_surface_y≈{base_surface_y:.2f}м, "
            f"target_y≈{target_y:.2f}м, "
            f"alt_over_surface_Y≈{target_y - base_surface_y:.2f}м"
        )

        # Второе значение – базовая высота поверхности (для логов в patrol.py),
        # третье – фактическая высота над этой поверхностью по оси Y.
        return target_point, base_surface_y, target_y - base_surface_y





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

    def lift_drone_to_point_altitude(
        self,
        point: Tuple[float, float, float],
        altitude: float,
        trace_step: Optional[float] = None,
        trace_distance: Optional[float] = None,
        speed: Optional[float] = 20
    ) -> None:
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

        surface_point = self._find_surface_point_along_gravity(point, down, max_trace, step)
        if surface_point is None:
            surface_height = self.radar_controller.get_surface_height(point[0], point[2])
            if surface_height is not None:
                surface_point = (point[0], surface_height, point[2])
                print("Surface found via vertical lookup.")
            else:
                print("Surface not found; moving along up vector from given point.")
                surface_point = point

        target_point = (
            surface_point[0] + up[0] * altitude,
            surface_point[1] + up[1] * altitude,
            surface_point[2] + up[2] * altitude,
        )

        print(
            f"Lifting to altitude over point: point={point}, surface={surface_point}, "
            f"target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
        )


        # self.grid.create_gps_marker("LiftTarget", coordinates=target_point)
        # _fly_to(self.rc, target_point, "LiftToPointAltitude", speed_far=speed, speed_near=speed)
        goto(self.grid, target_point, speed=speed)

        self.visited_points.append(point)

        new_pos = _get_pos(self.rc)
        if new_pos:
            self.visited_points.append(new_pos)

    def fly_forward_to_altitude(self, distance: float, altitude: float) -> None:
        print(f"fly_forward_to_altitude: distance={distance}, altitude={altitude}")
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

        target_point, base_y, alt_up = self.calculate_safe_target_along_path(
            pos,
            forward_point,
            altitude,
            max_step=10.0,
        )

        print(
            "Flying to target: "
            f"({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f}), "
            f"base_surface_y={base_y:.2f}, alt_along_up={alt_up:.2f}"
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
        max_surf, last_surf, had_oob, nearest_oob_dist = self._sample_surface_along_path(
            pos,
            horiz_dir,
            distance,
            step=max(cell_step, 5.0),
        )

        if had_oob and nearest_oob_dist is not None:
            scan_radius = getattr(self.radar_controller, "scan_params", {}).get(
                "radius",
                self.default_scan_radius,
            )
            if nearest_oob_dist < scan_radius * 0.9:
                print(
                    "_compute_target_over_surface: poor coverage along path "
                    f"within {nearest_oob_dist:.1f}m, performing live scan..."
                )
                try:
                    self.scan_voxels()
                except Exception as e:
                    print(f"_compute_target_over_surface: live scan failed: {e}")
                else:
                    max_surf, last_surf, had_oob, nearest_oob_dist = self._sample_surface_along_path(
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

    def load_map_region(
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

        data = self.shared_map_controller.load_region(center=center, radius=radius)

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

    def perform_surface_scan_blocking(self, scan_radius: float) -> None:
        """
        Выполнить живой скан радара с указанным радиусом, блокирующе.

        - Временно увеличивает radius у RadarController (если метод set_scan_params есть).
        - Вызывает scan_voxels(), чтобы обновить локальную воксельную карту и SharedMap.
        - После завершения возвращает старый радиус.
        """
        rc = self.radar_controller
        old_radius = None

        try:
            scan_params = getattr(rc, "scan_params", {}) or {}
            old_radius = scan_params.get("radius", self.default_scan_radius)

            if hasattr(rc, "set_scan_params"):
                rc.set_scan_params(radius=scan_radius)

            print(
                f"perform_surface_scan_blocking: scanning voxels "
                f"with radius={scan_radius:.1f}m..."
            )
            self.scan_voxels()
        except Exception as e:
            print(f"perform_surface_scan_blocking: scan_voxels failed: {e}")
        finally:
            if old_radius is not None and hasattr(rc, "set_scan_params"):
                try:
                    rc.set_scan_params(radius=old_radius)
                except Exception as e:
                    print(
                        "perform_surface_scan_blocking: failed to restore "
                        f"previous scan radius {old_radius}: {e}"
                    )


    def _is_poorly_mapped_region(
        self,
        position: Point3D,
        radius_cells: int = 5,
        min_known_fraction: float = 0.7,
    ) -> bool:
        """
        Проверяет локальное покрытие карты вокруг позиции.

        True  -> вокруг точки мало известных колонок (считаем, что это край исследованной области).
        False -> покрытие достаточно плотное.

        radius_cells       – радиус окна в индексах XZ (например 5 -> квадрат ~11x11 колонок).
        min_known_fraction – минимальная доля колонок с твёрдыми вокселями.
        """
        rc = self.radar_controller

        if (
            rc.occupancy_grid is None
            or rc.origin is None
            or rc.cell_size is None
            or rc.size is None
        ):
            # Нет карты – это точно плохо
            return True

        ox, oy, oz = rc.origin
        cs = rc.cell_size
        size_x, size_y, size_z = rc.size

        px, py, pz = position

        idx_x = int((px - ox) / cs)
        idx_z = int((pz - oz) / cs)

        if not (0 <= idx_x < size_x and 0 <= idx_z < size_z):
            # Вне сетки – уже край
            return True

        total_columns = 0
        known_columns = 0

        for dx in range(-radius_cells, radius_cells + 1):
            x = idx_x + dx
            if x < 0 or x >= size_x:
                continue

            for dz in range(-radius_cells, radius_cells + 1):
                z = idx_z + dz
                if z < 0 or z >= size_z:
                    continue

                total_columns += 1

                # Есть ли хотя бы один твёрдый воксель в колонке (по Y)?
                has_solid = False
                for y in range(size_y - 1, -1, -1):
                    if rc.occupancy_grid[x, y, z]:
                        has_solid = True
                        break

                if has_solid:
                    known_columns += 1

        if total_columns == 0:
            # Окно полностью вывалилось за сетку
            return True

        known_fraction = known_columns / float(total_columns)

        # Чем меньше порог, тем менее строгий детектор;
        # 0.7 означает: хотя бы 70% колонок вокруг должны быть известными.
        if known_fraction < min_known_fraction:
            print(
                "_is_poorly_mapped_region: position=("
                f"{px:.2f}, {py:.2f}, {pz:.2f}), "
                f"known_fraction={known_fraction:.2f} < {min_known_fraction:.2f} "
                "-> рассматриваем как край исследованной области."
            )
            return True

        return False

    def find_nearest_resources(
            self,
            search_radius: float = 1500.0,
            max_results: int = 500,
            center: Optional[Tuple[float, float, float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Найти ближайшие ресурсы, используя УЖЕ ГОТОВУЮ карту радара.

        ВАЖНО:
        - НИКАКИХ новых сканов здесь нет.
        - Используются только те данные руды, которые уже есть в RadarController.

        :param search_radius: радиус поиска в метрах от точки center / текущей позиции дрона
        :param max_results: максимальное количество результатов
        :param center: точка центра поиска (если None — берём позицию RemoteControl)
        :return: список словарей вида:
                 {
                    "position": (x, y, z),
                    "distance": float,
                    "ore": <тип/название руды или None>
                 }
        """

        # 1. Определяем центр поиска
        if center is None:
            pos = _get_pos(self.rc)
            if not pos:
                print("find_nearest_resources: cannot get current RC position.")
                return []
            center = pos

        cx, cy, cz = center
        print(f"find_nearest_resources: center position ({cx:.2f}, {cy:.2f}, {cz:.2f}), search_radius={search_radius:.1f}m")

        # 2. Достаём уже сохранённые данные по ресурсам из RadarController
        # Ожидаем, что где-то при сканировании они были сохранены.
        ore_points = (
                getattr(self.radar_controller, "ore_cells", None)
                or getattr(self.radar_controller, "ore_points", None)
        )

        if not ore_points:
            print(
                "find_nearest_resources: no ore data in radar controller. "
                "Make sure map was filled by a previous scan in another script/process."
            )
            return []

        r2 = search_radius * search_radius
        results: List[Dict[str, Any]] = []

        # 3. Перебираем все сохранённые точки руды и считаем дистанции
        for cell in ore_points:
            # Поддерживаем разные форматы хранения: dict с position или прямые координаты
            if isinstance(cell, dict):
                position = cell.get("position")
                if position and isinstance(position, (list, tuple)) and len(position) >= 3:
                    x, y, z = position[0], position[1], position[2]
                else:
                    x = (
                            cell.get("x")
                            or cell.get("X")
                            or cell.get("worldX")
                            or cell.get("wx")
                    )
                    y = (
                            cell.get("y")
                            or cell.get("Y")
                            or cell.get("worldY")
                            or cell.get("wy")
                    )
                    z = (
                            cell.get("z")
                            or cell.get("Z")
                            or cell.get("worldZ")
                            or cell.get("wz")
                    )
                ore_type = (
                        cell.get("ore")
                        or cell.get("material")
                        or cell.get("type")
                )
            elif isinstance(cell, (tuple, list)) and len(cell) >= 3:
                x, y, z = cell[0], cell[1], cell[2]
                ore_type = None
            else:
                continue

            try:
                fx = float(x)
                fy = float(y)
                fz = float(z)
            except (TypeError, ValueError):
                continue

            dx = fx - cx
            dy = fy - cy
            dz = fz - cz
            dist2 = dx * dx + dy * dy + dz * dz

            if dist2 <= r2:
                results.append(
                    {
                        "position": (fx, fy, fz),
                        "distance": math.sqrt(dist2),
                        "ore": ore_type,
                    }
                )

        # 4. Сортируем по расстоянию и обрезаем до max_results
        results.sort(key=lambda item: item["distance"])

        if max_results is not None and max_results > 0:
            results = results[:max_results]

        print(
            f"find_nearest_resources: found {len(results)} ore cells "
            f"within {search_radius:.1f}m "
            f"(limit {max_results})."
        )

        # Debug: if no results, print all loaded ores
        if not results:
            print("Debug: All loaded ore_cells:")
            for cell in ore_points:
                if isinstance(cell, dict):
                    x = cell.get("x") or cell.get("X") or cell.get("worldX") or cell.get("wx")
                    y = cell.get("y") or cell.get("Y") or cell.get("worldY") or cell.get("wy")
                    z = cell.get("z") or cell.get("Z") or cell.get("worldZ") or cell.get("wz")
                    ore_type = cell.get("ore") or cell.get("material") or cell.get("type")
                elif isinstance(cell, (tuple, list)) and len(cell) >= 3:
                    x, y, z = cell[0], cell[1], cell[2]
                    ore_type = None
                else:
                    continue
                try:
                    fx = float(x)
                    fy = float(y)
                    fz = float(z)
                    dx = fx - cx
                    dy = fy - cy
                    dz = fz - cz
                    dist = math.sqrt(dx*dx + dy*dy + dz*dz)
                    print(f"  Ore: material={ore_type}, pos=({fx:.2f}, {fy:.2f}, {fz:.2f}), dist={dist:.2f}m")
                except:
                    pass

        return results

    # ------------------------------------------------------------------ #
    # Вспомогательные функции для measure_altitude_to_surface            #
    # ------------------------------------------------------------------ #

    def _vertical_lookup_surface(self, position: Point3D) -> Optional[Point3D]:
        """
        Пытается найти поверхность под точкой, глядя вертикально сверху вниз
        (через get_surface_height / occupancy_grid).

        Возвращает точку на поверхности (x, surface_y, z) или None, если
        информации по этой колонке нет.
        """
        x, _, z = position
        rc = self.radar_controller
        if rc is None:
            return None

        surface_y: Optional[float] = None

        # Сначала пробуем «нормальный» метод радара, если он есть
        if hasattr(rc, "get_surface_height"):
            surface_y = rc.get_surface_height(x, z)

        # Если метода нет или он вернул None — используем наш ручной helper
        if surface_y is None:
            surface_y = self._get_surface_height_for_world_xz(x, z)

        if surface_y is None:
            return None

        return (x, surface_y, z)

    def _gravity_trace_to_surface(
        self,
        position: Point3D,
        max_trace_distance: float = 500.0,
        step: Optional[float] = None,
    ) -> Optional[Point3D]:
        """
        Трассировка вдоль вектора гравитации через воксельную сетку.
        Ищет первый solid-воксель по направлению "down".
        """
        rc = self.radar_controller
        if (
            rc is None
            or rc.occupancy_grid is None
            or rc.origin is None
            or rc.cell_size is None
            or rc.size is None
        ):
            return None

        cell_size = rc.cell_size or 5.0
        if step is None or step <= 0.0:
            step = cell_size

        down = self._get_down_vector()

        return self._find_surface_point_along_gravity(
            position,
            down,
            max_distance=max_trace_distance,
            step=step,
        )

    def _altitude_along_up(
        self,
        position: Point3D,
        surface_point: Point3D,
    ) -> float:
        """
        Скалярная высота точки относительно поверхности вдоль вектора 'up'.
        """
        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        vx = position[0] - surface_point[0]
        vy = position[1] - surface_point[1]
        vz = position[2] - surface_point[2]

        return vx * up[0] + vy * up[1] + vz * up[2]
