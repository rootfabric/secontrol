#!/usr/bin/env python3
"""
Тестовый полёт вперёд по пересечённой местности.

Для каждого шага:
- берём текущую позицию и forward дрона;
- считаем точку впереди на distance_step;
- через SurfaceFlightController.calculate_surface_point_at_altitude
  получаем целевую точку на заданной высоте над поверхностью;
- логируем высоту поверхности и высоту цели над ней;
- летим к цели;
- после перелёта ещё раз меряем фактическую высоту над поверхностью.

Скрипт нужен, чтобы проверить поведение над крутыми склонами.
"""

import math
import time
from typing import Tuple, Optional

from secontrol.controllers.surface_flight_controller import SurfaceFlightController
from secontrol.tools.navigation_tools import goto

Point3D = Tuple[float, float, float]

# Настройки теста
GRID_NAME = "taburet"
TEST_ALTITUDE = 50.0          # целевая высота над поверхностью
DISTANCE_STEP = 50.0          # шаг вперёд за один перелёт (м)
NUM_STEPS = 20                # сколько шагов сделать
SPEED = 15.0                  # скорость полёта
PAUSE_BETWEEN_STEPS = 1.0     # пауза между шагами (сек)

DEFAULT_SCAN_RADIUS = 100.0
DEFAULT_BOUNDING_BOX_Y = 50.0


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


def main() -> None:
    controller = SurfaceFlightController(
        GRID_NAME,
        scan_radius=DEFAULT_SCAN_RADIUS,
        boundingBoxY=DEFAULT_BOUNDING_BOX_Y,
    )

    pos = _get_pos(controller.rc)
    if pos is None:
        print("Не удалось получить позицию RemoteControl. Завершение.")
        return

    print(f"Начальная позиция дрона: {pos}")
    controller.visited_points.append(pos)

    # Если ещё нет occupancy_grid – делаем первичный скан
    if (
        getattr(controller, "radar_controller", None) is None
        or controller.radar_controller.occupancy_grid is None
    ):
        print("Нет локальной карты поверхности, выполняю первичный скан...")
        solid, metadata, contacts, ore_cells = controller.scan_voxels()
        print(
            f"[init] Скана: solid={len(solid or [])}, "
            f"ores={len(ore_cells or []) if ore_cells is not None else 0}"
        )
    else:
        print("Использую уже загруженную карту поверхности (occupancy_grid).")

    for step in range(1, NUM_STEPS + 1):
        print("\n" + "=" * 60)
        print(f"ШАГ {step}/{NUM_STEPS}")

        # Текущая позиция
        pos = _get_pos(controller.rc)
        if pos is None:
            print("Не удалось получить текущую позицию, выхожу.")
            break

        px, py, pz = pos
        print(f"Текущая позиция: ({px:.2f}, {py:.2f}, {pz:.2f})")

        # Высота поверхности под текущей позицией
        surface_current = None
        if getattr(controller, "radar_controller", None) is not None:
            surface_current = controller.radar_controller.get_surface_height(px, pz)

        if surface_current is not None:
            alt_over_surface = py - surface_current
            print(
                f"Текущая поверхность под дроном: {surface_current:.2f}, "
                f"высота над поверхностью: {alt_over_surface:.2f}м"
            )
        else:
            print("Поверхность под дроном по карте не найдена.")

        # Вектор forward в мировых координатах
        forward, _, _ = controller.rc.get_orientation_vectors_world()
        fx, fy, fz = forward
        print(f"Forward-вектор: ({fx:.3f}, {fy:.3f}, {fz:.3f})")

        # Точка впереди на DISTANCE_STEP
        forward_point = (
            px + fx * DISTANCE_STEP,
            py + fy * DISTANCE_STEP,
            pz + fz * DISTANCE_STEP,
        )
        print(
            "Forward-точка (до учёта рельефа): "
            f"({forward_point[0]:.2f}, {forward_point[1]:.2f}, {forward_point[2]:.2f})"
        )

        # Высота поверхности под forward-точкой (по карте)
        surf_forward = None
        if getattr(controller, "radar_controller", None) is not None:
            surf_forward = controller.radar_controller.get_surface_height(
                forward_point[0], forward_point[2]
            )
        if surf_forward is not None:
            print(
                f"Поверхность под forward-точкой (по карте): y={surf_forward:.2f}, "
                f"геом. высота forward-точки: y={forward_point[1]:.2f}, "
                f"разница: {forward_point[1] - surf_forward:.2f}м"
            )
        else:
            print("Поверхность под forward-точкой по карте не найдена (до вызова контроллера).")

        # Целевая точка на заданной высоте над поверхностью
        target_point = controller.calculate_surface_point_at_altitude(
            forward_point,
            TEST_ALTITUDE,
        )

        tx, ty, tz = target_point
        print(
            "Целевая точка от контроллера: "
            f"({tx:.2f}, {ty:.2f}, {tz:.2f}) на высоте {TEST_ALTITUDE:.1f}м над поверхностью (по расчёту)."
        )

        # Проверим фактическую высоту цели над поверхностью по текущей карте
        surface_at_target = None
        if getattr(controller, "radar_controller", None) is not None:
            surface_at_target = controller.radar_controller.get_surface_height(tx, tz)

        if surface_at_target is not None:
            alt_target_over_surface = ty - surface_at_target
            print(
                f"Поверхность под целевой точкой: y={surface_at_target:.2f}, "
                f"цель y={ty:.2f}, высота над поверхностью={alt_target_over_surface:.2f}м"
            )
            if alt_target_over_surface < 0:
                print(
                    "!!! ВНИМАНИЕ: целевая точка НИЖЕ поверхности по карте. "
                    "Это кейс для отладки резких склонов."
                )
        else:
            print("Поверхность под целевой точкой по карте не найдена.")

        # Для наглядности создадим GPS-метки
        controller.grid.create_gps_marker(
            f"TestStep{step}_Forward",
            coordinates=forward_point,
        )
        controller.grid.create_gps_marker(
            f"TestStep{step}_Target",
            coordinates=target_point,
        )

        # Полёт к целевой точке
        print("Движение к целевой точке...")
        goto(controller.grid, target_point, speed=SPEED)

        # После перелёта ещё раз меряем высоту над поверхностью
        time.sleep(PAUSE_BETWEEN_STEPS)
        new_pos = _get_pos(controller.rc)
        if new_pos is None:
            print("Не удалось получить позицию после полёта, выхожу.")
            break

        nx, ny, nz = new_pos
        print(f"Позиция после полёта: ({nx:.2f}, {ny:.2f}, {nz:.2f})")

        surface_after = None
        if getattr(controller, "radar_controller", None) is not None:
            surface_after = controller.radar_controller.get_surface_height(nx, nz)

        if surface_after is not None:
            alt_after = ny - surface_after
            print(
                f"Поверхность под дроном после полёта: y={surface_after:.2f}, "
                f"высота над поверхностью={alt_after:.2f}м"
            )
            if alt_after < 0:
                print(
                    "!!! ВНИМАНИЕ: дрон оказался НИЖЕ поверхности по карте после полёта. "
                    "Это критический кейс, надо разбираться с логикой расчёта."
                )
        else:
            print("После полёта поверхность под дроном по карте не найдена.")

        controller.visited_points.append(new_pos)

    print("\nТест завершён.")
    print(f"Всего посещённых точек: {len(controller.visited_points)}")


if __name__ == "__main__":
    main()
