#!/usr/bin/env python3
"""
Патрульный полёт дрона по окружностям вокруг базы
в плоскости, перпендикулярной вектору гравитации.

Для каждой точки патруля:
- координаты на «горизонтальной» окружности считаются в плоскости,
  построенной относительно гравитации;
- высота над поверхностью считается через
  SurfaceFlightController.calculate_surface_point_at_altitude.

Шаг по углу подбирается так, чтобы расстояние между соседними
точками по дуге не превышало max_segment_length.
"""

import math
import time
from typing import Tuple, Optional

from secontrol.controllers.surface_flight_controller import SurfaceFlightController
from secontrol.tools.navigation_tools import goto


Point3D = Tuple[float, float, float]


def _get_pos(rc) -> Optional[Point3D]:
    """Чтение мировых координат из телеметрии RemoteControl."""
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
    Строим два ортонормальных вектора (h1, h2) в плоскости,
    перпендикулярной вектору гравитации (down).

    down предполагается нормированным (что даёт SurfaceFlightController._get_down_vector).
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

    # Контроллер полёта над поверхностью (строит карту по радару)
    controller = SurfaceFlightController(grid_name, scan_radius=200.0, boundingBoxY=60.0)

    # Начальная позиция — центр патруля
    base_pos = _get_pos(controller.rc)
    if base_pos is None:
        print("Не удалось получить позицию RemoteControl. Завершение.")
        return

    print(f"Базовая позиция (центр патруля): {base_pos}")
    controller.visited_points.append(base_pos)

    # Первый плотный скан для заполнения occupancy_grid
    print("Первичный скан поверхности для заполнения карты...")
    solid, metadata, contacts, ore_cells = controller.scan_voxels()
    print(
        f"[init] Начальный скан: solid={len(solid or [])}, ores={len(ore_cells or [])}"
    )

    # Горизонтальная система координат относительно гравитации
    down = controller._get_down_vector()
    print(f"Гравитация (down): {down}")
    h1, h2 = _build_horizontal_basis(down)
    print(f"Горизонтальные базисы: h1={h1}, h2={h2}")

    # Параметры патруля
    flight_altitude = 50.0       # высота над поверхностью
    ring_radius = 100.0          # стартовый радиус
    ring_radius_step = 100.0     # шаг увеличения радиуса после полного круга
    max_ring_radius = 3000.0     # максимальный радиус облёта

    # Максимально допустимое расстояние между соседними точками по дуге
    max_segment_length = 100.0   # метров

    angle = 0.0  # начальный угол в радианах

    while True:
        if ring_radius > max_ring_radius:
            print(f"Достигнут максимальный радиус {max_ring_radius} м. Ожидание на орбите.")
            time.sleep(10.0)
            continue

        # Текущая позиция (для логов и отладки)
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

        # Точка патруля в "горизонтальной" плоскости (до учёта рельефа)
        flat_point = (
            base_pos[0] + offset[0],
            base_pos[1] + offset[1],
            base_pos[2] + offset[2],
        )

        print(
            "Плоская патрульная точка (до учёта рельефа): "
            f"({flat_point[0]:.2f}, {flat_point[1]:.2f}, {flat_point[2]:.2f})"
        )

        # Рассчитываем точку на заданной высоте над поверхностью по гравитации
        target_point = controller.calculate_surface_point_at_altitude(
            flat_point,
            flight_altitude,
        )

        print(
            "Патрульная точка: "
            f"угол={math.degrees(angle):.1f}°, "
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

        # Периодически обновляем карту, чтобы учитывать изменения рельефа
        # (например, добыча ресурсов). Делать слишком часто дорого.
        if int(ring_radius) % 200 == 0 and abs(math.degrees(angle)) < 1e-3:
            print("Обновляю карту радиусом 200м...")
            controller.scan_voxels()

        # --- Динамический шаг по углу, чтобы расстояние по дуге не превышало max_segment_length ---

        if ring_radius > 1e-3:
            angle_step = max_segment_length / ring_radius
        else:
            # На очень маленьких радиусах считаем круг целиком за один шаг
            angle_step = 2.0 * math.pi

        # Ограничиваем максимальный шаг по углу (для стабильности траектории)
        max_angle_step_rad = math.radians(90.0)
        if angle_step > max_angle_step_rad:
            angle_step = max_angle_step_rad

        segment_distance = ring_radius * angle_step
        print(
            f"Следующий шаг по углу: {math.degrees(angle_step):.2f}°, "
            f"дуга≈{segment_distance:.1f}м (макс {max_segment_length:.1f}м)"
        )

        # Следующая точка по углу / следующее кольцо
        angle += angle_step
        if angle >= 2.0 * math.pi:
            angle -= 2.0 * math.pi
            ring_radius += ring_radius_step
            print(f"Переход на новое кольцо: радиус={ring_radius:.1f}м")

        time.sleep(0.5)


if __name__ == "__main__":
    main()
