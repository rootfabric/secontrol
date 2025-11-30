from __future__ import annotations
import math
import os
import sys
from typing import Tuple, List

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples"))

from secontrol.common import prepare_grid
from secontrol.devices.ore_detector_device import OreDetectorDevice
from secontrol.devices.remote_control_device import RemoteControlDevice
from secontrol.controllers.radar_controller import RadarController

from examples.organized.autopilot.drone_dock_helpers import _get_pos, _fly_to


class SurfaceFlightController:
    """
    Controller for flying over planet surface using radar voxel data.
    Maintains altitude above surface and tracks visited points.
    """

    def __init__(self, grid_name: str, scan_radius: float = 100):
        self.grid = prepare_grid(grid_name)

        # Find devices
        radars = self.grid.find_devices_by_type(OreDetectorDevice)
        rcs = self.grid.find_devices_by_type(RemoteControlDevice)

        if not radars:
            raise RuntimeError("No OreDetector (radar) found on grid.")
        if not rcs:
            raise RuntimeError("No RemoteControl found on grid.")

        self.radar: OreDetectorDevice = radars[0]
        self.rc: RemoteControlDevice = rcs[0]

        # Основной "широкий" контроллер радара
        self.radar_controller = RadarController(self.radar, radius=scan_radius)

        # Узкий вертикальный контроллер
        self.vertical_radar_controller = RadarController(
            self.radar,
            radius=200,
            voxel_step=1,
            cell_size=10.0,
            boundingBoxX=20,
            boundingBoxZ=20,
        )

        # Visited points
        self.visited_points: List[Tuple[float, float, float]] = []

        # Последний список solid-точек с радара
        self.last_solid: List[Tuple[float, float, float]] = []

    # ------------------------------------------------------------------ #
    # Radar
    # ------------------------------------------------------------------ #

    def scan_voxels(self):
        """Scan voxels using the main radar controller and cache solid points."""
        solid, metadata, contacts, ore_cells = self.radar_controller.scan_voxels()
        self.last_solid = list(solid) if solid is not None else []
        return solid, metadata, contacts, ore_cells

    def scan_voxels_vertical(self):
        """Scan voxels using the vertical narrow-beam radar controller."""
        solid, metadata, contacts, ore_cells = self.vertical_radar_controller.scan_voxels(
            radius=350,
            voxel_step=1,
            cell_size=10.0,
            boundingBoxX=20,
            boundingBoxZ=20,
        )
        # вертикальный скан в last_solid не пишем, он для других задач
        return solid, metadata, contacts, ore_cells

    # ------------------------------------------------------------------ #
    # Geometry helpers
    # ------------------------------------------------------------------ #

    def _get_down_vector(self) -> Tuple[float, float, float]:
        """
        Return normalized gravity vector (down direction).

        ВАЖНО:
        В телеметрии gravitationalVector, судя по логам, смотрит ВВЕРХ (от планеты),
        поэтому для "down" нам нужно взять ИНВЕРСИЮ (-g).
        """
        gravity_vector = self.rc.telemetry.get("gravitationalVector") if self.rc.telemetry else None
        if gravity_vector:
            g_x = gravity_vector.get("x", 0.0)
            g_y = gravity_vector.get("y", 0.0)
            g_z = gravity_vector.get("z", 0.0)
            g_len = math.sqrt(g_x * g_x + g_y * g_y + g_z * g_z)
            if g_len:
                # Делаем down = -gravity_vector (к планете)
                down_x = -g_x / g_len
                down_y = -g_y / g_len
                down_z = -g_z / g_len
                # Небольшой отладочный принт один раз можно оставить:
                # print(f"[Gravity] raw=({g_x:.3f}, {g_y:.3f}, {g_z:.3f}), down=({down_x:.3f}, {down_y:.3f}, {down_z:.3f})")
                return (down_x, down_y, down_z)

        # Fallback: "down" along -Y
        return (0.0, -1.0, 0.0)


    def _project_forward_to_horizontal(
        self,
        forward: Tuple[float, float, float],
        down: Tuple[float, float, float],
    ) -> Tuple[float, float, float]:
        """
        Project forward vector into plane perpendicular to 'down'
        (i.e. get horizontal direction along surface).
        """
        dot_fg = forward[0] * down[0] + forward[1] * down[1] + forward[2] * down[2]
        horizontal_forward = (
            forward[0] - dot_fg * down[0],
            forward[1] - dot_fg * down[1],
            forward[2] - dot_fg * down[2],
        )

        horiz_len = math.sqrt(
            horizontal_forward[0] * horizontal_forward[0]
            + horizontal_forward[1] * horizontal_forward[1]
            + horizontal_forward[2] * horizontal_forward[2]
        )
        if horiz_len == 0.0:
            print("Cannot compute horizontal forward vector, using original forward direction.")
            f_len = math.sqrt(
                forward[0] * forward[0]
                + forward[1] * forward[1]
                + forward[2] * forward[2]
            ) or 1.0
            return (forward[0] / f_len, forward[1] / f_len, forward[2] / f_len)

        return (
            horizontal_forward[0] / horiz_len,
            horizontal_forward[1] / horiz_len,
            horizontal_forward[2] / horiz_len,
        )

    def _sample_surface_along_path(
        self,
        start: Tuple[float, float, float],
        direction: Tuple[float, float, float],
        distance: float,
        step: float,
    ) -> Tuple[float | None, float | None]:
        """
        Sample surface height along path.

        Returns:
            (max_surface_y, last_surface_y)
        """
        max_surface_y: float | None = None
        last_surface_y: float | None = None

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
            if self.radar_controller.origin:
                dist_sample_to_origin = math.sqrt(
                    (sample[0] - self.radar_controller.origin[0]) ** 2
                    + (sample[1] - self.radar_controller.origin[1]) ** 2
                    + (sample[2] - self.radar_controller.origin[2]) ** 2
                )
                print(f"    Distance from sample to grid origin: {dist_sample_to_origin:.2f}m")

            surface_y = self.radar_controller.get_surface_height(sample[0], sample[2])
            if surface_y is None:
                # Debug for None
                if (
                    self.radar_controller.occupancy_grid is None
                    or self.radar_controller.origin is None
                    or self.radar_controller.cell_size is None
                    or self.radar_controller.size is None
                ):
                    print("    No occupancy grid data available")
                else:
                    idx_x = int(
                        (sample[0] - self.radar_controller.origin[0])
                        / self.radar_controller.cell_size
                    )
                    idx_z = int(
                        (sample[2] - self.radar_controller.origin[2])
                        / self.radar_controller.cell_size
                    )
                    in_bounds = (
                        0 <= idx_x < self.radar_controller.size[0]
                        and 0 <= idx_z < self.radar_controller.size[2]
                    )
                    if not in_bounds:
                        print(
                            f"    Out of bounds: idx_x={idx_x}, idx_z={idx_z}, "
                            f"grid_size=({self.radar_controller.size[0]}, "
                            f"{self.radar_controller.size[2]})"
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

        return max_surface_y, last_surface_y

    # ------------------------------------------------------------------ #
    # Safety check against solid voxels
    # ------------------------------------------------------------------ #

    def _is_segment_clear_of_solids(
        self,
        start: Tuple[float, float, float],
        target: Tuple[float, float, float],
        min_clearance: float = 3.0,
    ) -> bool:
        """
        Проверяет, что от отрезка start→target до всех solid-точек
        есть минимум min_clearance метров.

        Использует евклидово расстояние до ближайшей точки отрезка.
        """
        if not self.last_solid:
            # Нет данных – считаем путь свободным (контроль высоты уже есть).
            return True

        sx, sy, sz = start
        tx, ty, tz = target

        seg_vec = (tx - sx, ty - sy, tz - sz)
        seg_len2 = seg_vec[0] ** 2 + seg_vec[1] ** 2 + seg_vec[2] ** 2
        if seg_len2 <= 1e-6:
            return True

        min_clearance2 = min_clearance * min_clearance

        for vx, vy, vz in self.last_solid:
            # Вектор от start до вокселя
            px = vx - sx
            py = vy - sy
            pz = vz - sz

            # Параметр t проекции на отрезок
            t = (
                px * seg_vec[0]
                + py * seg_vec[1]
                + pz * seg_vec[2]
            ) / seg_len2

            if t <= 0.0:
                closest = (sx, sy, sz)
            elif t >= 1.0:
                closest = (tx, ty, tz)
            else:
                closest = (
                    sx + seg_vec[0] * t,
                    sy + seg_vec[1] * t,
                    sz + seg_vec[2] * t,
                )

            dx = vx - closest[0]
            dy = vy - closest[1]
            dz = vz - closest[2]
            dist2 = dx * dx + dy * dy + dz * dz

            if dist2 < min_clearance2:
                dist = math.sqrt(dist2)
                print(
                    f"[SAFETY] Collision risk: voxel ({vx:.2f}, {vy:.2f}, {vz:.2f}) "
                    f"too close to path (distance {dist:.2f}m < {min_clearance:.2f}m)."
                )
                return False

        return True

    # ------------------------------------------------------------------ #
    # Target computation
    # ------------------------------------------------------------------ #

    def _compute_target_over_surface(
        self,
        pos: Tuple[float, float, float],
        forward: Tuple[float, float, float],
        distance: float,
        altitude: float,
    ) -> Tuple[float, float, float]:
        """
        Строит точку над поверхностью:

        1) Берём forward корабля.
        2) Проецируем его в плоскость, перпендикулярную вектору гравитации.
        3) Идём по этой горизонтальной проекции на distance метров.
        4) По пути семплируем высоту поверхности.
        5) Берём max высоты по пути и поднимаемся на altitude вдоль 'up'.
        """

        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])
        print(f"Down vector: {down}")

        horiz_dir = self._project_forward_to_horizontal(forward, down)
        print(f"Horizontal forward vector: {horiz_dir}")

        target_base = (
            pos[0] + horiz_dir[0] * distance,
            pos[1] + horiz_dir[1] * distance,
            pos[2] + horiz_dir[2] * distance,
        )
        print(
            f"Target base calculation: pos={pos}, "
            f"horiz_dir={horiz_dir}, distance={distance}, "
            f"target_base={target_base}"
        )

        max_surface_y, last_surface_y = self._sample_surface_along_path(
            pos,
            horiz_dir,
            distance,
            step=5.0,
        )
        print(
            f"Sampled surface along path: "
            f"max_surface_y={max_surface_y}, last_surface_y={last_surface_y}"
        )

        surface_y = max_surface_y if max_surface_y is not None else last_surface_y

        if surface_y is None:
            print("No surface data along path, using plain horizontal move.")
            target_point = target_base
        else:
            surface_point = (
                target_base[0],
                surface_y,
                target_base[2],
            )
            print(f"Surface point at target_base: {surface_point}")

            target_point = (
                surface_point[0] + up[0] * altitude,
                surface_point[1] + up[1] * altitude,
                surface_point[2] + up[2] * altitude,
            )

            offset_vec = (
                target_point[0] - surface_point[0],
                target_point[1] - surface_point[1],
                target_point[2] - surface_point[2],
            )
            alt_along_gravity = -(
                offset_vec[0] * down[0]
                + offset_vec[1] * down[1]
                + offset_vec[2] * down[2]
            )
            print(
                f"Surface height used: {surface_y:.2f}, "
                f"altitude_along_gravity≈{alt_along_gravity:.2f} "
                f"(requested: {altitude:.2f})"
            )

        print(f"Final target point: {target_point}")

        if self.radar_controller.origin:
            ox, oy, oz = self.radar_controller.origin
            dist_target_to_origin = math.sqrt(
                (target_point[0] - ox) ** 2
                + (target_point[1] - oy) ** 2
                + (target_point[2] - oz) ** 2
            )
            print(
                f"Distance from target point to grid origin: "
                f"{dist_target_to_origin:.2f}m"
            )

        return target_point

    # ------------------------------------------------------------------ #
    # Surface height helper for vertical controller
    # ------------------------------------------------------------------ #

    def _get_surface_height_near(
        self,
        center_x: float,
        center_z: float,
        ctrl: RadarController,
        max_radius: float = 80.0,
        step: float = 5.0,
    ) -> Tuple[float | None, Tuple[float, float]]:
        """
        Ищет высоту поверхности рядом с точкой (center_x, center_z) для заданного RadarController.

        Логика:
        1) Сначала пробуем ровно под центром.
        2) Потом по кольцам радиуса r = step, 2*step, ... max_radius
           и углам 0..360 с шагом 30°, как только нашли первую валидную высоту – считаем её ближайшей.
        """
        best_y: float | None = None
        best_pos: Tuple[float, float] = (center_x, center_z)

        # 1) Сначала пробуем строго под кораблём
        h0 = ctrl.get_surface_height(center_x, center_z)
        if h0 is not None:
            print(
                f"[SurfaceHeightNear] direct center hit: y={h0:.2f} "
                f"at XZ=({center_x:.2f}, {center_z:.2f})"
            )
            return h0, (center_x, center_z)

        # 2) Кольца вокруг центра
        angle_step_deg = 30.0
        print(
            f"[SurfaceHeightNear] scanning around XZ=({center_x:.2f}, {center_z:.2f}), "
            f"max_radius={max_radius:.1f}, step={step:.1f}"
        )

        radius = step
        while radius <= max_radius + 1e-3:
            angle_deg = 0.0
            while angle_deg < 360.0:
                rad = math.radians(angle_deg)
                sx = center_x + math.cos(rad) * radius
                sz = center_z + math.sin(rad) * radius

                h = ctrl.get_surface_height(sx, sz)
                if h is not None:
                    print(
                        f"[SurfaceHeightNear] found y={h:.2f} at "
                        f"XZ=({sx:.2f}, {sz:.2f}), radius={radius:.1f}, angle={angle_deg:.1f}"
                    )
                    return h, (sx, sz)

                angle_deg += angle_step_deg

            radius += step

        print("[SurfaceHeightNear] no surface height found within radius.")
        return best_y, best_pos

    # ------------------------------------------------------------------ #
    # Vertical adjustment
    # ------------------------------------------------------------------ #

    def adjust_altitude_with_vertical_scan(
            self,
            altitude: float,
            max_delta: float = 200.0,
    ) -> None:
        """
        Выставиться на заданную высоту над поверхностью под кораблём (по оси Y).

        1) Делаем вертикальный скан.
        2) Ищем поверхность под кораблём (сначала по occupancy grid вертикального контроллера,
           если не получается — по облаку solid).
        3) Цель: surface_y + altitude по оси Y, X/Z = как у корабля.
        """

        print(f"Adjusting altitude with vertical scan, target altitude={altitude}m")

        pos = _get_pos(self.rc)
        if not pos:
            print("[VerticalAdjust] Cannot get current position for vertical adjustment.")
            return

        ship_x, ship_y, ship_z = pos
        print(f"[VerticalAdjust] ship_pos=({ship_x:.2f}, {ship_y:.2f}, {ship_z:.2f})")

        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])
        print(
            f"[VerticalAdjust] down=({down[0]:.6f}, {down[1]:.6f}, {down[2]:.6f}), "
            f"up=({up[0]:.6f}, {up[1]:.6f}, {up[2]:.6f})"
        )

        # --- 1. Вертикальный скан вокруг корабля ---
        solid, metadata, contacts, ore_cells = self.scan_voxels_vertical()
        if solid is None:
            print("[VerticalAdjust] No radar data received after retries.")
            return

        print(f"Vertical scan: {len(solid)} solid points")
        # Если нужно, можно закомментить, чтобы не спамить
        # print("solid adjust_altitude_with_vertical_scan", solid)

        if not solid:
            print("[VerticalAdjust] Vertical scan returned no voxels, cannot adjust altitude.")
            return

        surface_y: float | None = None
        surface_source = "none"

        # --- 2. Пытаемся использовать occupancy grid вертикального контроллера ---
        ctrl = self.vertical_radar_controller
        if (
                ctrl is not None
                and ctrl.occupancy_grid is not None
                and ctrl.origin is not None
                and ctrl.cell_size is not None
                and ctrl.size is not None
        ):
            surface_y_grid, best_pos = self._get_surface_height_near(
                ship_x,
                ship_z,
                ctrl,
                max_radius=80.0,
                step=5.0,
            )

            if surface_y_grid is not None:
                surface_y = surface_y_grid
                surface_source = "occupancy_grid"
                print(
                    f"[VerticalAdjust] surface_y from occupancy grid: {surface_y:.2f} "
                    f"at XZ=({best_pos[0]:.2f}, {best_pos[1]:.2f})"
                )

        # --- 3. Бэкап: используем облако solid, если по сетке не вышло ---
        if surface_y is None:
            best_voxel = None
            best_d2 = None

            for (vx, vy, vz) in solid:
                # Интересуют только воксели НИЖЕ корабля по высоте,
                # чтобы не тянуться к стенам выше нас.
                if vy >= ship_y:
                    continue

                dx = vx - ship_x
                dz = vz - ship_z
                d2 = dx * dx + dz * dz

                if best_voxel is None or d2 < best_d2:
                    best_voxel = (vx, vy, vz)
                    best_d2 = d2

            if best_voxel is not None:
                surface_y = best_voxel[1]
                surface_source = "solid_cloud"
                horiz_dist = math.sqrt(best_d2) if best_d2 is not None else 0.0
                print(
                    f"[VerticalAdjust] surface_y from solid cloud: {surface_y:.2f}, "
                    f"voxel={best_voxel}, horiz_dist={horiz_dist:.2f}m"
                )

        if surface_y is None:
            print("[VerticalAdjust] Could not determine surface under ship, abort.")
            return

        # --- 4. Точка поверхности под кораблём ---
        surface_point = (ship_x, surface_y, ship_z)
        print(
            f"[VerticalAdjust] using surface_point=({surface_point[0]:.2f}, "
            f"{surface_point[1]:.2f}, {surface_point[2]:.2f}) from {surface_source}"
        )

        # --- 5. Текущая высота над поверхностью по Y и вдоль гравитации ---
        current_alt_y = ship_y - surface_y
        offset_vec_ship = (
            ship_x - surface_point[0],
            ship_y - surface_point[1],
            ship_z - surface_point[2],
        )
        current_alt_gravity = (
                offset_vec_ship[0] * up[0]
                + offset_vec_ship[1] * up[1]
                + offset_vec_ship[2] * up[2]
        )

        print(
            f"[VerticalAdjust] current_alt_Y≈{current_alt_y:.2f}m, "
            f"current_alt_gravity≈{current_alt_gravity:.2f}m"
        )

        # --- 6. Цель: surface_y + altitude по оси Y ---
        target_y = surface_y + altitude
        target_point = (ship_x, target_y, ship_z)

        # Для инфы посчитаем смещение и высоту вдоль гравитации до цели
        offset_vec_target = (
            target_point[0] - surface_point[0],
            target_point[1] - surface_point[1],
            target_point[2] - surface_point[2],
        )
        alt_along_gravity = (
                offset_vec_target[0] * up[0]
                + offset_vec_target[1] * up[1]
                + offset_vec_target[2] * up[2]
        )

        move_dy = target_y - ship_y
        move_dist = abs(move_dy)  # X/Z не меняем, поэтому расстояние = |ΔY|

        print(
            f"Computed target above surface: {target_point}, "
            f"surface_y={surface_y:.2f}, "
            f"target_y={target_y:.2f}, "
            f"move_dY={move_dy:.2f}m, move_dist≈{move_dist:.2f}m, "
            f"altitude_along_gravity≈{alt_along_gravity:.2f}m"
        )

        # sanity-check: не улетаем СЛИШКОМ далеко по высоте
        # sanity-check: не улетаем слишком далеко по высоте
        if move_dist > max_delta:
            if current_alt_y < 0:
                # Мы уже ниже поверхности -> лучше вылезти, даже если шаг большой.
                print(
                    f"[VerticalAdjust] move_dist={move_dist:.1f}m > {max_delta}m, "
                    f"НО current_alt_Y={current_alt_y:.2f}m < 0 (корабль ниже поверхности). "
                    f"Игнорируем лимит max_delta и всё равно поднимаемся."
                )
            else:
                print(
                    f"[VerticalAdjust] Refusing to move by {move_dist:.1f}m (> {max_delta}m), "
                    f"skip vertical adjustment."
                )
                return


        # Маркер для наглядности
        self.grid.create_gps_marker("VerticalAdjust", coordinates=target_point)

        # Летим строго по высоте (по сути по Y)
        _fly_to(
            self.rc,
            target_point,
            "VerticalAdjust",
            speed_far=5.0,
            speed_near=2.0,
        )

        pos_after = _get_pos(self.rc)
        if pos_after:
            self.visited_points.append(pos_after)
            print(
                f"[VerticalAdjust] After move ship_y={pos_after[1]:.2f}, "
                f"expected≈{target_y:.2f}, diff≈{pos_after[1] - target_y:.2f}m"
            )

    # ------------------------------------------------------------------ #
    # Flight API
    # ------------------------------------------------------------------ #

    def fly_forward_over_surface(self, distance: float, altitude: float):
        """
        Fly forward for given distance, maintaining altitude above surface.

        При риске коллизии с solid-вокселями:
        1) НЕ летим вперёд;
        2) поднимаем корабль вертикально над поверхностью
           через adjust_altitude_with_vertical_scan(...).
        """

        print(f"Flying forward {distance}m at {altitude}m above surface.")

        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        print(f"Current position: {pos}")
        if self.radar_controller.origin:
            dist_to_origin = math.sqrt(
                (pos[0] - self.radar_controller.origin[0]) ** 2
                + (pos[1] - self.radar_controller.origin[1]) ** 2
                + (pos[2] - self.radar_controller.origin[2]) ** 2
            )
            print(f"Distance to occupancy grid origin: {dist_to_origin:.2f}m")

        # Текущий forward корабля
        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Using ship forward as direction: {forward}")

        self.visited_points.append(pos)

        # Сначала считаем цель над поверхностью
        candidate = self._compute_target_over_surface(pos, forward, distance, altitude)

        # Проверка на коллизию с solid-вокселями по всему сегменту
        if not self._is_segment_clear_of_solids(pos, candidate, min_clearance=3.0):
            print(
                "[SAFETY] Path to candidate intersects solid voxels. "
                "Raising ship vertically before forward move..."
            )

            # Поднимаем корабль вертикальным сканом.
            # Берём не меньше 50 м над поверхностью, как ты и просил.
            safety_altitude = max(altitude, 50.0)
            self.adjust_altitude_with_vertical_scan(safety_altitude)

            # После вертикального подъёма вперёд в этом вызове НЕ летим.
            # Ожидается, что внешний цикл ещё раз вызовет scan_voxels()
            # и потом снова fly_forward_over_surface(...) уже с новой высотой.
            return

        # Если путь чистый – летим в рассчитанную точку
        target_point = candidate
        self.grid.create_gps_marker(f"Target{distance:.0f}m", coordinates=target_point)

        _fly_to(
            self.rc,
            target_point,
            f"MoveForward{distance:.0f}m",
            speed_far=10.0,
            speed_near=5.0,
        )

        pos_after = _get_pos(self.rc)
        if pos_after:
            self.visited_points.append(pos_after)

        print(f"Flight complete. Visited points: {len(self.visited_points)}")

    def get_visited_points(self) -> List[Tuple[float, float, float]]:
        """Get list of visited points."""
        return self.visited_points.copy()

    def return_to_start(self):
        """Return to the first visited point."""
        if len(self.visited_points) < 2:
            print("No points to return to.")
            return
        start = self.visited_points[0]
        self.fly_to_point(start[0], start[2], 10.0)

    def fly_to_point(self, target_x: float, target_z: float, altitude: float):
        """Fly to specific point at altitude above surface."""
        pos = _get_pos(self.rc)
        if not pos:
            return

        self.visited_points.append(pos)

        surf_h = self.radar_controller.get_surface_height(target_x, target_z)
        target_y = surf_h + altitude if surf_h is not None else pos[1]

        _fly_to(
            self.rc,
            (target_x, target_y, target_z),
            "FlyToPoint",
            speed_far=10.0,
            speed_near=5.0,
        )

        pos_after = _get_pos(self.rc)
        if pos_after:
            self.visited_points.append(pos_after)

    def move_forward_simple(self, distance: float):
        """Move forward for given distance using ship's forward vector."""
        print(f"Moving forward {distance}m using ship's forward vector.")

        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Forward vector: {forward}")

        target_x = pos[0] + forward[0] * distance
        target_y = pos[1] + forward[1] * distance
        target_z = pos[2] + forward[2] * distance

        print(f"Target: ({target_x:.2f}, {target_y:.2f}, {target_z:.2f})")

        self.grid.create_gps_marker(f"Forward{distance:.0f}m", coordinates=(target_x, target_y, target_z))

        _fly_to(
            self.rc,
            (target_x, target_y, target_z),
            f"MoveForward{distance:.0f}m",
            speed_far=10.0,
            speed_near=5.0,
        )

        pos_after = _get_pos(self.rc)
        if pos_after:
            self.visited_points.append(pos_after)

        print("Move complete.")

    def move_forward_at_altitude(self, distance: float, altitude: float):
        """Move forward horizontally and stop at a point above the surface."""
        print(f"Moving forward {distance}m at {altitude}m above surface.")

        pos = _get_pos(self.rc)
        if not pos:
            print("Cannot get current position.")
            return

        self.visited_points.append(pos)

        forward, _, _ = self.rc.get_orientation_vectors_world()
        target_point = self._compute_target_over_surface(pos, forward, distance, altitude)

        self.grid.create_gps_marker(f"Target{distance:.0f}m", coordinates=target_point)

        _fly_to(
            self.rc,
            target_point,
            f"MoveForward{distance:.0f}m",
            speed_far=10.0,
            speed_near=5.0,
        )

        pos_after = _get_pos(self.rc)
        if pos_after:
            self.visited_points.append(pos_after)

        print("Move complete.")

    def ensure_min_altitude_with_vertical_scan(
        self,
        min_altitude: float,
        max_delta: float = 500.0,
        search_radius: float = 80.0,
        step: float = 5.0,
    ) -> None:
        """
        Гарантирует, что корабль находится не ниже min_altitude над поверхностью под ним.

        1) Делаем вертикальный скан.
        2) Ищем поверхность под кораблём (сначала по occupancy grid вертикального контроллера,
           если не получается — по облаку solid).
        3) Считаем фактическую высоту вдоль вектора гравитации.
        4) Если current_alt < min_altitude -> поднимаемся через adjust_altitude_with_vertical_scan.
        """

        pos = _get_pos(self.rc)
        if not pos:
            print("[AltitudeCheck] Cannot get current position.")
            return

        ship_x, ship_y, ship_z = pos
        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        print(
            f"[AltitudeCheck] ship_pos=({ship_x:.2f}, {ship_y:.2f}, {ship_z:.2f}), "
            f"min_altitude={min_altitude:.2f}"
        )

        # --- Вертикальный скан ---
        solid, metadata, contacts, ore_cells = self.scan_voxels_vertical()
        if solid is None:
            print("[AltitudeCheck] No radar data from vertical scan.")
            return

        print(f"[AltitudeCheck] Vertical scan solid count: {len(solid)}")

        surface_y: float | None = None
        surface_source = "none"

        # --- 1) Пытаемся взять поверхность из occupancy grid вертикального контроллера ---
        ctrl = self.vertical_radar_controller
        if (
            ctrl is not None
            and ctrl.occupancy_grid is not None
            and ctrl.origin is not None
            and ctrl.cell_size is not None
            and ctrl.size is not None
        ):
            surface_y_grid, best_pos = self._get_surface_height_near(
                ship_x,
                ship_z,
                ctrl,
                max_radius=search_radius,
                step=step,
            )
            if surface_y_grid is not None:
                surface_y = surface_y_grid
                surface_source = "vertical_occupancy_grid"
                print(
                    f"[AltitudeCheck] surface_y from vertical grid: {surface_y:.2f} "
                    f"at XZ=({best_pos[0]:.2f}, {best_pos[1]:.2f})"
                )

        # --- 2) Бэкап: берём ближайший по XZ воксель НИЖЕ корабля ---
        if surface_y is None:
            best_voxel = None
            best_d2 = None

            for vx, vy, vz in solid:
                if vy >= ship_y:
                    # Считаем только воксели ниже корабля, чтобы не тянуться к стенам выше
                    continue

                dx = vx - ship_x
                dz = vz - ship_z
                d2 = dx * dx + dz * dz

                if best_voxel is None or d2 < best_d2:
                    best_voxel = (vx, vy, vz)
                    best_d2 = d2

            if best_voxel is not None:
                surface_y = best_voxel[1]
                surface_source = "solid_cloud"
                horiz_dist = math.sqrt(best_d2) if best_d2 is not None else 0.0
                print(
                    f"[AltitudeCheck] surface_y from solid: {surface_y:.2f}, "
                    f"voxel={best_voxel}, horiz_dist={horiz_dist:.2f}m"
                )

        if surface_y is None:
            print("[AltitudeCheck] Could not determine surface under ship, skip altitude check.")
            return

        # Строим точку поверхности строго под кораблём (XZ те же, меняем только Y)
        surface_point = (ship_x, surface_y, ship_z)

        # Вектор от поверхности к кораблю
        offset_vec = (
            ship_x - surface_point[0],
            ship_y - surface_point[1],
            ship_z - surface_point[2],
        )

        # Высота вдоль гравитации (altitude_along_gravity)
        current_alt = offset_vec[0] * up[0] + offset_vec[1] * up[1] + offset_vec[2] * up[2]

        print(
            f"[AltitudeCheck] source={surface_source}, "
            f"surface_y={surface_y:.2f}, ship_y={ship_y:.2f}, "
            f"current_alt≈{current_alt:.2f}m, required={min_altitude:.2f}m"
        )

        if current_alt >= min_altitude:
            print("[AltitudeCheck] Altitude OK, no adjustment needed.")
            return

        print(
            f"[AltitudeCheck] Altitude too low, raising to {min_altitude:.2f}m "
            f"using vertical adjust..."
        )
        self.adjust_altitude_with_vertical_scan(min_altitude, max_delta=max_delta)

    def lift_drone_to_altitude(self, target_altitude: float, max_delta: float = 200.0):
        """
        Lift the drone to a specified altitude above the surface using radar data.

        Args:
            target_altitude: The desired altitude above the surface in meters.
            max_delta: Maximum allowed change in height to prevent excessive movement.
        """
        # Get current position
        curr_pos = _get_pos(self.rc)
        if not curr_pos:
            self.rc.update()
            curr_pos = _get_pos(self.rc)
            if not curr_pos:
                print("Не удалось получить позицию дрона")
                return

        x, y, z = curr_pos

        # Ensure we have radar data: scan vertical if occupancy_grid is empty
        if self.vertical_radar_controller.occupancy_grid is None:
            print("Сканирую воксели для определения поверхности...")
            self.scan_voxels_vertical()

        # Get surface height below the drone
        surface_y = self.vertical_radar_controller.get_surface_height(x, z)
        if surface_y is None:
            print("Не удалось определить высоту поверхности под дроном")
            return

        # Get gravity up vector
        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])

        # Calculate current altitude along gravity
        surface_point = (x, surface_y, z)
        offset_vec = (x - surface_point[0], y - surface_point[1], z - surface_point[2])
        current_alt = offset_vec[0] * up[0] + offset_vec[1] * up[1] + offset_vec[2] * up[2]

        # Calculate required delta altitude
        delta_alt = target_altitude - current_alt

        # Check max_delta
        if abs(delta_alt) > max_delta:
            if current_alt < 0:
                # Дрон ниже поверхности -> игнорируем max_delta и поднимаемся
                print(f"Изменение высоты {delta_alt:.2f} > {max_delta}, НО дрон ниже поверхности ({current_alt:.2f}m), поднимаемся")
            else:
                print(f"Изменение высоты {delta_alt:.2f} превышает max_delta {max_delta}, отменяю")
                return

        # Calculate target point along gravity up vector
        target_point = (
            x + up[0] * delta_alt,
            y + up[1] * delta_alt,
            z + up[2] * delta_alt
        )
        print(f"Поднимаю дрон с alt={current_alt:.2f} до alt={target_altitude:.2f} вдоль гравитации (target_point: {target_point})")

        _fly_to(self.rc, target_point, "LiftToAltitude", speed_far=5.0, speed_near=2.0)

        print("Подъем завершен")


if __name__ == "__main__":
    controller = SurfaceFlightController("taburet", scan_radius=50)
    controller.scan_voxels_vertical()
    controller.lift_drone_to_altitude(50, max_delta=100)

    exit(0)

    TARGET_ALTITUDE = 50.0
    STEP_DISTANCE = 20.0

    for i in range(100):
        print("Scanning voxels...")
        solid, metadata, contacts, ore_cells = controller.scan_voxels()
        solid_count = len(solid) if solid is not None else 0
        print(f"[Wide scan] solid points: {solid_count}")

        # 1) Сначала проверяем, что текущая высота >= TARGET_ALTITUDE
        controller.ensure_min_altitude_with_vertical_scan(TARGET_ALTITUDE)

        # 2) Потом уже двигаемся вперёд по поверхности
        controller.fly_forward_over_surface(STEP_DISTANCE, TARGET_ALTITUDE)

        print("Visited points:", controller.get_visited_points())
