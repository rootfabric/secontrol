from __future__ import annotations
import math
import os
import sys
from typing import Tuple, List

sys.path.append(os.path.dirname(__file__))
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'examples'))

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

        self.radar_controller = RadarController(self.radar, radius=scan_radius)

        # Visited points
        self.visited_points: List[Tuple[float, float, float]] = []

    def scan_voxels(self):
        """Scan voxels using the radar controller."""
        return self.radar_controller.scan_voxels()

    def _get_down_vector(self) -> Tuple[float, float, float]:
        """Return normalized gravity vector (down direction)."""
        gravity_vector = self.rc.telemetry.get("gravitationalVector") if self.rc.telemetry else None
        if gravity_vector:
            g_x = gravity_vector.get("x", 0.0)
            g_y = gravity_vector.get("y", 0.0)
            g_z = gravity_vector.get("z", 0.0)
            g_len = math.sqrt(g_x * g_x + g_y * g_y + g_z * g_z)
            if g_len:
                return (g_x / g_len, g_y / g_len, g_z / g_len)
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
            f_len = math.sqrt(forward[0] * forward[0] + forward[1] * forward[1] + forward[2] * forward[2]) or 1.0
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
                # Extra debug why we got None
                if (
                        self.radar_controller.occupancy_grid is None
                        or self.radar_controller.origin is None
                        or self.radar_controller.cell_size is None
                        or self.radar_controller.size is None
                ):
                    print("    No occupancy grid data available")
                else:
                    idx_x = int(
                        (sample[0] - self.radar_controller.origin[0]) / self.radar_controller.cell_size
                    )
                    idx_z = int(
                        (sample[2] - self.radar_controller.origin[2]) / self.radar_controller.cell_size
                    )
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

        return max_surface_y, last_surface_y

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
        2) Проецируем его в плоскость, перпендикулярную вектору гравитации (т.е. в "горизонт").
        3) Идём по этой горизонтальной проекции на distance метров.
        4) По пути семплируем высоту поверхности из occupancy grid.
        5) Берём высоту поверхности (max по пути) и поднимаемся на altitude
           вдоль вектора "вверх" (против гравитации).
        """

        # --- 1. Вектор "вниз" (по гравитации) и "вверх" (против неё) ---
        down = self._get_down_vector()
        up = (-down[0], -down[1], -down[2])
        print(f"Down vector: {down}")

        # --- 2. Горизонтальный forward (проекция на плоскость, перпендикулярную down) ---
        horiz_dir = self._project_forward_to_horizontal(forward, down)
        print(f"Horizontal forward vector: {horiz_dir}")

        # --- 3. Базовая точка по горизонтали (без учёта высоты) ---
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

        # --- 4. Профиль высоты по пути из occupancy grid ---
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
            # Совсем нет данных по поверхности – просто летим по горизонтали
            print("No surface data along path, using plain horizontal move.")
            target_point = target_base
        else:
            # Точка на поверхности под целевой горизонтальной проекцией
            surface_point = (
                target_base[0],
                surface_y,
                target_base[2],
            )
            print(f"Surface point at target_base: {surface_point}")

            # --- 5. Поднимаемся на altitude ВДОЛЬ 'up' (против гравитации), а не по оси Y ---
            target_point = (
                surface_point[0] + up[0] * altitude,
                surface_point[1] + up[1] * altitude,
                surface_point[2] + up[2] * altitude,
            )

            # Проверка: реальная высота вдоль гравитации должна быть ≈ altitude
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

        # Отладка: расстояние цели до origin occupancy-грида
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

    def fly_forward_over_surface(self, distance: float, altitude: float):
        """
        Fly forward for given distance, maintaining altitude above surface.

        ВАЖНО: здесь больше нет попытки "подогнать" радиус до origin.
        Летим просто вперёд по ориентации корабля, над поверхностью.
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

        # Берём текущий forward корабля
        forward, _, _ = self.rc.get_orientation_vectors_world()
        print(f"Using ship forward as direction: {forward}")

        self.visited_points.append(pos)

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
        self.fly_to_point(start[0], start[2], 10.0)  # Assume altitude 10m

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


if __name__ == "__main__":
    # Example: fly forward 15m at 50m above surface
    controller = SurfaceFlightController("taburet", scan_radius=80)

    # контроллер сканирует узким лучем под себя
    controller_vertical = RadarController("taburet",
                                          radius=200,
                                          voxel_step=1,
                                          cell_size=10.0,
                                          boundingBoxX=20,
                                          boundingBoxZ=20,
                                          )

    for i in range(10):
        solid, metadata, contacts, ore_cells = controller.scan_voxels()
        print(solid)

        controller.fly_forward_over_surface(50, 50)
        print("Visited points:", controller.get_visited_points())
