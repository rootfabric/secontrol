#!/usr/bin/env python3
"""
Патрульный полёт дрона по окружности вокруг базы
в плоскости, перпендикулярной вектору гравитации.

Высота над поверхностью по каждой точке патруля
считается через SurfaceFlightController.calculate_surface_point_at_altitude.
"""

import math
import time
from typing import Tuple, Optional

from secontrol.controllers.surface_flight_controller import SurfaceFlightController
from secontrol.tools.navigation_tools import goto


Point3D = Tuple[float, float, float]


def _get_pos(rc) -> Optional[Point3D]:
    tel = rc.telemetry or {}
    pos = tel.get("worldPosition") or tel.get("position")
    if not pos:
        return None
    return (
        float(pos.get("x", 0.0)),
        float(pos.get("y", 0.0)),
        float(pos.get("z", 0.0)),
    )


def _build_horizontal_basis(down: Point3D) -> Tuple[Point3D, Point3D]:
    """
    Строим два ортонормальных вектора в плоскости,
    перпендикулярной вектору гравитации (down).
    """
    dx, dy, dz = down

    # Берём произвольный вектор, неколлинеарный down
    if abs(dx) < 0.9:
        ref = (1.0, 0.0, 0.0)
    else:
        ref = (0.0, 1.0, 0.0)

    ax, ay, az = ref
    bx, by, bz = down

    # h1 = normalize(cross(ref, down))
    ux = ay * bz - az * by
    uy = az * bx - ax * bz
    uz = ax * by - ay * bx
    len_u = math.sqrt(ux * ux + uy * uy + uz * uz) or 1.0
    ux /= len_u
    uy /= len_u
    uz /= len_u

    # h2 = normalize(cross(down, h1))
    vx = by * uz - bz * uy
    vy = bz * ux - bx * uz
    vz = bx * uy - by * ux
    len_v = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
    vx /= len_v
    vy /= len_v
    vz /= len_v

    return (ux, uy, uz), (vx, vy, vz)


def main() -> None:
    grid_name = "taburet"

    # Контроллер полёта над поверхностью
    controller = SurfaceFlightController(grid_name, scan_radius=200.0, boundingBoxY=60.0)

    # Начальная позиция
    base_pos = _get_pos(controller.rc)
    if base_pos is None:
        print("Не удалось получить позицию RemoteControl. Завершение.")
        return

    print(f"Базовая позиция (центр патруля): {base_pos}")
    controller.visited_points.append(base_pos)

    # Выполним один плотный скан, чтобы заполнить occupancy_grid
    print("Первичный скан поверхности для заполнения карты...")
    solid, metadata, contacts, ore_cells = controller.scan_voxels()
    print(
        f"Начальный скан завершён: solid={len(solid or [])}, ores={len(ore_cells or [])}"
    )

    # Горизонтальная система координат относительно гравитации
    down = controller._get_down_vector()
    print(f"Гравитация (down): {down}")
    h1, h2 = _build_horizontal_basis(down)
    print(f"Горизонтальные базисы: h1={h1}, h2={h2}")

    # Параметры патруля
    flight_altitude = 50.0      # высота над поверхностью
    ring_radius = 100.0         # стартовый радиус
    ring_radius_step = 100.0
    max_ring_radius = 3000.0

    angle = 0.0
    angle_step_deg = 45.0
    angle_step = math.radians(angle_step_deg)

    while True:
        if ring_radius > max_ring_radius:
            print(f"Достигнут максимальный радиус {max_ring_radius} м. Ожидание на орбите.")
            time.sleep(10.0)
            continue

        # Текущая позиция (для контроля и логов)
        current_pos = _get_pos(controller.rc) or base_pos
        print(f"\nТекущая позиция дрона: {current_pos}")

        # Горизонтальное смещение в плоскости, перпендикулярной гравитации
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        offset = (
            ring_radius * (cos_a * h1[0] + sin_a * h2[0]),
            ring_radius * (cos_a * h1[1] + sin_a * h2[1]),
            ring_radius * (cos_a * h1[2] + sin_a * h2[2]),
        )

        # Точка патруля в "горизонтальной" плоскости
        flat_point = (
            base_pos[0] + offset[0],
            base_pos[1] + offset[1],
            base_pos[2] + offset[2],
        )

        print(
            f"Плоская патрульная точка (до учёта рельефа): "
            f"({flat_point[0]:.2f}, {flat_point[1]:.2f}, {flat_point[2]:.2f})"
        )

        # Рассчитываем точку на заданной высоте над поверхностью по гравитации
        target_point = controller.calculate_surface_point_at_altitude(
            flat_point,
            flight_altitude,
        )

        print(
            f"Патрульная точка: угол={math.degrees(angle):.1f}°, "
            f"радиус={ring_radius:.1f}м, "
            f"target=({target_point[0]:.2f}, {target_point[1]:.2f}, {target_point[2]:.2f})"
        )

        controller.grid.create_gps_marker(
            f"Patrol_r{ring_radius:.0f}_a{math.degrees(angle):.0f}",
            coordinates=target_point,
        )

        # Полёт к точке
        print("Движение к patrol-точке...")
        goto(controller.grid, target_point, speed=20.0)

        new_pos = _get_pos(controller.rc)
        if new_pos:
            print(f"Текущая позиция после перемещения: {new_pos}")
            controller.visited_points.append(new_pos)

        # Чуть-чуть обновляем карту время от времени, чтобы не "ослепнуть"
        # (дорого сканировать каждый шаг, поэтому редко)
        if int(ring_radius) % 200 == 0 and abs(math.degrees(angle)) < 1e-3:
            print("Обновляю карту радиусом 200м...")
            controller.scan_voxels()

        # Следующая точка по углу / кольцу
        angle += angle_step
        if angle >= 2.0 * math.pi:
            angle -= 2.0 * math.pi
            ring_radius += ring_radius_step

        time.sleep(0.5)


if __name__ == "__main__":
    main()
